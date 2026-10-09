#!/data/data/com.termux/files/usr/bin/bash
# Copy the roadbean shortcuts where Termux:Widget finds them.
set -e
here="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$HOME/.shortcuts" "$HOME/roadbean/inbox"
for f in "$here"/shortcuts/rb-*; do
  install -m 755 "$f" "$HOME/.shortcuts/$(basename "$f")"
done
echo "Installed to ~/.shortcuts. Needs: pkg install termux-api git ffmpeg; Termux:API and Termux:Widget apps."
echo "Run: termux-microphone-record once by hand to grant microphone permission."
