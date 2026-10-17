"""Treasury tools: record sales pulled by other bays, and reconcile."""
from .. import config

async def record_sales(ctx, *, sales_from: str = "collect.sales", bay: str = "etsy", dry_run: bool = True, **_):
    sales = _lookup(ctx, sales_from) or []
    total = 0.0
    for s in sales:
        ctx["_ledger"].emit(bay, "sale", f"Sale ${s['amount']:.2f} · {s.get('title','')}", agent="VAULT", amount=s["amount"], run_id=ctx["run_id"])
        if s.get("print_cost"):
            ctx["_ledger"].emit(bay, "cost", f"Print + shipping ${s['print_cost']:.2f} · {s.get('title','')}", agent="VAULT", amount=s["print_cost"], run_id=ctx["run_id"])
        total += s["amount"]
    return {"recorded": len(sales), "total": round(total, 2), "cost": 0.0, "summary": f"{len(sales)} sale(s) recorded, ${total:.2f}"}

async def record_payout(ctx, *, bay: str = "studio", dry_run: bool = True, **_):
    """Record the payout for a delivered order (in dry run, immediately; live, when the platform clears it)."""
    o = ctx.get("order") or {}
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
    if d:
        ctx["_ledger"].kv_set("directive", d)
        st = mission.state(ctx["_ledger"])
        ctx["_ledger"].emit("core", "mission", "Directive updated · " + d, agent=config.MOTHER_NAME, directive=d, velocity_per_day=st["velocity_per_day"], run_id=ctx["run_id"])
    return {"cost": 0.0, "summary": "Directive published" if d else "No directive change"}
