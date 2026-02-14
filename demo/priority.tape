# STOEI Demo: Priority Tab
# View priority and toggle between Users/Accounts/Jobs views

Output "demo/priority.gif"

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

# Hidden setup + launch + wait for load + navigate to Priority tab
Source "demo/setup.tape"
Hide
Type "stoei"
Enter
Sleep 8s
Type "4"
Sleep 1s
Show

# Show the Priority tab
Sleep 1s

# Toggle views
Type "u"
Sleep 1s
Type "a"
Sleep 1s
Type "j"
Sleep 1s

# Quit
Type "q"
Sleep 0.5s
