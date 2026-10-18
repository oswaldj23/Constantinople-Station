"""Treasury tools: record sales pulled by other bays, and reconcile."""
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
