// Command stoei is a terminal UI for monitoring Slurm jobs.
package main

import (
	"fmt"
	"os"

	tea "charm.land/bubbletea/v2"

	"github.com/pjhartout/stoei/internal/config"
	"github.com/pjhartout/stoei/internal/slurm"
	"github.com/pjhartout/stoei/internal/store"
	"github.com/pjhartout/stoei/internal/ui"
	"github.com/pjhartout/stoei/internal/ui/components"
)

// version is the build version, set at release time via
// -ldflags "-X main.version=...". Local builds report "dev".
var version = "dev"

func main() {
	if len(os.Args) > 1 {
		switch os.Args[1] {
		case "--version", "-v", "version":
			fmt.Println("stoei", version)
			return
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
	// it. Job history/energy/wait-time come from the controller ("scontrol show
	// jobs") accumulated into a persistent on-disk journal — never slurmdbd/sacct —
	// so the head node is not queried at all; squeue, scontrol, and the rest run
	// live. The alt-screen is a View field in Bubble Tea v2, so NewProgram takes
	// just the model.
	client := slurm.NewClient(slurm.ExecRunner{}, slurm.WithJournal(slurm.JournalPath()))

	ring := components.NewLogRing(components.DefaultMaxLogLines)
	p := tea.NewProgram(ui.NewWithConfig(st, client, ring, cfg, cfgPath))
	if _, err := p.Run(); err != nil {
		fmt.Fprintln(os.Stderr, "stoei:", err)
		os.Exit(1)
	}
}
