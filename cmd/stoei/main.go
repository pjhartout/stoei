// Command stoei is a terminal UI for monitoring Slurm jobs.
package main

import (
	"fmt"
	"io"
	"os"
	"time"

	tea "charm.land/bubbletea/v2"

	"github.com/pjhartout/stoei/internal/config"
	"github.com/pjhartout/stoei/internal/slurm"
	"github.com/pjhartout/stoei/internal/store"
	"github.com/pjhartout/stoei/internal/ui"
	"github.com/pjhartout/stoei/internal/ui/components"
	"github.com/pjhartout/stoei/internal/update"
)

// version is the build version, set at release time via
// -ldflags "-X main.version=...". Local builds report "dev".
var version = "dev"

// usage prints the CLI surface: the TUI launches with no arguments.
func usage(w io.Writer) {
	_, _ = fmt.Fprintln(w, `stoei — a terminal UI for monitoring Slurm jobs

Usage:
  stoei            launch the TUI
  stoei update     replace this binary with the latest release
  stoei reset      clear the persistent job journal
  stoei version    print the version`)
}

func main() {
	if len(os.Args) > 1 {
		switch os.Args[1] {
		case "--version", "-v", "version":
			fmt.Println("stoei", version)
			return
		case "--help", "-h", "help":
			usage(os.Stdout)
			return
		case "reset":
			// Clear the persistent job journal and the sacct reconcile stamp,
			// starting the local history fresh with an immediate backfill.
			if path := slurm.JournalPath(); path != "" {
				for _, p := range []string{path, slurm.AcctStampPath(path)} {
					if err := os.Remove(p); err != nil && !os.IsNotExist(err) {
						fmt.Fprintln(os.Stderr, "stoei: reset failed:", err)
						os.Exit(1)
					}
				}
			}
			fmt.Println("stoei: cleared the job journal")
			return
		case "update":
			// Self-update: replace this binary with the latest GitHub release.
			if err := update.Run(os.Stdout, version); err != nil {
				fmt.Fprintln(os.Stderr, "stoei: update failed:", err)
				os.Exit(1)
			}
			return
		default:
			fmt.Fprintf(os.Stderr, "stoei: unknown command %q\n\n", os.Args[1])
			usage(os.Stderr)
			os.Exit(2)
		}
	}

	st := store.New()

	// Resolve and load the user config; a missing file yields defaults. The path
	// is threaded into the model so the settings modal persists changes there.
	cfgPath, err := config.Path()
	if err != nil {
		fmt.Fprintln(os.Stderr, "stoei: cannot resolve config path:", err)
		os.Exit(1)
	}
	cfg, err := config.LoadFile(cfgPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, "stoei: failed to load config, using defaults:", err)
		cfg = config.Default()
	}

	// Wire the one-way dependency chain: a Runner shells out to Slurm, the Client
	// builds/parses commands, the Store holds the data, and the root model renders
	// it. Job history comes from the controller ("scontrol show jobs")
	// accumulated into a persistent on-disk journal, reconciled against a single
	// nightly sacct query; squeue, scontrol, and the rest run live. Every command
	// the runner executes is reported to the in-memory log ring the Logs tab
	// renders. The alt-screen is a View field in Bubble Tea v2, so NewProgram
	// takes just the model.
	ring := components.NewLogRing(components.DefaultMaxLogLines)
	runner := slurm.LoggedRunner{
		Inner: slurm.ExecRunner{},
		Log:   func(level, msg string) { ring.Append(level, msg, time.Now()) },
	}
	client := slurm.NewClient(runner, slurm.WithJournal(slurm.JournalPath()))

	p := tea.NewProgram(ui.NewWithConfig(st, client, ring, cfg, cfgPath).WithVersion(version))
	if _, err := p.Run(); err != nil {
		fmt.Fprintln(os.Stderr, "stoei:", err)
		os.Exit(1)
	}
}
