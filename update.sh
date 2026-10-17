#!/usr/bin/env bash
# Pull the latest code and restart the service. Run on the server:  bash /opt/constantinople/update.sh
set -e
cd /opt/constantinople
git pull -q
.venv/bin/pip install -q -r requirements.txt
systemctl restart constantinople
sleep 2 && systemctl is-active constantinople && echo "Updated and running."
