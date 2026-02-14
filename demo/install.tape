# STOEI Demo: Install & Launch
# Records the uv tool install + first launch with loading screen

Output "demo/install.mp4"

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
