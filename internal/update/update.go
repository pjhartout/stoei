// Package update implements the self-updater: it resolves the latest GitHub
// release, downloads the platform tarball, verifies its checksum, and atomically
// replaces the running binary. The TUI uses the cached latest-version lookup to
// show an update hint; the "stoei update" subcommand drives the full flow.
package update

import (
	"archive/tar"
	"compress/gzip"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"
)

// repo is the GitHub repository releases are published to.
const repo = "pjhartout/stoei"

// apiBase and downloadBase are package variables so tests can point the client
// at a local httptest server.
var (
	apiBase      = "https://api.github.com"
	downloadBase = "https://github.com"
)

// httpTimeout bounds every request: an update check must never hang the caller.
const httpTimeout = 10 * time.Second

// cacheTTL is how long a cached latest-version lookup stays fresh. Login nodes
// share one public IP against GitHub's unauthenticated rate limit, so the TUI
// consults the cache file rather than the API on most launches.
const cacheTTL = 24 * time.Hour

// Latest returns the latest release tag (e.g. "v0.10.0") from the GitHub API.
func Latest(ctx context.Context) (string, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet,
		apiBase+"/repos/"+repo+"/releases/latest", nil)
	if err != nil {
		return "", err
	}
	client := &http.Client{Timeout: httpTimeout}
	resp, err := client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close() //nolint:errcheck
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("release lookup: %s", resp.Status)
	}
	var release struct {
		TagName string `json:"tag_name"`
	}
	if err := json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(&release); err != nil {
		return "", err
	}
	if release.TagName == "" {
		return "", errors.New("release lookup: empty tag")
	}
	return release.TagName, nil
}

// LatestCached is Latest behind a ~24h on-disk cache, for the TUI's quiet
// startup check. Cache errors fall through to the network; network errors with
// a stale cache present return the stale tag rather than failing.
func LatestCached(ctx context.Context) (string, error) {
	path, cached, fresh := readCache()
	if fresh {
		return cached, nil
	}
	tag, err := Latest(ctx)
	if err != nil {
		if cached != "" {
			return cached, nil
		}
		return "", err
	}
	if path != "" {
		//nolint:errcheck // best-effort cache; the lookup already succeeded.
		os.WriteFile(path, []byte(tag+" "+strconv.FormatInt(time.Now().Unix(), 10)+"\n"), 0o644)
	}
	return tag, nil
}

// readCache returns the cache path, any cached tag, and whether it is fresh.
func readCache() (path, tag string, fresh bool) {
	dir, err := os.UserCacheDir()
	if err != nil {
		return "", "", false
	}
	path = filepath.Join(dir, "stoei", "latest-release")
	//nolint:errcheck // absent or unreadable cache simply means a network lookup.
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return "", "", false
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		return path, "", false
	}
	fields := strings.Fields(string(raw))
	if len(fields) != 2 {
		return path, "", false
	}
	ts, err := strconv.ParseInt(fields[1], 10, 64)
	if err != nil {
		return path, "", false
	}
	return path, fields[0], time.Since(time.Unix(ts, 0)) < cacheTTL
}

// IsNewer reports whether latest is a strictly newer semver tag than current.
// A current version that does not parse (e.g. "dev") is never "outdated": local
// builds get no update hint.
func IsNewer(current, latest string) bool {
	c, okC := parseSemver(current)
	l, okL := parseSemver(latest)
	if !okC || !okL {
		return false
	}
	for i := range c {
		if l[i] != c[i] {
			return l[i] > c[i]
		}
	}
	return false
}

// IsRelease reports whether v is a parseable release version. Local "dev"
// builds are not releases: they skip the update check entirely.
func IsRelease(v string) bool {
	_, ok := parseSemver(v)
	return ok
}

// parseSemver parses "v1.2.3" or "1.2.3" into its numeric triplet.
func parseSemver(v string) ([3]int, bool) {
	parts := strings.SplitN(strings.TrimPrefix(strings.TrimSpace(v), "v"), ".", 3)
	var out [3]int
	if len(parts) != 3 {
		return out, false
	}
	for i, p := range parts {
		n, err := strconv.Atoi(p)
		if err != nil || n < 0 {
			return out, false
		}
		out[i] = n
	}
	return out, true
}

// assetName is the GoReleaser artifact name for a version on this platform.
func assetName(version string) string {
	ext := "tar.gz"
	if runtime.GOOS == "windows" {
		ext = "zip"
	}
	return fmt.Sprintf("stoei_%s_%s_%s.%s",
		strings.TrimPrefix(version, "v"), runtime.GOOS, runtime.GOARCH, ext)
}

// checksumFor finds name's sha256 in a GoReleaser checksums.txt body.
func checksumFor(checksums []byte, name string) (string, error) {
	for _, line := range strings.Split(string(checksums), "\n") {
		fields := strings.Fields(line)
		if len(fields) == 2 && fields[1] == name {
			return fields[0], nil
		}
	}
	return "", fmt.Errorf("no checksum for %s", name)
}

// extractBinary pulls the "stoei" executable out of a release tar.gz.
func extractBinary(archive []byte) ([]byte, error) {
	gz, err := gzip.NewReader(strings.NewReader(string(archive)))
	if err != nil {
		return nil, err
	}
	defer gz.Close() //nolint:errcheck
	tr := tar.NewReader(gz)
	for {
		hdr, err := tr.Next()
		if err == io.EOF {
			return nil, errors.New("stoei binary not found in archive")
		}
		if err != nil {
			return nil, err
		}
		if filepath.Base(hdr.Name) == "stoei" && hdr.Typeflag == tar.TypeReg {
			return io.ReadAll(tr)
		}
	}
}

// fetch downloads url fully, capped at 256MB.
func fetch(ctx context.Context, url string) ([]byte, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, err
	}
	client := &http.Client{Timeout: 5 * time.Minute}
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close() //nolint:errcheck
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("download %s: %s", url, resp.Status)
	}
	return io.ReadAll(io.LimitReader(resp.Body, 256<<20))
}

// Apply downloads the tag's release for this platform, verifies its sha256
// against the published checksums, and atomically replaces the binary at dst
// (write to a temp file in the same directory, then rename). On Linux/macOS the
// running process keeps its old inode, so replacing a live binary is safe.
func Apply(ctx context.Context, tag, dst string) error {
	if runtime.GOOS == "windows" {
		return errors.New("self-update is not supported on Windows; download the release zip manually")
	}
	name := assetName(tag)
	base := downloadBase + "/" + repo + "/releases/download/" + tag + "/"

	archive, err := fetch(ctx, base+name)
	if err != nil {
		return err
	}
	checksums, err := fetch(ctx, base+"checksums.txt")
	if err != nil {
		return err
	}
	want, err := checksumFor(checksums, name)
	if err != nil {
		return err
	}
	sum := sha256.Sum256(archive)
	if got := hex.EncodeToString(sum[:]); got != want {
		return fmt.Errorf("checksum mismatch for %s: got %s want %s", name, got, want)
	}

	binary, err := extractBinary(archive)
	if err != nil {
		return err
	}
	tmp, err := os.CreateTemp(filepath.Dir(dst), ".stoei-update-*")
	if err != nil {
		return err
	}
	tmpName := tmp.Name()
	if _, err := tmp.Write(binary); err != nil {
		tmp.Close()        //nolint:errcheck
		os.Remove(tmpName) //nolint:errcheck
		return err
	}
	if err := tmp.Close(); err != nil {
		os.Remove(tmpName) //nolint:errcheck
		return err
	}
	if err := os.Chmod(tmpName, 0o755); err != nil {
		os.Remove(tmpName) //nolint:errcheck
		return err
	}
	if err := os.Rename(tmpName, dst); err != nil {
		os.Remove(tmpName) //nolint:errcheck
		return err
	}
	return nil
}

// Run drives the "stoei update" subcommand: resolve the latest release, compare
// against the running version, and replace the current executable. Output goes
// to w in the compact "current → latest" form.
func Run(w io.Writer, currentVersion string) error {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
	defer cancel()

	latest, err := Latest(ctx)
	if err != nil {
		return err
	}
	fmt.Fprintf(w, "current %s → latest %s\n", currentVersion, latest) //nolint:errcheck
	if _, ok := parseSemver(currentVersion); ok && !IsNewer(currentVersion, latest) {
		fmt.Fprintln(w, "already up to date") //nolint:errcheck
		return nil
	}

	exe, err := os.Executable()
	if err != nil {
		return err
	}
	exe, err = filepath.EvalSymlinks(exe)
	if err != nil {
		return err
	}
	if err := Apply(ctx, latest, exe); err != nil {
		return err
	}
	fmt.Fprintf(w, "downloaded %s ✓ checksum\nupdated %s\n", assetName(latest), exe) //nolint:errcheck
	return nil
}
