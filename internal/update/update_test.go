package update

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"testing"
	"time"
)

func TestIsNewer(t *testing.T) {
	cases := []struct {
		current, latest string
		want            bool
	}{
		{"v0.10.0", "v0.10.1", true},
		{"v0.10.0", "v0.11.0", true},
		{"v0.10.0", "v1.0.0", true},
		{"v0.10.0", "v0.10.0", false},
		{"v0.11.0", "v0.10.9", false},
		{"0.9.0", "v0.10.0", true}, // bare and v-prefixed forms mix
		{"dev", "v99.0.0", false},  // local builds are never "outdated"
		{"v0.10.0", "nightly", false},
	}
	for _, c := range cases {
		if got := IsNewer(c.current, c.latest); got != c.want {
			t.Errorf("IsNewer(%q, %q) = %v; want %v", c.current, c.latest, got, c.want)
		}
	}
}

func TestChecksumFor(t *testing.T) {
	body := []byte("abc123  stoei_0.10.0_linux_amd64.tar.gz\ndef456  stoei_0.10.0_darwin_arm64.tar.gz\n")
	got, err := checksumFor(body, "stoei_0.10.0_darwin_arm64.tar.gz")
	if err != nil || got != "def456" {
		t.Errorf("checksumFor = %q, %v; want def456", got, err)
	}
	if _, err := checksumFor(body, "missing.tar.gz"); err == nil {
		t.Error("missing asset should error")
	}
}

// tarGz builds an in-memory release archive holding the named file.
func tarGz(t *testing.T, name string, content []byte) []byte {
	t.Helper()
	var buf bytes.Buffer
	gz := gzip.NewWriter(&buf)
	tw := tar.NewWriter(gz)
	if err := tw.WriteHeader(&tar.Header{Name: name, Mode: 0o755, Size: int64(len(content))}); err != nil {
		t.Fatal(err)
	}
	if _, err := tw.Write(content); err != nil {
		t.Fatal(err)
	}
	if err := tw.Close(); err != nil {
		t.Fatal(err)
	}
	if err := gz.Close(); err != nil {
		t.Fatal(err)
	}
	return buf.Bytes()
}

func TestExtractBinary(t *testing.T) {
	want := []byte("fake-binary")
	got, err := extractBinary(tarGz(t, "stoei", want))
	if err != nil || !bytes.Equal(got, want) {
		t.Errorf("extractBinary = %q, %v; want %q", got, err, want)
	}
	if _, err := extractBinary(tarGz(t, "README.md", []byte("nope"))); err == nil {
		t.Error("archive without the binary should error")
	}
}

// TestApplyEndToEnd drives Apply against a local test server: download, verify,
// and atomically replace the destination binary.
func TestApplyEndToEnd(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("self-update unsupported on windows")
	}
	newBinary := []byte("#!/bin/sh\necho new\n")
	asset := assetName("v0.11.0")
	archive := tarGz(t, "stoei", newBinary)
	sum := sha256.Sum256(archive)
	checksums := hex.EncodeToString(sum[:]) + "  " + asset + "\n"

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case strings.HasSuffix(r.URL.Path, asset):
			w.Write(archive) //nolint:errcheck
		case strings.HasSuffix(r.URL.Path, "checksums.txt"):
			w.Write([]byte(checksums)) //nolint:errcheck
		default:
			http.NotFound(w, r)
		}
	}))
	defer srv.Close()
	oldBase := downloadBase
	downloadBase = srv.URL
	defer func() { downloadBase = oldBase }()

	dst := filepath.Join(t.TempDir(), "stoei")
	if err := os.WriteFile(dst, []byte("old"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := Apply(context.Background(), "v0.11.0", dst); err != nil {
		t.Fatalf("Apply: %v", err)
	}
	got, err := os.ReadFile(dst)
	if err != nil || !bytes.Equal(got, newBinary) {
		t.Errorf("dst = %q, %v; want the new binary", got, err)
	}
	if info, _ := os.Stat(dst); info.Mode().Perm() != 0o755 {
		t.Errorf("dst mode = %v; want 0755", info.Mode().Perm())
	}
}

// TestApplyRejectsBadChecksum asserts a tampered archive never reaches dst.
func TestApplyRejectsBadChecksum(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("self-update unsupported on windows")
	}
	asset := assetName("v0.11.0")
	archive := tarGz(t, "stoei", []byte("evil"))
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasSuffix(r.URL.Path, asset) {
			w.Write(archive) //nolint:errcheck
			return
		}
		w.Write([]byte("deadbeef  " + asset + "\n")) //nolint:errcheck
	}))
	defer srv.Close()
	oldBase := downloadBase
	downloadBase = srv.URL
	defer func() { downloadBase = oldBase }()

	dst := filepath.Join(t.TempDir(), "stoei")
	if err := os.WriteFile(dst, []byte("old"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := Apply(context.Background(), "v0.11.0", dst); err == nil ||
		!strings.Contains(err.Error(), "checksum mismatch") {
		t.Fatalf("Apply = %v; want checksum mismatch", err)
	}
	if got, _ := os.ReadFile(dst); string(got) != "old" {
		t.Errorf("dst overwritten despite bad checksum: %q", got)
	}
}

// TestLatestParsesRelease drives Latest against a local API stub.
func TestLatestParsesRelease(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Write([]byte(`{"tag_name":"v0.11.0"}`)) //nolint:errcheck
	}))
	defer srv.Close()
	oldBase := apiBase
	apiBase = srv.URL
	defer func() { apiBase = oldBase }()

	tag, err := Latest(context.Background())
	if err != nil || tag != "v0.11.0" {
		t.Errorf("Latest = %q, %v; want v0.11.0", tag, err)
	}
}

// stubBase points a base-URL variable at a local test server for the test's duration.
func stubBase(t *testing.T, base *string, h http.HandlerFunc) {
	t.Helper()
	srv := httptest.NewServer(h)
	old := *base
	*base = srv.URL
	t.Cleanup(func() { *base = old; srv.Close() })
}

// isolateCache redirects the user cache dir into a temp dir and returns the cache file path.
func isolateCache(t *testing.T) string {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("cache isolation relies on unix cache env vars")
	}
	dir := t.TempDir()
	t.Setenv("XDG_CACHE_HOME", dir)
	t.Setenv("HOME", dir)
	base, err := os.UserCacheDir()
	if err != nil {
		t.Fatalf("UserCacheDir: %v", err)
	}
	return filepath.Join(base, "stoei", "latest-release")
}

// writeCache seeds the cache file with tag stamped at unix time ts.
func writeCache(t *testing.T, path, tag string, ts int64) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(tag+" "+strconv.FormatInt(ts, 10)+"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
}

// TestLatestErrors asserts HTTP failures, bad JSON, and empty tags all fail the release lookup.
func TestLatestErrors(t *testing.T) {
	cases := []struct {
		name, body string
		status     int
	}{
		{"http error", "", http.StatusInternalServerError},
		{"bad json", "{", http.StatusOK},
		{"empty tag", `{"tag_name":""}`, http.StatusOK},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			stubBase(t, &apiBase, func(w http.ResponseWriter, _ *http.Request) {
				w.WriteHeader(c.status)
				w.Write([]byte(c.body)) //nolint:errcheck
			})
			if _, err := Latest(context.Background()); err == nil {
				t.Error("expected error")
			}
		})
	}
}

// TestLatestRejectsMalformedBase asserts a bad API base fails request construction without any IO.
func TestLatestRejectsMalformedBase(t *testing.T) {
	old := apiBase
	apiBase = "://bad"
	t.Cleanup(func() { apiBase = old })
	if _, err := Latest(context.Background()); err == nil {
		t.Error("expected error for malformed API base")
	}
}

// TestIsRelease asserts only full numeric semver tags count as release builds.
func TestIsRelease(t *testing.T) {
	cases := []struct {
		v    string
		want bool
	}{
		{"v1.2.3", true},
		{"1.2.3", true},
		{" v1.2.3\n", true},
		{"dev", false},
		{"", false},
		{"v1.2", false},
		{"v1.2.3.4", false},
		{"v1.-2.3", false},
	}
	for _, c := range cases {
		if got := IsRelease(c.v); got != c.want {
			t.Errorf("IsRelease(%q) = %v; want %v", c.v, got, c.want)
		}
	}
}

// TestAssetNameEmbedsPlatform asserts the artifact name strips the v prefix and targets the running platform.
func TestAssetNameEmbedsPlatform(t *testing.T) {
	got := assetName("v0.11.0")
	if !strings.HasPrefix(got, "stoei_0.11.0_") {
		t.Errorf("assetName = %q; want stoei_0.11.0_ prefix", got)
	}
	if !strings.Contains(got, runtime.GOOS+"_"+runtime.GOARCH) {
		t.Errorf("assetName = %q; want %s_%s platform", got, runtime.GOOS, runtime.GOARCH)
	}
}

// tarEntry describes one file in a synthetic release archive.
type tarEntry struct {
	name     string
	typeflag byte
	content  []byte
}

// tarGzEntries builds an in-memory archive from a list of entries.
func tarGzEntries(t *testing.T, entries []tarEntry) []byte {
	t.Helper()
	var buf bytes.Buffer
	gz := gzip.NewWriter(&buf)
	tw := tar.NewWriter(gz)
	for _, e := range entries {
		hdr := &tar.Header{Name: e.name, Typeflag: e.typeflag, Mode: 0o755, Size: int64(len(e.content))}
		if err := tw.WriteHeader(hdr); err != nil {
			t.Fatal(err)
		}
		if _, err := tw.Write(e.content); err != nil {
			t.Fatal(err)
		}
	}
	if err := tw.Close(); err != nil {
		t.Fatal(err)
	}
	if err := gz.Close(); err != nil {
		t.Fatal(err)
	}
	return buf.Bytes()
}

// TestExtractBinarySkipsDecoys asserts extraction picks the regular stoei file over same-named directories and other entries.
func TestExtractBinarySkipsDecoys(t *testing.T) {
	want := []byte("real-binary")
	archive := tarGzEntries(t, []tarEntry{
		{"README.md", tar.TypeReg, []byte("docs")},
		{"stoei", tar.TypeDir, nil},
		{"bin/stoei.txt", tar.TypeReg, []byte("decoy")},
		{"stoei_0.11.0_linux_amd64/stoei", tar.TypeReg, want},
	})
	got, err := extractBinary(archive)
	if err != nil || !bytes.Equal(got, want) {
		t.Errorf("extractBinary = %q, %v; want %q", got, err, want)
	}
}

// TestExtractBinaryRejectsCorruptArchives asserts non-gzip bytes and gzip-wrapped non-tar data both error.
func TestExtractBinaryRejectsCorruptArchives(t *testing.T) {
	if _, err := extractBinary([]byte("not a gzip")); err == nil {
		t.Error("plain bytes should fail gzip decoding")
	}
	var buf bytes.Buffer
	gz := gzip.NewWriter(&buf)
	if _, err := gz.Write([]byte("not a tar stream")); err != nil {
		t.Fatal(err)
	}
	if err := gz.Close(); err != nil {
		t.Fatal(err)
	}
	if _, err := extractBinary(buf.Bytes()); err == nil {
		t.Error("gzip without a tar stream should fail")
	}
}

// TestLatestCachedFreshCacheSkipsNetwork asserts a fresh cache answers without any API call.
func TestLatestCachedFreshCacheSkipsNetwork(t *testing.T) {
	path := isolateCache(t)
	writeCache(t, path, "v9.9.9", time.Now().Unix())
	stubBase(t, &apiBase, func(http.ResponseWriter, *http.Request) {
		t.Error("unexpected API call with a fresh cache")
	})
	tag, err := LatestCached(context.Background())
	if err != nil || tag != "v9.9.9" {
		t.Errorf("LatestCached = %q, %v; want v9.9.9", tag, err)
	}
}

// TestLatestCachedStaleCacheSurvivesNetworkError asserts a stale cached tag beats a failed lookup.
func TestLatestCachedStaleCacheSurvivesNetworkError(t *testing.T) {
	path := isolateCache(t)
	writeCache(t, path, "v8.8.8", 1)
	stubBase(t, &apiBase, func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	})
	tag, err := LatestCached(context.Background())
	if err != nil || tag != "v8.8.8" {
		t.Errorf("LatestCached = %q, %v; want stale v8.8.8", tag, err)
	}
}

// TestLatestCachedFailsWithoutCacheOrNetwork asserts no cache plus a failed lookup surfaces the error.
func TestLatestCachedFailsWithoutCacheOrNetwork(t *testing.T) {
	isolateCache(t)
	stubBase(t, &apiBase, func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	})
	if tag, err := LatestCached(context.Background()); err == nil {
		t.Errorf("LatestCached = %q; want error", tag)
	}
}

// TestLatestCachedWritesThroughToCache asserts a successful lookup persists and later answers from cache.
func TestLatestCachedWritesThroughToCache(t *testing.T) {
	path := isolateCache(t)
	stubBase(t, &apiBase, func(w http.ResponseWriter, _ *http.Request) {
		w.Write([]byte(`{"tag_name":"v1.2.3"}`)) //nolint:errcheck
	})
	tag, err := LatestCached(context.Background())
	if err != nil || tag != "v1.2.3" {
		t.Fatalf("LatestCached = %q, %v; want v1.2.3", tag, err)
	}
	raw, err := os.ReadFile(path)
	if err != nil || !strings.HasPrefix(string(raw), "v1.2.3 ") {
		t.Errorf("cache file = %q, %v; want v1.2.3 prefix", raw, err)
	}
	stubBase(t, &apiBase, func(http.ResponseWriter, *http.Request) {
		t.Error("unexpected API call after the cache was primed")
	})
	tag, err = LatestCached(context.Background())
	if err != nil || tag != "v1.2.3" {
		t.Errorf("second LatestCached = %q, %v; want cached v1.2.3", tag, err)
	}
}

// TestReadCacheRejectsMalformedContent asserts malformed cache files are treated as absent.
func TestReadCacheRejectsMalformedContent(t *testing.T) {
	path := isolateCache(t)
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	for _, content := range []string{"v1.2.3", "v1.2.3 12 extra", "v1.2.3 notanumber"} {
		if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
			t.Fatal(err)
		}
		gotPath, tag, fresh := readCache()
		if gotPath != path || tag != "" || fresh {
			t.Errorf("readCache(%q) = %q, %q, %v; want path, empty, stale", content, gotPath, tag, fresh)
		}
	}
}

// TestReadCacheUnavailableDir asserts cache-dir failures disable caching without breaking the lookup.
func TestReadCacheUnavailableDir(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("relies on unix cache env vars")
	}
	t.Setenv("XDG_CACHE_HOME", "")
	t.Setenv("HOME", "")
	if path, tag, fresh := readCache(); path != "" || tag != "" || fresh {
		t.Errorf("readCache = %q, %q, %v; want disabled cache", path, tag, fresh)
	}
	stubBase(t, &apiBase, func(w http.ResponseWriter, _ *http.Request) {
		w.Write([]byte(`{"tag_name":"v1.2.3"}`)) //nolint:errcheck
	})
	if tag, err := LatestCached(context.Background()); err != nil || tag != "v1.2.3" {
		t.Errorf("LatestCached = %q, %v; want v1.2.3 without caching", tag, err)
	}
}

// TestReadCacheMkdirFailure asserts a file squatting on the cache dir disables caching.
func TestReadCacheMkdirFailure(t *testing.T) {
	path := isolateCache(t)
	if err := os.WriteFile(filepath.Dir(path), []byte("squatter"), 0o644); err != nil {
		t.Fatal(err)
	}
	if p, tag, fresh := readCache(); p != "" || tag != "" || fresh {
		t.Errorf("readCache = %q, %q, %v; want disabled cache", p, tag, fresh)
	}
}

// TestFetchRejectsMalformedURL asserts fetch fails fast on an unparsable URL without any IO.
func TestFetchRejectsMalformedURL(t *testing.T) {
	if _, err := fetch(context.Background(), "://bad-url"); err == nil {
		t.Error("expected error for malformed URL")
	}
}

// TestRunUpToDate asserts Run stops after the version report when nothing newer exists.
func TestRunUpToDate(t *testing.T) {
	stubBase(t, &apiBase, func(w http.ResponseWriter, _ *http.Request) {
		w.Write([]byte(`{"tag_name":"v0.5.0"}`)) //nolint:errcheck
	})
	var buf bytes.Buffer
	if err := Run(&buf, "v0.5.0"); err != nil {
		t.Fatalf("Run: %v", err)
	}
	out := buf.String()
	if !strings.Contains(out, "current v0.5.0 → latest v0.5.0") || !strings.Contains(out, "already up to date") {
		t.Errorf("Run output = %q; want up-to-date report", out)
	}
}

// TestRunSurfacesLookupFailure asserts Run propagates a failed release lookup.
func TestRunSurfacesLookupFailure(t *testing.T) {
	stubBase(t, &apiBase, func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	})
	var buf bytes.Buffer
	if err := Run(&buf, "v0.5.0"); err == nil {
		t.Error("expected error from failed lookup")
	}
}

// TestRunAbortsWhenDownloadFails asserts a dev build attempts the update but a failed download aborts safely.
func TestRunAbortsWhenDownloadFails(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("self-update unsupported on windows")
	}
	stubBase(t, &apiBase, func(w http.ResponseWriter, _ *http.Request) {
		w.Write([]byte(`{"tag_name":"v0.1.0"}`)) //nolint:errcheck
	})
	stubBase(t, &downloadBase, http.NotFound)
	var buf bytes.Buffer
	err := Run(&buf, "dev")
	if err == nil || !strings.Contains(err.Error(), "download") {
		t.Errorf("Run = %v; want download error", err)
	}
}

// TestApplyErrors asserts each pre-write failure aborts before touching the destination binary.
func TestApplyErrors(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("self-update unsupported on windows")
	}
	goodArchive := tarGz(t, "stoei", []byte("new-binary"))
	noBinArchive := tarGz(t, "README.md", []byte("docs"))
	asset := assetName("v0.11.0")
	sumOf := func(b []byte) string {
		s := sha256.Sum256(b)
		return hex.EncodeToString(s[:])
	}
	cases := []struct {
		name       string
		archive    []byte
		checksums  string // empty means the checksums download 404s
		missingDir bool
		dstIsDir   bool
		want       string
	}{
		{"checksums download fails", goodArchive, "", false, false, "download"},
		{"missing checksum entry", goodArchive, "deadbeef  other.tar.gz\n", false, false, "no checksum"},
		{"binary missing from archive", noBinArchive, sumOf(noBinArchive) + "  " + asset + "\n", false, false, "not found in archive"},
		{"unwritable destination", goodArchive, sumOf(goodArchive) + "  " + asset + "\n", true, false, ""},
		{"destination is a directory", goodArchive, sumOf(goodArchive) + "  " + asset + "\n", false, true, ""},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			stubBase(t, &downloadBase, func(w http.ResponseWriter, r *http.Request) {
				switch {
				case strings.HasSuffix(r.URL.Path, asset):
					w.Write(c.archive) //nolint:errcheck
				case strings.HasSuffix(r.URL.Path, "checksums.txt") && c.checksums != "":
					w.Write([]byte(c.checksums)) //nolint:errcheck
				default:
					http.NotFound(w, r)
				}
			})
			dir := t.TempDir()
			dst := filepath.Join(dir, "stoei")
			switch {
			case c.missingDir:
				dst = filepath.Join(dir, "missing", "stoei")
			case c.dstIsDir:
				if err := os.Mkdir(dst, 0o755); err != nil {
					t.Fatal(err)
				}
			default:
				if err := os.WriteFile(dst, []byte("old"), 0o755); err != nil {
					t.Fatal(err)
				}
			}
			err := Apply(context.Background(), "v0.11.0", dst)
			if err == nil || (c.want != "" && !strings.Contains(err.Error(), c.want)) {
				t.Fatalf("Apply = %v; want error containing %q", err, c.want)
			}
			if !c.missingDir && !c.dstIsDir {
				if got, _ := os.ReadFile(dst); string(got) != "old" {
					t.Errorf("dst modified on failure: %q", got)
				}
			}
		})
	}
}
