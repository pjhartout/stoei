package store

import "testing"

// TestAggregateAccountResources covers the Current Resource Usage aggregation:
// CPUs/memory/GPUs summed from each job's TRES and unique nodes counted across
// expanded node lists. Ports formatters.py 888-916.
func TestAggregateAccountResources(t *testing.T) {
	jobs := []AllUsersJob{
		{TRES: "cpu=8,mem=16G,gres/gpu:a100=2", NodeList: "n[01-02]"},
		{TRES: "cpu=4,mem=8G,gres/gpu:a100=1", NodeList: "n02"}, // n02 overlaps
		{TRES: "", NodeList: ""},                                // empty contributes nothing
	}
	got := AggregateAccountResources(jobs)

	if got.TotalCPUs != 12 {
		t.Errorf("TotalCPUs = %d; want 12", got.TotalCPUs)
	}
	if got.TotalMemoryGB != 24.0 {
		t.Errorf("TotalMemoryGB = %.1f; want 24.0", got.TotalMemoryGB)
	}
	if got.TotalGPUs != 3 {
		t.Errorf("TotalGPUs = %d; want 3", got.TotalGPUs)
	}
	// n01, n02 unique (n02 appears twice).
	if got.UniqueNodes != 2 {
		t.Errorf("UniqueNodes = %d; want 2", got.UniqueNodes)
	}
}

func TestAggregateAccountResourcesEmpty(t *testing.T) {
	got := AggregateAccountResources(nil)
	if got.TotalCPUs != 0 || got.TotalGPUs != 0 || got.UniqueNodes != 0 || got.TotalMemoryGB != 0 {
		t.Errorf("empty aggregate = %+v; want all zero", got)
	}
}
