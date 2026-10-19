"""One-time Pinterest login so the station can pin listings (OAuth 2).
    python -m constantinople pinterest-auth
Needs PINTEREST_APP_ID and PINTEREST_APP_SECRET (developers.pinterest.com → My apps → create app; add
http://localhost:3005/oauth/redirect as a redirect URI; "trial access" is enough for your own account)."""
import base64, secrets, sys
from urllib.parse import urlencode, urlparse, parse_qs
import httpx
from . import config
from .etsy_auth import env_set

AUTH = "https://www.pinterest.com/oauth/"
TOKEN = "https://api.pinterest.com/v5/oauth/token"
REDIRECT = "http://localhost:3005/oauth/redirect"
SCOPES = "boards:read,boards:write,pins:read,pins:write,user_accounts:read"


def main():
    import os
    cid, sec = os.getenv("PINTEREST_APP_ID"), os.getenv("PINTEREST_APP_SECRET")
    if not cid: cid = input("Pinterest App ID: ").strip(); env_set(PINTEREST_APP_ID=cid)
    if not sec: sec = input("Pinterest App secret: ").strip(); env_set(PINTEREST_APP_SECRET=sec)
    state = secrets.token_hex(8)
    url = AUTH + "?" + urlencode({"client_id": cid, "redirect_uri": REDIRECT, "response_type": "code", "scope": SCOPES, "state": state})
    print("\n1) Open this link signed in to the Pinterest account for the shop, and allow:\n\n" + url)
    print("\n2) The browser lands on a page that fails to load (localhost:3005). Copy the whole address and paste it here.\n")
    landed = input("Paste the address: ").strip(); q = parse_qs(urlparse(landed).query); code = (q.get("code") or [None])[0]
    if not code: sys.exit("No code in that address; run again.")
    basic = base64.b64encode(f"{cid}:{sec}".encode()).decode()
    r = httpx.post(TOKEN, headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"},
                   data={"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT}, timeout=30)
    if r.status_code != 200: sys.exit(f"Token exchange failed: {r.status_code} {r.text[:300]}")
    t = r.json(); env_set(PINTEREST_ACCESS_TOKEN=t["access_token"], PINTEREST_REFRESH_TOKEN=t.get("refresh_token", ""))
    me = httpx.get("https://api.pinterest.com/v5/user_account", headers={"Authorization": f"Bearer {t['access_token']}"}, timeout=30)
    print(f"\nLinked Pinterest account: {me.json().get('username', '?')}" if me.status_code == 200 else "\nToken saved.")
    print("Done. Restart the station (sudo systemctl restart constantinople). The Pin Deck makes its own board on the first run.")
