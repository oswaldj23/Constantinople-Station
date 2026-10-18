"""The ledger is the station's memory: one SQLite file holding every event, every dollar, and the
state of every bay. If it happened, it is written. The dashboard's Archive, Ledger and HUD are all
views over this table."""
import json, sqlite3, threading, time
from datetime import datetime, timezone
from typing import Any, Optional

from . import config

_lock = threading.Lock()


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class Ledger:
    def __init__(self, path: str = config.DB_PATH):
        self.path = path
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self._init()
        self._listeners: list = []

    # ── schema ──────────────────────────────────────────────────────────
    def _init(self):
        with _lock:
            self.db.executescript(
                """
                CREATE TABLE IF NOT EXISTS events(
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  ts TEXT NOT NULL, bay TEXT NOT NULL, kind TEXT NOT NULL,
                  step INTEGER, agent TEXT, msg TEXT NOT NULL, amount REAL,
                  run_id TEXT, data TEXT
                );
                CREATE INDEX IF NOT EXISTS ev_bay ON events(bay, id);
                CREATE INDEX IF NOT EXISTS ev_kind ON events(kind, id);
                CREATE TABLE IF NOT EXISTS bays(
                  id TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'running',
                  rev REAL NOT NULL DEFAULT 0, cost REAL NOT NULL DEFAULT 0,
                  runs INTEGER NOT NULL DEFAULT 0, conf REAL NOT NULL DEFAULT 90,
                  step INTEGER NOT NULL DEFAULT 0, last_run TEXT
                );
                CREATE TABLE IF NOT EXISTS approvals(
                  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, bay TEXT NOT NULL,
                  step TEXT NOT NULL, gate TEXT NOT NULL, summary TEXT NOT NULL, payload TEXT,
                  status TEXT NOT NULL DEFAULT 'pending', decided_ts TEXT
                );
                CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
                CREATE TABLE IF NOT EXISTS artifacts(
                  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, bay TEXT NOT NULL,
                  run_id TEXT, kind TEXT NOT NULL, title TEXT, payload TEXT
                );
                """
            )
            self.db.commit()

    # ── bays ────────────────────────────────────────────────────────────
    def ensure_bay(self, bay_id: str, status: str = "running"):
        with _lock:
            self.db.execute("INSERT OR IGNORE INTO bays(id,status) VALUES(?,?)", (bay_id, status))
            self.db.commit()

    def bay(self, bay_id: str) -> dict:
        row = self.db.execute("SELECT * FROM bays WHERE id=?", (bay_id,)).fetchone()
        return dict(row) if row else {}

    def bays(self) -> dict:
        return {r["id"]: dict(r) for r in self.db.execute("SELECT * FROM bays")}

    def set_status(self, bay_id: str, status: str):
        with _lock:
            self.db.execute("UPDATE bays SET status=? WHERE id=?", (status, bay_id))
            self.db.commit()

    def bump(self, bay_id: str, **cols):
        """Increment numeric columns, e.g. bump('etsy', rev=24.5, cost=0.03)."""
        if not cols:
            return
        sets = ", ".join(f"{k}={k}+?" for k in cols)
        with _lock:
            self.db.execute(f"UPDATE bays SET {sets} WHERE id=?", (*cols.values(), bay_id))
            self.db.commit()

    def set_step(self, bay_id: str, step: int, last_run: Optional[str] = None):
        with _lock:
            if last_run:
                self.db.execute("UPDATE bays SET step=?, last_run=? WHERE id=?", (step, last_run, bay_id))
            else:
                self.db.execute("UPDATE bays SET step=? WHERE id=?", (step, bay_id))
            self.db.commit()

    # ── events ──────────────────────────────────────────────────────────
    def emit(self, bay: str, kind: str, msg: str, *, step: Optional[int] = None, agent: Optional[str] = None,
             amount: Optional[float] = None, run_id: Optional[str] = None, **data: Any) -> dict:
        ev = {"ts": _utc(), "bay": bay, "kind": kind, "msg": msg}
        if step is not None: ev["step"] = step
        if agent: ev["agent"] = agent
        if amount is not None: ev["amount"] = round(float(amount), 4)
        if run_id: ev["run_id"] = run_id
        ev.update({k: v for k, v in data.items() if v is not None})
        with _lock:
            cur = self.db.execute(
                "INSERT INTO events(ts,bay,kind,step,agent,msg,amount,run_id,data) VALUES(?,?,?,?,?,?,?,?,?)",
                (ev["ts"], bay, kind, step, agent, msg, ev.get("amount"), run_id, json.dumps(data) if data else None),
            )
            self.db.commit()
            ev["id"] = cur.lastrowid
        if kind == "sale":
            self.bump(bay, rev=amount or 0)
        if kind == "cost" or (kind == "step" and amount):
            self.bump(bay, cost=amount or 0)
        for fn in list(self._listeners):
            try:
                fn(ev)
            except Exception:
                pass
        return ev

    def subscribe(self, fn):
        self._listeners.append(fn)
        return lambda: self._listeners.remove(fn)

    def recent(self, limit: int = 200, bay: Optional[str] = None, kind: Optional[str] = None) -> list[dict]:
        q, args = "SELECT * FROM events", []
        conds = []
        if bay: conds.append("bay=?"); args.append(bay)
        if kind: conds.append("kind=?"); args.append(kind)
        if conds: q += " WHERE " + " AND ".join(conds)
        q += " ORDER BY id DESC LIMIT ?"; args.append(limit)
        out = []
        for r in self.db.execute(q, args):
            d = dict(r)
            extra = json.loads(d.pop("data") or "{}")
            d = {k: v for k, v in d.items() if v is not None}
            d.update(extra)
            out.append(d)
        return out

    # ── approvals ───────────────────────────────────────────────────────
    def request_approval(self, bay: str, step: str, gate: str, summary: str, payload: dict) -> int:
        with _lock:
            cur = self.db.execute(
                "INSERT INTO approvals(ts,bay,step,gate,summary,payload) VALUES(?,?,?,?,?,?)",
                (_utc(), bay, step, gate, summary, json.dumps(payload)),
            )
            self.db.commit()
            return cur.lastrowid

    def approval(self, aid: int) -> Optional[dict]:
        r = self.db.execute("SELECT * FROM approvals WHERE id=?", (aid,)).fetchone()
        return dict(r) if r else None

    def approvals(self, status: str = "pending") -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM approvals WHERE status=? ORDER BY id", (status,))]

    def decide(self, aid: int, status: str):
        with _lock:
            self.db.execute("UPDATE approvals SET status=?, decided_ts=? WHERE id=?", (status, _utc(), aid))
            self.db.commit()

    # ── artifacts (designs, listings, deliverables) ─────────────────────
    def save_artifact(self, bay: str, kind: str, title: str, payload: dict, run_id: Optional[str] = None) -> int:
        with _lock:
            cur = self.db.execute(
                "INSERT INTO artifacts(ts,bay,run_id,kind,title,payload) VALUES(?,?,?,?,?,?)",
                (_utc(), bay, run_id, kind, title, json.dumps(payload)),
            )
            self.db.commit()
            return cur.lastrowid

    def artifacts(self, bay: Optional[str] = None, limit: int = 20, kind_filter: Optional[str] = None) -> list[dict]:
        q, args, conds = "SELECT * FROM artifacts", [], []
        if bay: conds.append("bay=?"); args.append(bay)
        if kind_filter: conds.append("kind=?"); args.append(kind_filter)
        if conds: q += " WHERE " + " AND ".join(conds)
        q += " ORDER BY id DESC LIMIT ?"; args.append(limit)
        out = []
        for r in self.db.execute(q, args):
            d = dict(r); d["payload"] = json.loads(d["payload"] or "{}"); out.append(d)
        return out

    # ── key/value (mission leg, directive) ──────────────────────────────
    def kv_get(self, k: str):
        r = self.db.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return r["v"] if r else None

    def kv_set(self, k: str, v: str):
        with _lock:
            self.db.execute("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))
            self.db.commit()

    # ── totals ──────────────────────────────────────────────────────────
    def totals(self) -> dict:
        r = self.db.execute("SELECT COALESCE(SUM(rev),0) rev, COALESCE(SUM(cost),0) cost FROM bays").fetchone()
        return {"rev": round(r["rev"], 2), "cost": round(r["cost"], 4)}

    def snapshot(self) -> dict:
        from . import mission
        return {"kind": "snapshot", "ts": _utc(), "bays": self.bays(), "totals": self.totals(),
                "pending_approvals": len(self.approvals("pending")),
                "station": config.STATION_NAME, "callsign": config.CALLSIGN,
                "mission": mission.state(self), "integrations": config.integrations()}
