package slurm

import "testing"

func TestParseElapsedToSeconds(t *testing.T) {
	tests := []struct {
		name string
		in   string
		want float64
	}{
		{"hhmmss", "01:30:00", 5400},
		{"hhmmss small", "00:05:30", 330},
		{"mmss", "05:30", 330},
		{"ss", "30", 30},
		{"days", "1-00:00:00", 86400},
		{"days full", "2-12:30:45", 2*86400 + 12*3600 + 30*60 + 45},
		{"week", "7-00:00:00", 7 * 86400},
		{"empty", "", 0},
		{"whitespace", "   ", 0},
		{"invalid", "invalid", 0},
		{"invalid colons", "abc:def:ghi", 0},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := ParseElapsedToSeconds(tt.in); got != tt.want {
				t.Errorf("ParseElapsedToSeconds(%q) = %v, want %v", tt.in, got, tt.want)
			}
		})
	}
}

func TestParseSlurmTimestamp(t *testing.T) {
	tests := []struct {
		name   string
		in     string
		wantOK bool
	}{
		{"valid", "2024-01-15T10:30:00", true},
		{"whitespace trimmed", "  2024-01-15T10:30:00  ", true},
		{"unknown", "Unknown", false},
		{"none", "None", false},
		{"na", "N/A", false},
		{"empty", "", false},
		{"garbage", "not-a-timestamp", false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, ok := ParseSlurmTimestamp(tt.in)
			if ok != tt.wantOK {
				t.Fatalf("ParseSlurmTimestamp(%q) ok = %v, want %v", tt.in, ok, tt.wantOK)
			}
			if ok && got.Format("2006-01-02T15:04:05") != "2024-01-15T10:30:00" {
				t.Errorf("parsed time = %v, want 2024-01-15T10:30:00", got)
			}
		})
	}
}

func TestWaitTimeSeconds(t *testing.T) {
	tests := []struct {
		name   string
		submit string
		start  string
		want   float64
		wantOK bool
	}{
		{"five minutes", "2024-01-15T10:30:00", "2024-01-15T10:35:00", 300, true},
		{"zero wait", "2024-01-15T10:30:00", "2024-01-15T10:30:00", 0, true},
		{"long wait", "2024-01-15T10:00:00", "2024-01-15T12:30:00", 9000, true},
		{"missing start", "2024-01-15T10:30:00", "Unknown", 0, false},
		{"missing submit", "Unknown", "2024-01-15T10:35:00", 0, false},
		// start before submit is a data error and yields no value.
		{"negative dropped", "2024-01-15T10:35:00", "2024-01-15T10:30:00", 0, false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, ok := WaitTimeSeconds(tt.submit, tt.start)
			if ok != tt.wantOK {
				t.Fatalf("WaitTimeSeconds(%q,%q) ok = %v, want %v", tt.submit, tt.start, ok, tt.wantOK)
			}
			if ok && got != tt.want {
				t.Errorf("WaitTimeSeconds(%q,%q) = %v, want %v", tt.submit, tt.start, got, tt.want)
			}
		})
	}
}
