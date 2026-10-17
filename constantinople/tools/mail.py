"""Real Comms inbox. Etsy sends every buyer message and order as an email; Printify sends order and
production emails. HERALD reads them here. Replies to Etsy buyers cannot be sent by email, so HERALD
drafts the reply and hands it to the Creator on Telegram to paste into Etsy (one tap to copy)."""
import email, imaplib, re
from email.header import decode_header
from .. import config

ETSY_SENDERS = ("etsy.com",)
PRINTIFY_SENDERS = ("printify.com",)


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
    out = []
    try:
        M = imaplib.IMAP4_SSL(config.MAIL_IMAP_HOST); M.login(config.MAIL_USER, config.MAIL_PASSWORD); M.select("INBOX")
        typ, data = M.search(None, "(UNSEEN)")
        for num in (data[0].split() if data and data[0] else [])[-20:]:
            typ, raw = M.fetch(num, "(RFC822)")
            msg = email.message_from_bytes(raw[0][1]); frm = (msg.get("From") or "").lower(); subj = _subject(msg); body = _text(msg)
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
    except Exception as e:
        return {"messages": [], "cost": 0.0, "incident": f"Mailbox error · {type(e).__name__}: {str(e)[:100]}"}
    return {"messages": out, "cost": 0.0, "summary": f"{len(out)} buyer message(s)" if out else "inbox clear"}
