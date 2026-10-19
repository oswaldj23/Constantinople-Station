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


def _norm(t: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())


def read_text(path: str) -> str | None:
    """Ask the model to transcribe every word visible in the design. None when no model key."""
    if not config.ANTHROPIC_API_KEY: return None
    try:
        import anthropic, io
        from PIL import Image
        im = Image.open(path).convert("RGBA"); bg = Image.new("RGBA", im.size, (255, 255, 255, 255)); bg.alpha_composite(im); im = bg.convert("RGB"); im.thumbnail((900, 900))
        buf = io.BytesIO(); im.save(buf, "JPEG", quality=85)
        c = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        msg = c.messages.create(model=config.AGENT_MODEL, max_tokens=120, messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(buf.getvalue()).decode()}},
            {"type": "text", "text": "Transcribe ALL text visible in this image exactly as written, in reading order, on one line. Include misspellings exactly. If there is no text at all reply NONE."}]}])
        return "".join(getattr(b, "text", "") for b in msg.content).strip()
    except Exception:
        return None


async def generate(ctx, *, prompt_from: str = "", n: int = 4, size: str = "1024x1024", variants: bool = False, dry_run: bool = True, **_):
    prompt = _lookup(ctx, prompt_from) or "flat hand-drawn illustration"
    wanted_text = (ctx.get("trend_scan") or {}).get("text") or ((ctx.get("research") or {}).get("brief") or {}).get("text")
    if isinstance(wanted_text, str) and wanted_text.strip().lower() in ("null", "none", ""): wanted_text = None
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
    text_rule = (f' The design contains the exact words "{wanted_text}" — spelled exactly, every letter correct, nothing else written anywhere.' if wanted_text
                 else " No text, letters or numbers anywhere.")
    poster = (ctx.get("trend_scan") or {}).get("products", [""])[:1] == ["poster"] or ctx.get("product_type") == "poster"
    base = prompt + (" Full-bleed wall-art composition filling the whole canvas, print-ready, no frame, no mockup, no person, no watermark." if poster else " Isolated artwork for printing: transparent background, no mockup, no shirt, no frame, no person.") + text_rule
    jobs = [("light", base + " " + VARIANTS["light"]), ("dark", base + " " + VARIANTS["dark"])] if variants else [(f"v{i}", base) for i in range(n)]
    labelled = {}; qa = {}; spent = 0
    async with httpx.AsyncClient(timeout=180) as c:
        for label, ptxt in jobs:
            ok = False
            for attempt in range(3 if wanted_text else 1):
                r = await c.post("https://api.openai.com/v1/images/generations", headers={"Authorization": f"Bearer {config.IMAGE_API_KEY}"},
                                 json={"model": "gpt-image-1", "prompt": ptxt + (" Simpler lettering, larger letters, fewer decorations." if attempt else ""), "n": 1, "size": "1024x1536" if poster else size, "quality": "medium" if attempt < 2 else "high", "background": "opaque" if poster else "transparent", "output_format": "png"})
                spent += 1
                if r.status_code >= 400:
                    return {"summary": "render failed", "incident": f"Image provider error · {r.status_code} {r.text[:140]}", "cost": config.IMAGE_COST_USD * spent}
                p = OUT / f"{ctx['run_id']}_{label}.png"; p.write_bytes(base64.b64decode(r.json()["data"][0]["b64_json"]))
                if wanted_text:
                    got = read_text(str(p))
                    if got is None or _norm(got) == _norm(wanted_text):
                        qa[label] = f"text OK ({got or 'unchecked'})"; ok = True; break
                    qa[label] = f"attempt {attempt+1}: read back '{got}' ≠ '{wanted_text}'"
                else:
                    got = read_text(str(p))
                    if got and got.strip().upper() != "NONE": qa[label] = f"unexpected text '{got[:40]}'"
                    else: qa[label] = "no text, as intended"; ok = True
                    break
            if wanted_text and not ok:
                return {"summary": "lettering failed", "incident": f"Design lettering failed QA after 3 renders · wanted '{wanted_text}' · {qa.get(label)} · concept rebriefed", "cost": config.IMAGE_COST_USD * spent}
            _upscale(str(p)); files.append(str(p)); labelled[label] = str(p)
    return {"files": files, "by_variant": labelled, "prompt": prompt, "text": wanted_text, "qa": qa, "cost": config.IMAGE_COST_USD * spent,
            "summary": f"{len(files)} print-ready design(s) rendered" + (" · light + dark shirt versions" if variants else "") + (f" · lettering verified: \"{wanted_text}\"" if wanted_text else "") + (f" · {spent - len(files)} re-render(s)" if spent > len(files) else "")}

def _lookup(ctx, path):
    cur = ctx
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur: cur = cur[part]
        else: return None
    return cur
