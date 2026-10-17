"""Etsy Open API v3. Used for two things: polling receipts (sales) into the Treasury, and pulling shop
conversations into the Comms Deck. Listing creation goes through Printify, which publishes for us.
Docs: https://developers.etsy.com/documentation  — needs an app key + OAuth2 access token with
transactions_r and shops_r scopes. Automation and AI-made goods have shop policy requirements; read them
and keep disclosure on."""
import random
from .. import config
API = "https://openapi.etsy.com/v3/application"

async def poll_receipts(ctx, *, dry_run: bool = True, **_):
    if dry_run or not config.ETSY_ACCESS_TOKEN:
        n = random.choice([0, 0, 1, 1, 2])
        sales = [{"receipt_id": random.randint(10**9, 10**10), "amount": random.choice([14.99, 22.0, 24.95, 27.99, 34.0, 44.0]),
                  "title": random.choice(["garden era floral tee", "moon phase mug", "cozy book club sweatshirt"])} for _ in range(n)]
        return {"sales": sales, "cost": 0.0, "summary": f"{len(sales)} new receipt(s)"}
    import httpx
    async with httpx.AsyncClient(timeout=60, headers={"x-api-key": config.ETSY_API_KEY, "Authorization": f"Bearer {config.ETSY_ACCESS_TOKEN}"}) as c:
        r = await c.get(f"{API}/shops/{config.ETSY_SHOP_ID}/receipts", params={"limit": 25, "was_paid": "true"}); r.raise_for_status()
        sales = [{"receipt_id": x["receipt_id"], "amount": x["grandtotal"]["amount"] / x["grandtotal"]["divisor"],
                  "title": (x.get("transactions") or [{}])[0].get("title", "")} for x in r.json().get("results", [])]
    return {"sales": sales, "cost": 0.0, "summary": f"{len(sales)} receipt(s) pulled"}

async def poll_messages(ctx, *, dry_run: bool = True, **_):
    """Etsy conversations are not exposed to third-party apps for most sellers; the usual route is
    email-notification parsing or a mailbox integration. Dry run fabricates one occasionally."""
    if dry_run or not config.ETSY_ACCESS_TOKEN:
        if random.random() < 0.5:
            return {"messages": [], "cost": 0.0, "summary": "inbox clear"}
        m = random.choice(["Can I get this in XL?", "Does the mug ship to Canada?", "Received the wrong size", "Is the candle soy wax?"])
        return {"messages": [{"platform": "etsy", "from": "buyer", "text": m, "order_id": random.randint(10**8, 10**9)}], "cost": 0.0, "summary": "1 inbound message"}
    return {"messages": [], "cost": 0.0, "summary": "message polling not configured"}
