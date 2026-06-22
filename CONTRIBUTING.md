# Contributing to Stoei

Thanks for your interest in contributing!

## Prerequisites

- Go 1.25 or newer (the Charm v2 modules require it)
- [golangci-lint](https://golangci-lint.run/) for linting
- Optionally, a Slurm login node for manual testing

## Setup

```bash
git clone https://github.com/pjhartout/stoei.git
cd stoei
go build ./...
pre-commit install   # optional: runs gofmt/vet/golangci-lint on commit
```

Run the app with `go run ./cmd/stoei`.

## Layout

```
cmd/stoei/        # main entry point
internal/slurm/   # Slurm command runner, parsers, types
internal/store/   # data store + derivations (cluster stats, energy, wait times)
internal/ui/      # Bubble Tea root model, tabs, modals, components, theme
internal/config/  # config load/save + defaults
```

Dependencies flow one way: `ui → store → slurm`, enforced by depguard in
`.golangci.yml`. Keep that direction — the store never imports the UI, and the
slurm package never imports the store. The test seams are `slurm.Runner`,
`store.SlurmClient`, and the UI `Modal`/`Component` interfaces.

## Checks

Run before pushing (CI in `.github/workflows/go.yml` runs the same):

```bash
gofmt -l .            # must print nothing
go vet ./...
golangci-lint run
go test ./... -race
```

## Tests

- Tests MUST NOT shell out to a real scheduler. Use the `slurm.Runner` /
  `store.SlurmClient` fakes and the golden fixtures under
  `internal/slurm/testdata/`.
- No sleeps and no wall-clock — inject clocks where time matters.
- Do not run the TUI itself in automation; it blocks on a terminal.

## Pull requests

- Keep the `ui → store → slurm` dependency direction intact.
- PR descriptions are a summary of the changes only — no test-plan or checklist
  sections.
- Do not add AI co-author trailers.

## Releases

Push a `v*` tag; GoReleaser builds and publishes the binaries.
