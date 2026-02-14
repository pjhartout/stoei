# STOEI Demo: Nodes Tab
# View nodes and sort columns

Output "demo/nodes.gif"

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

# Hidden setup + launch + wait for load + navigate to Nodes tab
Source "demo/setup.tape"
Hide
Type "stoei"
Enter
Sleep 8s
Type "2"
Sleep 1s
Show

# Show the Nodes tab
Sleep 1s

# Sort nodes
Type "o"
Sleep 1s
Type "o"
Sleep 1.5s

# Quit
Type "q"
Sleep 0.5s
