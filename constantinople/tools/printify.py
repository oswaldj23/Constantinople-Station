"""Printify: create a product from an uploaded design, then publish it to the connected Etsy shop.
Docs: https://developers.printify.com  (upload image → create product with blueprint/provider/variants → publish)"""
import random
from .. import config
API = "https://api.printify.com/v1"

async def create_product(ctx, *, design_from: str = "design_draft.files", products=("tee",), dry_run: bool = True, **_):
    concept = (ctx.get("trend_scan") or {}).get("concept", "design")
    if dry_run or not config.PRINTIFY_API_KEY:
        pid = f"pf_{random.randint(100000, 999999)}"
        return {"product_id": pid, "mockups": [f"https://example.invalid/mockup/{pid}/{p}.png" for p in products],
                "cost": 0.0, "summary": f"Mockups built for {', '.join(products)} ({pid})"}
    import httpx
    files = _lookup(ctx, design_from) or []
    async with httpx.AsyncClient(timeout=60, headers={"Authorization": f"Bearer {config.PRINTIFY_API_KEY}"}) as c:
        up = await c.post(f"{API}/uploads/images.json", json={"file_name": "design.png", "contents": _b64(files[0])})
        up.raise_for_status(); image_id = up.json()["id"]
        # blueprint_id/print_provider_id/variants depend on the product you sell; look them up once via
        # GET /catalog/blueprints.json and keep them in bays/etsy.yaml args.
        body = {"title": concept.title(), "description": "", "blueprint_id": 6, "print_provider_id": 99,
                "variants": [{"id": 12100, "price": 2495, "is_enabled": True}],
                "print_areas": [{"variant_ids": [12100], "placeholders": [{"position": "front", "images": [{"id": image_id, "x": 0.5, "y": 0.5, "scale": 1, "angle": 0}]}]}]}
        r = await c.post(f"{API}/shops/{config.PRINTIFY_SHOP_ID}/products.json", json=body); r.raise_for_status()
        p = r.json()
        return {"product_id": p["id"], "mockups": [i["src"] for i in p.get("images", [])], "cost": 0.0, "summary": f"Product {p['id']} created"}

async def publish(ctx, *, product_from: str = "mockup_build.product_id", dry_run: bool = True, **_):
    pid = _lookup(ctx, product_from)
    if dry_run or not config.PRINTIFY_API_KEY:
        if random.random() < 0.15:
            return {"summary": "publish failed", "incident": random.choice(["Print partner API timeout on publish · retry", "Marketplace rate limit on listing create · backing off"]), "cost": 0.0}
        return {"listing_id": f"etsy_{random.randint(10**9, 10**10)}", "cost": 0.20, "summary": f"Listing live for {pid} (listing fee $0.20)"}
    import httpx
    async with httpx.AsyncClient(timeout=60, headers={"Authorization": f"Bearer {config.PRINTIFY_API_KEY}"}) as c:
        r = await c.post(f"{API}/shops/{config.PRINTIFY_SHOP_ID}/products/{pid}/publish.json",
                         json={"title": True, "description": True, "images": True, "variants": True, "tags": True})
        r.raise_for_status()
    return {"listing_id": pid, "cost": 0.20, "summary": f"Published {pid} to Etsy via Printify"}

def _lookup(ctx, path):
    cur = ctx
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur: cur = cur[part]
        else: return None
    return cur

def _b64(path):
    import base64; return base64.b64encode(open(path, "rb").read()).decode()


async def poll_orders(ctx, *, dry_run: bool = True, **_):
    """Real sales without Etsy's API: every order placed in the connected Etsy shop shows up in Printify.
    Returns only orders not seen before (tracked in the ledger), as sales for Treasury to record."""
    if dry_run or not config.PRINTIFY_API_KEY:
        n = random.choice([0, 0, 1, 1, 2])
        sales = [{"receipt_id": f"pf{random.randint(10**7, 10**8)}", "amount": random.choice([14.99, 22.0, 24.95, 27.99, 34.0]), "title": random.choice(["garden era floral tee", "moon phase mug", "cozy book club sweatshirt"])} for _ in range(n)]
        return {"sales": sales, "cost": 0.0, "summary": f"{len(sales)} new order(s)"}
    import httpx
    L = ctx.get("_ledger"); seen = set((L.kv_get("printify_seen") or "").split(",")) if L else set()
    sales = []
    async with httpx.AsyncClient(timeout=60, headers={"Authorization": f"Bearer {config.PRINTIFY_API_KEY}"}) as c:
        r = await c.get(f"{API}/shops/{config.PRINTIFY_SHOP_ID}/orders.json", params={"limit": 50}); r.raise_for_status()
        for o in r.json().get("data", []):
            oid = str(o["id"])
            if oid in seen or o.get("status") in ("canceled",): continue
            seen.add(oid)
            # merchant revenue = what the buyer paid for items (cents); print cost is deducted separately by Printify
            amount = sum(li.get("metadata", {}).get("price", 0) * li.get("quantity", 1) for li in o.get("line_items", [])) / 100
            title = (o.get("line_items") or [{}])[0].get("metadata", {}).get("title", "order")
            cost = (o.get("total_price", 0) or 0) / 100  # what Printify charges us for printing+shipping
            sales.append({"receipt_id": oid, "amount": amount, "title": title, "print_cost": cost})
    if L: L.kv_set("printify_seen", ",".join(sorted(seen)[-500:]))
    return {"sales": sales, "cost": 0.0, "summary": f"{len(sales)} new order(s) from the shop"}
