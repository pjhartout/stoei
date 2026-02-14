# STOEI Demo: Jobs Tab
# Navigate rows and sort columns

Output "demo/jobs.mp4"

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
