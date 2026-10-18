"""Signal Deck helpers: turn the YouTube scan into a shared brief the Clip Forge and Mother can act on,
and remember what we have already made so the Forge does not repeat itself."""
import json
from .. import config


async def compile_brief(ctx, *, scan_from: str = "shorts_scan", rank_from: str = "signal_rank", dry_run: bool = True, **_):
    scan = ctx.get(scan_from) or {}; rank = ctx.get(rank_from) or {}
    seeds = [{k: s.get(k) for k in ("format", "sub", "title", "score", "comments", "gist")} for s in ((ctx.get("story_scan") or {}).get("seeds") or [])[:12]]
    genres = scan.get("genres") or []
    top = genres[:5]
    picks = rank.get("picks") or [{"genre": g["genre"], "format": "fast cuts, big captions, hook in the first second", "why": f"{g['top_views']:,} top views vs {g['supply']:,} uploads"} for g in top[:3]]
    brief = {"scanned_at": scan.get("scanned_at"), "leaders": [{"genre": g["genre"], "top_views": g["top_views"], "median_views": g["median_views"], "supply": g["supply"], "opportunity": g["opportunity"]} for g in top],
             "picks": picks, "hooks": rank.get("hooks") or [], "avoid": rank.get("avoid") or ["copyrighted gameplay or music you do not own", "reposting other creators' clips", "anything that needs a real person on camera"],
             "product_angle": rank.get("product_angle") or "none",
             "story_seeds": seeds, "seed_note": "aita/revenge/story: retell in our own words with names, places and identifying details changed; horror: premise shape only, write original"}
    L = ctx.get("_ledger")
    if L is not None:
        try: L.kv_set("signal_brief", json.dumps(brief, default=str))
        except Exception: pass
    return {**brief, "cost": 0.0, "summary": f"brief: {', '.join(p['genre'] for p in picks[:3])}"}


ROTATION = ["horror", "aita", "revenge", "story", "horror", "aita", "facts", "revenge", "story", "horror"]


def next_format(L) -> str:
    """Deterministic rotation so the writer cannot drift toward one format. Product is allowed only when the
    brief asks for it AND none of the last five shorts was a product short."""
    recent = recent_clips(L, 6); kinds = [c.get("format") or c.get("kind") for c in recent]
    brief = latest_brief(L); wants_product = (brief.get("product_angle") or "none").strip().lower() not in ("", "none", "null")
    if wants_product and len(recent) >= 5 and "product" not in kinds[:5]:
        return "product"
    n = L.db.execute("SELECT COUNT(*) c FROM artifacts WHERE kind='clip'").fetchone()["c"]
    return ROTATION[n % len(ROTATION)]


def latest_brief(L) -> dict:
    try: return json.loads(L.kv_get("signal_brief") or "{}")
    except Exception: return {}


def recent_clips(L, n: int = 12) -> list:
    out = []
    for a in L.artifacts(kind_filter="clip", limit=n):
        p = a["payload"]; r = p.get("render") or {}; up = p.get("upload") or {}; sc = p.get("script") or {}
        out.append({"title": a["title"], "ts": a["ts"], "file": r.get("file"), "thumb": r.get("thumb"), "duration": r.get("duration"), "url": up.get("url"),
                    "genre": sc.get("genre"), "kind": sc.get("kind"), "format": sc.get("format"), "run_id": a.get("run_id")})
    return out
