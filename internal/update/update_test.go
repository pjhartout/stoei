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
	"strings"
	"testing"
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
