package slurm

import (
	"fmt"
	"strconv"
	"strings"
)

// ExpandNodeList expands a Slurm NodeList expression into the set of individual
// hostnames it denotes, returned as a sorted, de-duplicated slice. It handles the
// bracket notation including ranges ("node[01-04]"), comma lists inside brackets
// ("node[01,03]"), multiple prefix groups ("gpu[01-02],cpu[01-02]"), and
// zero-padded indices. Pending-state placeholders such as "(None)" and empty
// input yield nil. Ports nodelist.expand_nodelist (which returns a Python set;
// here the result is sorted for determinism).
func ExpandNodeList(nodelist string) []string {
	set := expandNodeListSet(nodelist)
	if len(set) == 0 {
		return nil
	}
	out := make([]string, 0, len(set))
	for name := range set {
		out = append(out, name)
	}
	sortStrings(out)
	return out
}

// expandNodeListSet does the work of ExpandNodeList and returns the raw set so
// callers that only need membership or a count avoid an allocation/sort.
func expandNodeListSet(nodelist string) map[string]struct{} {
	nodelist = strings.TrimSpace(nodelist)
	if nodelist == "" || strings.HasPrefix(nodelist, "(") {
		return nil
	}

	result := make(map[string]struct{})
	for _, token := range splitNodeList(nodelist) {
		if token == "" {
			continue
		}
		if strings.Contains(token, "[") {
			for name := range expandBracketExpr(token) {
				result[name] = struct{}{}
			}
		} else {
			result[token] = struct{}{}
		}
	}
	return result
}

// splitNodeList splits a NodeList string on commas that are not inside brackets,
// porting nodelist._split_nodelist.
func splitNodeList(s string) []string {
	var tokens []string
	depth := 0
	var current strings.Builder
	for _, ch := range s {
		switch ch {
		case '[':
			depth++
			current.WriteRune(ch)
		case ']':
			depth--
			current.WriteRune(ch)
		case ',':
			if depth == 0 {
				tokens = append(tokens, current.String())
				current.Reset()
			} else {
				current.WriteRune(ch)
			}
		default:
			current.WriteRune(ch)
		}
	}
	if current.Len() > 0 {
		tokens = append(tokens, current.String())
	}
	return tokens
}

// expandBracketExpr expands one bracket expression such as "node[01-04,07]" into
// a set of hostnames, porting nodelist._expand_bracket_expr. A malformed
// expression (missing bracket or bad range) yields an empty set, matching the
// Python behavior of logging a warning and skipping.
func expandBracketExpr(expr string) map[string]struct{} {
	open := strings.IndexByte(expr, '[')
	closeIdx := strings.IndexByte(expr, ']')
	if open < 0 || closeIdx < 0 {
		return nil
	}

	prefix := expr[:open]
	spec := expr[open+1 : closeIdx]

	result := make(map[string]struct{})
	for _, part := range strings.Split(spec, ",") {
		if strings.Contains(part, "-") {
			rangeParts := strings.SplitN(part, "-", 2)
			startStr, endStr := rangeParts[0], rangeParts[1]
			start, err1 := strconv.Atoi(startStr)
			end, err2 := strconv.Atoi(endStr)
			if err1 != nil || err2 != nil {
				continue
			}
			width := len(startStr)
			for i := start; i <= end; i++ {
				result[fmt.Sprintf("%s%0*d", prefix, width, i)] = struct{}{}
			}
		} else {
			result[prefix+part] = struct{}{}
		}
	}
	return result
}
