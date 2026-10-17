"""One-time Etsy login for the station (OAuth 2 with PKCE).
    python -m constantinople etsy-auth
Prints a link; the Creator opens it, approves, and pastes back the address the browser lands on.
Stores the access + refresh tokens and the shop id in .env. tools/etsy.py refreshes the token hourly."""
import base64, hashlib, secrets, sys, re, time
from urllib.parse import urlencode, urlparse, parse_qs
import httpx
from . import config

AUTH = "https://www.etsy.com/oauth/connect"
TOKEN = "https://api.etsy.com/v3/public/oauth/token"
REDIRECT = "http://localhost:3003/oauth/redirect"
SCOPES = "transactions_r shops_r listings_r email_r"


def env_set(**kv):
    p = config.ROOT / ".env"
    s = p.read_text()
    for k, v in kv.items():
        if re.search(rf"^{k}=.*$", s, re.M):
            s = re.sub(rf"^{k}=.*$", f"{k}={v}", s, flags=re.M)
        else:
            s += f"\n{k}={v}"
    p.write_text(s)


def main():
    key = config.ETSY_API_KEY
    if not key:
        key = input("Etsy app KEYSTRING (from etsy.com/developers/your-apps): ").strip()
        env_set(ETSY_API_KEY=key)
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_hex(8)
    url = AUTH + "?" + urlencode({"response_type": "code", "client_id": key, "redirect_uri": REDIRECT, "scope": SCOPES,
                                  "state": state, "code_challenge": challenge, "code_challenge_method": "S256"})
    print("\n1) Open this link in your browser, signed in to the Etsy account that owns the shop, and click Grant access:\n")
    print(url)
    print("\n2) The browser will land on a page that fails to load (localhost:3003). That is expected.")
    print("   Copy the ENTIRE address from the address bar and paste it here.\n")
    landed = input("Paste the address: ").strip()
    q = parse_qs(urlparse(landed).query)
    code = (q.get("code") or [None])[0]
    if not code:
        sys.exit("No code found in that address. Run again and paste the full URL (it contains ?code=...).")
    if (q.get("state") or [state])[0] != state:
        sys.exit("State mismatch; run again.")
    r = httpx.post(TOKEN, data={"grant_type": "authorization_code", "client_id": key, "redirect_uri": REDIRECT, "code": code, "code_verifier": verifier}, timeout=30)
    if r.status_code != 200:
        sys.exit(f"Token exchange failed: {r.status_code} {r.text[:300]}")
    t = r.json()
    access, refresh, exp = t["access_token"], t["refresh_token"], int(time.time()) + int(t.get("expires_in", 3600))
    me = httpx.get("https://openapi.etsy.com/v3/application/users/me", headers={"x-api-key": key, "Authorization": f"Bearer {access}"}, timeout=30).json()
    shop_id = me.get("shop_id")
    env_set(ETSY_ACCESS_TOKEN=access, ETSY_REFRESH_TOKEN=refresh, ETSY_TOKEN_EXPIRES=exp, **({"ETSY_SHOP_ID": shop_id} if shop_id else {}))
    print(f"\nLinked. Etsy user {me.get('user_id')} · shop id {shop_id}. Tokens saved to .env; the engine refreshes them automatically.")
    print("Restart the station:  systemctl restart constantinople")


if __name__ == "__main__":
    main()
