"""MOTHER — the overseer. The crew reports to her; she reports to the Creator.

She watches every event. When an incident lands she triages it and acts on her own authority:
retry a run, hold or lift a bay, send Research for a fresh brief, wake a standby bay. When a bay asks
for approval she decides it herself inside the limits the Creator set (AUTONOMY=full, DAILY_SPEND_CAP),
and escalates anything outside them. Every sweep she checks for stalled bays and mission drift.
Nothing she does is hidden: every decision is an event with her name on it."""
import asyncio, logging, random
from datetime import datetime, timezone
from . import config, agents, mission

log = logging.getLogger("constantinople.mother")

ACTIONS = ("retry", "hold", "lift", "rebrief", "wake", "watch", "escalate")


class Mother:
    def __init__(self, ledger, orch):
        self.L = ledger; self.orch = orch
        self.retries: dict[str, int] = {}
        self.name = config.MOTHER_NAME
        ledger.subscribe(self._on_event)
        self._loop = None

    def say(self, msg: str, **data):
        return self.L.emit("core", "mother", msg, agent=self.name, **data)

    # ── wiring ─────────────────────────────────────────────────────────
    async def start(self):
        self._loop = asyncio.get_running_loop()
        self.say(f"{self.name} online · autonomy {config.AUTONOMY.upper()} · daily spend cap ${config.DAILY_SPEND_CAP:.2f} · reporting to {config.CREATOR}")
        asyncio.create_task(self._sweep())

    def _on_event(self, ev: dict):
        if ev.get("kind") == "incident" and self._loop:
            self._loop.call_soon_threadsafe(lambda: asyncio.create_task(self.triage(ev)))

    # ── incident triage ────────────────────────────────────────────────
    async def triage(self, ev: dict):
        bay = ev["bay"]
        result, cost, _ = await agents.run_agent(self.name, "mother_triage.md", {"incident": ev, "_ledger": self.L, "run_id": f"mother-{ev.get('id','')}", "retries": self.retries.get(bay, 0)}, dry_run=config.DRY_RUN)
        action = result.get("action", "watch"); reason = result.get("reason", "")
        if action not in ACTIONS: action = "watch"
        await self.act(bay, action, reason, ev)
        if cost: self.L.emit("core", "cost", "Triage reasoning", agent=self.name, amount=cost)

    async def act(self, bay: str, action: str, reason: str, ev: dict | None = None):
        if action == "retry":
            n = self.retries.get(bay, 0) + 1; self.retries[bay] = n
            if n > config.MAX_RETRIES:
                return await self.act(bay, "escalate", f"{n-1} retries failed · {reason}", ev)
            delay = min(300, 20 * 2 ** (n - 1)) / config.SPEED
            self.say(f"Triage {bay}: retry {n}/{config.MAX_RETRIES} in {int(delay)}s · {reason}", action=action, bay_ref=bay)
            await asyncio.sleep(delay)
            if bay in self.orch.bays and self.L.bay(bay).get("status") in ("running", "boost"):
                await self.orch.runner.enqueue(bay, {})
        elif action == "hold":
            self.orch.set_status(bay, "hold") if self.L.bay(bay).get("status") != "hold" else None
            self.say(f"Triage {bay}: HOLD · {reason}. Lifting after review.", action=action, bay_ref=bay)
            asyncio.create_task(self._lift_later(bay, 900 / config.SPEED))
        elif action == "lift":
            if self.L.bay(bay).get("status") == "hold": self.orch.set_status(bay, "hold")
            self.retries[bay] = 0
            self.say(f"{bay}: hold lifted · {reason}", action=action, bay_ref=bay)
        elif action == "rebrief":
            self.say(f"Triage {bay}: discarded · sending Research for a fresh brief · {reason}", action=action, bay_ref=bay)
            if "research" in self.orch.bays: await self.orch.runner.enqueue("research", {})
        elif action == "wake":
            self.orch.set_status(bay, "wake"); self.say(f"Waking {bay} · {reason}", action=action, bay_ref=bay)
        elif action == "escalate":
            aid = self.L.request_approval(bay, "mother", "escalation", f"{self.name} needs {config.CREATOR}: {reason}", {"incident": ev or {}})
            self.say(f"ESCALATED to {config.CREATOR} · #{aid} · {bay}: {reason}", action=action, bay_ref=bay, approval=aid)
            self.retries[bay] = 0
        else:
            self.say(f"Watching {bay} · {reason}", action="watch", bay_ref=bay)

    async def _lift_later(self, bay, delay):
        await asyncio.sleep(delay)
        if self.L.bay(bay).get("status") == "hold":
            await self.act(bay, "lift", "review window passed, no repeat incident")

    # ── approvals ──────────────────────────────────────────────────────
    def spent_today(self) -> float:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        r = self.L.db.execute("SELECT COALESCE(SUM(amount),0) s FROM events WHERE (kind='cost' OR kind='step') AND amount>0 AND ts LIKE ?", (day + "%",)).fetchone()
        return float(r["s"] or 0)

    async def consider(self, aid: int, bay: str, gate: str, summary: str, est_cost: float = 0.0) -> bool:
        """Decide a gate on the Creator's behalf. Returns True if she decided it (either way)."""
        if config.AUTONOMY != "full":
            self.say(f"Approval #{aid} waits for {config.CREATOR} (autonomy ASSIST) · {summary}", approval=aid)
            return False
        if gate == "approve_spend":
            spent = self.spent_today()
            if spent + est_cost <= config.DAILY_SPEND_CAP:
                self.L.decide(aid, "approved", self.name); self.say(f"Approved #{aid} · spend ${spent + est_cost:.2f} of ${config.DAILY_SPEND_CAP:.2f} today · {summary}", approval=aid, decision="approved"); return True
            self.say(f"Declined #{aid} · daily cap reached (${spent:.2f}) · escalating to {config.CREATOR}", approval=aid, decision="held"); return False
        if gate == "approve_publish":
            self.L.decide(aid, "approved", self.name); self.say(f"Approved #{aid} · doctrine checks passed · {summary}", approval=aid, decision="approved"); return True
        return False

    # ── sweeps ─────────────────────────────────────────────────────────
    async def _sweep(self):
        k = 0
        while True:
            await asyncio.sleep(max(20, 300 / config.SPEED)); k += 1
            try:
                now = datetime.now(timezone.utc)
                for b in self.orch.bays.values():
                    st = self.L.bay(b.id)
                    if st.get("status") not in ("running", "boost") or b.trigger == "event" or not st.get("last_run"): continue
                    last = self.L.db.execute("SELECT MAX(ts) t FROM events WHERE bay=? AND kind IN ('complete','step','poll')", (b.id,)).fetchone()["t"]
                    if last:
                        age = (now - datetime.fromisoformat(last.replace("Z", "+00:00"))).total_seconds()
                        if age > 3 * b.cadence / config.SPEED + 60:
                            self.L.emit(b.id, "incident", f"Stalled · no completed run in {int(age)}s (cadence {int(b.cadence/config.SPEED)}s)", agent=self.name)
                m = mission.state(self.L)
                if k % 6 == 0: self.say(f"Watch · all bays checked · ${m['banked']:,.2f} banked · {m['velocity_per_day']:,.2f}/sol · leg {m['leg']:02d} to {m['next_waypoint']['name']}", velocity_per_day=m["velocity_per_day"])
            except Exception:
                log.exception("sweep failed")
