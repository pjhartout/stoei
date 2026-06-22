// Package store holds the application's data layer. It owns the Slurm datasets
// (running jobs, history, nodes, fair share, priority, energy, derived cluster
// stats), each with its own load state and request generation, and exposes pure
// derive helpers. The store is mutated only inside the root Update; tabs and
// modals render from it and never fetch.
//
// Layering: store depends on slurm, never on ui.
package store
