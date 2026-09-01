package slurm

import "strings"

// maxStdIOPadWidth bounds the sbatch zero-pad width honored during pattern
// expansion, comfortably above the widest real job id.
const maxStdIOPadWidth = 20

// jobStdIO returns the expanded stdout/stderr log paths for a job record. An
// unset stderr defaults to the stdout file: without an explicit -e the
// scheduler merges stderr into stdout, and sacct then reports StdErr as empty.
// Placeholder values ("(null)", "N/A") are treated as unset.
func jobStdIO(stdOut, stdErr, jobIDRaw, arrayJobID, arrayTaskID, user, name string) (string, string) {
	out := expandStdIOPath(stdIOValue(stdOut), jobIDRaw, arrayJobID, arrayTaskID, user, name)
	errPath := expandStdIOPath(stdIOValue(stdErr), jobIDRaw, arrayJobID, arrayTaskID, user, name)
	if errPath == "" {
		errPath = out
	}
	return out, errPath
}

// stdIOValue normalizes a scheduler-reported path value: the placeholders the
// commands print for an unset path become "".
func stdIOValue(v string) string {
	v = strings.TrimSpace(v)
	if v == "(null)" || v == "N/A" {
		return ""
	}
	return v
}

// expandStdIOPath expands the sbatch filename patterns whose values the job
// record pins down: %% (literal %), %j (raw job id), %A (array master id),
// %a (array task id), %u (user), %x (job name). scontrol and squeue expand
// these themselves, but sacct reports the pattern verbatim, so journal records
// backfilled from accounting would otherwise point at files that do not exist.
// A specifier whose value is unknown here (%N and friends are node-scoped; %j
// for an array task from sacct, whose raw per-task id accounting does not
// report in this query) is left verbatim rather than guessed: a visible
// pattern beats a plausible wrong path. An sbatch zero-pad width ("%3a") is
// honored for numeric values.
func expandStdIOPath(path, jobIDRaw, arrayJobID, arrayTaskID, user, name string) string {
	if !strings.ContainsRune(path, '%') {
		return path
	}
	values := map[byte]string{
		'j': numericOnly(jobIDRaw),
		'A': numericOnly(arrayJobID),
		'a': numericOnly(arrayTaskID),
		'u': user,
		'x': name,
	}
	var b strings.Builder
	b.Grow(len(path))
	for i := 0; i < len(path); {
		if path[i] != '%' {
			b.WriteByte(path[i])
			i++
			continue
		}
		spec := i + 1
		for spec < len(path) && path[spec] >= '0' && path[spec] <= '9' {
			spec++
		}
		if spec >= len(path) {
			b.WriteString(path[i:])
			break
		}
		if path[spec] == '%' && spec == i+1 {
			b.WriteByte('%')
			i = spec + 1
			continue
		}
		v := values[path[spec]]
		if v == "" {
			b.WriteString(path[i : spec+1])
			i = spec + 1
			continue
		}
		// A digit run between % and the specifier is an sbatch zero-pad
		// width ("%3a" → "007"). Widths beyond maxStdIOPadWidth are treated
		// as literal text: no real path uses them, and honoring an absurd
		// width would balloon the expansion.
		width := 0
		for k := i + 1; k < spec && width <= maxStdIOPadWidth; k++ {
			width = width*10 + int(path[k]-'0')
		}
		if width > maxStdIOPadWidth {
			b.WriteString(path[i : spec+1])
			i = spec + 1
			continue
		}
		for len(v) < width {
			v = "0" + v
		}
		b.WriteString(v)
		i = spec + 1
	}
	return b.String()
}

// numericOnly returns id when it is a plain decimal number, else "". It guards
// the id specifiers against squeue's "N/A" placeholder and against array
// leader forms ("123_[0-99]") whose per-task value is not a single number.
func numericOnly(id string) string {
	if id == "" {
		return ""
	}
	for i := 0; i < len(id); i++ {
		if id[i] < '0' || id[i] > '9' {
			return ""
		}
	}
	return id
}
