# STOEI Demo: Quick Filter
# Filter jobs by state, then clear the filter

Output "demo/filtering.mp4"

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

# Hidden setup + launch + wait for load
Source "demo/setup.tape"
Hide
Type "stoei"
Enter
Sleep 5s
Show

# Show the Jobs tab briefly
Sleep 0.5s

# Open filter
Type "/"
Sleep 0.5s

# Type filter expression
Type "state:RUNNING"
Enter
Sleep 2s

# Clear filter
Escape
Sleep 1.5s

# Quit
Type "q"
Sleep 0.5s
