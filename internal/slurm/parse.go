package slurm

import (
	"regexp"
	"sort"
	"strconv"
	"strings"
)

const (
	// minSqueueParts is the minimum pipe-separated field count a pipe-delimited
	// squeue row must have. Ports parser.MIN_SQUEUE_PARTS.
	minSqueueParts = 8
	// minSacctParts is the minimum field count a sacct history row must have.
	// Ports parser.MIN_SACCT_PARTS.
	minSacctParts = 10
)

// scontrolKVPattern ports the single-record Key=Value pattern in
// parser.parse_scontrol_output: a key of one or more "\w+" segments joined by
// "/", an "=", then a value that is a maximal run of non-space characters (which
// may itself contain "=", as in "TRES=cpu=32,mem=256G"). When the run is empty
// the Python lookahead branch yields an empty value, which "\S*" reproduces. A
// key like "ReqB:S:C:T=" captures only its final "\w+" segment ("T") because the
// key sub-pattern does not allow ":".
var scontrolKVPattern = regexp.MustCompile(`(\w+(?:/\w+)*)=(\S*)`)

// ParseScontrolFields parses "scontrol show jobid/node" output into a Key=Value
// map. Continuation lines (those indented by three spaces) are joined onto the
// preceding line first. Ports parser.parse_scontrol_output.
func ParseScontrolFields(raw string) map[string]string {
	result := make(map[string]string)
	joined := strings.ReplaceAll(raw, "\n   ", " ")
	for _, m := range scontrolKVPattern.FindAllStringSubmatch(joined, -1) {
		result[m[1]] = m[2]
	}
	return result
}

// ParseNodes parses "scontrol show nodes" output into a slice of Node records.
// Records are split on the "NodeName=" anchor rather than on blank lines, so
// blank lines that SLURM emits within a single node's block (for example before
// a Reason field) do not start a new record. Ports
// parser.parse_scontrol_nodes_output and the regression in Python commit 2ff0fd5.
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
			// Defensive: lines before the first NodeName= are ignored, matching
			// Python where current_node stays empty until a NodeName= appears.
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
// that are neither whitespace nor "="). It anchors at the search start so the
// finditer emulator in parseNodeLine controls advancement. Ports the head of the
// pattern in parser.parse_scontrol_nodes_output.
var nodeKeyPattern = regexp.MustCompile(`^(\w+(?:[/:]\w+)*)=([^\s=]+)`)

// kv is a parsed key/value pair from a node line.
type kv struct{ key, value string }

// parseNodeLine reproduces Python re.finditer over the node Key=Value pattern
//
//	(\w+(?:[/:]\w+)*)=([^\s=]+(?:\s+[^\s=]+)*?)(?=\s+\w+(?:[/:]\w+)*=|$)
//
// for a single (already stripped) line. The value extends across whitespace,
// consuming additional "[^\s=]+" tokens, but stops as soon as the remainder
// begins a new "\s+Key=" anchor or the line ends; the non-greedy value means it
// takes the shortest span that satisfies that boundary. Like Python's finditer it
// advances one byte at a time when no match starts at the current position, which
// is what lets a value such as "CfgTRES=cpu=192,..." be skipped until the final
// "gres/gpu:h200=8" anchors a valid match.
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
		// Extend the value across "\s+[^\s=]+" tokens, choosing the shortest span
		// (non-greedy) for which the next position begins a "\s+Key=" anchor or the
		// line ends. If no reachable boundary exists (because the next character is
		// "=", as in "CfgTRES=cpu=192,..."), the whole match fails and finditer
		// advances one byte, so this anchor is skipped entirely.
		matched := true
		for !nodeBoundary(line, valEnd) {
			next := nodeNextValueToken(line, valEnd)
			if next == valEnd {
				matched = false
				break
			}
			valEnd = next
		}
		if !matched {
			i++
			continue
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

// nodeNextValueToken returns the end offset after consuming one "\s+[^\s=]+"
// continuation token starting at p, or p unchanged when none can be consumed.
func nodeNextValueToken(line string, p int) int {
	j := p
	for j < len(line) && (line[j] == ' ' || line[j] == '\t') {
		j++
	}
	if j == p || j >= len(line) {
		return p
	}
	k := j
	for k < len(line) && line[k] != ' ' && line[k] != '\t' && line[k] != '=' {
		k++
	}
	if k == j {
		return p
	}
	return k
}

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
// header and skipped, and rows with fewer than eight fields are dropped. Ports
// parser.parse_squeue_output plus the column layout of get_running_jobs.
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

// ParseHistory parses pipe-delimited "sacct" history output into HistoryJob
// records plus aggregate requeue statistics. The first line is treated as a
// header and skipped; rows with fewer than ten fields are dropped. Jobs are
// sorted by numeric base job ID descending (most recent first), with
// non-numeric IDs sorting as zero. Ports parser.parse_sacct_output.
func ParseHistory(raw string) ([]HistoryJob, HistoryStats) {
	lines := splitNonTrailing(raw)
	if len(lines) <= 1 {
		return nil, HistoryStats{}
	}

	var jobs []HistoryJob
	stats := HistoryStats{}
	for _, line := range lines[1:] {
		parts := strings.Split(line, "|")
		if len(parts) < minSacctParts {
			continue
		}
		jobs = append(jobs, HistoryJob{
			ID:       parts[0],
			Name:     parts[1],
			State:    parts[2],
			Restart:  parts[3],
			Elapsed:  parts[4],
			ExitCode: parts[5],
			NodeList: parts[6],
			Submit:   parts[7],
			Start:    parts[8],
			End:      parts[9],
			Raw:      parts,
		})
		if n, err := strconv.Atoi(parts[3]); err == nil {
			stats.TotalRequeues += n
			if n > stats.MaxRequeues {
				stats.MaxRequeues = n
			}
		}
	}
	stats.TotalJobs = len(jobs)

	sort.SliceStable(jobs, func(i, j int) bool {
		return historySortKey(jobs[i].ID) > historySortKey(jobs[j].ID)
	})
	return jobs, stats
}

// historySortKey returns the integer base job ID used to order history rows,
// matching the Python job_sort_key (split on "_", parse int, 0 on failure).
func historySortKey(jobID string) int {
	base := strings.TrimSpace(strings.SplitN(jobID, "_", 2)[0])
	n, err := strconv.Atoi(base)
	if err != nil {
		return 0
	}
	return n
}

// ParseJobDetail parses pipe-delimited single-job sacct output into a Key=Value
// map using the supplied field names. It picks the main job entry, skipping
// sub-steps whose JobID contains a "." (such as ".batch" or ".0"), and drops
// empty values. Ports parser.parse_sacct_job_output.
func ParseJobDetail(raw string, fields []string) map[string]string {
	lines := splitNonTrailing(raw)
	if len(lines) == 0 {
		return map[string]string{}
	}

	mainLine := ""
	for _, line := range lines {
		jobID := strings.SplitN(line, "|", 2)[0]
		if !strings.Contains(jobID, ".") || strings.HasSuffix(jobID, ".") {
			mainLine = line
			break
		}
	}
	if mainLine == "" {
		mainLine = lines[0]
	}

	parts := strings.Split(mainLine, "|")
	result := make(map[string]string)
	for i, field := range fields {
		if i < len(parts) {
			if v := strings.TrimSpace(parts[i]); v != "" {
				result[field] = v
			}
		}
	}
	return result
}

// allUsersColEnds are the cumulative column end offsets for the all-users
// "squeue -O" layout (JobID:30,Name:50,UserName:15,Partition:15,StateCompact:10,
// TimeUsed:12,NumNodes:6,NodeList:80) with TRES taking the remainder. Ports the
// _SQUEUE_ALL_COL_* constants in commands.py.
var allUsersColEnds = []int{30, 80, 95, 110, 120, 132, 138, 218}

// userColEnds are the cumulative column end offsets for the single-user
// "squeue -O" layout (JobID:30,Name:50,Partition:15,StateCompact:10,TimeUsed:12,
// NumNodes:6,NodeList:80) with TRES taking the remainder. Ports the
// _SQUEUE_USER_COL_* constants in commands.py.
var userColEnds = []int{30, 80, 95, 105, 117, 123, 203}

// sliceFixedWidth cuts a line into the fields delimited by ends (cumulative end
// offsets), trimming each, and returns the trailing remainder after the last
// offset as the final field. A field whose start lies beyond the line length is
// the empty string, matching the bounds guards in commands.py.
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
// an empty JobID are skipped. Ports get_all_running_jobs +
// _parse_fixed_width_squeue_line in commands.py.
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

// ParseUserJobs parses fixed-width single-user "squeue -O" output into UserJob
// records, applying the same blank/short/empty-JobID filtering as
// ParseAllUsersJobs. Ports get_user_jobs in commands.py.
func ParseUserJobs(raw string) []UserJob {
	var jobs []UserJob
	for _, line := range strings.Split(strings.TrimSpace(raw), "\n") {
		if strings.TrimSpace(line) == "" {
			continue
		}
		if len(line) < userColEnds[0] {
			continue
		}
		f := sliceFixedWidth(line, userColEnds)
		if f[0] == "" {
			continue
		}
		jobs = append(jobs, UserJob{
			ID: f[0], Name: f[1], Partition: f[2], State: f[3],
			Time: f[4], NumNodes: f[5], NodeList: f[6], TRES: f[7],
		})
	}
	return jobs
}

// fairShareFieldCount is the column count of sshare output (SSHARE_FIELDS).
const fairShareFieldCount = 8

// ParseFairShare parses pipe-delimited "sshare" output into FairShareEntry
// records. Rows with fewer than eight fields are skipped; each field is trimmed.
// A trailing empty field from sshare's parsable mode is ignored because only the
// first eight columns are used. Ports get_fair_share_priority +
// parse_sshare_output.
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

// priorityFieldCount is the column count of sprio output (SPRIO_FIELDS).
const priorityFieldCount = 9

// ParsePriority parses pipe-delimited "sprio" output into PriorityEntry records,
// sorted by numeric Priority descending (non-numeric priorities sort as zero).
// Rows with fewer than nine fields are skipped and every field is trimmed. Ports
// get_pending_job_priority + parse_sprio_output.
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

// priorityValue parses a priority string to a float, returning 0 on failure to
// match parse_sprio_output's priority_sort_key.
func priorityValue(s string) float64 {
	v, err := strconv.ParseFloat(s, 64)
	if err != nil {
		return 0
	}
	return v
}

// energyFieldCount is the column count of the energy sacct query
// (ENERGY_HISTORY_FIELDS).
const energyFieldCount = 6

// energyValidStates is the set of job states that count toward energy use. Ports
// commands.ENERGY_VALID_STATES.
var energyValidStates = map[string]struct{}{
	"COMPLETED":     {},
	"FAILED":        {},
	"CANCELLED":     {},
	"TIMEOUT":       {},
	"NODE_FAIL":     {},
	"PREEMPTED":     {},
	"OUT_OF_MEMORY": {},
}

// ParseEnergyRecords parses pipe-delimited energy sacct output into EnergyRecord
// values, keeping only rows whose base state (the first whitespace-separated
// token, so "CANCELLED by 123" matches "CANCELLED") is in energyValidStates.
// Rows with fewer than six fields are skipped. Ports the parsing/filtering loop
// in get_energy_job_history. Fields are not trimmed here, matching the Python
// getter which slices the raw split on "|" without stripping.
func ParseEnergyRecords(raw string) []EnergyRecord {
	var records []EnergyRecord
	for _, parts := range iterPipeRows(raw, energyFieldCount, false) {
		state := ""
		if parts[5] != "" {
			state = strings.Fields(parts[5])[0]
		}
		if _, ok := energyValidStates[state]; !ok {
			continue
		}
		records = append(records, EnergyRecord{
			JobID:     parts[0],
			User:      parts[1],
			Elapsed:   parts[2],
			NCPUS:     parts[3],
			AllocTRES: parts[4],
			State:     parts[5],
		})
	}
	return records
}

// waitTimeFieldCount is the column count of the wait-time sacct query
// (WAIT_TIME_FIELDS).
const waitTimeFieldCount = 5

// ParseWaitTimeRecords parses pipe-delimited wait-time sacct output into
// WaitTimeRecord values, dropping rows whose Start time is unknown/empty (still
// pending). Rows with fewer than five fields are skipped. Ports the
// parsing/filtering loop in get_wait_time_job_history.
func ParseWaitTimeRecords(raw string) []WaitTimeRecord {
	var records []WaitTimeRecord
	for _, parts := range iterPipeRows(raw, waitTimeFieldCount, false) {
		start := strings.TrimSpace(parts[4])
		if isUnknownTimestamp(start) {
			continue
		}
		records = append(records, WaitTimeRecord{
			JobID:     parts[0],
			Partition: parts[1],
			State:     parts[2],
			Submit:    parts[3],
			Start:     parts[4],
		})
	}
	return records
}

// iterPipeRows yields the pipe-separated fields of each non-blank line in out
// that has at least numFields columns, optionally trimming each field. Ports
// commands._iter_pipe_rows.
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

// splitNonTrailing splits raw on newlines after trimming surrounding whitespace,
// mirroring Python's raw.strip().split("\n"). An empty (post-trim) input yields a
// nil slice rather than a one-element slice containing "".
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
