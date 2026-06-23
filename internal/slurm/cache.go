package slurm

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"os"
	"path/filepath"
	"time"
)

// cacheExt is the suffix of a cached-output file.
const cacheExt = ".cache"

// CacheDir returns the directory where cached sacct output is stored, under
// $XDG_CACHE_HOME/stoei (or ~/.cache/stoei). It returns "" when no home/cache
// directory can be resolved, which disables persistent caching.
func CacheDir() string {
	base := os.Getenv("XDG_CACHE_HOME")
	if base == "" {
		home, err := os.UserHomeDir()
		if err != nil {
			return ""
		}
		base = filepath.Join(home, ".cache")
	}
	return filepath.Join(base, "stoei", "sacct")
}

// CachingRunner wraps a Runner with a persistent on-disk cache for sacct output.
// sacct queries hit slurmdbd on the head node and are expensive; this serves a
// cached result for up to ttl (keyed by the exact command + args), so the head
// node is queried at most once per ttl per distinct query and the cache survives
// restarts — a warm start issues no sacct at all. Only sacct is cached; squeue,
// scontrol, sshare, sprio, and scancel always run live, since they are cheap and
// must be current. Caching is best-effort: any cache I/O error falls back to
// running the command, so the cache can never break a fetch. The exported methods
// are safe for concurrent use (the only shared state is the filesystem, written
// atomically).
type CachingRunner struct {
	inner Runner
	dir   string
	ttl   time.Duration
	// now returns the current time; injectable so the TTL can be unit-tested
	// without sleeping. It defaults to time.Now.
	now func() time.Time
}

// NewCachingRunner returns a CachingRunner that caches sacct output under dir for
// ttl. A ttl <= 0 or an empty dir disables caching (every command runs live).
func NewCachingRunner(inner Runner, dir string, ttl time.Duration) *CachingRunner {
	return &CachingRunner{inner: inner, dir: dir, ttl: ttl, now: time.Now}
}

// Run serves cached sacct output when a fresh cache entry exists; otherwise it
// runs the command and, on success, caches the output. Non-sacct commands always
// run live.
func (r *CachingRunner) Run(ctx context.Context, name string, args ...string) ([]byte, error) {
	if name != "sacct" || r.ttl <= 0 || r.dir == "" {
		return r.inner.Run(ctx, name, args...)
	}
	path := r.cachePath(name, args)
	if data, ok := r.readFresh(path); ok {
		return data, nil
	}
	out, err := r.inner.Run(ctx, name, args...)
	if err == nil {
		r.write(path, out)
	}
	return out, err
}

// cachePath maps a command and its args to a cache file path. The key is a
// SHA-256 over the name and each arg (NUL-separated), so different windows and
// users get distinct entries.
func (r *CachingRunner) cachePath(name string, args []string) string {
	h := sha256.New()
	_, _ = h.Write([]byte(name))
	for _, a := range args {
		_, _ = h.Write([]byte{0})
		_, _ = h.Write([]byte(a))
	}
	return filepath.Join(r.dir, hex.EncodeToString(h.Sum(nil))+cacheExt)
}

// readFresh returns the cached output when the file exists and is younger than
// ttl; the file's modification time is the fetch time.
func (r *CachingRunner) readFresh(path string) ([]byte, bool) {
	info, err := os.Stat(path)
	if err != nil || r.now().Sub(info.ModTime()) > r.ttl {
		return nil, false
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, false
	}
	return data, true
}

// write stores data at path atomically (write a temp file, then rename) so a
// concurrent reader never observes a partial file. Errors are ignored — caching
// is best-effort and must never break a fetch.
func (r *CachingRunner) write(path string, data []byte) {
	if err := os.MkdirAll(r.dir, 0o755); err != nil {
		return
	}
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, data, 0o644); err != nil {
		return
	}
	if err := os.Rename(tmp, path); err != nil {
		_ = os.Remove(tmp)
	}
}

// Compile-time assertion that CachingRunner satisfies Runner.
var _ Runner = (*CachingRunner)(nil)
