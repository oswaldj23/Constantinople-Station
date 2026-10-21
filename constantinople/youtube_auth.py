"""One-time YouTube login for the Clip Forge (OAuth 2, desktop app flow).
    python -m constantinople youtube-auth
Needs YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET in .env (a "Desktop app" OAuth client from Google Cloud).
Prints a link; the Creator opens it on the account that owns the channel, approves, and pastes back the
address the browser lands on. Stores the refresh token and channel id in .env."""
import secrets, sys
from urllib.parse import urlencode, urlparse, parse_qs
import httpx
from . import config
from .etsy_auth import env_set

AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
REDIRECT = "http://localhost:3004/oauth/redirect"
SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly https://www.googleapis.com/auth/youtube.force-ssl https://www.googleapis.com/auth/yt-analytics.readonly"


def main():
    cid, sec = config.YOUTUBE_CLIENT_ID, config.YOUTUBE_CLIENT_SECRET
    if not cid:
        cid = input("OAuth Client ID (ends in .apps.googleusercontent.com): ").strip(); env_set(YOUTUBE_CLIENT_ID=cid)
    if not sec:
        sec = input("OAuth Client secret: ").strip(); env_set(YOUTUBE_CLIENT_SECRET=sec)
    state = secrets.token_hex(8)
    url = AUTH + "?" + urlencode({"client_id": cid, "redirect_uri": REDIRECT, "response_type": "code", "scope": SCOPES, "access_type": "offline", "prompt": "consent", "state": state})
    print("\n1) Open this link, signed in to the Google account that owns the YouTube channel, and allow access:\n")
    print(url)
    print("\n2) The browser lands on a page that fails to load (localhost:3004). That is expected.")
    print("   Copy the ENTIRE address from the address bar and paste it here.\n")
    landed = input("Paste the address: ").strip()
    q = parse_qs(urlparse(landed).query); code = (q.get("code") or [None])[0]
    if not code: sys.exit("No code in that address. Run again and paste the full URL (it contains ?code=...).")
    if (q.get("state") or [state])[0] != state: sys.exit("State mismatch; run again.")
    r = httpx.post(TOKEN, data={"code": code, "client_id": cid, "client_secret": sec, "redirect_uri": REDIRECT, "grant_type": "authorization_code"}, timeout=30)
    if r.status_code != 200: sys.exit(f"Token exchange failed: {r.status_code} {r.text[:300]}")
    tok = r.json(); rt = tok.get("refresh_token")
    if not rt: sys.exit("Google returned no refresh token. Remove the app at myaccount.google.com/permissions and run again.")
    env_set(YOUTUBE_REFRESH_TOKEN=rt)
    ch = httpx.get("https://www.googleapis.com/youtube/v3/channels", params={"part": "snippet", "mine": "true"}, headers={"Authorization": f"Bearer {tok['access_token']}"}, timeout=30)
    items = ch.json().get("items", []) if ch.status_code == 200 else []
    if items:
        env_set(YOUTUBE_CHANNEL=items[0]["id"]); print(f"\nLinked channel: {items[0]['snippet']['title']}")
    else:
        print("\nToken saved, but no channel was found on this account. Create a channel on youtube.com first, then run again.")
    print("Done. Restart the station (sudo systemctl restart constantinople) and the Clip Forge can post.")
