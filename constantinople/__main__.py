"""CLI.
  python -m constantinople serve                  run the engine + dashboard on http://127.0.0.1:8787
  python -m constantinople once etsy              run one bay's workflow once, in the foreground
  python -m constantinople order --niche finance --qty 3 --amount 105     hand an order to the studio (needs serve running)
  python -m constantinople message "Can I get this in XL?"                hand a message to comms (needs serve running)
  python -m constantinople approvals              list pending gates
  python -m constantinople approve 3 | reject 3   decide a gate
  python -m constantinople tail                   print the event stream
  python -m constantinople etsy-auth              one-time Etsy login (stores tokens in .env)
  python -m constantinople youtube-auth           one-time YouTube login so the Clip Forge can post
  python -m constantinople youtube-check          does the stored YouTube login still work?
  python -m constantinople footage URL            pull a free-to-use gameplay video into footage/ and record its credit
  python -m constantinople clip --niche "coffee shop" --brief "..." --cta "..."   order a short (needs serve running)
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
    sub.add_parser("etsy-auth"); sub.add_parser("youtube-auth"); sub.add_parser("youtube-check")
    p = sub.add_parser("footage"); p.add_argument("url"); p.add_argument("--credit", default=None, help="credit line (default: the uploader's channel name)")
    p = sub.add_parser("clip"); p.add_argument("--niche", default="small business"); p.add_argument("--brief", default=""); p.add_argument("--cta", default="Link in bio."); p.add_argument("--amount", type=float, default=config.CLIP_PRICE)
    a = ap.parse_args(argv)
    base = f"http://{config.HOST}:{config.PORT}"

    if a.cmd == "footage":
        import subprocess, json as _j, shutil as _sh
        d = config.ROOT / "footage"; d.mkdir(exist_ok=True)
        if not _sh.which("yt-dlp"): subprocess.run([sys.executable, "-m", "pip", "install", "-q", "yt-dlp"])
        info = subprocess.run(["yt-dlp", "-J", "--no-playlist", a.url], capture_output=True, text=True)
        if info.returncode != 0: sys.exit("could not read that video: " + info.stderr[-300:])
        meta = _j.loads(info.stdout); credit = a.credit or (meta.get("uploader") or meta.get("channel") or "") ; title = meta.get("title", "")
        print(f"Downloading: {title}\n  credit: {credit}")
        r = subprocess.run(["yt-dlp", "--no-playlist", "-f", "bv*[height<=1080][ext=mp4]/b[height<=1080]/b", "--merge-output-format", "mp4", "-o", str(d / "%(id)s.%(ext)s"), a.url])
        if r.returncode != 0: sys.exit("download failed")
        fname = f"{meta.get('id')}.mp4"
        with open(d / "CREDITS.txt", "a") as fh: fh.write(f"{fname} | {credit} (YouTube) · {title[:80]}\n")
        print(f"Saved footage/{fname} · credit recorded. The Forge will use it from the next short. Remember: only videos whose uploader allows reuse.")
        return
    if a.cmd == "youtube-check":
        from .tools.youtube import check; r = check()
        print(f"YouTube: OK · channel '{r['channel']}' · {r.get('subscribers')} subscribers · {r.get('videos')} videos" if r["ok"] else f"YouTube: NOT working · {r['error']}"); return
    if a.cmd == "youtube-auth":
        from .youtube_auth import main as yt; yt(); return
    if a.cmd == "clip":
        import httpx; r = httpx.post(f"{base}/inbound/clip_order", json={"niche": a.niche, "brief": a.brief, "cta": a.cta, "amount": a.amount}, timeout=10); print(r.json()); return
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
