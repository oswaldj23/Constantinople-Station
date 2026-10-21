#!/usr/bin/env bash
# Pull the latest code, add any new settings to .env (keeping your values), and restart the service.
# Run on the server:  bash /opt/constantinople/update.sh
set -e
cd /opt/constantinople
git pull -q
.venv/bin/pip install -q -r requirements.txt
if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null; then
  echo "installing ffmpeg (one time, ~1 min)…"; apt-get update -qq; apt-get install -y -qq ffmpeg fonts-dejavu-core >/dev/null || sudo apt-get install -y -qq ffmpeg fonts-dejavu-core >/dev/null
fi
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
sleep 2 && systemctl is-active constantinople && echo "Updated and running."
