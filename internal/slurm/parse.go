package slurm

import (
	"math"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
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
		// A job name may itself contain the delimiter (sbatch -J 'a|b'), and only
		// the name can: anchor the six fixed fields at the tail and rejoin the
		// middle as the name instead of indexing forward past parts[0].
		tail := parts[len(parts)-6:]
		jobs = append(jobs, RunningJob{
			ID:         parts[0],
			Name:       strings.Join(parts[1:len(parts)-6], "|"),
			State:      tail[0],
			Time:       tail[1],
			Nodes:      tail[2],
			NodeList:   tail[3],
			SubmitTime: tail[4],
			StartTime:  tail[5],
		})
	}
	return jobs
}

// allUsersColEnds are the cumulative column end offsets for the all-users
// "squeue -O" layout (JobID:30,Name:50,UserName:15,Partition:15,StateCompact:10,
// TimeUsed:12,NumNodes:6,NodeList:80,Reason:40) with TRES taking the remainder.
var allUsersColEnds = []int{30, 80, 95, 110, 120, 132, 138, 218, 258}

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
			State: f[4], Time: f[5], NumNodes: f[6], NodeList: f[7],
			Reason: f[8], TRES: f[9],
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
	for _, parts := range iterPipeRows(raw, fairShareFieldCount) {
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

// PriorityFormat is the sprio -o format: identity columns, the total priority,
// then every weighted factor. %o (account), %r (partition name), and %n (QOS
// name) are the name columns; the capital letters are the weighted factors.
const PriorityFormat = "%i|%u|%o|%r|%n|%Y|%A|%F|%J|%P|%Q|%T|%B|%S|%N"

// priorityFieldCount is the column count of PriorityFormat.
const priorityFieldCount = 15

// ParsePriority parses pipe-delimited "sprio" output in PriorityFormat into
// PriorityEntry records, sorted by Priority descending. Rows with fewer than
// fifteen fields are skipped, every field is trimmed, and a non-numeric factor
// reads as zero.
func ParsePriority(raw string) []PriorityEntry {
	var entries []PriorityEntry
	for _, parts := range iterPipeRows(raw, priorityFieldCount) {
		entries = append(entries, PriorityEntry{
			JobID:     parts[0],
			User:      parts[1],
			Account:   parts[2],
			Partition: parts[3],
			QOS:       parts[4],
			Priority:  parseInt64(parts[5]),
			Factors: PriorityFactors{
				Age:       parseInt64(parts[6]),
				FairShare: parseInt64(parts[7]),
				JobSize:   parseInt64(parts[8]),
				Partition: parseInt64(parts[9]),
				QOS:       parseInt64(parts[10]),
				TRES:      sumTRESWeights(parts[11]),
				Assoc:     parseInt64(parts[12]),
				Site:      parseInt64(parts[13]),
				Nice:      parseInt64(parts[14]),
			},
		})
	}
	sort.SliceStable(entries, func(i, j int) bool {
		return entries[i].Priority > entries[j].Priority
	})
	return entries
}

// parseInt64 parses a whole number, accepting a float form and rounding it, and
// returns 0 for anything else so an absent or malformed factor contributes
// nothing.
func parseInt64(s string) int64 {
	s = strings.TrimSpace(s)
	if v, err := strconv.ParseInt(s, 10, 64); err == nil {
		return v
	}
	if v, err := strconv.ParseFloat(s, 64); err == nil {
		return int64(math.Round(v))
	}
	return 0
}

// sumTRESWeights sums the values of a weighted-TRES list such as
// "cpu=120,gres/gpu=45", which is what sprio prints for %T. Entries without a
// numeric value are skipped; an empty list sums to 0.
func sumTRESWeights(s string) int64 {
	var total int64
	for _, part := range strings.Split(s, ",") {
		if _, v, ok := strings.Cut(part, "="); ok {
			total += parseInt64(v)
		}
	}
	return total
}

// ParsePriorityConfig extracts the Priority* settings from "scontrol show
// config" output, whose lines read "Key = Value". Unset values print as "(null)"
// and read as zero/empty; a missing key does the same, so an unparseable or
// truncated config yields a zero PriorityConfig rather than an error.
func ParsePriorityConfig(raw string) PriorityConfig {
	kv := map[string]string{}
	for _, line := range strings.Split(raw, "\n") {
		k, v, ok := strings.Cut(line, "=")
		if !ok {
			continue
		}
		v = strings.TrimSpace(v)
		if v == "(null)" {
			v = ""
		}
		kv[strings.TrimSpace(k)] = v
	}
	return PriorityConfig{
		Type: kv["PriorityType"],
		Weights: PriorityWeights{
			Age:       parseInt64(kv["PriorityWeightAge"]),
			Assoc:     parseInt64(kv["PriorityWeightAssoc"]),
			FairShare: parseInt64(kv["PriorityWeightFairShare"]),
			JobSize:   parseInt64(kv["PriorityWeightJobSize"]),
			Partition: parseInt64(kv["PriorityWeightPartition"]),
			QOS:       parseInt64(kv["PriorityWeightQOS"]),
			TRES:      kv["PriorityWeightTRES"],
		},
		MaxAge:        time.Duration(ParseElapsedToSeconds(kv["PriorityMaxAge"]) * float64(time.Second)),
		DecayHalfLife: time.Duration(ParseElapsedToSeconds(kv["PriorityDecayHalfLife"]) * float64(time.Second)),
		FavorSmall:    strings.EqualFold(kv["PriorityFavorSmall"], "yes"),
	}
}

// iterPipeRows yields the trimmed pipe-separated fields of each non-blank line
// in out that has at least numFields columns.
func iterPipeRows(out string, numFields int) [][]string {
	var rows [][]string
	for _, line := range strings.Split(strings.TrimSpace(out), "\n") {
		if strings.TrimSpace(line) == "" {
			continue
		}
		parts := strings.Split(line, "|")
		for i := range parts {
			parts[i] = strings.TrimSpace(parts[i])
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
