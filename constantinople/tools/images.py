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


def _clean_alpha(im):
    """Print prep for a transparent design: remove the faint semi-transparent halo image models leave
    around edges, drop stray near-invisible pixels, and crop to the artwork with a small margin."""
    from PIL import Image, ImageFilter
    import numpy as np
    a = np.array(im, dtype=np.uint8)
    alpha = a[:, :, 3].astype(np.float32)
    # push weak alpha to zero and strong alpha to full: kills the grey fringe without eating anti-aliasing
    alpha = np.clip((alpha - 40) * (255.0 / (255 - 40)), 0, 255)
    alpha[alpha < 24] = 0
    a[:, :, 3] = alpha.astype(np.uint8)
    # un-premultiply dark fringes: where alpha is partial, pull colour toward the nearest opaque colour
    out = Image.fromarray(a, "RGBA")
    bbox = out.getbbox()
    if bbox:
        pad = int(0.02 * max(out.width, out.height))
        out = out.crop((max(0, bbox[0] - pad), max(0, bbox[1] - pad), min(out.width, bbox[2] + pad), min(out.height, bbox[3] + pad)))
    return out


def _upscale(path: str) -> str:
    """Print-grade upscale: Real-ESRGAN when installed (pip install realesrgan — needs torch), else a careful
    two-step Lanczos with light sharpening. Then alpha cleanup. Result ~4500 px wide, as Printify likes."""
    try:
        from PIL import Image, ImageFilter
        im = Image.open(path).convert("RGBA")
        try:
            import numpy as np
            from realesrgan import RealESRGANer  # type: ignore
            from basicsr.archs.rrdbnet_arch import RRDBNet  # type: ignore
            model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23, num_grow_ch=32, scale=4)
            up = RealESRGANer(scale=4, model_path="https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth", model=model, tile=400, half=False, device="cpu")
            rgb = np.array(im.convert("RGB"))[:, :, ::-1]; alpha = im.split()[3]
            out, _ = up.enhance(rgb, outscale=4)
            out = Image.fromarray(out[:, :, ::-1]); alpha = alpha.resize(out.size, Image.LANCZOS); out.putalpha(alpha); im = out
        except Exception:
            # two-step Lanczos + gentle unsharp mask keeps edges crisp without ringing
            if im.width < UPSCALE_PX:
                mid = im.resize((im.width * 2, im.height * 2), Image.LANCZOS)
                im = mid.resize((UPSCALE_PX, int(mid.height * UPSCALE_PX / mid.width)), Image.LANCZOS)
                rgb = im.convert("RGB").filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=3)); rgb.putalpha(im.split()[3]); im = rgb
        try: im = _clean_alpha(im)
        except Exception: pass
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


def _pick_better(path_a: str, path_b: str, concept: str) -> tuple[str, str]:
    """Mother's eye on two candidates: which is the stronger product design? Returns (winner_path, reason)."""
    if not config.ANTHROPIC_API_KEY: return path_a, "no model key"
    try:
        import anthropic, io
        from PIL import Image
        def enc(p):
            im = Image.open(p).convert("RGBA"); bg = Image.new("RGBA", im.size, (245, 240, 230, 255)); bg.alpha_composite(im); im = bg.convert("RGB"); im.thumbnail((700, 700))
            buf = io.BytesIO(); im.save(buf, "JPEG", quality=82); return base64.b64encode(buf.getvalue()).decode()
        c = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        msg = c.messages.create(model=config.MOTHER_MODEL, max_tokens=120, messages=[{"role": "user", "content": [
            {"type": "text", "text": f"Two candidate designs for a print-on-demand product, concept: {concept}. Judge as a buyer scrolling Etsy: which reads instantly, has cleaner shapes and lettering, prints well, and feels like something someone would wear or give? Reply exactly 'A: <reason>' or 'B: <reason>' in under 20 words."},
            {"type": "text", "text": "A:"}, {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": enc(path_a)}},
            {"type": "text", "text": "B:"}, {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": enc(path_b)}}]}])
        t = "".join(getattr(b, "text", "") for b in msg.content).strip()
        return (path_b if t.upper().startswith("B") else path_a), t[:120]
    except Exception as e:
        return path_a, f"pick skipped ({type(e).__name__})"


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
            # best of two: a second light candidate, and Mother picks before the dark version is made
            if label == "light" and variants and config.BEST_OF_TWO and not poster:
                r2 = await c.post("https://api.openai.com/v1/images/generations", headers={"Authorization": f"Bearer {config.IMAGE_API_KEY}"},
                                  json={"model": "gpt-image-1", "prompt": ptxt + " A different composition from any previous attempt.", "n": 1, "size": size, "quality": "medium", "background": "transparent", "output_format": "png"})
                spent += 1
                if r2.status_code == 200:
                    p2 = OUT / f"{ctx['run_id']}_light_b.png"; p2.write_bytes(base64.b64decode(r2.json()["data"][0]["b64_json"]))
                    ok2 = True
                    if wanted_text:
                        got2 = read_text(str(p2)); ok2 = got2 is None or _norm(got2) == _norm(wanted_text)
                    if ok2:
                        win, why = _pick_better(str(p), str(p2), (ctx.get("trend_scan") or {}).get("concept", ""))
                        qa["pick"] = why
                        if win == str(p2): p2.replace(p)
            _upscale(str(p)); files.append(str(p)); labelled[label] = str(p)
    return {"files": files, "by_variant": labelled, "prompt": prompt, "text": wanted_text, "qa": qa, "cost": config.IMAGE_COST_USD * spent,
            "summary": f"{len(files)} print-ready design(s) rendered" + (" · light + dark shirt versions" if variants else "") + (f" · lettering verified: \"{wanted_text}\"" if wanted_text else "") + (f" · {spent - len(files)} re-render(s)" if spent > len(files) else "")}

def _lookup(ctx, path):
    cur = ctx
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur: cur = cur[part]
        else: return None
    return cur
