#!/usr/bin/env bash
# Mac/Linux: keeps the engine running, restarting on crash. For boot-time start use launchd (Mac) or a systemd unit (Linux); see README.
cd "$(dirname "$0")"
while true; do
  echo "$(date '+%F %T')  launching station..."
  python3 -m constantinople serve
  echo "$(date '+%F %T')  engine stopped - restarting in 10s (Ctrl+C twice to quit)"
  sleep 10
done
