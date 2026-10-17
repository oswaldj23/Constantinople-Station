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
