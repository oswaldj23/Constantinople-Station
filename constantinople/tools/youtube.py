"""YouTube Data API v3: the Signal Deck's eyes (what shorts are being watched, how many are being made)
and the Clip Forge's launch pad (uploads). Scanning needs only an API key; uploading needs the OAuth
refresh token that `python -m constantinople youtube-auth` stores.

Quota: 10,000 units/day. search.list costs 100, videos.list 1, an upload 1,600 — the daily scan below
spends ~1,700 units for 16 genres, leaving room for ~5 uploads a day."""
import json, math, random, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import httpx
from .. import config

API = "https://www.googleapis.com/youtube/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def _iso8601_seconds(d: str) -> int:
    import re
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d or "")
    if not m: return 0
    h, mi, s = (int(x or 0) for x in m.groups()); return h * 3600 + mi * 60 + s


# ── Signal Deck: scan ────────────────────────────────────────────────────
async def scan_shorts(ctx, *, genres=None, days: int = 7, dry_run: bool = True, **_):
    """For each genre: the top short-form videos of the last `days` by view count, plus how many shorts were
    uploaded (supply). Returns per-genre views, supply, median views, and an opportunity score
    (demand per competing upload). Signal Deck ranks genres by that score."""
    genres = genres or config.SIGNAL_GENRES
    if dry_run or not config.YOUTUBE_API_KEY:
        rows = []
        for g in genres:
            supply = random.randint(40, 1000); top = random.randint(200_000, 40_000_000)
            rows.append({"genre": g, "supply": supply, "top_views": top, "median_views": int(top * random.uniform(0.02, 0.2)), "total_views": int(top * random.uniform(2, 6)),
                         "opportunity": round(math.log10(top) * 10 / math.log10(supply + 10), 1),
                         "examples": [{"title": f"{g} #{i+1}", "views": int(top / (i + 1)), "channel": "sample", "url": "", "duration": random.randint(15, 58)} for i in range(3)]})
        rows.sort(key=lambda r: -r["opportunity"])
        return {"genres": rows, "scanned_at": datetime.now(timezone.utc).isoformat(), "cost": 0.0, "summary": f"{len(rows)} genres scanned (sample) · hottest: {rows[0]['genre']}"}
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = []; units = 0
    async with httpx.AsyncClient(timeout=30) as c:
        for g in genres:
            try:
                r = await c.get(f"{API}/search", params={"key": config.YOUTUBE_API_KEY, "part": "snippet", "q": f"{g} #shorts", "type": "video", "videoDuration": "short",
                                                          "order": "viewCount", "publishedAfter": since, "maxResults": 25, "safeSearch": "moderate"})
                units += 100
                if r.status_code == 403 and "quota" in r.text.lower():
                    return {"summary": "YouTube quota exhausted for today", "incident": "YouTube Data API quota exhausted · scan postponed to tomorrow", "cost": 0.0}
                r.raise_for_status()
                items = r.json().get("items", []); ids = [i["id"]["videoId"] for i in items if i.get("id", {}).get("videoId")]
                supply = int(r.json().get("pageInfo", {}).get("totalResults", 0))
                views = []; examples = []
                if ids:
                    v = await c.get(f"{API}/videos", params={"key": config.YOUTUBE_API_KEY, "part": "statistics,contentDetails,snippet", "id": ",".join(ids)}); units += 1
                    for it in v.json().get("items", []):
                        dur = _iso8601_seconds(it["contentDetails"]["duration"])
                        if dur > 180: continue
                        vc = int(it["statistics"].get("viewCount", 0)); views.append(vc)
                        examples.append({"title": it["snippet"]["title"][:80], "views": vc, "channel": it["snippet"]["channelTitle"][:40], "url": f"https://youtube.com/shorts/{it['id']}", "duration": dur,
                                         "likes": int(it["statistics"].get("likeCount", 0) or 0), "comments": int(it["statistics"].get("commentCount", 0) or 0)})
                examples.sort(key=lambda e: -e["views"]); views.sort(reverse=True)
                top = views[0] if views else 0; med = views[len(views) // 2] if views else 0
                opp = round(math.log10(top + 10) * 10 / math.log10(supply + 10), 1) if top else 0
                rows.append({"genre": g, "supply": supply, "top_views": top, "median_views": med, "total_views": sum(views), "opportunity": opp, "examples": examples[:5]})
            except Exception as e:
                rows.append({"genre": g, "error": str(e)[:120], "supply": 0, "top_views": 0, "median_views": 0, "total_views": 0, "opportunity": 0, "examples": []})
    rows.sort(key=lambda r: -r["opportunity"])
    return {"genres": rows, "scanned_at": datetime.now(timezone.utc).isoformat(), "quota_units": units, "cost": 0.0,
            "summary": f"{len(rows)} genres scanned · hottest: {rows[0]['genre']} (top {rows[0]['top_views']:,} views vs {rows[0]['supply']:,} uploads)"}


async def channel_stats(ctx, *, dry_run: bool = True, **_):
    """Our own channel's recent shorts: views per video, so Treasury and Mother see what lands."""
    if dry_run or not config.YOUTUBE_API_KEY or not config.YOUTUBE_CHANNEL:
        return {"videos": [], "cost": 0.0, "summary": "no channel stats (channel not linked)"}
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{API}/search", params={"key": config.YOUTUBE_API_KEY, "part": "id", "channelId": config.YOUTUBE_CHANNEL, "type": "video", "order": "date", "maxResults": 20})
        ids = [i["id"]["videoId"] for i in r.json().get("items", []) if i.get("id", {}).get("videoId")]
        if not ids: return {"videos": [], "cost": 0.0, "summary": "channel has no videos yet"}
        v = await c.get(f"{API}/videos", params={"key": config.YOUTUBE_API_KEY, "part": "statistics,snippet", "id": ",".join(ids)})
        vids = [{"id": it["id"], "title": it["snippet"]["title"], "views": int(it["statistics"].get("viewCount", 0)), "likes": int(it["statistics"].get("likeCount", 0) or 0), "published": it["snippet"]["publishedAt"]} for it in v.json().get("items", [])]
    tot = sum(x["views"] for x in vids)
    return {"videos": vids, "cost": 0.0, "summary": f"{len(vids)} shorts on channel · {tot:,} views total"}


# ── Clip Forge: upload ───────────────────────────────────────────────────
def access_token() -> str | None:
    if not (config.YOUTUBE_CLIENT_ID and config.YOUTUBE_CLIENT_SECRET and config.YOUTUBE_REFRESH_TOKEN): return None
    r = httpx.post(TOKEN_URL, data={"client_id": config.YOUTUBE_CLIENT_ID, "client_secret": config.YOUTUBE_CLIENT_SECRET, "refresh_token": config.YOUTUBE_REFRESH_TOKEN, "grant_type": "refresh_token"}, timeout=30)
    if r.status_code != 200: return None
    return r.json().get("access_token")


async def upload(ctx, *, dry_run: bool = True, privacy: str = "public", **_):
    """Resumable upload of the rendered short with title/description/tags from the script. Dry run records a pretend URL."""
    r = ctx.get("render") or {}; sc = ctx.get("script") or {}
    if not r.get("file"): return {"summary": "nothing to upload", "cost": 0.0}
    title = (sc.get("title") or "New from the Forge")[:95]
    if "#shorts" not in title.lower(): title = (title[:87] + " #Shorts")
    desc = (sc.get("caption") or "") + "\n\n" + " ".join("#" + h.strip("#") for h in sc.get("hashtags", [])) + "\n\nMade by " + config.STATION_NAME + "."
    if dry_run or not config.YOUTUBE_REFRESH_TOKEN:
        return {"url": f"https://youtube.com/shorts/dryrun_{ctx['run_id'][-6:]}", "video_id": None, "cost": 0.0, "summary": f"upload skipped ({'dry run' if dry_run else 'YouTube not linked'}) · file kept at {Path(r['file']).name}"}
    tok = access_token()
    if not tok: return {"summary": "youtube auth failed", "incident": "YouTube refresh token rejected · run `python -m constantinople youtube-auth` again", "cost": 0.0}
    meta = {"snippet": {"title": title, "description": desc[:4900], "tags": [h.strip("#") for h in sc.get("hashtags", [])][:15], "categoryId": "22"},
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False}}
    size = Path(r["file"]).stat().st_size
    async with httpx.AsyncClient(timeout=600) as c:
        init = await c.post("https://www.googleapis.com/upload/youtube/v3/videos", params={"uploadType": "resumable", "part": "snippet,status"},
                            headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json; charset=UTF-8", "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)}, json=meta)
        if init.status_code != 200:
            msg = init.text[:160]
            if "quotaExceeded" in msg or "uploadLimitExceeded" in msg: return {"summary": "upload limit", "incident": "YouTube upload limit reached for today · clip kept, will post tomorrow", "cost": 0.0}
            return {"summary": "upload init failed", "incident": f"YouTube upload init failed · {init.status_code} {msg}", "cost": 0.0}
        loc = init.headers["Location"]
        with open(r["file"], "rb") as fh:
            up = await c.put(loc, headers={"Authorization": f"Bearer {tok}", "Content-Type": "video/mp4", "Content-Length": str(size)}, content=fh.read())
        if up.status_code not in (200, 201): return {"summary": "upload failed", "incident": f"YouTube upload failed · {up.status_code} {up.text[:160]}", "cost": 0.0}
        vid = up.json()["id"]
        # thumbnail (allowed once the channel is verified by phone; ignore failures)
        try:
            if r.get("thumb"):
                with open(r["thumb"], "rb") as th:
                    await c.post("https://www.googleapis.com/upload/youtube/v3/thumbnails/set", params={"videoId": vid}, headers={"Authorization": f"Bearer {tok}", "Content-Type": "image/jpeg"}, content=th.read())
        except Exception: pass
    return {"url": f"https://youtube.com/shorts/{vid}", "video_id": vid, "cost": 0.0, "summary": f"live on YouTube · {title}"}
