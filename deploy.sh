#!/usr/bin/env bash
# One-line server install for Constantinople Station (Ubuntu 22.04/24.04, run as root):
#   curl -fsSL https://raw.githubusercontent.com/oswaldj23/constantinople-station/main/deploy.sh | bash
# Installs Python + git, pulls the code to /opt/constantinople, creates .env (asks a few questions),
# locks the firewall to SSH + Tailscale, and registers the engine as a service that survives reboots.
set -euo pipefail
REPO="${REPO:-https://github.com/oswaldj23/constantinople-station.git}"
DIR=/opt/constantinople
ask(){ local p="$1" d="$2" v; read -r -p "$p [$d]: " v </dev/tty || true; echo "${v:-$d}"; }

echo "== Constantinople Station · server install =="
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq && apt-get install -y -qq python3 python3-venv python3-pip git ufw >/dev/null

if [ -d "$DIR/.git" ]; then git -C "$DIR" pull -q; else git clone -q "$REPO" "$DIR"; fi
cd "$DIR"
python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  NAME=$(ask "Station name" "Constantinople Station")
  CREATOR=$(ask "Your name (Mother escalates to you by it)" "the Creator")
  AUTO=$(ask "Mother autonomy: full (she decides within caps) or assist (asks you)" "full")
  CAP=$(ask "Daily spend cap in USD Mother may approve on her own" "10")
  sed -i "s/^STATION_NAME=.*/STATION_NAME=$NAME/; s/^CREATOR=.*/CREATOR=$CREATOR/; s/^AUTONOMY=.*/AUTONOMY=$AUTO/; s/^DAILY_SPEND_CAP=.*/DAILY_SPEND_CAP=$CAP/; s/^HOST=.*/HOST=0.0.0.0/" .env
  echo "Wrote .env (edit later with: nano $DIR/.env  then: systemctl restart constantinople)"
fi

# firewall: SSH from anywhere, the dashboard only over Tailscale
ufw allow OpenSSH >/dev/null; ufw allow in on tailscale0 >/dev/null 2>&1 || true; ufw --force enable >/dev/null

cat > /etc/systemd/system/constantinople.service <<UNIT
[Unit]
Description=Constantinople Station engine
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=$DIR
ExecStart=$DIR/.venv/bin/python -m constantinople serve
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload && systemctl enable --now constantinople >/dev/null
sleep 2
systemctl is-active constantinople >/dev/null && echo "== Running. Service: constantinople · logs: journalctl -u constantinople -f" || { echo "!! service failed to start"; journalctl -u constantinople -n 30 --no-pager; exit 1; }
echo "Next: install Tailscale to reach the dashboard privately:  curl -fsSL https://tailscale.com/install.sh | sh && tailscale up"
echo "Then open http://<this server's Tailscale IP>:8787 from any device on your tailnet."
