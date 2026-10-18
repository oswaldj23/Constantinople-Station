"""The story market: what people are upvoting right now in the story subreddits.

This feeds the Signal Deck PREMISES, not scripts. Posts on Reddit belong to the people who wrote them
(r/nosleep stories are fiction by named authors; AITA posts are real people's lives), and YouTube treats
narrating text you did not write as reused content. So REEL reads the seeds for what is landing — the
situations, the hook shapes, the emotional beats — and writes its own story with its own details.

Reads Reddit's public JSON with a descriptive User-Agent (allowed, ~10 requests/min). If a cloud host is
blocked (403/429), set REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET from a free "script" app at
reddit.com/prefs/apps and the same scan runs through the official API."""
import asyncio, os, time
from datetime import datetime, timezone
import httpx
from .. import config

SUBS = {
    "horror":  ["nosleep", "LetsNotMeet", "Paranormal", "creepyencounters"],
    "aita":    ["AmItheAsshole", "AITAH", "AmIOverreacting"],
    "revenge": ["pettyrevenge", "MaliciousCompliance", "ProRevenge"],
    "story":   ["tifu", "TrueOffMyChest", "confession", "MadeMeSmile", "offmychest"],
}
UA = "constantinople-station/1.0 (signal deck; +https://github.com/oswaldj23/Constantinople-Station)"


def _oauth_token() -> str | None:
    cid, sec = os.getenv("REDDIT_CLIENT_ID"), os.getenv("REDDIT_CLIENT_SECRET")
    if not (cid and sec): return None
    try:
        r = httpx.post("https://www.reddit.com/api/v1/access_token", auth=(cid, sec), data={"grant_type": "client_credentials"}, headers={"User-Agent": UA}, timeout=20)
        return r.json().get("access_token") if r.status_code == 200 else None
    except Exception:
        return None


async def _top(c: httpx.AsyncClient, sub: str, tok: str | None, limit: int = 12) -> list:
    base = "https://oauth.reddit.com" if tok else "https://www.reddit.com"
    h = {"User-Agent": UA, **({"Authorization": f"bearer {tok}"} if tok else {})}
    r = await c.get(f"{base}/r/{sub}/top.json", params={"t": "day", "limit": limit, "raw_json": 1}, headers=h)
    if r.status_code in (403, 429): raise PermissionError(f"{r.status_code}")
    r.raise_for_status()
    out = []
    for ch in r.json().get("data", {}).get("children", []):
        d = ch.get("data", {})
        if d.get("over_18") or d.get("stickied") or d.get("is_video"): continue
        body = (d.get("selftext") or "").strip()
        if len(body) < 300: continue   # a real story, not a link or a one-liner
        age_h = max(0.5, (time.time() - float(d.get("created_utc", time.time()))) / 3600)
        out.append({"sub": sub, "title": d.get("title", "")[:140], "score": int(d.get("score", 0)), "comments": int(d.get("num_comments", 0)),
                    "velocity": round(int(d.get("score", 0)) / age_h, 1), "words": len(body.split()),
                    "gist": " ".join(body.split())[:1600 if sub.lower() not in ("nosleep", "letsnotmeet", "paranormal", "creepyencounters") else 420] + ("…" if len(body) > 420 else ""),   # real-life posts: enough to retell the situation; fiction: premise only
                    "url": "https://www.reddit.com" + d.get("permalink", "")})
    return out


async def scan_stories(ctx, *, per_format: int = 4, dry_run: bool = True, **_):
    """Top story posts of the day per format, ranked by upvotes per hour. Returns seeds (title, gist, numbers)."""
    if dry_run:
        seeds = [{"format": "horror", "sub": "nosleep", "title": "My apartment has a door that isn't on the floor plan", "score": 4200, "comments": 310, "velocity": 350, "gist": "(sample) a tenant finds a sealed door; the landlord denies it exists", "url": ""},
                 {"format": "aita", "sub": "AmItheAsshole", "title": "AITA for leaving my sister's wedding before the first dance?", "score": 9800, "comments": 2100, "velocity": 816, "gist": "(sample) paid for the dress, got thanked by the wrong family, left quietly", "url": ""},
                 {"format": "revenge", "sub": "MaliciousCompliance", "title": "Boss said 'only do exactly what's in your job description'. So I did.", "score": 7100, "comments": 640, "velocity": 592, "gist": "(sample) literal compliance exposes how much unpaid work was being done", "url": ""},
                 {"format": "story", "sub": "tifu", "title": "TIFU by replying-all to the entire company with my grocery list", "score": 3900, "comments": 520, "velocity": 325, "gist": "(sample) an accidental reply-all becomes an office legend", "url": ""}]
        return {"seeds": seeds, "source": "sample", "cost": 0.0, "summary": f"{len(seeds)} story seeds (sample)"}
    tok = _oauth_token(); seeds = []; blocked = False; errors = 0
    async with httpx.AsyncClient(timeout=25, follow_redirects=True) as c:
        for fmt, subs in SUBS.items():
            rows = []
            for sub in subs:
                try:
                    rows += await _top(c, sub, tok)
                except PermissionError:
                    blocked = True; break
                except Exception:
                    errors += 1
                await asyncio.sleep(1.2)   # stay well under the public rate limit
            if blocked: break
            rows.sort(key=lambda r: -r["velocity"])
            for r in rows[:per_format]: seeds.append({"format": fmt, **r})
    if blocked and not seeds:
        return {"seeds": [], "source": "blocked", "cost": 0.0,
                "summary": "Reddit refused this server (403/429) · add REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET from reddit.com/prefs/apps (free 'script' app) to scan through the official API"}
    seeds.sort(key=lambda r: -r["velocity"])
    return {"seeds": seeds, "source": "oauth" if tok else "public", "scanned_at": datetime.now(timezone.utc).isoformat(), "cost": 0.0,
            "summary": f"{len(seeds)} story seeds · hottest: {seeds[0]['title'][:60]} ({seeds[0]['score']:,} upvotes, r/{seeds[0]['sub']})" if seeds else f"no story seeds ({errors} subreddit errors)"}
