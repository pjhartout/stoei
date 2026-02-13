# STOEI Demo
# Full walkthrough: install, launch, explore panes, sort columns

Output "demo/demo.gif"
Output "demo/demo.mp4"

Set FontSize 14
Set Width 1400
Set Height 800
Set Framerate 30
Set PlaybackSpeed 1.5
Set TypingSpeed 30ms
Set Theme "nord"
Set WindowBar Colorful
Set WindowBarSize 40
Set Padding 10

# Hidden setup: PATH, mocks, nord config
Source "demo/setup.tape"

# -- Act 1: Install stoei as a uv tool --
Type "uv tool install ."
Enter
Sleep 5s

# -- Act 2: Launch --
Type "stoei"
Enter

# Loading screen
Sleep 7s

# -- Act 3: Jobs tab (default) --
Sleep 2s

# Navigate the job list
Type "j"
Sleep 0.2s
Type "j"
Sleep 0.2s
Type "j"
Sleep 0.2s
Type "j"
Sleep 1s

# Sort columns
Type "o"
Sleep 1s
Type "o"
Sleep 1s
Type "o"
Sleep 1.5s

# -- Act 4: Nodes tab --
Type "2"
Sleep 2s

# Sort nodes
Type "o"
Sleep 1s
Type "o"
Sleep 1.5s

# -- Act 5: Users tab --
Type "3"
Sleep 2s

# -- Act 6: Priority tab --
Type "4"
Sleep 2s

# -- Act 7: Back to Jobs, quick filter --
Type "1"
Sleep 1s

Type "/"
Sleep 0.5s
Type "state:RUNNING"
Enter
Sleep 1.5s

# Clear filter
Escape
Sleep 1s

# -- Act 8: Quit --
Type "q"
Sleep 1s
