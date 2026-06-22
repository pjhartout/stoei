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

func main() {
	// Wire the one-way dependency chain: an ExecRunner shells out to Slurm, the
	// Client builds/parses commands, the Store holds the data, and the root model
	// renders it. The alt-screen is a View field in Bubble Tea v2, so NewProgram
	// takes just the model.
	client := slurm.NewClient(slurm.ExecRunner{})
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

	ring := components.NewLogRing(components.DefaultMaxLogLines)
	p := tea.NewProgram(ui.NewWithConfig(st, client, ring, cfg, cfgPath))
	if _, err := p.Run(); err != nil {
		fmt.Fprintln(os.Stderr, "stoei:", err)
		os.Exit(1)
	}
}
