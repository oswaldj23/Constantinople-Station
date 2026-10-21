"""HTTP surface: the dashboard connects to /events (Server-Sent Events) and posts bridge commands.
Webhooks let the outside world push orders, messages and sales in.

  GET  /events                      SSE stream; first message is a snapshot
  GET  /state                       snapshot + recent events
  GET  /archive?limit=200&bay=etsy  ledger query
  GET  /approvals                   pending gates
  POST /approvals/{id}/approve|reject
  POST /bays/{id}/hold|boost|wake   bridge controls (the dashboard's HOLD/BOOST buttons call these)
  POST /bays/{id}/run               start a run now
  POST /inbound/order               {"niche":"finance","qty":3,"amount":105,"brief":"..."}   → Thumbnail Studio
  POST /inbound/message             {"platform":"etsy","from":"buyer","text":"...","order_id":1}  → Comms Deck
  POST /inbound/sale                {"amount":24.95,"title":"...","bay":"etsy"}               → Treasury
  GET  /                            serves the dashboard
"""
import asyncio, json, logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .ledger import Ledger
from .orchestrator import Orchestrator

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
app = FastAPI(title="Constantinople engine", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

ledger = Ledger()
orch = Orchestrator(ledger)
(config.ROOT / "output" / "images").mkdir(parents=True, exist_ok=True)
app.mount("/output", StaticFiles(directory=str(config.ROOT / "output")), name="output")


def _img_urls(paths) -> list[str]:
    out = []
    for pth in paths or []:
        pth = str(pth)
        if "/output/" in pth: out.append("/output/" + pth.split("/output/", 1)[1])
    return out
subscribers: set[asyncio.Queue] = set()
_loop: asyncio.AbstractEventLoop | None = None


def _disp(ev: dict) -> dict:
    d = orch.bays.get(ev.get("bay"))
    return {**ev, "bay": d.display, "source_bay": ev["bay"]} if d and d.display != ev["bay"] else ev


def _fanout(ev: dict):
    if _loop is None: return
    ev = _disp(ev)
    for q in list(subscribers):
        _loop.call_soon_threadsafe(q.put_nowait, ev)


@app.on_event("startup")
async def _start():
    global _loop
    _loop = asyncio.get_running_loop()
    ledger.subscribe(_fanout)
    await orch.start()


@app.on_event("shutdown")
async def _stop():
    await orch.stop()


@app.get("/events")
async def events(request: Request):
    q: asyncio.Queue = asyncio.Queue()
    subscribers.add(q)

    async def gen():
        try:
            yield f"data: {json.dumps(ledger.snapshot())}\n\n"
            for ev in reversed(ledger.recent(150)):
                yield f"data: {json.dumps(_disp(ev))}\n\n"
            while True:
                if await request.is_disconnected(): break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(ev)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            subscribers.discard(q)
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/state")
def state():
    return {**ledger.snapshot(), "recent": ledger.recent(60), "bays_spec": {k: {"name": b.name, "steps": [s["name"] for s in b.steps], "agents": b.agents} for k, b in orch.bays.items()}}


@app.get("/archive")
def archive(limit: int = 200, bay: str | None = None, kind: str | None = None):
    return ledger.recent(limit, bay, kind)


@app.get("/artifacts")
def artifacts(bay: str | None = None, limit: int = 20):
    return ledger.artifacts(bay, limit)


@app.get("/approvals")
def approvals(status: str = "pending", limit: int = 200):
    rows = []
    for a in ledger.approvals(status, limit):
        try: payload = json.loads(a.get("payload") or "{}")
        except Exception: payload = {}
        dd = payload.get("design_draft") or {}
        a = {k: v for k, v in a.items() if k != "payload"}
        a["images"] = _img_urls(dd.get("files"))
        a["concept"] = (payload.get("trend_scan") or {}).get("concept") or (payload.get("listing_draft") or {}).get("title")
        a["mockups"] = (payload.get("mockup_build") or {}).get("mockups") or []
        rows.append(a)
    return rows


@app.get("/designs")
def designs(limit: int = 12):
    """Recent designs the crew rendered, newest first, with the concept they belong to."""
    d = config.ROOT / "output" / "images"
    files = sorted(d.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit * 2]
    rows = []
    for f in files:
        run_id = f.stem.rsplit("_", 1)[0]
        ev = ledger.db.execute("SELECT msg FROM events WHERE run_id=? AND kind='step' AND step=1 ORDER BY id LIMIT 1", (run_id,)).fetchone()
        concept = ev["msg"].split(":", 1)[1].strip() if ev and ":" in ev["msg"] else run_id
        rows.append({"url": f"/output/images/{f.name}", "run_id": run_id, "variant": f.stem.rsplit("_", 1)[-1], "concept": concept[:80], "ts": f.stat().st_mtime})
    return rows[:limit]


@app.get("/listings")
def listings():
    from . import memory
    return memory.listing_performance(ledger)


@app.get("/memory")
def memory_digest(days: int = 7):
    from . import memory
    return memory.digest(ledger, days)


@app.get("/mother")
def mother():
    """What Mother has done lately, and what she is waiting on the Creator for."""
    return {"name": config.MOTHER_NAME, "autonomy": config.AUTONOMY, "daily_cap": config.DAILY_SPEND_CAP, "spent_today": orch.mother.spent_today(),
            "escalations": [a for a in ledger.approvals("pending") if a["gate"] == "escalation"], "recent": ledger.recent(40, kind="mother")}


@app.post("/approvals/{aid}/{decision}")
def decide(aid: int, decision: str):
    if decision not in ("approve", "reject"): raise HTTPException(400, "approve|reject")
    if not ledger.approval(aid): raise HTTPException(404)
    orch.runner.decide(aid, "approved" if decision == "approve" else "rejected", config.CREATOR)
    return {"ok": True, "id": aid, "status": decision}


@app.post("/halt")
def halt(): return {"ok": True, "held": orch.halt_all()}


@app.post("/resume")
def resume(): return {"ok": True, "resumed": orch.resume_all()}


@app.post("/bays/{bay_id}/{action}")
async def bay_action(bay_id: str, action: str):
    if bay_id not in orch.bays: raise HTTPException(404, "unknown bay")
    if action == "run":
        asyncio.create_task(orch.run_once(bay_id)); return {"ok": True, "started": bay_id}
    if action not in ("hold", "boost", "wake", "standby"): raise HTTPException(400, "hold|boost|wake|standby|run")
    return {"ok": True, "status": orch.set_status(bay_id, action)}


@app.post("/inbound/order")
async def inbound_order(body: dict):
    body.setdefault("order_id", f"FO{abs(hash(json.dumps(body, sort_keys=True))) % 10**8}")
    ledger.emit("studio", "order", f"Order {body['order_id']}: {body.get('niche','?')} thumbnails ×{body.get('qty',1)} · ${float(body.get('amount',0)):.2f}", agent="RAY", amount=None)
    await orch.runner.enqueue("studio", {"order": body}); return {"ok": True}


@app.post("/inbound/message")
async def inbound_message(body: dict):
    ledger.emit("comms", "message", f"Inbound ({body.get('platform','?')}): \"{body.get('text','')[:120]}\"", agent="HERALD")
    await orch.runner.enqueue("comms", {"message": body}); return {"ok": True}


@app.post("/inbound/clip_order")
async def inbound_clip_order(body: dict):
    """A paid made-to-order short: {"niche":"coffee shop","brief":"...","cta":"Visit us on 5th St","amount":35,"images":[...urls]}"""
    body.setdefault("order_id", f"CO{abs(hash(json.dumps(body, sort_keys=True))) % 10**8}")
    amt = float(body.get("amount") or config.CLIP_PRICE); body["amount"] = amt
    ledger.emit("clips", "order", f"Clip order {body['order_id']}: {body.get('niche','?')} short · ${amt:.2f}", agent="REEL", amount=None)
    await orch.runner.enqueue("clip_orders", {"clip_order": body}); return {"ok": True, "order_id": body["order_id"]}


@app.get("/signal")
def signal_brief():
    from .tools import signal
    return {"brief": signal.latest_brief(ledger), "clips": signal.recent_clips(ledger, 12)}


@app.get("/pnl")
async def pnl(days: int = 30):
    from .tools import treasury
    return await treasury.pnl({"_ledger": ledger, "run_id": "pnl"}, days=days)


@app.get("/clips")
def clips_list(limit: int = 12):
    from .tools import signal
    rows = signal.recent_clips(ledger, limit)
    for r in rows:
        for k in ("file", "thumb"):
            if r.get(k) and "/output/" in r[k]: r[k] = "/output/" + r[k].split("/output/", 1)[1]
    return {"clips": rows}


@app.post("/inbound/sale")
async def inbound_sale(body: dict):
    bay = body.get("bay", "etsy")
    ledger.emit(bay, "sale", f"Sale ${float(body['amount']):.2f} · {body.get('title','')}", agent="VAULT", amount=float(body["amount"]))
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def dashboard():
    p = config.DASH_DIR / "index.html"
    if not p.exists(): return HTMLResponse("<p>dashboard/index.html missing</p>", 404)
    body = p.read_text()
    if "<html" not in body[:200]:
        body = '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"></head><body style="margin:0">' + body + "</body></html>"
    return HTMLResponse(body.replace('placeholder="http://localhost:8787/events"', f'placeholder="http://{config.HOST}:{config.PORT}/events" value="/events"'))


def main():
    import uvicorn
    uvicorn.run("constantinople.server:app", host=config.HOST, port=config.PORT, log_level="info")


if __name__ == "__main__":
    main()
