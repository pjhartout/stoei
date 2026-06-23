# Common setup for all demo tapes - Source this at the top.
# Puts the freshly-built stoei binary and mock SLURM commands on PATH, points
# the mocks at the golden fixtures, and writes a clean nord config with energy on.
#
# Assumes record.sh has already cd'd to the project root and built demo/bin/stoei.

Hide
Type "export PATH=$PWD/demo/bin:$PWD/tests/mocks:/opt/homebrew/bin:$PATH"
Enter
Sleep 0.2s
Type "export STOEI_DEMO_DATA=$PWD/internal/slurm/testdata"
Enter
Sleep 0.2s
Type "export STOEI_CONFIG_DIR=/tmp/stoei-demo-config XDG_CACHE_HOME=/tmp/stoei-demo-cache"
Enter
Sleep 0.2s
Type "rm -rf /tmp/stoei-demo-config /tmp/stoei-demo-cache && mkdir -p /tmp/stoei-demo-config"
Enter
Sleep 0.2s
Type `printf 'theme: nord\nenergy_enabled: true\n' > /tmp/stoei-demo-config/config.yaml`
Enter
Sleep 0.2s
Type "clear"
Enter
Sleep 0.3s
# NOTE: stays hidden — each tape calls Show when ready
