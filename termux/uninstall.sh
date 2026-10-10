#!/data/data/com.termux/files/usr/bin/bash
# Remove the roadbean shortcuts from Termux:Widget. Your memos are kept unless you pass --purge.
#   bash termux/uninstall.sh            # remove shortcuts only
#   bash termux/uninstall.sh --purge    # also delete $RB_HOME (default ~/roadbean), including the inbox
set -e
RB_HOME="${RB_HOME:-$HOME/roadbean}"

termux-microphone-record -q >/dev/null 2>&1 || true   # stop a recording left running

for name in rb-memo rb-sync rb-photo; do
  for dir in "$HOME/.shortcuts/tasks" "$HOME/.shortcuts"; do   # tasks/ is current; the top level is from older installs
    if [ -e "$dir/$name" ]; then
      rm -f "$dir/$name"
      echo "removed ${dir/#$HOME/\~}/$name"
    fi
  done
done
rm -f "$RB_HOME/.recording"

if [ "$1" = "--purge" ]; then
  if [ -d "$RB_HOME" ]; then
    printf 'Delete %s and every memo/photo in it? [y/N] ' "$RB_HOME"
    read -r answer
    case "$answer" in
      y|Y) rm -rf "$RB_HOME"; echo "deleted $RB_HOME" ;;
      *)   echo "kept $RB_HOME" ;;
    esac
  fi
else
  echo "Kept $RB_HOME (memos and photos). Re-run with --purge to delete it."
fi
echo "Remove the widgets from your home screen by hand; Termux:Widget can't do that for you."
