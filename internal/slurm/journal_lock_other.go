//go:build !linux && !darwin

package slurm

// lockJournal is a no-op on platforms without flock; the in-process mutex still
// serializes writers within a single stoei.
func lockJournal(string) func() { return func() {} }
