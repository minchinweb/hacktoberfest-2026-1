#!/data/data/com.termux/files/usr/bin/bash
# Make ~/roadbean a git repo whose remote is where your laptop pulls memos from.
#   bash termux/init-repo.sh git@github.com:YOU/roadbean-inbox.git
# The remote must be PRIVATE: memos contain your voice, client names and (optionally) locations.
set -e
REMOTE="${1:?usage: init-repo.sh <git remote url>}"
RB_HOME="${RB_HOME:-$HOME/roadbean}"
mkdir -p "$RB_HOME/inbox"
cd "$RB_HOME"
[ -d .git ] || git init -q -b main
cat > .gitignore <<'IGN'
.recording
# generated on the laptop by `roadbean process`; keep them out of sync so pulls never conflict
*.transcript.txt
*.extract.json
IGN
git config user.name  >/dev/null || git config user.name  "roadbean phone"
git config user.email >/dev/null || git config user.email "roadbean@localhost"
git remote get-url origin >/dev/null 2>&1 && git remote set-url origin "$REMOTE" || git remote add origin "$REMOTE"
touch inbox/.gitkeep
git add .gitignore inbox/.gitkeep
git commit -qm "roadbean inbox" 2>/dev/null || true
git push -u origin main
echo "Done. Test it: tap rb-memo twice, then rb-sync, then 'git pull' in your laptop clone."
