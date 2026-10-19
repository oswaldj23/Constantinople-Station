"""Stock images: the closest thing to passive income on board. Adobe Stock accepts generative-AI images
(labelled as such, no real people, no brands, no recognisable artworks) and takes uploads over SFTP.
The bay generates themed sets, writes titles and keywords, and uploads the JPGs plus a metadata CSV.
Adobe then needs one click from the Creator per batch — select the uploaded files, tick "Created using
generative AI", submit — which the bridge reminds you about weekly. Royalties are ~33% of each licence.

Setup: contributor.stock.adobe.com → Upload → "Connect via SFTP" shows the host, your username and lets you
set an SFTP password. Put them in STOCK_SFTP_HOST / STOCK_SFTP_USER / STOCK_SFTP_PASSWORD."""
import base64, csv, io, json, os, random
from pathlib import Path
from .. import config

OUT = config.ROOT / "output" / "stock"
MIN_PIXELS = 4_000_000   # Adobe: at least 4 MP


def _env(k, d=None):
    return os.getenv(k) or d


def _gen(prompt: str) -> bytes | None:
    import httpx
    r = httpx.post("https://api.openai.com/v1/images/generations", headers={"Authorization": f"Bearer {config.IMAGE_API_KEY}"},
                   json={"model": "gpt-image-1", "prompt": prompt, "n": 1, "size": "1536x1024", "quality": "high", "background": "opaque", "output_format": "png"}, timeout=240)
    return base64.b64decode(r.json()["data"][0]["b64_json"]) if r.status_code == 200 else None


async def render(ctx, *, dry_run: bool = True, **_):
    """Render the set: N images from the brief's prompts, upscaled to ≥4 MP JPG."""
    from PIL import Image
    b = ctx.get("stock_brief") or {}; items = b.get("images") or []
    d = OUT / ctx["run_id"]; d.mkdir(parents=True, exist_ok=True)
    files = []; cost = 0.0
    for i, it in enumerate(items[:10]):
        prompt = it.get("prompt", b.get("theme", "abstract texture")) + " No text, no watermark, no logos, no recognisable people, no brand products, no famous artworks or buildings. Clean, commercial stock-photo quality."
        raw = None if (dry_run or not config.IMAGE_API_KEY) else _gen(prompt)
        if raw: im = Image.open(io.BytesIO(raw)).convert("RGB"); cost += 0.17
        else:
            im = Image.new("RGB", (1536, 1024), (random.randint(60, 200), random.randint(60, 200), random.randint(60, 200)))
        if im.width * im.height < MIN_PIXELS:
            s = (MIN_PIXELS / (im.width * im.height)) ** 0.5 * 1.05; im = im.resize((int(im.width * s), int(im.height * s)), Image.LANCZOS)
        f = d / f"{ctx['run_id']}_{i+1:02d}.jpg"; im.save(f, "JPEG", quality=94, dpi=(300, 300))
        files.append({"file": str(f), "title": it.get("title", b.get("theme", "")), "keywords": it.get("keywords", []), "category": it.get("category", 8)})
    return {"files": files, "cost": round(cost, 2), "summary": f"{len(files)} stock image(s) rendered"}


async def upload(ctx, *, dry_run: bool = True, **_):
    """SFTP the JPGs and a metadata CSV (Filename, Title, Keywords, Category, Releases) to Adobe Stock."""
    r = ctx.get("render") or {}; files = r.get("files") or []
    if not files: return {"summary": "nothing to upload", "cost": 0.0}
    d = OUT / ctx["run_id"]; csvp = d / "metadata.csv"
    with open(csvp, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["Filename", "Title", "Keywords", "Category", "Releases"])
        for f in files:
            kws = [k.strip() for k in f["keywords"] if k.strip()][:49]
            w.writerow([Path(f["file"]).name, f["title"][:200], ",".join(kws), f.get("category", 8), ""])
    host, user, pw = _env("STOCK_SFTP_HOST", "sftp.contributor.adobestock.com"), _env("STOCK_SFTP_USER"), _env("STOCK_SFTP_PASSWORD")
    if dry_run or not (user and pw):
        return {"uploaded": 0, "csv": str(csvp), "cost": 0.0, "summary": f"{len(files)} image(s) + metadata ready ({'dry run' if dry_run else 'STOCK_SFTP_USER/PASSWORD not set'}) · kept in output/stock/"}
    try:
        import paramiko
        t = paramiko.Transport((host, 22)); t.connect(username=user, password=pw); s = paramiko.SFTPClient.from_transport(t)
        n = 0
        for f in files:
            s.put(f["file"], Path(f["file"]).name); n += 1
        s.put(str(csvp), f"{ctx['run_id']}_metadata.csv"); s.close(); t.close()
    except Exception as e:
        return {"summary": "upload failed", "incident": f"Adobe Stock SFTP failed · {type(e).__name__}: {str(e)[:120]} · check STOCK_SFTP_* in .env", "cost": 0.0}
    L = ctx.get("_ledger")
    if L is not None:
        try: L.kv_set("stock_pending", str(int(L.kv_get("stock_pending") or 0) + n))
        except Exception: pass
    return {"uploaded": n, "csv": str(csvp), "cost": 0.0, "summary": f"{n} image(s) uploaded to Adobe Stock · waiting for your one-click submit in the contributor portal"}
