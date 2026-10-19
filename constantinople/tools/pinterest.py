"""Pinterest: the shop's free traffic. One pin per listing per run — the real mockup, a keyword title, a short
description and the Etsy link — on a board the station creates. Pinterest pins keep sending clicks for
months, which is why Etsy sellers live there. Trial API access is enough for your own account."""
import base64, json, os, re, time
import httpx
from .. import config

API = "https://api.pinterest.com/v5"


def _env(k):
    v = os.getenv(k)
    if v: return v
    try:
        for line in (config.ROOT / ".env").read_text().splitlines():
            m = re.match(rf"^{k}=(.*)$", line.strip())
            if m and m.group(1).strip(): return m.group(1).strip()
    except Exception: pass
    return None


def _token() -> str | None:
    tok = _env("PINTEREST_ACCESS_TOKEN"); rt = _env("PINTEREST_REFRESH_TOKEN"); cid = _env("PINTEREST_APP_ID"); sec = _env("PINTEREST_APP_SECRET")
    if tok:
        r = httpx.get(f"{API}/user_account", headers={"Authorization": f"Bearer {tok}"}, timeout=20)
        if r.status_code == 200: return tok
    if rt and cid and sec:
        basic = base64.b64encode(f"{cid}:{sec}".encode()).decode()
        r = httpx.post(f"{API}/oauth/token", headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"}, data={"grant_type": "refresh_token", "refresh_token": rt}, timeout=20)
        if r.status_code == 200:
            from ..etsy_auth import env_set
            new = r.json()["access_token"]; env_set(PINTEREST_ACCESS_TOKEN=new); return new
    return None


async def _board(c, L) -> str | None:
    bid = L.kv_get("pinterest_board") if L is not None else None
    if bid: return bid
    r = await c.get(f"{API}/boards", params={"page_size": 50})
    if r.status_code == 200:
        for b in r.json().get("items", []):
            if b.get("name", "").lower().startswith(config.STATION_NAME.split()[0].lower()):
                if L is not None: L.kv_set("pinterest_board", b["id"])
                return b["id"]
    r = await c.post(f"{API}/boards", json={"name": f"{config.STATION_NAME.split()[0]} Shop · gifts made to order", "privacy": "PUBLIC", "description": "Original designs on tees, sweatshirts, mugs and totes. Made to order, shipped in days."})
    if r.status_code in (200, 201):
        bid = r.json()["id"]
        if L is not None: L.kv_set("pinterest_board", bid)
        return bid
    return None


def _pick_listing(L) -> dict | None:
    """The live listing pinned least recently (round-robin), with its mockup and Etsy URL."""
    pinned = json.loads(L.kv_get("pinned") or "{}")
    best = None
    for a in L.artifacts(kind_filter="listing", limit=100):
        p = a["payload"]; mb = p.get("mockup_build") or {}; pub = p.get("pub_sync") or {}
        if not pub.get("listing_id") or not mb.get("mockups"): continue
        key = str(mb.get("product_id")); last = pinned.get(key, 0)
        if best is None or last < best[0]: best = (last, a, key)
    if not best: return None
    _, a, key = best; p = a["payload"]; ld = p.get("listing_draft") or {}; mb = p.get("mockup_build") or {}
    return {"key": key, "product_id": mb.get("product_id"), "title": ld.get("title") or a["title"], "tags": ld.get("tags") or [], "description": ld.get("description", ""), "mockups": mb.get("mockups") or [], "concept": a["title"]}


async def _etsy_url(c_printify, pid: str) -> str | None:
    """The listing's public URL, from Printify's record of the published product."""
    if not (config.PRINTIFY_API_KEY and config.PRINTIFY_SHOP_ID and pid): return None
    r = await c_printify.get(f"https://api.printify.com/v1/shops/{config.PRINTIFY_SHOP_ID}/products/{pid}.json", headers={"Authorization": f"Bearer {config.PRINTIFY_API_KEY}"})
    if r.status_code != 200: return None
    ext = r.json().get("external") or {}
    return ext.get("handle") or None


async def pin(ctx, *, dry_run: bool = True, **_):
    L = ctx.get("_ledger")
    listing = _pick_listing(L) if L is not None else None
    if not listing: return {"cost": 0.0, "summary": "nothing live to pin yet"}
    cap = ctx.get("pin_caption") or {}
    title = (cap.get("title") or listing["title"])[:100]
    desc = (cap.get("description") or listing["description"][:400]) + "\n" + " ".join("#" + t.replace(" ", "") for t in listing["tags"][:6])
    if dry_run or not _token():
        return {"pin_id": None, "title": title, "cost": 0.0, "summary": f"pin drafted ({'dry run' if dry_run else 'Pinterest not linked'}): {title[:60]}"}
    tok = _token()
    async with httpx.AsyncClient(timeout=60, headers={"Authorization": f"Bearer {tok}"}) as c, httpx.AsyncClient(timeout=30) as cp:
        board = await _board(c, L)
        if not board: return {"summary": "no board", "incident": "Pinterest: could not find or create a board · check the app's scopes (boards:write)", "cost": 0.0}
        link = await _etsy_url(cp, listing["product_id"]) or f"https://www.etsy.com/shop/{config.STATION_NAME.split()[0]}"
        body = {"board_id": board, "title": title, "description": desc[:500], "link": link, "alt_text": listing["concept"][:400],
                "media_source": {"source_type": "image_url", "url": listing["mockups"][0]}}
        r = await c.post(f"{API}/pins", json=body)
        if r.status_code == 429: return {"summary": "rate limited", "incident": "Pinterest rate limit · will pin again next run", "cost": 0.0}
        if r.status_code >= 400: return {"summary": "pin failed", "incident": f"Pinterest refused the pin · {r.status_code} {r.text[:140]}", "cost": 0.0}
        pid = r.json().get("id")
    pinned = json.loads(L.kv_get("pinned") or "{}"); pinned[listing["key"]] = int(time.time()); L.kv_set("pinned", json.dumps(pinned))
    return {"pin_id": pid, "title": title, "link": link, "url": f"https://www.pinterest.com/pin/{pid}/", "cost": 0.0, "summary": f"pinned: {title[:60]} → {link}"}
