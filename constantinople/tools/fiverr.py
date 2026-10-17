"""Fiverr has no public order API. Orders reach the Thumbnail Studio one of three ways:
  1. POST /inbound/order on this engine (from a Zapier/Make email parser or a browser agent),
  2. an IMAP mailbox poll of Fiverr order notification emails (fill in `poll_inbox`),
  3. by hand, from the engine CLI: `python -m constantinople order studio --niche finance --qty 3 --amount 105`.
Delivery is uploaded back to the Fiverr order page by a human or a browser agent; this tool packages the files."""
import random, shutil
from pathlib import Path
from .. import config

async def poll_inbox(ctx, *, dry_run: bool = True, **_):
    if dry_run:
        if random.random() < 0.6:
            return {"orders": [], "cost": 0.0, "summary": "no new orders"}
        qty = random.choice([1, 2, 3, 5]); amt = qty * random.choice([25, 35, 45])
        return {"orders": [{"order_id": f"FO{random.randint(10**7, 10**8)}", "niche": random.choice(["finance", "true crime", "cooking", "travel vlog", "tech review"]),
                            "qty": qty, "amount": amt, "brief": "high contrast, reaction face, 3 words max"}], "cost": 0.0, "summary": "1 new order"}
    return {"orders": [], "cost": 0.0, "summary": "inbox polling not configured"}

async def package(ctx, *, files_from: str = "render_batch.files", picks_from: str = "score.picks", dry_run: bool = True, **_):
    files = _lookup(ctx, files_from) or []
    picks = _lookup(ctx, picks_from) or list(range(min(3, len(files))))
    out = config.ROOT / "output" / "deliveries" / ctx["run_id"]; out.mkdir(parents=True, exist_ok=True)
    delivered = []
    for i in picks:
        if i < len(files):
            dst = out / f"thumbnail_{i+1}.png"; shutil.copy(files[i], dst); delivered.append(str(dst))
    return {"delivered": delivered, "folder": str(out), "cost": 0.0, "summary": f"{len(delivered)} finals packaged in {out.name}"}

def _lookup(ctx, path):
    cur = ctx
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur: cur = cur[part]
        else: return None
    return cur
