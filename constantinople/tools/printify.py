"""Printify: turn a design into a real product and publish it to the connected Etsy shop.
Docs: https://developers.printify.com
Flow: upload design image → pick blueprint + print provider + variants from the catalog → create product
(returns mockups) → copy MINT's title/description/tags onto it → publish to Etsy."""
import base64, random
from .. import config
API = "https://api.printify.com/v1"

# Product types the shop rotates through. Blueprints are found in Printify's catalog by title keywords
# (ids differ by region/time); the `fallback` id is the well-known one. Prices are retail, in cents.
PRODUCTS = {
    "tee":        {"titles": ["Unisex Heavy Cotton Tee"], "fallback": 6,  "price": {"default": 2495, "2XL": 2695, "3XL": 2895}, "label": "T-Shirt", "scale": 0.85, "y": 0.4},
    "sweatshirt": {"titles": ["Unisex Heavy Blend", "Crewneck Sweatshirt"], "fallback": 49, "price": {"default": 3995, "2XL": 4295, "3XL": 4495}, "label": "Sweatshirt", "scale": 0.75, "y": 0.42},
    "hoodie":     {"titles": ["Unisex Heavy Blend", "Hooded Sweatshirt"], "fallback": 77, "price": {"default": 4495, "2XL": 4795, "3XL": 4995}, "label": "Hoodie", "scale": 0.7, "y": 0.45},
    "mug":        {"titles": ["Ceramic Mug", "11oz"], "fallback": 68, "price": {"default": 1695, "15oz": 1995}, "label": "Mug", "scale": 0.9, "y": 0.5},
    "tote":       {"titles": ["Tote Bag"], "fallback": 1086, "price": {"default": 1995}, "label": "Tote Bag", "scale": 0.8, "y": 0.5},
    "poster":     {"titles": ["Matte", "Vertical Posters"], "fallback": 282, "price": {"default": 2495, '16" x 20"': 3495, '18" x 24"': 3995, '24" x 36"': 5495}, "label": "Art Print", "scale": 1.0, "y": 0.5},
}
ROTATION = [p.strip() for p in (__import__("os").getenv("PRODUCT_ROTATION") or "tee,sweatshirt,mug,poster,tee,tote,hoodie").split(",") if p.strip() in PRODUCTS] or ["tee"]
PROVIDER_PREF = ["SwiftPOD", "Monster Digital", "Printify Choice", "Print Geek", "Underground Threads", "District Photo", "Dream Junction"]
LIGHT = {"White", "Natural", "Sand", "Ash", "Ice Grey", "Light Blue", "Light Pink", "Sport Grey", "Oatmeal Heather"}
DARK = {"Black", "Navy", "Dark Heather", "Charcoal", "Forest Green", "Maroon", "Dark Chocolate"}
COLORS = {"White", "Black", "Natural", "Sand", "Sport Grey", "Navy", "Dark Heather"}
SIZES = ["S", "M", "L", "XL", "2XL"]


def next_product(L) -> str:
    """Which product type this run makes: a fixed rotation (PRODUCT_ROTATION), advanced per listing run."""
    try:
        n = L.db.execute("SELECT COUNT(*) c FROM artifacts WHERE kind='listing'").fetchone()["c"]
    except Exception:
        n = 0
    return ROTATION[n % len(ROTATION)]


_catalog_cache = {}
async def _find_blueprint(c, ptype: str) -> int:
    """Look the product type up in Printify's catalog by title keywords (cached), else the known id."""
    spec = PRODUCTS[ptype]
    if ptype in _catalog_cache: return _catalog_cache[ptype]
    try:
        if "all" not in _catalog_cache:
            r = await c.get(f"{API}/catalog/blueprints.json"); r.raise_for_status(); _catalog_cache["all"] = r.json()
        for bp in _catalog_cache["all"]:
            t = bp.get("title", "")
            if all(k.lower() in t.lower() for k in spec["titles"]) and ("Gildan" in t or ptype in ("mug", "tote")):
                _catalog_cache[ptype] = bp["id"]; return bp["id"]
    except Exception:
        pass
    _catalog_cache[ptype] = spec["fallback"]; return spec["fallback"]


def _price_for(ptype: str, v: dict) -> int:
    size = v.get("options", {}).get("size", "")
    return PRODUCTS[ptype]["price"].get(size, PRODUCTS[ptype]["price"]["default"])


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
    if not chosen:  # mugs/totes: no colour/size grid worth filtering; take what the provider offers (up to 6)
        chosen = allv[:6]
    return provider, chosen


async def create_product(ctx, *, design_from: str = "design_draft.files", products=("tee",), dry_run: bool = True, **_):
    concept = (ctx.get("trend_scan") or {}).get("concept", "design")
    # which product: the trend scan may name one (from the rotation shown to it); else the rotation itself
    wanted = [p for p in ((ctx.get("trend_scan") or {}).get("products") or []) if p in PRODUCTS]
    ptype = wanted[0] if wanted else (next_product(ctx["_ledger"]) if ctx.get("_ledger") is not None else "tee")
    spec = PRODUCTS[ptype]
    if dry_run or not config.PRINTIFY_API_KEY:
        pid = f"pf_{random.randint(100000, 999999)}"
        return {"product_id": pid, "product": spec["label"], "type": ptype, "provider": "sample", "mockups": [f"https://example.invalid/mockup/{pid}/{ptype}.png"],
                "cost": 0.0, "summary": f"Mockups built for {spec['label'].lower()} ({pid})"}
    import httpx
    files = _lookup(ctx, design_from) or []
    if not files: return {"summary": "no design file", "incident": "Mockup build skipped · no design file from Design draft", "cost": 0.0}
    by_variant = (ctx.get("design_draft") or {}).get("by_variant") or {}
    light_path = by_variant.get("light") or files[0]; dark_path = by_variant.get("dark") or light_path
    async with httpx.AsyncClient(timeout=180, headers=_hdr()) as c:
        ids = {}
        for label, path in {"light": light_path, "dark": dark_path}.items():
            if path in ids.values(): continue
            up = await c.post(f"{API}/uploads/images.json", json={"file_name": f"{ctx['run_id']}_{label}.png", "contents": _b64(path)})
            if up.status_code >= 400: return {"summary": "upload failed", "incident": f"Print partner rejected the design upload · {up.status_code} {up.text[:120]}", "cost": 0.0}
            ids[label] = up.json()["id"]
        light_id = ids.get("light"); dark_id = ids.get("dark", light_id)
        bp = await _find_blueprint(c, ptype)
        provider, variants = await _pick_provider_and_variants(c, bp)
        light_v = [v["id"] for v in variants if v.get("options", {}).get("color") not in DARK or ptype in ("poster", "mug")]
        dark_v = [v["id"] for v in variants if v.get("options", {}).get("color") in DARK and ptype not in ("poster", "mug")]
        areas = []; place = {"x": 0.5, "y": spec["y"], "scale": spec["scale"], "angle": 0}
        if light_v: areas.append({"variant_ids": light_v, "placeholders": [{"position": "front", "images": [{"id": light_id, **place}]}]})
        if dark_v: areas.append({"variant_ids": dark_v, "placeholders": [{"position": "front", "images": [{"id": dark_id, **place}]}]})
        body = {"title": f"{concept.title()} {spec['label']}"[:140], "description": f"{concept}. Made to order.", "blueprint_id": bp, "print_provider_id": provider["id"],
                "variants": [{"id": v["id"], "price": _price_for(ptype, v), "is_enabled": True} for v in variants],
                "print_areas": areas}
        r = await c.post(f"{API}/shops/{config.PRINTIFY_SHOP_ID}/products.json", json=body)
        if r.status_code >= 400: return {"summary": "product create failed", "incident": f"Print partner could not create the product · {r.status_code} {r.text[:160]}", "cost": 0.0}
        p = r.json()
        mockups = [i["src"] for i in p.get("images", []) if i.get("src")]
        return {"product_id": p["id"], "product": spec["label"], "type": ptype, "mockups": mockups, "provider": provider["title"], "variants": len(variants), "cost": 0.0,
                "summary": f"{spec['label']} {p['id']} built · {provider['title']} · {len(variants)} variants · {len(mockups)} mockups"}


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
