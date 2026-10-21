"""The orchestrator keeps every bay on schedule: cadence bays run every N seconds (scaled by SPEED),
event bays run whenever something lands in their queue (an order, a message, a sale), and the Core
heartbeats so the dashboard knows the engine is alive."""
import asyncio, logging, random
from . import config
from .ledger import Ledger
from .workflow import Bay, Runner, Hold, Rejected, Incident
from .mother import Mother
from .telegram import Telegram
from . import mission

log = logging.getLogger("constantinople")


class Orchestrator:
    def __init__(self, ledger: Ledger):
        self.ledger = ledger
        self.bays = Bay.load_all()
        self.runner = Runner(ledger, self.bays)
        for b in self.bays.values():
            ledger.ensure_bay(b.id, "standby" if b.standby else "running")
        self.tasks: list[asyncio.Task] = []
        self.mother = Mother(ledger, self)
        self.runner.mother = self.mother
        self.telegram = Telegram(ledger, self)

    async def start(self):
        self.ledger.emit("core", "status", f"{config.STATION_NAME} engine online · {len(self.bays)} bays loaded · {'DRY RUN' if config.DRY_RUN else 'LIVE'}", agent=config.CALLSIGN)
        st = mission.state(self.ledger)
        self.ledger.emit("core", "mission", f"Prime mission active · leg {st['leg']:02d} of {st['legs']} · ${st['banked']:,.2f} banked · next waypoint {st['next_waypoint']['name']} ({mission.short(st['next_waypoint']['amount'])})", agent=config.MOTHER_NAME)
        await self.mother.start()
        await self.telegram.start()
        asyncio.create_task(self._resume_gated_runs())
        for b in self.bays.values():
            self.tasks.append(asyncio.create_task(self._loop(b), name=b.id))
        self.tasks.append(asyncio.create_task(self._heartbeat()))

    async def _resume_gated_runs(self):
        """Approvals used to live only inside the running process; a restart orphaned them. Now any run that was
        waiting at a gate (pending, or approved but never finished) is resumed from that step."""
        import json
        await asyncio.sleep(3)
        rows = self.ledger.approvals("pending", 50) + self.ledger.approvals("approved", 50)
        for a in rows:
            if a["gate"] == "escalation" or a["bay"] not in self.bays: continue
            try: payload = json.loads(a.get("payload") or "{}")
            except Exception: continue
            run_id = payload.get("run_id")
            if not run_id: continue
            done = self.ledger.db.execute("SELECT 1 FROM events WHERE run_id=? AND kind IN ('complete','incident') LIMIT 1", (run_id,)).fetchone()
            granted = self.ledger.db.execute("SELECT 1 FROM events WHERE run_id=? AND kind='status' AND msg LIKE 'Approval #% granted' AND msg LIKE ?", (run_id, f"Approval #{a['id']} granted")).fetchone()
            if done or granted: continue
            bay = self.bays[a["bay"]]
            if not any(st["id"] == a["step"] for st in bay.steps): continue
            log.info("resuming %s run %s at %s (approval #%s %s)", bay.id, run_id, a["step"], a["id"], a["status"])
            asyncio.create_task(self._guarded(bay, None, {"approval_id": a["id"], "step_id": a["step"], "ctx": payload}))
            await asyncio.sleep(0.5)

    async def stop(self):
        for t in self.tasks: t.cancel()

    async def run_once(self, bay_id: str, seed: dict | None = None):
        return await self._guarded(self.bays[bay_id], seed)

    async def _guarded(self, bay: Bay, seed=None, resume=None):
        try:
            return await self.runner.run(bay, seed, resume)
        except Hold:
            log.info("%s held", bay.id)
        except Rejected:
            log.info("%s rejected at gate", bay.id)
        except Incident as e:
            log.info("%s incident: %s", bay.id, e)
        except Exception as e:  # noqa
            log.exception("bay %s failed", bay.id)
            self.ledger.emit(bay.id, "incident", f"{type(e).__name__}: {str(e)[:140]}", agent="CONSTANTINOPLE")

    def _since_last_complete(self, bay_id: str) -> float | None:
        from datetime import datetime, timezone
        r = self.ledger.db.execute("SELECT MAX(ts) t FROM events WHERE bay=? AND kind IN ('complete','step')", (bay_id,)).fetchone()
        if not r or not r["t"]: return None
        return (datetime.now(timezone.utc) - datetime.fromisoformat(r["t"].replace("Z", "+00:00"))).total_seconds()

    async def _loop(self, bay: Bay):
        q = self.runner.queues.setdefault(bay.id, asyncio.Queue())
        await asyncio.sleep(random.uniform(1, 6) / config.SPEED)
        # resume the schedule: if this bay ran recently, wait out the rest of its cadence instead of firing on every restart
        if bay.trigger != "event":
            age = self._since_last_complete(bay.id)
            if age is not None and age < bay.cadence / config.SPEED:
                await asyncio.sleep(bay.cadence / config.SPEED - age)
        while True:
            state = self.ledger.bay(bay.id)
            if state.get("status") == "standby":
                await asyncio.sleep(10); continue
            if bay.trigger == "event":
                seed = await q.get()
                if self.ledger.bay(bay.id).get("status") == "hold":
                    await q.put(seed); await asyncio.sleep(5); continue
                await self._guarded(bay, seed)
                continue
            # cadence: a queued seed (e.g. a story's part two) runs half a cycle after the last run, then the normal rhythm resumes
            if not q.empty():
                await asyncio.sleep(bay.cadence / config.SPEED / 2)
                if self.ledger.bay(bay.id).get("status") == "hold": continue
                await self._guarded(bay, await q.get())
                await asyncio.sleep(bay.cadence / config.SPEED / 2); continue
            if state.get("status") == "hold":
                await asyncio.sleep(5); continue
            await self._guarded(bay)
            boost = state.get("status") == "boost"
            try:
                import json as _j; mult = float((_j.loads(self.ledger.kv_get("allocation") or "{}")).get(bay.id, 1.0) or 1.0)
            except Exception: mult = 1.0
            await asyncio.sleep(bay.cadence / config.SPEED / (1.8 if boost else 1.0) / max(0.25, min(2.0, mult)))

    async def _heartbeat(self):
        mission.check_waypoint(self.ledger, config.MOTHER_NAME)
        n = 0
        while True:
            await asyncio.sleep(30)
            n += 1
            mission.check_waypoint(self.ledger, config.MOTHER_NAME)
            self.ledger.emit("core", "poll", "Heartbeat · all bays reporting", step=4, agent=config.CALLSIGN, quiet=True)
            if n % 120 == 0:  # hourly housekeeping: clear render intermediates, watch the disk
                try:
                    from . import housekeeping; housekeeping.tidy(self.ledger)
                    from datetime import datetime as _dt
                    if _dt.utcnow().hour == 7 and self.ledger.kv_get("backup_day") != _dt.utcnow().strftime("%Y-%m-%d"):   # ~03:00 New York
                        r = housekeeping.backup(self.ledger); self.ledger.kv_set("backup_day", _dt.utcnow().strftime("%Y-%m-%d"))
                        self.ledger.emit("core", "poll", f"Nightly backup {'ok' if r.get('ok') else 'FAILED'} · {r.get('size_mb', 0)} MB", agent=config.MOTHER_NAME, quiet=True)
                except Exception: log.exception("housekeeping")
            if n % 20 == 0:   # every ten minutes: a mission log line the whole crew sees
                st = mission.state(self.ledger)
                self.ledger.emit("core", "mission", f"Mission log · ${st['banked']:,.2f} banked · {st['leg_pct']}% of leg {st['leg']:02d} to {st['next_waypoint']['name']} · {st['doublings_left']} doublings to Trillion Dawn",
                                 agent=config.MOTHER_NAME, velocity_per_day=st["velocity_per_day"])

    # bridge controls
    def set_status(self, bay_id: str, action: str) -> str:
        cur = self.ledger.bay(bay_id).get("status", "running")
        new = {"hold": "running" if cur == "hold" else "hold", "boost": "running" if cur == "boost" else "boost", "wake": "running", "standby": "standby"}[action]
        self.ledger.set_status(bay_id, new)
        self.ledger.emit(bay_id, "status", {"hold": "HOLD issued · spend and publishing paused", "running": "Normal cadence resumed", "boost": "BOOST approved · 1.8× cadence", "standby": "Bay to standby"}[new], agent="VAULT" if new == "boost" else config.MOTHER_NAME, status=new)
        return new
