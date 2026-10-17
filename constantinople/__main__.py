"""CLI.
  python -m constantinople serve                  run the engine + dashboard on http://127.0.0.1:8787
  python -m constantinople once etsy              run one bay's workflow once, in the foreground
  python -m constantinople order --niche finance --qty 3 --amount 105     hand an order to the studio (needs serve running)
  python -m constantinople message "Can I get this in XL?"                hand a message to comms (needs serve running)
  python -m constantinople approvals              list pending gates
  python -m constantinople approve 3 | reject 3   decide a gate
  python -m constantinople tail                   print the event stream
  python -m constantinople etsy-auth              one-time Etsy login (stores tokens in .env)
"""
import argparse, asyncio, json, sys

from . import config


def main(argv=None):
    ap = argparse.ArgumentParser(prog="constantinople")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve")
    p = sub.add_parser("once"); p.add_argument("bay")
    p = sub.add_parser("order"); p.add_argument("--niche", default="finance"); p.add_argument("--qty", type=int, default=1); p.add_argument("--amount", type=float, default=35); p.add_argument("--brief", default="high contrast, 3 words")
    p = sub.add_parser("message"); p.add_argument("text"); p.add_argument("--platform", default="etsy")
    sub.add_parser("approvals")
    p = sub.add_parser("approve"); p.add_argument("id", type=int)
    p = sub.add_parser("reject"); p.add_argument("id", type=int)
    sub.add_parser("tail")
    sub.add_parser("etsy-auth")
    a = ap.parse_args(argv)
    base = f"http://{config.HOST}:{config.PORT}"

    if a.cmd == "etsy-auth":
        from .etsy_auth import main as etsy_auth; etsy_auth(); return
    if a.cmd == "serve":
        from .server import main as serve; serve(); return
    if a.cmd == "once":
        from .ledger import Ledger
        from .orchestrator import Orchestrator
        L = Ledger(); L.subscribe(lambda ev: print(f"[{ev['ts'][11:19]}] {ev['bay']:<9} {ev['kind']:<9} {ev['msg']}" + (f"  (${ev['amount']:.3f})" if ev.get('amount') else "")))
        o = Orchestrator(L)
        if a.bay not in o.bays: sys.exit(f"unknown bay {a.bay}; have {', '.join(o.bays)}")
        config.AUTO_APPROVE = True
        asyncio.run(o.run_once(a.bay)); return
    import httpx
    if a.cmd == "order":
        print(httpx.post(f"{base}/inbound/order", json={"niche": a.niche, "qty": a.qty, "amount": a.amount, "brief": a.brief}).json())
    elif a.cmd == "message":
        print(httpx.post(f"{base}/inbound/message", json={"platform": a.platform, "from": "buyer", "text": a.text}).json())
    elif a.cmd == "approvals":
        for x in httpx.get(f"{base}/approvals").json(): print(f"#{x['id']:<4} {x['bay']:<9} {x['gate']:<16} {x['summary']}")
    elif a.cmd in ("approve", "reject"):
        print(httpx.post(f"{base}/approvals/{a.id}/{a.cmd}").json())
    elif a.cmd == "tail":
        with httpx.stream("GET", f"{base}/events", timeout=None) as r:
            for line in r.iter_lines():
                if line.startswith("data: "):
                    ev = json.loads(line[6:])
                    if ev.get("kind") == "snapshot": print("snapshot:", json.dumps(ev["totals"])); continue
                    print(f"[{ev['ts'][11:19]}] {ev['bay']:<9} {ev['kind']:<9} {ev['msg']}")


if __name__ == "__main__":
    main()
