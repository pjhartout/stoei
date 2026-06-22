package slurm

import "testing"

func TestParseArraySize(t *testing.T) {
	tests := []struct {
		name string
		in   string
		want int
	}{
		{"regular job", "12345", 1},
		{"single task", "12345_5", 1},
		{"single task zero", "12345_0", 1},
		// the headline edge case: a pending array expands to its task count.
		{"range 0-99", "12345_[0-99]", 100},
		{"range 1-100", "12345_[1-100]", 100},
		{"single element range", "12345_[0-0]", 1},
		// a %throttle changes scheduling, not the task count.
		{"throttle ignored", "12345_[0-99%5]", 100},
		{"throttle ignored 10", "12345_[0-99%10]", 100},
		{"comma list", "12345_[1,3,5]", 3},
		{"mixed list and range", "12345_[1,3,5,7-10]", 7},
		{"mixed range list", "12345_[0-4,10,20]", 7},
		{"empty", "", 1},
		{"whitespace trimmed", "  12345_[0-9]  ", 10},
		{"malformed open", "12345_[", 1},
		{"malformed empty brackets", "12345_[]", 1},
		{"malformed text", "12345_[abc]", 1},
		{"large", "12345_[0-999]", 1000},
		// invalid range where start > end falls back to 1.
		{"reversed range", "12345_[10-5]", 1},
		{"non-numeric range", "12345_[a-b]", 1},
		{"underscore but no array", "12345_abc", 1},
		{"real pending array", "47700_[0-49]", 50},
		{"real throttled array", "47701_[0-99%10]", 100},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := ParseArraySize(tt.in); got != tt.want {
				t.Errorf("ParseArraySize(%q) = %d, want %d", tt.in, got, tt.want)
			}
		})
	}
}

func TestNormalizeArrayJobID(t *testing.T) {
	tests := []struct {
		in, want string
	}{
		{"12345", "12345"},
		{"12345_5", "12345_5"},
		{"12345_[0-99]", "12345"},
		{"2135097_[3952-4331%500]", "2135097"},
		{"12345_[1,3,5,7-10]", "12345"},
		{"", ""},
		{"12345_[", "12345"},
		{"47700_[0-49]", "47700"},
	}
	for _, tt := range tests {
		if got := NormalizeArrayJobID(tt.in); got != tt.want {
			t.Errorf("NormalizeArrayJobID(%q) = %q, want %q", tt.in, got, tt.want)
		}
	}
}
