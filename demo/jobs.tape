# STOEI Demo: Jobs Tab
# Navigate rows and sort columns

Output "demo/jobs.gif"

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

# Jobs tab is the default — show it
Sleep 1s

# Navigate the job list
Type "j"
Sleep 0.3s
Type "j"
Sleep 0.3s
Type "j"
Sleep 0.3s
Type "j"
Sleep 1s

# Sort columns
Type "o"
Sleep 1s
Type "o"
Sleep 1s
Type "o"
Sleep 1.5s

# Quit
Type "q"
Sleep 0.5s
