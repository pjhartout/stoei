package store

import "testing"

func TestFormatWaitTime(t *testing.T) {
	cases := []struct {
		seconds float64
		want    string
	}{
		{-5, "0s"},
		{45, "45s"},
		{90, "1m"},
		{3600, "1.0h"},
		{5 * 3600, "5.0h"},
		{11 * 3600, "11h"},
		{25 * 3600, "1.0d"},
		{11 * 24 * 3600, "11d"},
	}
	for _, c := range cases {
		if got := FormatWaitTime(c.seconds); got != c.want {
			t.Errorf("FormatWaitTime(%v) = %q; want %q", c.seconds, got, c.want)
		}
	}
}
