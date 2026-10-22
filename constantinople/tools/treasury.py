"""Treasury tools: record sales pulled by other bays, and reconcile."""
from datetime import datetime, timedelta, timezone
from .. import config

async def record_sales(ctx, *, sales_from: str = "collect.sales", bay: str = "etsy", only_if_no_printify: bool = False, dry_run: bool = True, **_):
    sales = _lookup(ctx, sales_from) or []
    if only_if_no_printify and not dry_run and config.PRINTIFY_API_KEY:
        return {"recorded": 0, "total": 0.0, "cost": 0.0, "summary": f"{len(sales)} Etsy receipt(s) seen · already counted via Printify"}
    total = 0.0
    for s in sales:
        ctx["_ledger"].emit(bay, "sale", f"Sale ${s['amount']:.2f} · {s.get('title','')}", agent="VAULT", amount=s["amount"], run_id=ctx["run_id"])
        if s.get("print_cost"):
            ctx["_ledger"].emit(bay, "cost", f"Print + shipping ${s['print_cost']:.2f} · {s.get('title','')}", agent="VAULT", amount=s["print_cost"], run_id=ctx["run_id"])
        total += s["amount"]
    return {"recorded": len(sales), "total": round(total, 2), "cost": 0.0, "summary": f"{len(sales)} sale(s) recorded, ${total:.2f}"}

async def record_payout(ctx, *, bay: str = "studio", dry_run: bool = True, **_):
    """Record the payout for a delivered order (in dry run, immediately; live, when the platform clears it)."""
    o = ctx.get("order") or ctx.get("clip_order") or {}
    amt = float(o.get("amount") or 0)
    if amt:
        ctx["_ledger"].emit(bay, "sale", f"Payout ${amt:.2f} · order {o.get('order_id','?')} delivered", agent="VAULT", amount=amt, run_id=ctx["run_id"])
    return {"amount": amt, "cost": 0.0, "summary": f"Order closed · ${amt:.2f} payout recorded"}

async def pnl(ctx, *, days: int = 30, dry_run: bool = True, **_):
    """Profit and loss by channel over the window: revenue, print/platform costs, agent/API spend, margin,
    and output counts. Etsy fees are estimated at 9.5% of revenue (transaction + payment + listing)."""
    L = ctx["_ledger"]; since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = L.db.execute("SELECT bay, kind, amount, data FROM events WHERE ts>=?", (since,)).fetchall()
    ch = {}
    def c(b): return ch.setdefault(b, {"revenue": 0.0, "print_cost": 0.0, "fees": 0.0, "agent_spend": 0.0, "units": 0})
    import json as _j
    for r in rows:
        b = r["bay"]; amt = float(r["amount"] or 0)
        if r["kind"] == "sale":
            d = c(b); d["revenue"] += amt; d["units"] += 1
            try: d["print_cost"] += float((_j.loads(r["data"] or "{}") or {}).get("print_cost") or 0)
            except Exception: pass
            if b == "etsy": d["fees"] += amt * 0.095
        elif r["kind"] in ("step", "cost") and amt: c(b)["agent_spend"] += amt
    out = {}
    for b, d in ch.items():
        margin = d["revenue"] - d["print_cost"] - d["fees"] - d["agent_spend"]
        out[b] = {k: round(v, 2) for k, v in d.items()} | {"margin": round(margin, 2)}
    made = {"listings": L.db.execute("SELECT COUNT(*) c FROM artifacts WHERE kind='listing' AND ts>=?", (since,)).fetchone()["c"],
            "clips": L.db.execute("SELECT COUNT(*) c FROM artifacts WHERE kind='clip' AND ts>=?", (since,)).fetchone()["c"]}
    try:
        from .signal import our_results
        views = sum(v.get("views", 0) for v in (our_results(L).get("top") or []))
    except Exception: views = 0
    total_margin = round(sum(v["margin"] for v in out.values()), 2)
    L.kv_set("pnl", _j.dumps({"days": days, "channels": out, "made": made, "total_margin": total_margin}, default=str))
    return {"days": days, "channels": out, "made": made, "views_top": views, "total_margin": total_margin, "cost": 0.0,
            "summary": f"{days}d margin ${total_margin:,.2f} · " + " · ".join(f"{b} ${v['margin']:,.2f}" for b, v in out.items()) if out else f"{days}d · no money moved yet"}


async def shop_facts(ctx, *, dry_run: bool = True, **_):
    """What the ledger and Printify know about the shop, for the buyer's-eye audit."""
    import json as _j
    from .. import memory, calendar as cal
    L = ctx["_ledger"]; rows = memory.listing_performance(L)
    live = L.db.execute("SELECT COUNT(*) c FROM events WHERE bay='etsy' AND kind='publish' AND (msg LIKE 'Published %' OR msg LIKE 'Listing live %')").fetchone()["c"]
    products = []
    if not dry_run and config.PRINTIFY_API_KEY:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=60, headers={"Authorization": f"Bearer {config.PRINTIFY_API_KEY}"}) as c:
                r = await c.get(f"https://api.printify.com/v1/shops/{config.PRINTIFY_SHOP_ID}/products.json", params={"limit": 50})
                for p in (r.json().get("data", []) if r.status_code == 200 else []):
                    ext = p.get("external") or {}; vs = [v for v in p.get("variants", []) if v.get("is_enabled")]
                    products.append({"title": p.get("title", "")[:90], "published": bool(ext.get("handle")), "url": ext.get("handle"), "images": len(p.get("images", [])), "variants": len(vs),
                                     "price_range": [min((v["price"] for v in vs), default=0) / 100, max((v["price"] for v in vs), default=0) / 100], "has_disclosure": "ai tools" in (p.get("description") or "").lower(), "tags": len(p.get("tags") or [])})
        except Exception as e:
            products = [{"error": str(e)[:100]}]
    styles = {}; types = {}
    for a in L.artifacts(kind_filter="listing", limit=200):
        p = a["payload"]; st = (p.get("trend_scan") or {}).get("style") or "botanical"; ty = (p.get("mockup_build") or {}).get("product") or "T-Shirt"
        styles[st] = styles.get(st, 0) + 1; types[ty] = types.get(ty, 0) + 1
    return {"live_publish_events": live, "listings_in_ledger": len(rows), "printify_products": products, "style_mix": styles, "product_mix": types,
            "upcoming": [o for o in cal.upcoming() if "too late" not in o["verdict"]][:4], "integrations": config.integrations(), "cost": 0.0,
            "summary": f"{len(products) or len(rows)} products · {live} publish events · {len(styles)} styles · {len(types)} product types"}


async def pick_stale(ctx, *, max_items: int = 2, min_age_days: int = 30, dry_run: bool = True, **_):
    """Live listings 30+ days old with zero sales (and zero views when Etsy stats exist), not refreshed in 30 days."""
    import json as _j
    from .. import memory
    L = ctx["_ledger"]; rows = memory.listing_performance(L)
    refreshed = _j.loads(L.kv_get("seo_refreshed") or "{}")
    stats = []
    try: stats = _j.loads(L.kv_get("etsy_stats") or "[]")
    except Exception: pass
    def views_for(concept: str) -> int:
        c = (concept or "").lower()
        return max([int(s.get("views", 0)) for s in stats if c and c in (s.get("title") or "").lower()] or [0])
    now = datetime.now(timezone.utc).timestamp(); picks = []
    for r in rows:
        pid = r.get("product_id")
        if not pid or r["sales"] > 0 or r["age_days"] < min_age_days: continue
        if stats and views_for(r["concept"]) > 25: continue   # people are seeing it; the copy is not the problem
        if now - float(refreshed.get(str(pid), 0)) < 30 * 86400: continue
        picks.append(r)
    picks = picks[:max_items]
    if not picks: return {"nothing": True, "cost": 0.0, "summary": "no stale listings to refresh"}
    arts = {}
    for a in L.artifacts(kind_filter="listing", limit=200):
        p = a["payload"]; mb = p.get("mockup_build") or {}
        if mb.get("product_id"): arts[str(mb["product_id"])] = {"title": (p.get("listing_draft") or {}).get("title"), "tags": (p.get("listing_draft") or {}).get("tags"), "product": mb.get("product"), "style": (p.get("trend_scan") or {}).get("style")}
    listings = [{"product_id": r["product_id"], "concept": r["concept"], "age_days": r["age_days"], **arts.get(str(r["product_id"]), {})} for r in picks]
    return {"listings": listings, "cost": 0.0, "summary": f"{len(listings)} stale listing(s) picked for a refresh"}


async def apply_seo(ctx, *, dry_run: bool = True, **_):
    """Push the new title/tags to Printify and republish so Etsy picks them up; remember the refresh date."""
    import json as _j
    L = ctx["_ledger"]; rw = (ctx.get("rewrite") or {}).get("rewrites") or []
    if not rw: return {"cost": 0.0, "summary": "nothing rewritten"}
    done = []; refreshed = _j.loads(L.kv_get("seo_refreshed") or "{}")
    if dry_run or not config.PRINTIFY_API_KEY:
        for r in rw: refreshed[str(r["product_id"])] = datetime.now(timezone.utc).timestamp(); done.append(r["title"][:50])
    else:
        import httpx
        async with httpx.AsyncClient(timeout=60, headers={"Authorization": f"Bearer {config.PRINTIFY_API_KEY}"}) as c:
            for r in rw:
                pid = r["product_id"]
                u = await c.put(f"https://api.printify.com/v1/shops/{config.PRINTIFY_SHOP_ID}/products/{pid}.json", json={"title": str(r["title"])[:140], "tags": [str(t)[:20] for t in r.get("tags", [])][:13]})
                if u.status_code >= 400: continue
                await c.post(f"https://api.printify.com/v1/shops/{config.PRINTIFY_SHOP_ID}/products/{pid}/publish.json", json={"title": True, "description": False, "images": False, "variants": False, "tags": True, "keyFeatures": False, "shipping_template": False})
                refreshed[str(pid)] = datetime.now(timezone.utc).timestamp(); done.append(r["title"][:50])
    L.kv_set("seo_refreshed", _j.dumps(refreshed))
    if done: L.emit("treasury", "status", "Refreshed titles/tags: " + "; ".join(done), agent="VAULT", run_id=ctx["run_id"])
    return {"refreshed": done, "cost": 0.0, "summary": f"{len(done)} listing(s) refreshed and republished"}


FLOORS = {"etsy": 0.5, "clips": 0.5, "pins": 0.5, "signal": 0.5, "research": 0.5}
CEILS = {"etsy": 2.0, "clips": 1.0, "pins": 2.0, "signal": 1.5, "research": 2.0}   # clips capped by YouTube quota


async def apply_allocation(ctx, *, dry_run: bool = True, **_):
    """Store Mother's weekly multipliers (bounded, max ±0.5 change) and the experiment; the orchestrator reads them."""
    import json as _j
    L = ctx["_ledger"]; r = ctx.get("council") or {}; alloc = r.get("allocation") or {}
    prev = _j.loads(L.kv_get("allocation") or "{}")
    new = {}
    for bay in FLOORS:
        want = float(alloc.get(bay, 1.0) or 1.0); last = float(prev.get(bay, 1.0))
        want = max(last - 0.5, min(last + 0.5, want)); want = max(FLOORS[bay], min(CEILS[bay], want))
        new[bay] = round(want, 2)
    L.kv_set("allocation", _j.dumps(new))
    exp = r.get("experiment") or {}
    if exp.get("name"):
        L.kv_set("experiment", _j.dumps({**exp, "set_on": datetime.now(timezone.utc).strftime("%Y-%m-%d")}))
    if r.get("note"):
        from .. import memory; memory.add_note(L, "Council: " + r["note"])
    L.emit("core", "mother", "Council: " + ", ".join(f"{b} ×{m}" for b, m in new.items()) + (f" · experiment: {exp.get('name')} (target {exp.get('success')})" if exp.get("name") else ""), agent=config.MOTHER_NAME, run_id=ctx["run_id"], action="council")
    return {"allocation": new, "experiment": exp, "cost": 0.0, "summary": "allocation applied · " + ", ".join(f"{b} ×{m}" for b, m in new.items())}


async def reconcile(ctx, *, dry_run: bool = True, **_):
    t = ctx["_ledger"].totals()
    margin = (t["rev"] - t["cost"]) / t["rev"] * 100 if t["rev"] else 0
    return {"totals": t, "margin_pct": round(margin, 1), "cost": 0.0, "summary": f"Rev ${t['rev']:.2f} · spend ${t['cost']:.2f} · margin {margin:.1f}%"}

def _lookup(ctx, path):
    cur = ctx
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur: cur = cur[part]
        else: return None
    return cur


async def publish_directive(ctx, *, from_step: str = "mission_review", dry_run: bool = True, **_):
    """Store the Core's directive and announce it to the crew."""
    from .. import mission, config
    r = ctx.get(from_step) or {}
    d = r.get("directive")
    if d and d == ctx["_ledger"].kv_get("directive"):
        return {"cost": 0.0, "summary": "Directive unchanged"}
    note = r.get("note")
    if note:
        from .. import memory
        memory.add_note(ctx["_ledger"], note)
    if d:
        ctx["_ledger"].kv_set("directive", d)
        st = mission.state(ctx["_ledger"])
        ctx["_ledger"].emit("core", "mission", "Directive updated · " + d, agent=config.MOTHER_NAME, directive=d, velocity_per_day=st["velocity_per_day"], run_id=ctx["run_id"])
    return {"cost": 0.0, "summary": "Directive published" if d else "No directive change"}


async def reconcile_removed(L, c, rows: list) -> list:
    """Listings the ledger made that no longer exist in Printify were taken down by the Creator (a bad mockup,
    a design he did not like). Remember them, say so, and queue a remake of the same concept — the design is
    kept, the placement is rebuilt and re-checked — unless the Creator says otherwise. Returns the new removals."""
    import json as _j
    from .. import config as cfg
    r = await c.get(f"https://api.printify.com/v1/shops/{cfg.PRINTIFY_SHOP_ID}/products.json", params={"limit": 100})
    if r.status_code != 200: return []
    live_ids = {str(p["id"]) for p in r.json().get("data", [])}
    queue = _j.loads(L.kv_get("remake_queue") or "[]"); known = {str(q.get("product_id")) for q in queue}
    arts = {}
    for a in L.artifacts(kind_filter="listing", limit=300):
        p = a["payload"]; mb = p.get("mockup_build") or {}
        if mb.get("product_id"): arts[str(mb["product_id"])] = {"title": a["title"], "trend_scan": p.get("trend_scan") or {}, "product": mb.get("product"), "type": mb.get("type"), "design": p.get("design_draft") or {}}
    new = []
    for pid, info in arts.items():
        if pid in live_ids or pid in known or pid.startswith("pf_"): continue
        ts = info["trend_scan"]
        entry = {"product_id": pid, "title": info["title"], "concept": ts.get("concept"), "text": ts.get("text") or info["design"].get("text"), "style": ts.get("style"), "design_prompt": ts.get("design_prompt"),
                 "product_type": info.get("type") or "tee", "product": info.get("product"), "status": "queued", "removed_at": datetime.now(timezone.utc).isoformat()}
        queue.append(entry); new.append(entry)
    if new:
        L.kv_set("remake_queue", _j.dumps(queue[-50:]))
        for e in new:
            L.emit("review", "status", f"Creator removed \"{(e['title'] or e['concept'] or '')[:60]}\" ({(e['product'] or '').lower()}) from Printify · design kept, placement will be rebuilt and checked before it comes back · /remake off to cancel", agent="VAULT")
    return new


async def check_removed(ctx, *, dry_run: bool = True, **_):
    """Every Treasury cycle: has the Creator deleted any of our products in Printify? (see reconcile_removed)"""
    if dry_run or not config.PRINTIFY_API_KEY: return {"cost": 0.0, "summary": "removed check (sample)"}
    import httpx
    from .. import memory
    try:
        async with httpx.AsyncClient(timeout=60, headers={"Authorization": f"Bearer {config.PRINTIFY_API_KEY}"}) as c:
            new = await reconcile_removed(ctx["_ledger"], c, memory.listing_performance(ctx["_ledger"]))
    except Exception as e:
        return {"cost": 0.0, "summary": f"removed check skipped ({type(e).__name__})"}
    return {"removed": [n["title"] for n in new], "cost": 0.0, "summary": f"{len(new)} product(s) removed by the Creator · remake queued" if new else "no products removed"}


def next_remake(L) -> dict | None:
    """The oldest queued remake, if any: the Etsy bay makes this before anything new."""
    import json as _j
    try:
        q = _j.loads(L.kv_get("remake_queue") or "[]")
        return next((r for r in q if r.get("status") == "queued"), None)
    except Exception:
        return None


async def review_listings(ctx, *, dry_run: bool = True, **_):
    """Daily control loop: which listings sell, which are dead, what Research should double down on.
    Flags only by default. AUTO_RETIRE unpublishes stale listings; AUTO_PRICE raises winners' prices 10%."""
    from .. import memory, config as cfg
    rows = memory.listing_performance(ctx["_ledger"])
    winners = [r for r in rows if r["flag"] == "winner"]; stale = [r for r in rows if r["flag"] == "stale"]
    actions = []
    if not dry_run and cfg.PRINTIFY_API_KEY:
        import httpx
        async with httpx.AsyncClient(timeout=60, headers={"Authorization": f"Bearer {cfg.PRINTIFY_API_KEY}"}) as c:
            try:
                removed = await reconcile_removed(ctx["_ledger"], c, rows)
                if removed: actions.append(f"{len(removed)} removed by Creator → remake queued")
                gone = {str(r["product_id"]) for r in __import__("json").loads(ctx["_ledger"].kv_get("remake_queue") or "[]")}
                rows = [r for r in rows if str(r.get("product_id")) not in gone]; winners = [r for r in winners if str(r.get("product_id")) not in gone]; stale = [r for r in stale if str(r.get("product_id")) not in gone]
            except Exception:
                pass
            if cfg.AUTO_RETIRE:
                for r in stale:
                    if r.get("product_id"):
                        await c.post(f"https://api.printify.com/v1/shops/{cfg.PRINTIFY_SHOP_ID}/products/{r['product_id']}/unpublish.json"); actions.append(f"retired {r['concept']}")
            if cfg.AUTO_PRICE:
                for r in winners:
                    if r.get("product_id"):
                        pr = await c.get(f"https://api.printify.com/v1/shops/{cfg.PRINTIFY_SHOP_ID}/products/{r['product_id']}.json")
                        if pr.status_code == 200:
                            vs = [{"id": v["id"], "price": int(v["price"] * 1.10)} for v in pr.json().get("variants", []) if v.get("is_enabled")]
                            await c.put(f"https://api.printify.com/v1/shops/{cfg.PRINTIFY_SHOP_ID}/products/{r['product_id']}.json", json={"variants": vs}); actions.append(f"+10% on {r['concept']}")
    L = ctx["_ledger"]
    if winners: L.emit("treasury", "trend", "Winners: " + ", ".join(f"{w['concept']} ({w['sales']} sold)" for w in winners[:5]) + " · Research: make variants of these", agent="VAULT", run_id=ctx["run_id"])
    if stale: L.emit("treasury", "status", f"{len(stale)} listing(s) with no sales after 30 days" + (" · retired" if cfg.AUTO_RETIRE else " · flagged for review"), agent="VAULT", run_id=ctx["run_id"])
    L.kv_set("winners", ", ".join(w["concept"] for w in winners[:5]))
    return {"rows": len(rows), "winners": [w["concept"] for w in winners], "stale": [s["concept"] for s in stale], "actions": actions, "cost": 0.0,
            "summary": f"{len(rows)} listings reviewed · {len(winners)} winner(s) · {len(stale)} stale" + (f" · {len(actions)} action(s)" if actions else "")}
