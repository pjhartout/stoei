//go:build linux || darwin

package slurm

import (
	"os"
	"syscall"
)

// lockJournal takes an exclusive advisory lock on a sibling ".lock" file and
// returns its release func. The journal's atomic rename makes single writes
// crash-safe but is last-writer-wins for the whole file, so the load-merge-write
// cycle must be serialized across stoei processes or one instance's terminal
// records can be clobbered by another's older snapshot. The lock file is a
// stable inode (never renamed over), unlike the journal itself. Locking is
// best-effort: on any failure the release func is a no-op, because the journal
// must never break a fetch.
func lockJournal(path string) func() {
	f, err := os.OpenFile(path+".lock", os.O_CREATE|os.O_RDWR, 0o644)
	if err != nil {
		return func() {}
	}
	if err := syscall.Flock(int(f.Fd()), syscall.LOCK_EX); err != nil {
		_ = f.Close()
		return func() {}
	}
	return func() { _ = f.Close() } // closing the descriptor releases the flock
}
