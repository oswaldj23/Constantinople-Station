"""A bay is a YAML workflow. The runner walks its steps in order, writing a `step` event (with cost)
after each, pausing at approval gates, and finishing with a `complete` event. Step results accumulate in
`ctx` under the step id so later steps can reference them ("design_draft.files")."""
import asyncio, uuid, yaml
from pathlib import Path
from typing import Any, Optional

from . import config, agents
from .tools import resolve
from .ledger import Ledger


class Bay:
    def __init__(self, spec: dict):
        self.spec = spec
        self.id = spec["id"]; self.name = spec["name"]
        self.agents = spec.get("agents", [])
        self.steps = spec.get("steps", [])
        self.cadence = float(spec.get("cadence_seconds", 1800))
        self.trigger = spec.get("trigger", "cadence")     # cadence | event
        self.standby = bool(spec.get("standby", False))
        self.display = spec.get("display_as", self.id)   # which bay the dashboard shows this under

    @staticmethod
    def load_all(d: Path = config.BAYS_DIR) -> dict:
        out = {}
        for p in sorted(d.glob("*.yaml")):
            spec = yaml.safe_load(p.read_text())
            out[spec["id"]] = Bay(spec)
        return out


class Hold(Exception): pass
class Incident(Exception): pass
class Rejected(Exception): pass


class Runner:
    def __init__(self, ledger: Ledger, bays: dict):
        self.ledger = ledger; self.bays = bays
        self.mother = None
        self.shared: dict[str, Any] = {}     # cross-bay handoffs, e.g. shared["research"] = latest brief
        self.waits: dict[int, asyncio.Event] = {}

    async def run(self, bay: Bay, seed: Optional[dict] = None) -> dict:
        L = self.ledger
        run_id = f"{bay.id}-{uuid.uuid4().hex[:8]}"
        ctx: dict[str, Any] = {"run_id": run_id, "bay": bay.id, "_ledger": L, **self.shared}
        if seed: ctx.update(seed)
        L.bump(bay.id, runs=1)
        for i, st in enumerate(bay.steps):
            state = L.bay(bay.id)
            if state.get("status") == "hold":
                L.emit(bay.id, "status", f"Run paused at step {i+1:02d} · bay on HOLD", step=i + 1, run_id=run_id, status="hold")
                raise Hold()
            L.set_step(bay.id, i)
            agent = st.get("agent") or (bay.agents[0] if bay.agents else "CONSTANTINOPLE")
            # approval gate before anything that spends or publishes
            if st.get("gate") and not config.AUTO_APPROVE:
                await self._gate(bay, st, ctx, i, run_id)
            result, cost = await self._exec(st, ctx)
            if result.get("incident"):
                L.emit(bay.id, "incident", result["incident"], step=i + 1, agent=agent, run_id=run_id)
                raise Incident(result["incident"])
            ctx[st["id"]] = result
            if st.get("share"):
                self.shared[st["share"]] = result
            L.emit(bay.id, "poll" if st.get("quiet") else "step", f"{st['name']}: {result.get('summary','done')}", step=i + 1, agent=agent, amount=cost or None, run_id=run_id)
            if st.get("emit"):            # extra event kinds a step can raise (trend, publish, message…)
                L.emit(bay.id, st["emit"], result.get("summary", st["name"]), agent=agent, run_id=run_id, **({"to": st["to"]} if st.get("to") else {}))
            if st.get("transfer_to"):
                L.emit(bay.id, "transfer", f"{agent} carries {st['name'].lower()} to {st['transfer_to']}", agent=agent, run_id=run_id, to=st["transfer_to"])
            # hand sub-events to other bays (orders, messages, sales)
            for key, target in (st.get("fanout") or {}).items():
                for item in result.get(key) or []:
                    await self.enqueue(target, {target_key(target): item})
            if config.SPEED < 50:
                await asyncio.sleep(max(0.2, float(st.get("pause", 1.5)) / config.SPEED))
        L.set_step(bay.id, 0, last_run=run_id)
        title = _title(ctx)
        if bay.spec.get("artifact"):
            L.save_artifact(bay.id, bay.spec["artifact"], title, {k: v for k, v in ctx.items() if not k.startswith("_") and k not in self.shared}, run_id)
        if bay.spec.get("quiet") or bay.spec.get("no_complete"):
            return ctx
        L.emit(bay.id, "complete", bay.spec.get("complete_msg", "Run complete").replace("{title}", title), agent=bay.agents[-1] if bay.agents else "CONSTANTINOPLE",
               run_id=run_id, output={"title": title, "conf": ctx.get("score", {}).get("scores", [90])[0] if isinstance(ctx.get("score"), dict) else 90})
        return ctx

    async def _exec(self, st: dict, ctx: dict) -> tuple[dict, float]:
        kind = st.get("kind", "agent")
        dry = config.DRY_RUN
        if kind == "agent":
            result, cost, _ = await agents.run_agent(st.get("agent", "CONSTANTINOPLE"), st["prompt"], ctx, dry_run=dry)
            return result, cost
        if kind == "tool":
            fn = resolve(st["tool"])
            result = await fn(ctx, dry_run=dry, **(st.get("args") or {}))
            return result, float(result.pop("cost", 0) or 0)
        if kind == "noop":
            return {"summary": st.get("summary", st["name"])}, 0.0
        raise ValueError(f"unknown step kind {kind}")

    async def _gate(self, bay: Bay, st: dict, ctx: dict, i: int, run_id: str):
        summary = st.get("gate_summary", f"{bay.name} wants to {st['name'].lower()}").replace("{title}", _title(ctx))
        payload = {k: v for k, v in ctx.items() if not k.startswith("_") and isinstance(v, (dict, list, str, int, float))}
        aid = self.ledger.request_approval(bay.id, st["id"], st["gate"], summary, payload)
        self.ledger.emit(bay.id, "status", f"Awaiting approval #{aid}: {summary}", step=i + 1, agent=config.CALLSIGN, run_id=run_id, approval=aid)
        if self.mother is not None:
            await self.mother.consider(aid, bay.id, st["gate"], summary, float(st.get("est_cost", 0.2)))
        ev = asyncio.Event(); self.waits[aid] = ev
        while True:
            a = self.ledger.approval(aid)
            if a["status"] == "approved":
                self.ledger.emit(bay.id, "status", f"Approval #{aid} granted", step=i + 1, agent=config.CALLSIGN, run_id=run_id); return
            if a["status"] == "rejected":
                self.ledger.emit(bay.id, "incident", f"Approval #{aid} rejected · run abandoned", step=i + 1, agent=config.CALLSIGN, run_id=run_id); raise Rejected()
            try:
                await asyncio.wait_for(ev.wait(), timeout=5); ev.clear()
            except asyncio.TimeoutError:
                pass

    def decide(self, aid: int, status: str):
        self.ledger.decide(aid, status)
        if aid in self.waits: self.waits[aid].set()

    # event-triggered runs (orders, messages, sales) go through a queue the orchestrator drains
    def __post_init__(self): pass
    async def enqueue(self, bay_id: str, seed: dict):
        q = self.queues.setdefault(bay_id, asyncio.Queue()); await q.put(seed)
    queues: dict[str, asyncio.Queue] = {}


def target_key(bay_id: str) -> str:
    return {"studio": "order", "comms": "message", "treasury": "sale"}.get(bay_id, "input")


def _title(ctx: dict) -> str:
    if isinstance(ctx.get("message"), dict) and ctx["message"].get("text"):
        return '"' + ctx["message"]["text"][:70] + '"'
    if isinstance(ctx.get("order"), dict):
        o = ctx["order"]; return f"{o.get('niche','')} thumbnails ×{o.get('qty',1)}".strip()
    dr = ctx.get("demand_rank")
    if isinstance(dr, dict) and isinstance(dr.get("brief"), dict) and dr["brief"].get("concept"):
        return dr["brief"]["concept"]
    for k in ("listing_draft", "trend_scan", "draft_reply", "caption"):
        v = ctx.get(k)
        if isinstance(v, dict):
            for f in ("title", "concept", "summary"):
                if v.get(f): return str(v[f])
    return ctx.get("order", {}).get("niche", "") + " thumbnails" if ctx.get("order") else "run"
