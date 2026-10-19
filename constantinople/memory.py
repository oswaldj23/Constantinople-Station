"""Mother's memory. Everything is already in the ledger; this module turns it into things she can reason with:
a digest of the last N days, per-listing performance, and a short list of notes she writes to herself
after each mission review so directives improve week over week instead of resetting."""
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone


def _since(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def shop_state(L) -> dict:
    """How open for business the shop actually is: listings published to Etsy (not just drafted), the oldest
    one's age, and a plain verdict Mother must respect before blaming demand."""
    pubs = L.db.execute("SELECT ts, msg FROM events WHERE bay='etsy' AND kind='publish' AND (msg LIKE 'Published %' OR msg LIKE 'Listing live %') ORDER BY ts").fetchall()
    live = len(pubs)
    oldest = max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(pubs[0]["ts"].replace("Z", "+00:00"))).days) if pubs else 0
    drafted = L.db.execute("SELECT COUNT(*) c FROM artifacts WHERE kind='listing'").fetchone()["c"]
    if live == 0: verdict = "NOTHING IS LIVE ON ETSY YET. Zero sales means nothing about demand; the shop is not open. Get listings published first."
    elif oldest < 14: verdict = f"Shop opened {oldest} day(s) ago. New Etsy listings take 2–4 weeks to earn impressions; zero sales is expected and says nothing about demand yet."
    elif oldest < 45: verdict = f"Shop open {oldest} days. Judge demand per listing only after 30+ days live; prefer adding listings and occasions over cutting niches."
    else: verdict = f"Shop open {oldest} days; sales data is meaningful. Lean on winners, retire 45-day zero-sale listings."
    return {"listings_drafted": drafted, "listings_live_on_etsy": live, "oldest_live_days": oldest, "verdict": verdict}


def digest(L, days: int = 7) -> dict:
    since = _since(days)
    rows = L.db.execute("SELECT kind, bay, msg, amount, agent FROM events WHERE ts>=?", (since,)).fetchall()
    sales = [r for r in rows if r["kind"] == "sale"]
    costs = sum((r["amount"] or 0) for r in rows if r["kind"] in ("cost", "step") and r["amount"])
    titles = Counter((r["msg"].split("·", 1)[1].strip() if "·" in r["msg"] else r["msg"]) for r in sales)
    incidents = Counter(r["bay"] for r in rows if r["kind"] == "incident")
    directives = [r["msg"].replace("Directive updated · ", "") for r in rows if r["kind"] == "mission" and r["msg"].startswith("Directive updated")]
    notes = json.loads(L.kv_get("mother_notes") or "[]")
    return {"days": days, "sales_count": len(sales), "revenue": round(sum(r["amount"] or 0 for r in sales), 2), "cost": round(costs, 2),
            "listings": sum(1 for r in rows if r["kind"] == "complete" and r["bay"] == "etsy"),
            "incidents": sum(incidents.values()), "incidents_by_bay": dict(incidents),
            "mother_actions": sum(1 for r in rows if r["kind"] == "mother"),
            "top": titles.most_common(5), "directives": directives[-5:], "notes": notes[-5:], "shop": shop_state(L)}


def add_note(L, note: str, keep: int = 30):
    if not note: return
    notes = json.loads(L.kv_get("mother_notes") or "[]")
    notes.append(f"{datetime.now(timezone.utc).strftime('%m-%d')} · {note.strip()[:240]}")
    L.kv_set("mother_notes", json.dumps(notes[-keep:]))


def listing_performance(L, stale_days: int = 30, winner_sales: int = 3) -> list[dict]:
    """One row per listing the station has made: sales, revenue, age, and a flag Mother can act on."""
    arts = L.db.execute("SELECT ts, title, payload FROM artifacts WHERE kind='listing' ORDER BY id DESC").fetchall()
    sales = L.db.execute("SELECT msg, amount, ts FROM events WHERE kind='sale'").fetchall()
    by_title = defaultdict(lambda: {"n": 0, "rev": 0.0})
    for s in sales:
        t = (s["msg"].split("·", 1)[1].strip() if "·" in s["msg"] else s["msg"]).lower()
        by_title[t]["n"] += 1; by_title[t]["rev"] += s["amount"] or 0
    now = datetime.now(timezone.utc); out = []
    for a in arts:
        title = a["title"] or ""; key = title.lower()
        # sales from Printify carry the product title; match on the concept words before the first '|'
        concept = key.split("|")[0].strip()
        hit = by_title.get(key) or next((v for k, v in by_title.items() if concept and concept in k), {"n": 0, "rev": 0.0})
        age = max(0, (now - datetime.fromisoformat(a["ts"].replace("Z", "+00:00"))).days)
        p = json.loads(a["payload"] or "{}")
        flag = "winner" if hit["n"] >= winner_sales else ("stale" if age >= stale_days and hit["n"] == 0 else "")
        out.append({"title": title, "concept": concept, "style": (p.get("trend_scan") or {}).get("style") or ((p.get("research") or {}).get("brief") or {}).get("style") or "botanical", "sales": hit["n"], "revenue": round(hit["rev"], 2), "age_days": age, "flag": flag,
                    "product_id": (p.get("mockup_build") or {}).get("product_id"), "price": (p.get("listing_draft") or {}).get("price")})
    return out
