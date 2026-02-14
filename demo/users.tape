# STOEI Demo: Users Tab
# View users and toggle between Running/Pending/Energy views

Output "demo/users.gif"

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

# Hidden setup + launch + wait for load + navigate to Users tab
Source "demo/setup.tape"
Hide
Type "stoei"
Enter
Sleep 8s
Type "3"
Sleep 1s
Show

# Show the Users tab (defaults to Running view)
Sleep 2s

# Switch to Pending view
Type "p"
Sleep 2s

# Switch to Energy view
Type "e"
Sleep 2s

# Quit
Type "q"
Sleep 0.5s
