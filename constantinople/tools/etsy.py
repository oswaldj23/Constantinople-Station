"""Etsy Open API v3. Used for two things: polling receipts (sales) into the Treasury, and pulling shop
conversations into the Comms Deck. Listing creation goes through Printify, which publishes for us.
Docs: https://developers.etsy.com/documentation  — needs an app key + OAuth2 access token with
transactions_r and shops_r scopes. Automation and AI-made goods have shop policy requirements; read them
and keep disclosure on."""
import random, time
from .. import config
API = "https://openapi.etsy.com/v3/application"


def _headers():
    """Bearer headers, refreshing the hourly access token when it is within 5 minutes of expiry."""
    if config.ETSY_REFRESH_TOKEN and time.time() > config.ETSY_TOKEN_EXPIRES - 300:
        import httpx
        from ..etsy_auth import env_set, TOKEN
        r = httpx.post(TOKEN, data={"grant_type": "refresh_token", "client_id": config.ETSY_API_KEY, "refresh_token": config.ETSY_REFRESH_TOKEN}, timeout=30)
        if r.status_code == 200:
            t = r.json()
            config.ETSY_ACCESS_TOKEN, config.ETSY_REFRESH_TOKEN = t["access_token"], t.get("refresh_token", config.ETSY_REFRESH_TOKEN)
            config.ETSY_TOKEN_EXPIRES = int(time.time()) + int(t.get("expires_in", 3600))
            env_set(ETSY_ACCESS_TOKEN=config.ETSY_ACCESS_TOKEN, ETSY_REFRESH_TOKEN=config.ETSY_REFRESH_TOKEN, ETSY_TOKEN_EXPIRES=config.ETSY_TOKEN_EXPIRES)
    return {"x-api-key": config.ETSY_API_KEY, "Authorization": f"Bearer {config.ETSY_ACCESS_TOKEN}"}

async def poll_receipts(ctx, *, dry_run: bool = True, **_):
    if not dry_run and not config.ETSY_ACCESS_TOKEN:
        return {"sales": [], "cost": 0.0, "summary": "Etsy API not linked yet; sales come via Printify"}
    if dry_run or not config.ETSY_ACCESS_TOKEN:
        n = random.choice([0, 0, 1, 1, 2])
        sales = [{"receipt_id": random.randint(10**9, 10**10), "amount": random.choice([14.99, 22.0, 24.95, 27.99, 34.0, 44.0]),
                  "title": random.choice(["garden era floral tee", "moon phase mug", "cozy book club sweatshirt"])} for _ in range(n)]
        return {"sales": sales, "cost": 0.0, "summary": f"{len(sales)} new receipt(s)"}
    import httpx
    async with httpx.AsyncClient(timeout=60, headers=_headers()) as c:
        r = await c.get(f"{API}/shops/{config.ETSY_SHOP_ID}/receipts", params={"limit": 25, "was_paid": "true"}); r.raise_for_status()
        L = ctx.get("_ledger"); seen = set((L.kv_get("etsy_seen") or "").split(",")) if L else set()
        sales = []
        for x in r.json().get("results", []):
            rid = str(x["receipt_id"])
            if rid in seen: continue
            seen.add(rid)
            sales.append({"receipt_id": rid, "amount": x["grandtotal"]["amount"] / x["grandtotal"]["divisor"], "title": (x.get("transactions") or [{}])[0].get("title", "")})
        if L: L.kv_set("etsy_seen", ",".join(sorted(seen)[-500:]))
    return {"sales": sales, "cost": 0.0, "summary": f"{len(sales)} new receipt(s)"}

async def poll_messages(ctx, *, dry_run: bool = True, **_):
    """Etsy conversations are not exposed to third-party apps for most sellers; the usual route is
    email-notification parsing or a mailbox integration. Dry run fabricates one occasionally."""
    if dry_run or not config.ETSY_ACCESS_TOKEN:
        if random.random() < 0.5:
            return {"messages": [], "cost": 0.0, "summary": "inbox clear"}
        m = random.choice(["Can I get this in XL?", "Does the mug ship to Canada?", "Received the wrong size", "Is the candle soy wax?"])
        return {"messages": [{"platform": "etsy", "from": "buyer", "text": m, "order_id": random.randint(10**8, 10**9)}], "cost": 0.0, "summary": "1 inbound message"}
    return {"messages": [], "cost": 0.0, "summary": "message polling not configured"}


async def listing_stats(ctx, *, dry_run: bool = True, **_):
    """Views and favourites per active listing (needs the Etsy token). Stored for Mother's review."""
    if dry_run or not config.ETSY_ACCESS_TOKEN or not config.ETSY_SHOP_ID:
        return {"stats": [], "cost": 0.0, "summary": "Etsy stats unavailable (no Etsy token yet)"}
    import httpx, json
    async with httpx.AsyncClient(timeout=60, headers=_headers()) as c:
        r = await c.get(f"{API}/shops/{config.ETSY_SHOP_ID}/listings/active", params={"limit": 100}); r.raise_for_status()
        stats = [{"listing_id": x["listing_id"], "title": x.get("title", ""), "views": x.get("views", 0), "favorites": x.get("num_favorers", 0), "quantity": x.get("quantity", 0)} for x in r.json().get("results", [])]
    ctx["_ledger"].kv_set("etsy_stats", json.dumps(stats))
    return {"stats": stats, "cost": 0.0, "summary": f"{len(stats)} active listing(s) · {sum(s['views'] for s in stats)} views · {sum(s['favorites'] for s in stats)} favourites"}
