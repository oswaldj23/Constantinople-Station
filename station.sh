#!/usr/bin/env bash
# Everyday commands on the server. Usage: bash /opt/constantinople/station.sh <status|logs|approvals|approve N|reject N|restart|stop|start|env>
cd /opt/constantinople
case "${1:-status}" in
  status)    systemctl status constantinople --no-pager | head -5; .venv/bin/python -c "import json,urllib.request;d=json.load(urllib.request.urlopen('http://127.0.0.1:8787/mother'));print('Mother:',d['autonomy'],'· spent today $%.2f of $%.2f'%(d['spent_today'],d['daily_cap']),'· escalations:',len(d['escalations']))" ;;
  logs)      journalctl -u constantinople -f ;;
  approvals) .venv/bin/python -m constantinople approvals ;;
  approve|reject) .venv/bin/python -m constantinople "$1" "$2" ;;
  restart|stop|start) systemctl "$1" constantinople && echo "$1 done" ;;
  env)       nano .env && systemctl restart constantinople && echo "restarted with new settings" ;;
  *) echo "usage: station.sh status|logs|approvals|approve N|reject N|restart|stop|start|env" ;;
esac
