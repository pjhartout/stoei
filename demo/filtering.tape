# STOEI Demo: Quick Filter
# Filter jobs by state, then clear the filter

Output "demo/filtering.gif"

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

# Hidden setup + launch + wait for load
Source "demo/setup.tape"
Hide
Type "stoei"
Enter
Sleep 8s
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
