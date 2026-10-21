"""Signal Deck helpers: turn the YouTube scan into a shared brief the Clip Forge and Mother can act on,
and remember what we have already made so the Forge does not repeat itself."""
import json
from .. import config


async def compile_brief(ctx, *, scan_from: str = "shorts_scan", rank_from: str = "signal_rank", dry_run: bool = True, **_):
    scan = ctx.get(scan_from) or {}; rank = ctx.get(rank_from) or {}
    seeds = [{k: s.get(k) for k in ("format", "sub", "title", "score", "comments", "gist")} for s in ((ctx.get("story_scan") or {}).get("seeds") or [])[:12]]
    L0 = ctx.get("_ledger")
    if L0 is not None and (ctx.get("channel") or {}).get("videos"):
        try: L0.kv_set("channel_stats", json.dumps(ctx["channel"], default=str))
        except Exception: pass
    results = our_results(L0, ctx.get("channel")) if L0 is not None else {}
    genres = scan.get("genres") or []
    top = genres[:5]
    picks = rank.get("picks") or [{"genre": g["genre"], "format": "fast cuts, big captions, hook in the first second", "why": f"{g['top_views']:,} top views vs {g['supply']:,} uploads"} for g in top[:3]]
    brief = {"scanned_at": scan.get("scanned_at"), "leaders": [{"genre": g["genre"], "top_views": g["top_views"], "median_views": g["median_views"], "supply": g["supply"], "opportunity": g["opportunity"]} for g in top],
             "picks": picks, "hooks": rank.get("hooks") or [], "avoid": rank.get("avoid") or ["copyrighted gameplay or music you do not own", "reposting other creators' clips", "anything that needs a real person on camera"],
             "product_angle": rank.get("product_angle") or "none",
             "our_results": results, "story_seeds": seeds, "seed_note": "aita/revenge/story: retell in our own words with names, places and identifying details changed; horror: premise shape only, write original"}
    L = ctx.get("_ledger")
    if L is not None:
        try: L.kv_set("signal_brief", json.dumps(brief, default=str))
        except Exception: pass
    return {**brief, "cost": 0.0, "summary": f"brief: {', '.join(p['genre'] for p in picks[:3])}"}


ROTATION = ["horror", "aita", "revenge", "story", "horror", "aita", "facts", "revenge", "story", "horror"]
STORY_FORMATS = ["horror", "aita", "revenge", "story", "facts"]


def our_results(L, channel_stats: dict | None = None) -> dict:
    """What our own shorts did, by format: views per video from the channel scan joined to the Forge's archive
    (which knows each upload's format and hook). Stored in kv 'our_results' by the Signal Deck."""
    stats = channel_stats or {}
    if not stats:
        try: stats = json.loads(L.kv_get("channel_stats") or "{}")
        except Exception: stats = {}
    by_id = {v["id"]: v for v in (stats.get("videos") or []) if v.get("id")}
    try:
        an = json.loads(L.kv_get("yt_analytics") or "{}").get("videos") or {}
        for vid, a in an.items():
            by_id.setdefault(vid, {"id": vid, "views": a.get("views", 0)})
            by_id[vid]["avg_view_pct"] = a.get("avg_view_pct"); by_id[vid]["views"] = max(int(by_id[vid].get("views") or 0), int(a.get("views") or 0))
    except Exception: pass
    rows = []
    for a in L.artifacts(kind_filter="clip", limit=60):
        p = a["payload"]; up = p.get("upload") or {}; sc = p.get("script") or {}
        vid = up.get("video_id") or (up.get("url", "").rsplit("/", 1)[-1] if up.get("url") and "dryrun" not in up.get("url", "") else None)
        if vid and vid in by_id:
            rows.append({"format": sc.get("format") or sc.get("kind") or "story", "visual": sc.get("visual_mode") or "gameplay", "title": a["title"], "hook": sc.get("hook_card") or "", "views": int(by_id[vid].get("views") or 0), "likes": int(by_id[vid].get("likes") or 0), "retention": by_id[vid].get("avg_view_pct")})
    per = {}; vis = {}
    for r in rows:
        d = per.setdefault(r["format"], {"n": 0, "views": 0, "ret": [], "best": None})
        d["n"] += 1; d["views"] += r["views"]
        if r.get("retention") is not None: d["ret"].append(float(r["retention"]))
        if not d["best"] or r["views"] > d["best"]["views"]: d["best"] = {"title": r["title"], "hook": r["hook"], "views": r["views"], "retention": r.get("retention")}
        v = vis.setdefault(r["visual"], {"n": 0, "views": 0, "ret": []}); v["n"] += 1; v["views"] += r["views"]
        if r.get("retention") is not None: v["ret"].append(float(r["retention"]))
    for f, d in per.items():
        d["avg_views"] = round(d["views"] / d["n"]) if d["n"] else 0
        d["avg_retention"] = round(sum(d["ret"]) / len(d["ret"]), 1) if d["ret"] else None; d.pop("ret", None)
    for k, v in vis.items():
        v["avg_views"] = round(v["views"] / v["n"]) if v["n"] else 0; v["avg_retention"] = round(sum(v["ret"]) / len(v["ret"]), 1) if v["ret"] else None; v.pop("ret", None)
    top = sorted(rows, key=lambda r: -r["views"])[:5]
    return {"videos_with_stats": len(rows), "per_format": per, "per_visual": vis, "top": top, "note": "retention (avg % watched) is the primary signal; views second"}


def next_format(L) -> str:
    """Which format the next short is. Until the channel has data (8+ uploaded shorts with view counts) a fixed
    rotation; after that, two of every three picks go to the formats our own numbers favour (weighted by
    average views) and one in three explores the rest, so a format is never abandoned for good. Product is
    allowed only when the brief asks for it AND none of the last five shorts was a product short."""
    recent = recent_clips(L, 6); kinds = [c.get("format") or c.get("kind") for c in recent]
    brief = latest_brief(L); wants_product = (brief.get("product_angle") or "none").strip().lower() not in ("", "none", "null")
    if wants_product and len(recent) >= 5 and "product" not in kinds[:5]:
        return "product"
    n = L.db.execute("SELECT COUNT(*) c FROM artifacts WHERE kind='clip'").fetchone()["c"]
    res = our_results(L)
    if res["videos_with_stats"] >= 8 and len(res["per_format"]) >= 2:
        import random as _r
        rnd = _r.Random(n)   # deterministic per run count, so a restart does not reshuffle
        if n % 3 == 2:   # explore: the format we have tried least
            tried = {f: res["per_format"].get(f, {}).get("n", 0) for f in STORY_FORMATS}
            return min(tried, key=tried.get)
        # weight by retention when we have it (the signal that predicts growth), else by views
        weights = [max(1.0, (res["per_format"].get(f, {}).get("avg_retention") or 0) * 100 or res["per_format"].get(f, {}).get("avg_views", 0)) for f in STORY_FORMATS]
        return rnd.choices(STORY_FORMATS, weights=weights, k=1)[0]
    return ROTATION[n % len(ROTATION)]


def latest_brief(L) -> dict:
    try: return json.loads(L.kv_get("signal_brief") or "{}")
    except Exception: return {}


def recent_clips(L, n: int = 12) -> list:
    out = []
    for a in L.artifacts(kind_filter="clip", limit=n):
        p = a["payload"]; r = p.get("render") or {}; up = p.get("upload") or {}; sc = p.get("script") or {}
        out.append({"title": a["title"], "ts": a["ts"], "file": r.get("file"), "thumb": r.get("thumb"), "duration": r.get("duration"), "url": up.get("url"),
                    "genre": sc.get("genre"), "kind": sc.get("kind"), "format": sc.get("format"), "run_id": a.get("run_id"),
                    "caption": sc.get("caption") or "", "hashtags": sc.get("hashtags") or []})
    return out
