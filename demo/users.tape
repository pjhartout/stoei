# STOEI Demo: Users Tab
# View users and toggle between Running/Pending/Energy views

Output "demo/users.gif"

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

# Hidden setup + launch + wait for load + navigate to Users tab
Source "demo/setup.tape"
Hide
Type "stoei"
Enter
Sleep 8s
Type "3"
Sleep 1s
Show

# Show the Users tab
Sleep 1s

# Toggle views
Type "r"
Sleep 1s
Type "p"
Sleep 1s
Type "e"
Sleep 1s

# Quit
Type "q"
Sleep 0.5s
