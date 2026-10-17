"""Printify: turn a design into a real product and publish it to the connected Etsy shop.
Docs: https://developers.printify.com
Flow: upload design image → pick blueprint + print provider + variants from the catalog → create product
(returns mockups) → copy MINT's title/description/tags onto it → publish to Etsy."""
import base64, random
from .. import config
API = "https://api.printify.com/v1"

# Blueprint 6 = Gildan 5000 "Unisex Heavy Cotton Tee", the standard POD tee. Mugs/totes can be added later.
BLUEPRINTS = {"tee": 6}
PROVIDER_PREF = ["SwiftPOD", "Monster Digital", "Printify Choice", "Print Geek", "Underground Threads"]
COLORS = {"White", "Black", "Natural", "Sand", "Sport Grey"}
SIZES = ["S", "M", "L", "XL", "2XL"]
PRICE_CENTS = {"S": 2495, "M": 2495, "L": 2495, "XL": 2495, "2XL": 2695}


def _hdr():
    return {"Authorization": f"Bearer {config.PRINTIFY_API_KEY}"}


async def _pick_provider_and_variants(c, blueprint_id: int):
    r = await c.get(f"{API}/catalog/blueprints/{blueprint_id}/print_providers.json"); r.raise_for_status()
    providers = r.json()
    if not providers: raise RuntimeError("no print providers for blueprint")
    by_name = {p["title"]: p for p in providers}
    provider = next((by_name[n] for n in PROVIDER_PREF if n in by_name), providers[0])
    r = await c.get(f"{API}/catalog/blueprints/{blueprint_id}/print_providers/{provider['id']}/variants.json"); r.raise_for_status()
    allv = r.json().get("variants", [])
    chosen = [v for v in allv if v.get("options", {}).get("color") in COLORS and v.get("options", {}).get("size") in SIZES]
    if not chosen:  # fall back to the first 5 variants so a listing still goes out
        chosen = allv[:5]
    return provider, chosen


async def create_product(ctx, *, design_from: str = "design_draft.files", products=("tee",), dry_run: bool = True, **_):
    concept = (ctx.get("trend_scan") or {}).get("concept", "design")
    if dry_run or not config.PRINTIFY_API_KEY:
        pid = f"pf_{random.randint(100000, 999999)}"
        return {"product_id": pid, "mockups": [f"https://example.invalid/mockup/{pid}/{p}.png" for p in products],
                "cost": 0.0, "summary": f"Mockups built for {', '.join(products)} ({pid})"}
    import httpx
    files = _lookup(ctx, design_from) or []
    if not files: return {"summary": "no design file", "incident": "Mockup build skipped · no design file from Design draft", "cost": 0.0}
    pick = (ctx.get("design_pick") or {}).get("index", 0)
    design_path = files[min(pick, len(files) - 1)]
    async with httpx.AsyncClient(timeout=120, headers=_hdr()) as c:
        up = await c.post(f"{API}/uploads/images.json", json={"file_name": f"{ctx['run_id']}.png", "contents": _b64(design_path)})
        if up.status_code >= 400: return {"summary": "upload failed", "incident": f"Print partner rejected the design upload · {up.status_code} {up.text[:120]}", "cost": 0.0}
        image_id = up.json()["id"]
        provider, variants = await _pick_provider_and_variants(c, BLUEPRINTS["tee"])
        vids = [v["id"] for v in variants]
        body = {"title": concept.title()[:140], "description": f"{concept}. Made to order.", "blueprint_id": BLUEPRINTS["tee"], "print_provider_id": provider["id"],
                "variants": [{"id": v["id"], "price": PRICE_CENTS.get(v.get("options", {}).get("size", "M"), 2495), "is_enabled": True} for v in variants],
                "print_areas": [{"variant_ids": vids, "placeholders": [{"position": "front", "images": [{"id": image_id, "x": 0.5, "y": 0.4, "scale": 0.85, "angle": 0}]}]}]}
        r = await c.post(f"{API}/shops/{config.PRINTIFY_SHOP_ID}/products.json", json=body)
        if r.status_code >= 400: return {"summary": "product create failed", "incident": f"Print partner could not create the product · {r.status_code} {r.text[:160]}", "cost": 0.0}
        p = r.json()
        mockups = [i["src"] for i in p.get("images", []) if i.get("src")]
        return {"product_id": p["id"], "mockups": mockups, "provider": provider["title"], "variants": len(variants), "cost": 0.0,
                "summary": f"Product {p['id']} built · {provider['title']} · {len(variants)} size/colour variants · {len(mockups)} mockups"}


async def update_listing(ctx, *, product_from: str = "mockup_build.product_id", listing_from: str = "listing_draft", dry_run: bool = True, **_):
    """Copy MINT's title, description and tags onto the Printify product before publishing."""
    pid = _lookup(ctx, product_from); L = ctx.get(listing_from) or {}
    if dry_run or not config.PRINTIFY_API_KEY:
        return {"cost": 0.0, "summary": f"Listing copy applied to {pid}"}
    import httpx
    body = {}
    if L.get("title"): body["title"] = str(L["title"])[:140]
    if L.get("description"): body["description"] = str(L["description"])[:5000]
    if L.get("tags"): body["tags"] = [str(t)[:20] for t in L["tags"]][:13]
    async with httpx.AsyncClient(timeout=60, headers=_hdr()) as c:
        r = await c.put(f"{API}/shops/{config.PRINTIFY_SHOP_ID}/products/{pid}.json", json=body)
        if r.status_code >= 400: return {"summary": "listing update failed", "incident": f"Could not apply listing copy · {r.status_code} {r.text[:120]}", "cost": 0.0}
    return {"cost": 0.0, "summary": f"Listing copy applied: \"{body.get('title', '')[:60]}\""}


async def publish(ctx, *, product_from: str = "mockup_build.product_id", dry_run: bool = True, **_):
    pid = _lookup(ctx, product_from)
    if dry_run or not config.PRINTIFY_API_KEY:
        if random.random() < 0.15:
            return {"summary": "publish failed", "incident": random.choice(["Print partner API timeout on publish · retry", "Marketplace rate limit on listing create · backing off"]), "cost": 0.0}
        return {"listing_id": f"etsy_{random.randint(10**9, 10**10)}", "cost": 0.20, "summary": f"Listing live for {pid} (listing fee $0.20)"}
    import httpx
    async with httpx.AsyncClient(timeout=60, headers=_hdr()) as c:
        r = await c.post(f"{API}/shops/{config.PRINTIFY_SHOP_ID}/products/{pid}/publish.json",
                         json={"title": True, "description": True, "images": True, "variants": True, "tags": True, "keyFeatures": True, "shipping_template": True})
        if r.status_code >= 400: return {"summary": "publish failed", "incident": f"Publish to Etsy failed · {r.status_code} {r.text[:160]}", "cost": 0.0}
    return {"listing_id": pid, "cost": 0.20, "summary": f"Published {pid} to Etsy via Printify · listing appears in the shop within a few minutes ($0.20 listing fee)"}


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
    async with httpx.AsyncClient(timeout=60, headers=_hdr()) as c:
        r = await c.get(f"{API}/shops/{config.PRINTIFY_SHOP_ID}/orders.json", params={"limit": 50}); r.raise_for_status()
        for o in r.json().get("data", []):
            oid = str(o["id"])
            if oid in seen or o.get("status") in ("canceled",): continue
            seen.add(oid)
            amount = sum((li.get("metadata", {}).get("price", 0) or 0) * (li.get("quantity", 1) or 1) for li in o.get("line_items", [])) / 100
            title = (o.get("line_items") or [{}])[0].get("metadata", {}).get("title", "order")
            cost = (o.get("total_price", 0) or 0) / 100
            sales.append({"receipt_id": oid, "amount": amount, "title": title, "print_cost": cost})
    if L: L.kv_set("printify_seen", ",".join(sorted(seen)[-500:]))
    return {"sales": sales, "cost": 0.0, "summary": f"{len(sales)} new order(s) from the shop"}


def _lookup(ctx, path):
    cur = ctx
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur: cur = cur[part]
        else: return None
    return cur


def _b64(path):
    return base64.b64encode(open(path, "rb").read()).decode()
