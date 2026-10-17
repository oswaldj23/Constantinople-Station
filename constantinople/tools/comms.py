"""Send a reply back to the platform the message came from. Dry run logs it. Real implementations
differ per platform (Etsy conversations via mailbox; Fiverr inbox via browser agent)."""
from .. import config

async def send(ctx, *, reply_from: str = "draft_reply.reply", dry_run: bool = True, **_):
    reply = _lookup(ctx, reply_from) or ""
    m = ctx.get("message") or {}
    if dry_run:
        return {"sent": True, "cost": 0.0, "summary": f"Reply sent to {m.get('platform','?')} buyer ({len(reply)} chars)"}
    # Etsy conversations cannot be answered by API or email: hand the draft to the Creator (Telegram shows it with a copy box)
    ctx["_ledger"].emit("comms", "reply", f"Draft ready for {m.get('from','buyer')} · \"{reply[:80]}…\"", agent="HERALD", run_id=ctx["run_id"], draft=reply, to_buyer=m.get("from"))
    return {"sent": False, "cost": 0.0, "summary": f"Reply drafted for {m.get('from','buyer')} · sent to {config.CREATOR} to paste into Etsy"}

def _lookup(ctx, path):
    cur = ctx
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur: cur = cur[part]
        else: return None
    return cur
