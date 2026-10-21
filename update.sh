#!/usr/bin/env bash
# Pull the latest code, add any new settings to .env (keeping your values), and restart the service.
# Run on the server:  bash /opt/constantinople/update.sh
set -e
cd /opt/constantinople
PREV=$(git rev-parse HEAD)
git pull -q
.venv/bin/pip install -q -r requirements.txt
if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null; then
  echo "installing ffmpeg (one time, ~1 min)…"; apt-get update -qq; apt-get install -y -qq ffmpeg fonts-dejavu-core >/dev/null || sudo apt-get install -y -qq ffmpeg fonts-dejavu-core >/dev/null
fi
command -v sqlite3 >/dev/null || apt-get install -y -qq sqlite3 >/dev/null 2>&1 || true
command -v ffprobe >/dev/null && echo "ffmpeg: ok" || echo "ffmpeg: MISSING — run: sudo apt-get install -y ffmpeg"
# a small server needs swap for video renders; create 2 GB once if there is none
if [ "$(swapon --show --noheadings | wc -l)" = "0" ] && [ ! -f /swapfile ]; then
  echo "adding 2 GB swap for video renders…"
  (fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none) && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile && grep -q "/swapfile" /etc/fstab || echo "/swapfile none swap sw 0 0" >> /etc/fstab
fi
free -h | awk '/Swap/{print "swap: " $2}'
# carry new keys from .env.example into .env with their defaults; never touch keys you already have
added=0
while IFS= read -r line; do
  key="${line%%=*}"
  [[ "$line" =~ ^[A-Z_]+= ]] || continue
  if ! grep -q "^${key}=" .env; then
    default="${line#*=}"; default="${default%%#*}"; default="${default%"${default##*[![:space:]]}"}"
    echo "${key}=${default}" >> .env; added=$((added+1))
  fi
done < .env.example
[ "$added" -gt 0 ] && echo "added $added new setting(s) to .env (defaults; edit with: bash station.sh env)"
systemctl restart constantinople
# health check: the engine must answer /state within 90 s, or we roll back to the previous version
PORT=$(grep -E "^PORT=" .env | cut -d= -f2); PORT=${PORT:-8787}
ok=0
for i in $(seq 1 30); do
  sleep 3
  if curl -fsS "http://127.0.0.1:${PORT}/state" >/dev/null 2>&1; then ok=1; break; fi
done
notify() { tok=$(grep -E "^TELEGRAM_BOT_TOKEN=" .env | cut -d= -f2); chat=$(sqlite3 constantinople.db "select v from kv where k='telegram_chat'" 2>/dev/null || true)
  [ -n "$tok" ] && [ -n "$chat" ] && curl -fsS -m 10 "https://api.telegram.org/bot${tok}/sendMessage" -d chat_id="$chat" --data-urlencode text="$1" >/dev/null 2>&1 || true; }
if [ "$ok" = "1" ]; then
  echo "Updated and running ($(git rev-parse --short HEAD))."
else
  echo "Engine did not come up after the update — rolling back to ${PREV:0:7}"
  journalctl -u constantinople -n 30 --no-pager | tail -15 || true
  git checkout -q "$PREV" && systemctl restart constantinople && sleep 5
  if systemctl is-active --quiet constantinople; then
    echo "Rolled back to ${PREV:0:7} and running. Send the lines above to Claude."
    notify "⚠️ Update failed its health check; I rolled the station back to the previous version (${PREV:0:7}) and it's running. Send Claude the output of update.sh."
  else
    echo "Rollback also failed; run: journalctl -u constantinople -n 50"
    notify "🚨 Update failed and the rollback did not start the engine. Run: journalctl -u constantinople -n 50 and send it to Claude."
  fi
  exit 1
fi
