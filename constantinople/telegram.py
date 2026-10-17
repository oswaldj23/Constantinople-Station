"""Telegram bridge: the Creator's phone is the bridge console.

Mother sends approval requests with Approve / Reject buttons, escalations, incidents she could not fix,
waypoint crossings, and a daily report. The Creator can type commands:
  /status · /approvals · /approve N · /reject N · /hold BAY · /boost BAY · /report · /mother · /help

Setup: make a bot with @BotFather, put its token in TELEGRAM_BOT_TOKEN, restart, then send /start to the bot.
The first chat to send /start is bound as the Creator's chat; nobody else is answered."""
import asyncio, logging, json
from datetime import datetime, timezone
import httpx
from . import config, mission

log = logging.getLogger("constantinople.telegram")


class Telegram:
    def __init__(self, ledger, orch):
        self.L = ledger; self.orch = orch
        self.token = config.TELEGRAM_BOT_TOKEN
        self.api = f"https://api.telegram.org/bot{self.token}"
        self.chat = ledger.kv_get("telegram_chat") or config.TELEGRAM_CHAT_ID or None
        self.enabled = bool(self.token)
        self._offset = 0
        self._last_report_day = None
        self._loop = None

    # ── outbound ────────────────────────────────────────────────────────
    async def send(self, text: str, buttons: list | None = None, chat=None):
        chat = chat or self.chat
        if not self.enabled or not chat: return
        body = {"chat_id": chat, "text": text[:4000], "parse_mode": "HTML", "disable_web_page_preview": True}
        if buttons: body["reply_markup"] = {"inline_keyboard": buttons}
        try:
            async with httpx.AsyncClient(timeout=20) as c:
                await c.post(f"{self.api}/sendMessage", json=body)
        except Exception as e:
            log.warning("telegram send failed: %s", e)

    async def send_photo(self, url: str, caption: str = ""):
        if not self.enabled or not self.chat or not url: return
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                await c.post(f"{self.api}/sendPhoto", json={"chat_id": self.chat, "photo": url, "caption": caption[:1000]})
        except Exception as e:
            log.warning("telegram photo failed: %s", e)

    def on_event(self, ev: dict):
        """Called from the ledger thread; schedule outbound messages for noteworthy events."""
        if not self.enabled or not self.chat or not self._loop: return
        k = ev.get("kind"); msg = ev.get("msg", "")
        text = None; buttons = None
        if k == "status" and ev.get("approval") and msg.startswith("Awaiting approval"):
            aid = ev["approval"]
            text = f"🛎 <b>Approval #{aid}</b>\n{msg.split(':',1)[1].strip()}"
            buttons = [[{"text": "✅ Approve", "callback_data": f"approve:{aid}"}, {"text": "❌ Reject", "callback_data": f"reject:{aid}"}]]
        elif k == "mother" and ("ESCALATED" in msg or "Declined" in msg):
            text = f"🚨 <b>MOTHER</b>\n{msg}"
        elif k == "mission" and "WAYPOINT REACHED" in msg:
            text = f"🌟 <b>{msg}</b>"
        elif k == "sale":
            text = f"💰 {msg}"
        elif k == "complete" and ev.get("bay") == "etsy":
            text = f"🛍 <b>Listing live</b> · {msg}"
        elif k == "incident" and ev.get("bay") != "core":
            text = f"⚠️ <b>{ev.get('bay','').upper()}</b> · {msg}"
        elif k == "reply" and ev.get("draft"):
            text = f"✉️ <b>HERALD drafted a reply</b> — copy it into Etsy:\n\n<code>{ev['draft'][:1500]}</code>"
        if text:
            self._loop.call_soon_threadsafe(lambda: asyncio.create_task(self.send(text, buttons)))

    # ── inbound ─────────────────────────────────────────────────────────
    async def start(self):
        self._loop = asyncio.get_running_loop()
        if not self.enabled:
            log.info("telegram disabled (no TELEGRAM_BOT_TOKEN)"); return
        self.L.subscribe(self.on_event)
        asyncio.create_task(self._poll())
        asyncio.create_task(self._daily())
        if self.chat: await self.send(f"🛰 <b>{config.STATION_NAME}</b> engine online · {config.MOTHER_NAME} reporting to {config.CREATOR}.\nType /help for commands.")

    async def _poll(self):
        while True:
            try:
                async with httpx.AsyncClient(timeout=40) as c:
                    r = await c.get(f"{self.api}/getUpdates", params={"timeout": 30, "offset": self._offset})
                    for u in r.json().get("result", []):
                        self._offset = u["update_id"] + 1
                        await self._handle(u)
            except Exception as e:
                log.warning("telegram poll: %s", e); await asyncio.sleep(5)

    async def _handle(self, u: dict):
        if "callback_query" in u:
            cq = u["callback_query"]; chat = str(cq["message"]["chat"]["id"])
            if chat != str(self.chat): return
            action, aid = cq["data"].split(":"); aid = int(aid)
            self.orch.runner.decide(aid, "approved" if action == "approve" else "rejected")
            async with httpx.AsyncClient(timeout=20) as c:
                await c.post(f"{self.api}/answerCallbackQuery", json={"callback_query_id": cq["id"], "text": f"#{aid} {action}d"})
                await c.post(f"{self.api}/editMessageReplyMarkup", json={"chat_id": chat, "message_id": cq["message"]["message_id"], "reply_markup": {"inline_keyboard": []}})
            await self.send(f"{'✅' if action=='approve' else '❌'} #{aid} {action}d by {config.CREATOR}")
            return
        m = u.get("message") or {}
        text = (m.get("text") or "").strip(); chat = str((m.get("chat") or {}).get("id", ""))
        if not text: return
        if text.startswith("/start"):
            if not self.chat:
                self.chat = chat; self.L.kv_set("telegram_chat", chat)
                await self.send(f"Bound. This chat is now the bridge console for <b>{config.STATION_NAME}</b>. You are {config.CREATOR}; I am {config.MOTHER_NAME}.\n/help for commands.", chat=chat)
            elif chat == str(self.chat):
                await self.send("Already bound to this chat. /help for commands.")
            return
        if chat != str(self.chat): return   # ignore strangers
        await self.command(text)

    async def command(self, text: str):
        parts = text.split(); cmd = parts[0].lower().lstrip("/"); arg = parts[1] if len(parts) > 1 else None
        if cmd in ("help", "h"):
            await self.send("<b>Bridge commands</b>\n/status · /approvals · /approve N · /reject N\n/hold BAY · /boost BAY · /run BAY\n/report · /mother · /listings")
        elif cmd == "status":
            await self.send(self.status_text())
        elif cmd == "approvals":
            rows = self.L.approvals("pending")
            if not rows: await self.send("Nothing waiting on you."); return
            for a in rows:
                await self.send(f"🛎 <b>#{a['id']}</b> · {a['bay']} · {a['gate']}\n{a['summary']}",
                                [[{"text": "✅ Approve", "callback_data": f"approve:{a['id']}"}, {"text": "❌ Reject", "callback_data": f"reject:{a['id']}"}]])
        elif cmd in ("approve", "reject") and arg and arg.isdigit():
            if not self.L.approval(int(arg)): await self.send(f"No approval #{arg}."); return
            self.orch.runner.decide(int(arg), "approved" if cmd == "approve" else "rejected"); await self.send(f"#{arg} {cmd}d.")
        elif cmd in ("hold", "boost", "wake", "run") and arg:
            bay = arg.lower()
            if bay not in self.orch.bays: await self.send(f"Unknown bay. Bays: {', '.join(self.orch.bays)}"); return
            if cmd == "run": asyncio.create_task(self.orch.run_once(bay)); await self.send(f"Running {bay} now.")
            else: await self.send(f"{bay} → {self.orch.set_status(bay, cmd)}")
        elif cmd == "report":
            await self.send(self.report_text())
        elif cmd == "mother":
            rows = self.L.recent(8, kind="mother")
            await self.send("<b>MOTHER · recent decisions</b>\n" + "\n".join(f"• {r['msg'][:140]}" for r in rows) if rows else "No decisions yet.")
        elif cmd == "listings":
            from . import memory
            rows = memory.listing_performance(self.L)[:10]
            await self.send("<b>Listings</b>\n" + "\n".join(f"• {r['title'][:40]} · {r['sales']} sold · ${r['revenue']:.2f} · {r['age_days']}d{' · ' + r['flag'] if r.get('flag') else ''}" for r in rows) if rows else "No listings yet.")
        else:
            await self.send("Unknown command. /help")

    # ── reports ─────────────────────────────────────────────────────────
    def status_text(self) -> str:
        m = mission.state(self.L); t = self.L.totals(); pend = len(self.L.approvals("pending"))
        held = [b for b, s in self.L.bays().items() if s.get("status") == "hold"]
        return (f"<b>{config.STATION_NAME}</b>\n💵 Banked ${t['rev']:,.2f} · spend ${t['cost']:,.2f}\n"
                f"🧭 Leg {m['leg']:02d}/{m['legs']} · {m['leg_pct']}% to {m['next_waypoint']['name']} · {m['velocity_per_day']:,.2f}/sol\n"
                f"🛎 {pend} waiting on you · ⏸ held: {', '.join(held) or 'none'} · {'DRY RUN' if config.DRY_RUN else 'LIVE'} · autonomy {config.AUTONOMY}")

    def report_text(self) -> str:
        from . import memory
        d = memory.digest(self.L, days=1)
        m = mission.state(self.L)
        lines = [f"☀️ <b>Morning report · {config.STATION_NAME}</b>",
                 f"Last 24h: {d['sales_count']} sale(s) · ${d['revenue']:,.2f} · spend ${d['cost']:,.2f}",
                 f"Listings made: {d['listings']} · incidents: {d['incidents']} · Mother decisions: {d['mother_actions']}",
                 f"Mission: leg {m['leg']:02d} · {m['leg_pct']}% to {m['next_waypoint']['name']} · ETA {m['eta_next_days']} sols" if m.get('eta_next_days') else f"Mission: leg {m['leg']:02d} · {m['leg_pct']}% to {m['next_waypoint']['name']}",
                 f"Directive: {m.get('directive') or '—'}"]
        if d["top"]: lines.append("Top: " + "; ".join(f"{t} ({n})" for t, n in d["top"][:3]))
        if d["notes"]: lines.append(f"Mother's note: {d['notes'][-1]}")
        pend = len(self.L.approvals("pending"))
        if pend: lines.append(f"🛎 {pend} approval(s) waiting — /approvals")
        return "\n".join(lines)

    async def _daily(self):
        while True:
            await asyncio.sleep(60)
            now = datetime.now(timezone.utc); hour_local = (now.hour + config.REPORT_UTC_OFFSET) % 24
            day = now.strftime("%Y-%m-%d")
            if hour_local == config.REPORT_HOUR and self._last_report_day != day and self.chat:
                self._last_report_day = day
                await self.send(self.report_text())
