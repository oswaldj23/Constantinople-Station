"""Launch Bay: schedule and post content. Dry run writes the post to output/posts. Real: plug a social
scheduler API (Buffer, Later, Metricool…) or a browser agent."""
import json, random
from .. import config

async def schedule(ctx, *, caption_from: str = "caption.caption", dry_run: bool = True, **_):
    caption = _lookup(ctx, caption_from) or ""
    out = config.ROOT / "output" / "posts"; out.mkdir(parents=True, exist_ok=True)
    p = out / f"{ctx['run_id']}.json"
    p.write_text(json.dumps({"caption": caption, "when": "next peak window", "assets": ctx.get("assets", [])}, indent=2))
    return {"post_file": str(p), "cost": 0.0, "summary": random.choice(["Scheduled for peak window", "Queued behind 2 posts", "Scheduled: product photos + clip"])}

async def metrics(ctx, *, dry_run: bool = True, **_):
    return {"ctr": round(random.uniform(2, 7), 1), "cost": 0.0, "summary": f"Metrics pulled · CTR {random.uniform(2,7):.1f}%"}

def _lookup(ctx, path):
    cur = ctx
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur: cur = cur[part]
        else: return None
    return cur
