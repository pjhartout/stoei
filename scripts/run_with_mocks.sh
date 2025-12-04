#!/bin/bash
# Run stoei with mock SLURM commands for testing without a real cluster.
#
# Usage:
#   ./scripts/run_with_mocks.sh
#
# This prepends the tests/mocks directory to PATH so that squeue, sacct,
# and scontrol use the mock implementations.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
MOCKS_DIR="$PROJECT_DIR/tests/mocks"

export PATH="$MOCKS_DIR:$PATH"

echo "🧪 Running stoei with mock SLURM commands..."
echo "   Mock executables: $MOCKS_DIR"
echo ""

cd "$PROJECT_DIR" && uv run stoei "$@"
