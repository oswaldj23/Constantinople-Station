"""The orchestrator keeps every bay on schedule: cadence bays run every N seconds (scaled by SPEED),
event bays run whenever something lands in their queue (an order, a message, a sale), and the Core
heartbeats so the dashboard knows the engine is alive."""
import asyncio, logging, random
from . import config
from .ledger import Ledger
from .workflow import Bay, Runner, Hold, Rejected, Incident
from .mother import Mother
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

    async def start(self):
        self.ledger.emit("core", "status", f"{config.STATION_NAME} engine online · {len(self.bays)} bays loaded · {'DRY RUN' if config.DRY_RUN else 'LIVE'}", agent=config.CALLSIGN)
        st = mission.state(self.ledger)
        self.ledger.emit("core", "mission", f"Prime mission active · leg {st['leg']:02d} of {st['legs']} · ${st['banked']:,.2f} banked · next waypoint {st['next_waypoint']['name']} ({mission.short(st['next_waypoint']['amount'])})", agent=config.MOTHER_NAME)
        await self.mother.start()
        for b in self.bays.values():
            self.tasks.append(asyncio.create_task(self._loop(b), name=b.id))
        self.tasks.append(asyncio.create_task(self._heartbeat()))

    async def stop(self):
        for t in self.tasks: t.cancel()

    async def run_once(self, bay_id: str, seed: dict | None = None):
        return await self._guarded(self.bays[bay_id], seed)

    async def _guarded(self, bay: Bay, seed=None):
        try:
            return await self.runner.run(bay, seed)
        except Hold:
            log.info("%s held", bay.id)
        except Rejected:
            log.info("%s rejected at gate", bay.id)
        except Incident as e:
            log.info("%s incident: %s", bay.id, e)
        except Exception as e:  # noqa
            log.exception("bay %s failed", bay.id)
            self.ledger.emit(bay.id, "incident", f"{type(e).__name__}: {str(e)[:140]}", agent="CONSTANTINOPLE")

    async def _loop(self, bay: Bay):
        q = self.runner.queues.setdefault(bay.id, asyncio.Queue())
        await asyncio.sleep(random.uniform(1, 6) / config.SPEED)
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
            # cadence: also drain any queued seeds first
            if not q.empty():
                await self._guarded(bay, await q.get()); continue
            if state.get("status") == "hold":
                await asyncio.sleep(5); continue
            await self._guarded(bay)
            boost = state.get("status") == "boost"
            await asyncio.sleep(bay.cadence / config.SPEED / (1.8 if boost else 1.0))

    async def _heartbeat(self):
        mission.check_waypoint(self.ledger, config.MOTHER_NAME)
        n = 0
        while True:
            await asyncio.sleep(30)
            n += 1
            mission.check_waypoint(self.ledger, config.MOTHER_NAME)
            self.ledger.emit("core", "poll", "Heartbeat · all bays reporting", step=4, agent=config.CALLSIGN, quiet=True)
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
