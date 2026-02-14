# STOEI Demo: Install & Launch
# Records the uv tool install + first launch with loading screen

Output "demo/install.gif"

Set FontSize 18
Set Width 1000
Set Height 600
Set Framerate 15
Set PlaybackSpeed 1.0
Set TypingSpeed 30ms
Set Theme "nord"
Set WindowBar Colorful
Set WindowBarSize 30
Set Padding 8

# Hidden setup: PATH, mocks, nord config
Source "demo/setup.tape"
Show

# -- Install stoei as a uv tool --
Type "uv tool install ."
Enter
Sleep 5s

# -- Launch --
Type "stoei"
Enter

# Loading screen + app ready
Sleep 7s

# Quit
Type "q"
Sleep 0.5s
