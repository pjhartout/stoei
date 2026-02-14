# Common setup for all demo tapes - Source this at the top
# Sets up PATH for homebrew/uv, mock SLURM commands, and nord theme
#
# NOTE: Update the paths below if your project or homebrew location differs

Hide
Type "export PATH=/opt/homebrew/bin:$PATH"
Enter
Sleep 0.3s
Type "cd /Users/pjh/Documents/Git/stoei"
Enter
Sleep 0.3s
Type "export PATH=$PWD/tests/mocks:$PATH"
Enter
Sleep 0.3s
Type "export STOEI_CONFIG_DIR=/tmp/stoei-demo-config"
Enter
Sleep 0.3s
Type "mkdir -p /tmp/stoei-demo-config"
Enter
Sleep 0.3s
Type `printf '{"theme":"nord","energy_loading_enabled":true}' > /tmp/stoei-demo-config/settings.json`
Enter
Sleep 0.3s
Type "clear"
Enter
Sleep 0.3s
# NOTE: stays hidden — each tape calls Show when ready
