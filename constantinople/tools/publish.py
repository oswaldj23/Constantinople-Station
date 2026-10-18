"""Launch Bay: drafts a social post (caption + hashtags + the newest listing's mockup) and hands it to the
bridge — Telegram shows it with the image so the Creator can paste it into Instagram/TikTok/Pinterest in
ten seconds. No scheduler API is wired (none is free and reliable); the phone is the honest route."""
import json, random
from .. import config

async def schedule(ctx, *, caption_from: str = "caption.caption", dry_run: bool = True, **_):
    caption = _lookup(ctx, caption_from) or ""
    tags = " ".join((ctx.get("caption") or {}).get("hashtags") or [])
    out = config.ROOT / "output" / "posts"; out.mkdir(parents=True, exist_ok=True)
    image = None
    try:
        from .clips import latest_assets_from_listing
        a = latest_assets_from_listing(ctx["_ledger"]); image = (a.get("mockups") or [None])[0] or (a.get("designs") or [None])[0]
    except Exception: pass
    draft = (caption + ("\n\n" + tags if tags else "")).strip()
    p = out / f"{ctx['run_id']}.json"
    p.write_text(json.dumps({"caption": caption, "hashtags": tags, "image": image}, indent=2))
    return {"post_file": str(p), "draft": draft, "image": image, "cost": 0.0, "summary": "Post drafted and sent to the bridge" if draft else "Nothing to draft"}

async def metrics(ctx, *, dry_run: bool = True, **_):
    if dry_run: return {"ctr": round(random.uniform(2, 7), 1), "cost": 0.0, "summary": f"Metrics (simulated) · CTR {random.uniform(2,7):.1f}%"}
    return {"cost": 0.0, "summary": "No social metrics source wired · skipped"}

def _lookup(ctx, path):
    cur = ctx
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur: cur = cur[part]
        else: return None
    return cur
