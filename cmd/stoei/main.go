// Command stoei is a terminal UI for monitoring Slurm jobs.
package main

import (
	"fmt"
	"os"

	tea "charm.land/bubbletea/v2"

	"github.com/pjhartout/stoei/internal/slurm"
	"github.com/pjhartout/stoei/internal/store"
	"github.com/pjhartout/stoei/internal/ui"
)

func main() {
	// Wire the one-way dependency chain: an ExecRunner shells out to Slurm, the
	// Client builds/parses commands, the Store holds the data, and the root model
	// renders it. The alt-screen is a View field in Bubble Tea v2, so NewProgram
	// takes just the model.
	client := slurm.NewClient(slurm.ExecRunner{})
	st := store.New()
	p := tea.NewProgram(ui.New(st, client))
	if _, err := p.Run(); err != nil {
		fmt.Fprintln(os.Stderr, "stoei:", err)
		os.Exit(1)
	}
}
