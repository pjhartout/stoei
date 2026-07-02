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

### Local debug build

To make the `stoei` command run your working copy — a live build that recompiles
on each launch — symlink the dev wrapper onto your `PATH`:

```bash
ln -sf "$(pwd)/scripts/stoei-dev" ~/.local/bin/stoei   # ~/.local/bin must be on $PATH
```

Now `stoei` runs `go run ./cmd/stoei` from this checkout, always reflecting your
edits. If a release binary or the old Python tool is still installed, make sure
`~/.local/bin` comes first on your `PATH` so the wrapper wins. Prefer a fast
prebuilt binary over recompiling each launch? Build once and rebuild after
changes:

```bash
go build -o ~/.local/bin/stoei ./cmd/stoei
```

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

Run `scripts/release <version>` — it verifies a clean, gated `main`, then tags
and pushes so GoReleaser builds and publishes the binaries.
