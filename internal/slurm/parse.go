package slurm

import (
	"regexp"
	"sort"
	"strconv"
	"strings"
)

// minSqueueParts is the minimum pipe-separated field count a pipe-delimited
// squeue row must have to be parsed.
const minSqueueParts = 8

// scontrolKVPattern matches one Key=Value record from "scontrol show" output: a
// key of one or more "\w+" segments joined by "/", an "=", then a value that is a
// maximal run of non-space characters (which may itself contain "=", as in
// "TRES=cpu=32,mem=256G"). An empty run yields an empty value. A key like
// "ReqB:S:C:T=" captures only its final "\w+" segment ("T") because the key
// sub-pattern does not allow ":".
var scontrolKVPattern = regexp.MustCompile(`(\w+(?:/\w+)*)=(\S*)`)

// ParseScontrolFields parses "scontrol show jobid/node" output into a Key=Value
// map. Continuation lines (those indented by three spaces) are joined onto the
// preceding line first.
func ParseScontrolFields(raw string) map[string]string {
	result := make(map[string]string)
	joined := strings.ReplaceAll(raw, "\n   ", " ")
	for _, m := range scontrolKVPattern.FindAllStringSubmatch(joined, -1) {
		result[m[1]] = m[2]
	}
	return result
}

// ParseScontrolJobRecords splits multi-record "scontrol show jobid" output into
// one Key=Value map per record. An array job yields one record per task plus
// the pending aggregate; records are anchored on lines starting with "JobId="
// rather than blank lines, matching how ParseNodes anchors on "NodeName=".
func ParseScontrolJobRecords(raw string) []map[string]string {
	var records []map[string]string
	lines := strings.Split(raw, "\n")
	start := -1
	flush := func(end int) {
		if start < 0 {
			return
		}
		if f := ParseScontrolFields(strings.Join(lines[start:end], "\n")); len(f) > 0 {
			records = append(records, f)
		}
	}
	for i, line := range lines {
		if strings.HasPrefix(strings.TrimSpace(line), "JobId=") {
			flush(i)
			start = i
		}
	}
	flush(len(lines))
	return records
}

// ParseNodes parses "scontrol show nodes" output into a slice of Node records.
// Records are split on the "NodeName=" anchor rather than on blank lines, so
// blank lines that SLURM emits within a single node's block (for example before
// a Reason field) do not start a new record.
func ParseNodes(raw string) []Node {
	var nodes []Node
	var current map[string]string

	flush := func() {
		if current != nil {
			nodes = append(nodes, nodeFromFields(current))
			current = nil
		}
	}

	for _, line := range strings.Split(raw, "\n") {
		stripped := strings.TrimSpace(line)
		if stripped == "" {
			continue
		}
		if strings.HasPrefix(stripped, "NodeName=") {
			flush()
			current = make(map[string]string)
		}
		if current == nil {
			// Defensive: lines before the first NodeName= are ignored; no record is
			// accumulated until a NodeName= anchor opens one.
			continue
		}
		for _, kv := range parseNodeLine(stripped) {
			current[kv.key] = kv.value
		}
	}
	flush()
	return nodes
}

// nodeKeyPattern matches a single node Key=Value head: a key of "\w+" segments
// joined by "/" or ":", an "=", and the first value token (a run of characters
// that are neither whitespace nor "="). It anchors at the search start so
// parseNodeLine controls advancement byte by byte.
var nodeKeyPattern = regexp.MustCompile(`^(\w+(?:[/:]\w+)*)=([^\s=]+)`)

// kv is a parsed key/value pair from a node line.
type kv struct{ key, value string }

// parseNodeLine extracts the Key=Value pairs from a single (already stripped)
// node line. Each value runs from just after its "=" to the next " Key=" anchor
// (or the end of the line), so a value may itself contain spaces (a multi-word
// "Reason=bbusch [root@…]") and "=" signs (a "CfgTRES=cpu=192,…,gres/gpu:h200=8"
// TRES string). A position that does not begin a "Key=" head advances one byte.
func parseNodeLine(line string) []kv {
	var out []kv
	for i := 0; i < len(line); {
		head := nodeKeyPattern.FindStringSubmatchIndex(line[i:])
		if head == nil {
			i++
			continue
		}
		key := line[i+head[2] : i+head[3]]
		valStart := i + head[4]
		valEnd := i + head[5] // end of the first value token
		// Extend the value to the next " Key=" anchor or end of line, absorbing any
		// intervening spaces and "=" signs.
		for !nodeBoundary(line, valEnd) {
			valEnd++
		}
		out = append(out, kv{key: key, value: strings.TrimSpace(line[valStart:valEnd])})
		i = valEnd
	}
	return out
}

// nodeBoundary reports whether position p in line is a valid value boundary: the
// end of the line, or the start of a "\s+Key=" run. It emulates the trailing
// lookahead "(?=\s+\w+(?:[/:]\w+)*=|$)".
func nodeBoundary(line string, p int) bool {
	if p >= len(line) {
		return true
	}
	if line[p] != ' ' && line[p] != '\t' {
		return false
	}
	rest := line[p:]
	trimmed := strings.TrimLeft(rest, " \t")
	if len(trimmed) == len(rest) {
		return false // no whitespace actually consumed
	}
	loc := nodeKeyHeadEqual.FindStringIndex(trimmed)
	return loc != nil && loc[0] == 0
}

// nodeKeyHeadEqual matches a "Key=" head at the start of a string, used by
// nodeBoundary to detect the next anchor.
var nodeKeyHeadEqual = regexp.MustCompile(`^(\w+(?:[/:]\w+)*)=`)

// nodeFromFields lifts the convenience accessors out of a parsed field map.
func nodeFromFields(fields map[string]string) Node {
	return Node{
		Name:      fields["NodeName"],
		State:     fields["State"],
		CPUTot:    fields["CPUTot"],
		CPUAlloc:  fields["CPUAlloc"],
		RealMem:   fields["RealMemory"],
		AllocMem:  fields["AllocMem"],
		CfgTRES:   fields["CfgTRES"],
		AllocTRES: fields["AllocTRES"],
		Gres:      fields["Gres"],
		Reason:    fields["Reason"],
		Fields:    fields,
	}
}

// ParseRunningJobs parses pipe-delimited "squeue -o" output (the current user's
// running/pending jobs) into RunningJob records. The first line is treated as a
// header and skipped, and rows with fewer than eight fields are dropped.
func ParseRunningJobs(raw string) []RunningJob {
	lines := splitNonTrailing(raw)
	if len(lines) <= 1 {
		return nil
	}
	var jobs []RunningJob
	for _, line := range lines[1:] {
		parts := strings.Split(line, "|")
		if len(parts) < minSqueueParts {
			continue
		}
		// The format is unpadded; trim defensively for padded variants.
		for i := range parts {
			parts[i] = strings.TrimSpace(parts[i])
		}
		jobs = append(jobs, RunningJob{
			ID:         parts[0],
			Name:       parts[1],
			State:      parts[2],
			Time:       parts[3],
			Nodes:      parts[4],
			NodeList:   parts[5],
			SubmitTime: parts[6],
			StartTime:  parts[7],
			Raw:        parts,
		})
	}
	return jobs
}

// allUsersColEnds are the cumulative column end offsets for the all-users
// "squeue -O" layout (JobID:30,Name:50,UserName:15,Partition:15,StateCompact:10,
// TimeUsed:12,NumNodes:6,NodeList:80) with TRES taking the remainder.
var allUsersColEnds = []int{30, 80, 95, 110, 120, 132, 138, 218}

// sliceFixedWidth cuts a line into the fields delimited by ends (cumulative end
// offsets), trimming each, and returns the trailing remainder after the last
// offset as the final field. A field whose start lies beyond the line length is
// the empty string.
func sliceFixedWidth(line string, ends []int) []string {
	out := make([]string, 0, len(ends)+1)
	prev := 0
	for _, end := range ends {
		switch {
		case len(line) <= prev:
			out = append(out, "")
		case len(line) < end:
			out = append(out, strings.TrimSpace(line[prev:]))
		default:
			out = append(out, strings.TrimSpace(line[prev:end]))
		}
		prev = end
	}
	if len(line) > prev {
		out = append(out, strings.TrimSpace(line[prev:]))
	} else {
		out = append(out, "")
	}
	return out
}

// ParseAllUsersJobs parses fixed-width all-users "squeue -O" output into
// AllUsersJob records. Blank lines and rows shorter than the JobID column or with
// an empty JobID are skipped.
func ParseAllUsersJobs(raw string) []AllUsersJob {
	var jobs []AllUsersJob
	for _, line := range strings.Split(strings.TrimSpace(raw), "\n") {
		if strings.TrimSpace(line) == "" {
			continue
		}
		if len(line) < allUsersColEnds[0] {
			continue
		}
		f := sliceFixedWidth(line, allUsersColEnds)
		if f[0] == "" {
			continue
		}
		jobs = append(jobs, AllUsersJob{
			ID: f[0], Name: f[1], User: f[2], Partition: f[3],
			State: f[4], Time: f[5], NumNodes: f[6], NodeList: f[7], TRES: f[8],
		})
	}
	return jobs
}

// fairShareFieldCount is the column count of sshare output.
const fairShareFieldCount = 8

// ParseFairShare parses pipe-delimited "sshare" output into FairShareEntry
// records. Rows with fewer than eight fields are skipped; each field is trimmed.
// A trailing empty field from sshare's parsable mode is ignored because only the
// first eight columns are used.
func ParseFairShare(raw string) []FairShareEntry {
	var entries []FairShareEntry
	for _, parts := range iterPipeRows(raw, fairShareFieldCount, true) {
		entries = append(entries, FairShareEntry{
			Account:      parts[0],
			User:         parts[1],
			RawShares:    parts[2],
			NormShares:   parts[3],
			RawUsage:     parts[4],
			NormUsage:    parts[5],
			EffectvUsage: parts[6],
			FairShare:    parts[7],
		})
	}
	return entries
}

// priorityFieldCount is the column count of sprio output.
const priorityFieldCount = 9

// ParsePriority parses pipe-delimited "sprio" output into PriorityEntry records,
// sorted by numeric Priority descending (non-numeric priorities sort as zero).
// Rows with fewer than nine fields are skipped and every field is trimmed.
func ParsePriority(raw string) []PriorityEntry {
	var entries []PriorityEntry
	for _, parts := range iterPipeRows(raw, priorityFieldCount, true) {
		entries = append(entries, PriorityEntry{
			JobID:     parts[0],
			User:      parts[1],
			Account:   parts[2],
			Priority:  parts[3],
			Age:       parts[4],
			FairShare: parts[5],
			JobSize:   parts[6],
			Partition: parts[7],
			QOS:       parts[8],
		})
	}
	sort.SliceStable(entries, func(i, j int) bool {
		return priorityValue(entries[i].Priority) > priorityValue(entries[j].Priority)
	})
	return entries
}

// priorityValue parses a priority string to a float, returning 0 on failure so a
// malformed priority sorts last.
func priorityValue(s string) float64 {
	v, err := strconv.ParseFloat(s, 64)
	if err != nil {
		return 0
	}
	return v
}

// iterPipeRows yields the pipe-separated fields of each non-blank line in out
// that has at least numFields columns, optionally trimming each field.
func iterPipeRows(out string, numFields int, strip bool) [][]string {
	var rows [][]string
	for _, line := range strings.Split(strings.TrimSpace(out), "\n") {
		if strings.TrimSpace(line) == "" {
			continue
		}
		parts := strings.Split(line, "|")
		if strip {
			for i := range parts {
				parts[i] = strings.TrimSpace(parts[i])
			}
		}
		if len(parts) >= numFields {
			rows = append(rows, parts)
		}
	}
	return rows
}

// splitNonTrailing splits raw on newlines after trimming surrounding whitespace.
// An empty (post-trim) input yields a nil slice rather than a one-element slice
// containing "".
func splitNonTrailing(raw string) []string {
	trimmed := strings.TrimSpace(raw)
	if trimmed == "" {
		return nil
	}
	return strings.Split(trimmed, "\n")
}

// sortStrings sorts s in place. It is a thin wrapper so callers in this package
// avoid importing sort directly for a single use.
func sortStrings(s []string) { sort.Strings(s) }
