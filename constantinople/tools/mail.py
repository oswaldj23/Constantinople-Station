"""Real Comms inbox. Etsy sends every buyer message and order as an email; Printify sends order and
production emails. HERALD reads them here. Replies to Etsy buyers cannot be sent by email, so HERALD
drafts the reply and hands it to the Creator on Telegram to paste into Etsy (one tap to copy)."""
import email, imaplib, re
from email.header import decode_header
from .. import config

ETSY_SENDERS = ("etsy.com",)
PRINTIFY_SENDERS = ("printify.com",)
FIVERR_SENDERS = ("fiverr.com",)
CLIP_WORDS = ("short", "video", "clip", "reel", "tiktok", "youtube short", "edit")
THUMB_WORDS = ("thumbnail", "thumb")


def _money(text: str) -> float:
    m = re.findall(r"\$\s?(\d{1,4}(?:[.,]\d{2})?)", text)
    try: return max(float(x.replace(",", "")) for x in m) if m else 0.0
    except Exception: return 0.0


def _order_from(platform: str, subj: str, body: str) -> dict | None:
    """Turn a 'new order' email into a station order. Fiverr: 'You have a new order from X' / 'New order: ...'.
    Etsy (a service listing bought as a digital/custom item): 'You made a sale' with the listing title."""
    low = (subj + " " + body[:2000]).lower()
    if not any(k in low for k in ("new order", "you have an order", "you made a sale", "order #", "order from", "purchased")): return None
    m = re.search(r"(?:order|#)\s*#?\s*([A-Z0-9]{6,})", subj + " " + body[:1500], re.I); oid = (m.group(1) if m else None)
    buyer = (re.search(r"from ([A-Za-z0-9_\-]+)", subj) or re.search(r"([A-Za-z0-9_\-]+) has placed", body[:800]) or [None, "buyer"])[1]
    kind = "clip" if any(w in low for w in CLIP_WORDS) else ("thumb" if any(w in low for w in THUMB_WORDS) else None)
    if not kind: return None
    req = re.search(r"(?:requirements?|brief|details?|message)[:\s]+(.{20,900})", body, re.I | re.S)
    brief = re.sub(r"\s+", " ", req.group(1)).strip()[:900] if req else re.sub(r"\s+", " ", body).strip()[:600]
    return {"kind": kind, "platform": platform, "order_id": (platform[:2].upper() + oid) if oid else None, "buyer": buyer, "amount": _money(body) or _money(subj), "brief": brief, "subject": subj}



def _text(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try: return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "ignore")
                except Exception: pass
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                try:
                    html = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "ignore")
                    return re.sub(r"<[^>]+>", " ", html)
                except Exception: pass
        return ""
    try: return msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", "ignore")
    except Exception: return ""


def _subject(msg) -> str:
    raw = msg.get("Subject", ""); out = ""
    for part, enc in decode_header(raw):
        out += part.decode(enc or "utf-8", "ignore") if isinstance(part, bytes) else part
    return out


async def poll(ctx, *, dry_run: bool = True, **_):
    if dry_run:
        import random
        if random.random() < 0.5: return {"messages": [], "cost": 0.0, "summary": "inbox clear"}
        m = random.choice(["Can I get this in XL?", "Does the mug ship to Canada?", "Received the wrong size", "Is the candle soy wax?"])
        return {"messages": [{"platform": "etsy", "from": "buyer", "text": m}], "cost": 0.0, "summary": "1 inbound message"}
    if not (config.MAIL_IMAP_HOST and config.MAIL_USER and config.MAIL_PASSWORD):
        return {"messages": [], "cost": 0.0, "summary": "inbox not connected"}
    out = []; clip_orders = []; orders = []
    L = ctx.get("_ledger"); seen = set((L.kv_get("mail_orders_seen") or "").split(",")) if L is not None else set()
    try:
        M = imaplib.IMAP4_SSL(config.MAIL_IMAP_HOST); M.login(config.MAIL_USER, config.MAIL_PASSWORD); M.select("INBOX")
        typ, data = M.search(None, "(UNSEEN)")
        for num in (data[0].split() if data and data[0] else [])[-20:]:
            typ, raw = M.fetch(num, "(RFC822)")
            msg = email.message_from_bytes(raw[0][1]); frm = (msg.get("From") or "").lower(); subj = _subject(msg); body = _text(msg)
            platform = "fiverr" if any(d in frm for d in FIVERR_SENDERS) else ("etsy" if any(d in frm for d in ETSY_SENDERS) else None)
            order = _order_from(platform, subj, body) if platform else None
            if order:
                key = order["order_id"] or (subj[:60] + str(len(body)))
                if key not in seen:
                    seen.add(key)
                    if order["kind"] == "clip":
                        clip_orders.append({"order_id": order["order_id"] or f"MO{abs(hash(key)) % 10**8}", "niche": (order["brief"][:60] or "client short"), "brief": order["brief"], "cta": "", "amount": order["amount"] or config.CLIP_PRICE, "platform": platform, "buyer": order["buyer"]})
                    else:
                        orders.append({"order_id": order["order_id"] or f"MO{abs(hash(key)) % 10**8}", "niche": (order["brief"][:60] or "thumbnail"), "qty": 1, "amount": order["amount"] or 35.0, "brief": order["brief"], "platform": platform})
                    ctx["_ledger"].emit("clips" if order["kind"] == "clip" else "studio", "order", f"{platform.title()} order {order['order_id'] or ''}: {order['kind']} · ${(order['amount'] or 0):.2f} · {order['buyer']}", agent="REEL" if order["kind"] == "clip" else "RAY")
                M.store(num, "+FLAGS", "\\Seen"); continue
            if any(d in frm for d in ETSY_SENDERS) and ("message" in subj.lower() or "conversation" in subj.lower() or "reply" in subj.lower()):
                m = re.search(r"from (.+?)[:\n]", subj) ; buyer = m.group(1).strip() if m else "buyer"
                text = re.sub(r"\s+", " ", body).strip()[:1200]
                out.append({"platform": "etsy", "from": buyer, "text": text, "subject": subj})
                M.store(num, "+FLAGS", "\\Seen")
            elif any(d in frm for d in ETSY_SENDERS) and "order" in subj.lower():
                ctx["_ledger"].emit("etsy", "status", f"Etsy: {subj[:120]}", agent="HERALD"); M.store(num, "+FLAGS", "\\Seen")
            elif any(d in frm for d in PRINTIFY_SENDERS):
                ctx["_ledger"].emit("treasury", "status", f"Printify: {subj[:120]}", agent="VAULT"); M.store(num, "+FLAGS", "\\Seen")
        M.logout()
        if L is not None: L.kv_set("mail_orders_seen", ",".join(sorted(seen)[-500:]))
    except Exception as e:
        return {"messages": [], "cost": 0.0, "incident": f"Mailbox error · {type(e).__name__}: {str(e)[:100]}"}
    parts = [f"{len(out)} buyer message(s)" if out else "", f"{len(clip_orders)} clip order(s)" if clip_orders else "", f"{len(orders)} thumbnail order(s)" if orders else ""]
    return {"messages": out, "clip_orders": clip_orders, "orders": orders, "cost": 0.0, "summary": " · ".join(p for p in parts if p) or "inbox clear"}
