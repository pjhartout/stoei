// Command stoei is a terminal UI for monitoring Slurm jobs.
package main

import (
	"fmt"
	"os"

	tea "charm.land/bubbletea/v2"

	"github.com/pjhartout/stoei/internal/ui"
)

func main() {
	// In Bubble Tea v2 the alt-screen is a field on the View, not a program
	// option, so NewProgram takes just the model here.
	p := tea.NewProgram(ui.New())
	if _, err := p.Run(); err != nil {
		fmt.Fprintln(os.Stderr, "stoei:", err)
		os.Exit(1)
	}
}
