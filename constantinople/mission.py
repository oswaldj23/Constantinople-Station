"""The Prime Mission: $1,000,000,000,000 banked. Fifteen worlds on the route; the Core publishes
position, velocity and ETA every sol so the crew steers by the same numbers."""
import math
from datetime import datetime, timedelta, timezone
from . import config

WAYPOINTS = [(1e3, "First Light"), (1e4, "Ember Reach"), (1e5, "Meridian Gate"), (1e6, "Sable Crossing"),
             (1e7, "Bosphorus Deep"), (1e8, "The Verge"), (2.5e8, "Theodora's Reach"), (5e8, "Halfmark"),
             (1e9, "Aurum Belt"), (5e9, "Argent Field"), (1e10, "Cold Harbor"), (1e11, "Last Lantern"),
             (2.5e11, "Obsidian Gate"), (5e11, "Penumbra"), (1e12, "Trillion Dawn")]


def short(n: float) -> str:
    for v, u in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if n >= v: return f"${n / v:g}{u}"
    return f"${n:,.0f}"


def velocity_per_day(ledger, days: int = 14) -> float:
    """Revenue per day over the trailing window, from the ledger's sale events."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    row = ledger.db.execute("SELECT COALESCE(SUM(amount),0) s, MIN(ts) t0 FROM events WHERE kind='sale' AND ts>=?", (since,)).fetchone()
    if not row or not row["t0"]: return 0.0
    span = max(1 / 24, (datetime.now(timezone.utc) - datetime.fromisoformat(row["t0"].replace("Z", "+00:00"))).total_seconds() / 86400)
    return row["s"] / span


def state(ledger) -> dict:
    rev = max(1.0, ledger.totals()["rev"])
    li = next((i for i, (v, _) in enumerate(WAYPOINTS) if rev < v), len(WAYPOINTS) - 1)
    prev = 1.0 if li == 0 else WAYPOINTS[li - 1][0]
    nxt, name = WAYPOINTS[li]
    leg_pct = max(0.0, min(1.0, (math.log10(rev) - math.log10(prev)) / (math.log10(nxt) - math.log10(prev))))
    journey = max(0.0, min(1.0, (li - 1 + leg_pct) / (len(WAYPOINTS) - 1)))   # world to world; log-scale inside a leg
    vel = velocity_per_day(ledger)
    first = ledger.db.execute("SELECT MIN(ts) t FROM events").fetchone()["t"]
    return {
        "target": config.MISSION_TARGET, "banked": round(rev, 2), "leg": li + 1, "legs": len(WAYPOINTS),
        "next_waypoint": {"amount": nxt, "name": name}, "leg_pct": round(leg_pct * 100, 2), "journey_pct": round(journey * 100, 4),
        "velocity_per_day": round(vel, 2),
        "eta_next_days": round((nxt - rev) / vel, 1) if vel > 0 else None,
        "eta_target_days": round((config.MISSION_TARGET - rev) / vel, 1) if vel > 0 else None,
        "required_velocity_10y": round((config.MISSION_TARGET - rev) / 3652, 2),
        "doublings_left": round(max(0.0, math.log2(config.MISSION_TARGET / rev)), 2),
        "started_at": first, "directive": ledger.kv_get("directive"),
    }


def check_waypoint(ledger, emit_agent: str):
    """Emit a WAYPOINT REACHED event when the banked total crosses into a new leg."""
    st = state(ledger)
    last = int(ledger.kv_get("mission_leg") or 1)
    if st["leg"] > last:
        reached = WAYPOINTS[st["leg"] - 2]
        ledger.emit("core", "mission", f"WAYPOINT REACHED · {reached[1]} ({short(reached[0])}) · next: {st['next_waypoint']['name']} at {short(st['next_waypoint']['amount'])}",
                    agent=emit_agent, waypoint=reached[1], leg=st["leg"])
        ledger.kv_set("mission_leg", str(st["leg"]))
    elif ledger.kv_get("mission_leg") is None:
        ledger.kv_set("mission_leg", str(st["leg"]))
