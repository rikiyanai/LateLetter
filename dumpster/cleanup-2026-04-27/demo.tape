# LateLetter TUI Demo Recording
# Run: vhs demo.tape

Output demo.gif

Set Shell zsh
Set FontFamily "Courier New"
Set FontSize 14
Set Width 960
Set Height 600
Set Padding 10
Set Framerate 20
Set Theme "Builtin Dark"

# Activate venv and start demo
Type "source .venv/bin/activate && python3 demo_recipient.py --arc delivery --season autumn"
Enter
Sleep 2s

# Press Enter to open the garden
Enter
Sleep 4s

# Press e to unlock (open passphrase)
Type "e"
Sleep 1s

# Type passphrase
Type "biscuit"
Sleep 500ms
Enter

# Wait for verification spinner + bird animation + letter
Sleep 5s

# Read the letter for a moment
Sleep 3s

# Quit
Type "q"
Sleep 500ms
