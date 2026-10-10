#!/data/data/com.termux/files/usr/bin/bash
# Copy the roadbean shortcuts where Termux:Widget finds them.
# They go in ~/.shortcuts/tasks/ so a tap runs in the background instead of opening a terminal.
set -e
here="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$HOME/.shortcuts/tasks" "$HOME/roadbean/inbox"
for f in "$here"/shortcuts/rb-*; do
  name="$(basename "$f")"
  rm -f "$HOME/.shortcuts/$name"                      # older installs put them one level up (opens a terminal)
  install -m 755 "$f" "$HOME/.shortcuts/tasks/$name"
done
echo "Installed to ~/.shortcuts/tasks. Needs: pkg install termux-api git ffmpeg; Termux:API and Termux:Widget apps."
echo "Next: grant the microphone (run 'termux-microphone-record -d' once), then bash termux/init-repo.sh <private git remote>."
