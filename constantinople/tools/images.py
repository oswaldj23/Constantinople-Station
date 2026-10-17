"""Image generation for designs and thumbnails. Plug any provider in `_generate`.
Dry run writes a tiny placeholder PNG per variant so downstream steps have real file paths."""
import base64, random, struct, zlib
from pathlib import Path
from .. import config

OUT = config.ROOT / "output" / "images"

def _png(w, h, rgb):
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    def chunk(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")

VARIANTS = {"light": "Palette for printing on a WHITE or cream shirt: rich mid-tone and dark inks, no white fills.",
            "dark": "Palette for printing on a BLACK shirt: light, bright inks and white line work, no black fills."}
UPSCALE_PX = 4500   # Printify's comfortable print size for a tee front


def _upscale(path: str) -> str:
    try:
        from PIL import Image
        im = Image.open(path).convert("RGBA")
        if im.width < UPSCALE_PX:
            im = im.resize((UPSCALE_PX, int(im.height * UPSCALE_PX / im.width)), Image.LANCZOS)
            im.save(path, "PNG", optimize=True)
    except Exception:
        pass
    return path


async def generate(ctx, *, prompt_from: str = "", n: int = 4, size: str = "1024x1024", variants: bool = False, dry_run: bool = True, **_):
    prompt = _lookup(ctx, prompt_from) or "flat hand-drawn illustration"
    OUT.mkdir(parents=True, exist_ok=True)
    files = []
    if dry_run or config.IMAGE_PROVIDER == "none":
        if random.random() < 0.07:
            inc = "Render batch unusable · face crop failed on all candidates · re-render" if ctx.get("bay") == "studio" else "Design discarded · similarity score 0.91 above threshold 0.82"
            return {"summary": "discarded", "incident": inc, "cost": 0.0}
        for i in range(n):
            p = OUT / f"{ctx['run_id']}_{i}.png"
            p.write_bytes(_png(8, 8, (random.randint(80, 220), random.randint(80, 220), random.randint(80, 220))))
            files.append(str(p))
        return {"files": files, "prompt": prompt, "cost": config.IMAGE_COST_USD * n * (0 if dry_run else 1),
                "summary": f"{n} variants rendered"}
    # Real provider. Example for an OpenAI-compatible images endpoint; swap for your provider.
    import httpx
    base = prompt + " Isolated artwork for printing on a shirt: transparent background, no mockup, no shirt, no frame, no text unless asked."
    jobs = [("light", base + " " + VARIANTS["light"]), ("dark", base + " " + VARIANTS["dark"])] if variants else [(f"v{i}", base) for i in range(n)]
    labelled = {}
    async with httpx.AsyncClient(timeout=180) as c:
        for label, ptxt in jobs:
            r = await c.post("https://api.openai.com/v1/images/generations", headers={"Authorization": f"Bearer {config.IMAGE_API_KEY}"},
                             json={"model": "gpt-image-1", "prompt": ptxt, "n": 1, "size": size, "quality": "medium", "background": "transparent", "output_format": "png"})
            if r.status_code >= 400:
                return {"summary": "render failed", "incident": f"Image provider error · {r.status_code} {r.text[:140]}", "cost": config.IMAGE_COST_USD * len(labelled)}
            p = OUT / f"{ctx['run_id']}_{label}.png"; p.write_bytes(base64.b64decode(r.json()["data"][0]["b64_json"]))
            _upscale(str(p)); files.append(str(p)); labelled[label] = str(p)
    return {"files": files, "by_variant": labelled, "prompt": prompt, "cost": config.IMAGE_COST_USD * len(files),
            "summary": f"{len(files)} print-ready design(s) rendered" + (" · light + dark shirt versions" if variants else "")}

def _lookup(ctx, path):
    cur = ctx
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur: cur = cur[part]
        else: return None
    return cur
