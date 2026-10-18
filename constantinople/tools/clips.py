"""The Clip Forge: turns a brief into a finished vertical short.

script (model) → voiceover (OpenAI TTS) → word timings (Whisper) → scene images (listing mockups, designs,
AI b-roll) → 1080x1920 render with Ken Burns motion, crossfades, karaoke captions, optional music bed,
loudness-normalised audio (ffmpeg) → thumbnail → package. Dry run writes a short placeholder video so the
whole chain can be exercised without keys."""
import base64, json, math, os, random, shutil, subprocess, textwrap
from pathlib import Path
from .. import config

OUT = config.ROOT / "output" / "clips"
MUSIC_DIR = config.ROOT / "music"            # drop royalty-free .mp3 loops here; one is picked at random
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
W, H, FPS = 1080, 1920, 30


def _ffmpeg(*args, timeout=600):
    r = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-400:])


INSTALL_HINT = "ffmpeg is not installed on this machine · run: sudo apt-get install -y ffmpeg fonts-dejavu-core · then: sudo systemctl restart constantinople"


def _have_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def _ffprobe_duration(path) -> float:
    if shutil.which("ffprobe"):
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], capture_output=True, text=True)
        try: return float(r.stdout.strip())
        except Exception: pass
    # fall back to ffmpeg's own banner ("Duration: 00:00:25.10, ...")
    import re
    r = subprocess.run(["ffmpeg", "-i", str(path)], capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", r.stderr or "")
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0


# ── 1. voiceover ─────────────────────────────────────────────────────────
async def voiceover(ctx, *, script_from: str = "script", voice: str = None, dry_run: bool = True, **_):
    if not _have_ffmpeg(): return {"summary": "ffmpeg missing", "incident": INSTALL_HINT, "cost": 0.0}
    sc = ctx.get(script_from) or {}
    text = sc.get("voiceover") or " ".join(b.get("line", "") for b in sc.get("beats", []))
    d = OUT / ctx["run_id"]; d.mkdir(parents=True, exist_ok=True); mp3 = d / "voice.mp3"
    if dry_run or not config.IMAGE_API_KEY:
        # silent placeholder of a plausible length so timing code runs
        dur = max(8, min(40, len(text.split()) / 2.6))
        _ffmpeg("-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", f"{dur:.1f}", "-q:a", "9", str(mp3))
        return {"file": str(mp3), "duration": dur, "words": None, "cost": 0.0, "summary": f"voiceover placeholder · {dur:.0f}s"}
    import httpx
    voice = voice or config.TTS_VOICE
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post("https://api.openai.com/v1/audio/speech", headers={"Authorization": f"Bearer {config.IMAGE_API_KEY}"},
                         json={"model": config.TTS_MODEL, "voice": voice, "input": text, "response_format": "mp3", "speed": 1.04,
                               "instructions": "Warm, confident, unhurried narrator for a short product video. Natural pauses. No shouting."})
        if r.status_code >= 400: return {"summary": "tts failed", "incident": f"Voice provider error · {r.status_code} {r.text[:120]}", "cost": 0.0}
        mp3.write_bytes(r.content)
        # word timings for captions
        words = None
        try:
            with open(mp3, "rb") as fh:
                t = await c.post("https://api.openai.com/v1/audio/transcriptions", headers={"Authorization": f"Bearer {config.IMAGE_API_KEY}"},
                                 data={"model": "whisper-1", "response_format": "verbose_json", "timestamp_granularities[]": "word"}, files={"file": ("voice.mp3", fh, "audio/mpeg")})
            if t.status_code == 200: words = [{"w": w["word"], "s": w["start"], "e": w["end"]} for w in t.json().get("words", [])]
        except Exception: pass
    dur = _ffprobe_duration(mp3) or (words[-1]["e"] + 0.4 if words else max(8, len(text.split()) / 2.6))
    return {"file": str(mp3), "duration": dur, "words": words, "cost": round(len(text) / 1e6 * 15 + 0.006 * dur / 60, 4), "summary": f"voiceover {dur:.0f}s · {len(words or [])} word timings"}


# ── 2. scene images ──────────────────────────────────────────────────────
PALETTES = [((24, 32, 48), (8, 10, 14)), ((48, 30, 20), (12, 8, 6)), ((20, 44, 36), (6, 12, 10)), ((44, 22, 40), (10, 6, 12)), ((40, 40, 24), (10, 10, 6))]


def _compose_frame(src: str | None, out: Path, title: str | None = None, accent=(61, 255, 115), fallback_text: str | None = None, seed: int = 0):
    """1080x1920 frame: blurred fill of the image behind, the image itself centred, soft vignette, optional title band.
    With no image: a deep gradient with soft orbs and the spoken line as a large typographic card, so a clip
    never goes out black."""
    from PIL import Image, ImageFilter, ImageDraw, ImageFont
    canvas = Image.new("RGB", (W, H), (8, 10, 14))
    if not (src and Path(src).exists()):
        top, bot = PALETTES[seed % len(PALETTES)]
        grad = Image.new("RGB", (1, H)); gp = grad.load()
        for y in range(H):
            t = y / H; gp[0, y] = tuple(int(top[i] * (1 - t) + bot[i] * t) for i in range(3))
        canvas = grad.resize((W, H))
        orbs = Image.new("RGB", (W, H), (0, 0, 0)); od = ImageDraw.Draw(orbs); rnd = random.Random(seed)
        for _ in range(4):
            r = rnd.randint(180, 420); x = rnd.randint(-100, W); y = rnd.randint(-100, H)
            od.ellipse((x - r, y - r, x + r, y + r), fill=tuple(min(255, c + rnd.randint(30, 70)) for c in top))
        canvas = Image.blend(canvas, orbs.filter(ImageFilter.GaussianBlur(160)), 0.55)
        if fallback_text:
            try: font = ImageFont.truetype(FONT, 72)
            except Exception: font = ImageFont.load_default()
            d = ImageDraw.Draw(canvas); lines = textwrap.wrap(fallback_text, 18)[:5]; y = H // 2 - 48 * len(lines) - 120
            for ln in lines:
                bbox = d.textbbox((0, 0), ln, font=font); tw = bbox[2] - bbox[0]
                d.text(((W - tw) // 2 + 3, y + 3), ln, font=font, fill=(0, 0, 0)); d.text(((W - tw) // 2, y), ln, font=font, fill=(236, 240, 244)); y += 96
    if src and Path(src).exists():
        im = Image.open(src).convert("RGBA")
        bg = im.convert("RGB").resize((W, H)).filter(ImageFilter.GaussianBlur(40)); bg = Image.eval(bg, lambda v: int(v * 0.55)); canvas.paste(bg, (0, 0))
        scale = min((W - 160) / im.width, (H * 0.56) / im.height); fg = im.resize((int(im.width * scale), int(im.height * scale)), Image.LANCZOS)
        if fg.mode == "RGBA" and src.endswith(".png"):
            card = Image.new("RGBA", (fg.width + 80, fg.height + 80), (255, 255, 255, 235)); card.alpha_composite(fg, (40, 40)); fg = card
        canvas.paste(fg, ((W - fg.width) // 2, (H - fg.height) // 2 - 80), fg if fg.mode == "RGBA" else None)
    # vignette
    vg = Image.new("L", (W, H), 0); dv = ImageDraw.Draw(vg); dv.ellipse((-200, -100, W + 200, H + 100), fill=255); vg = vg.filter(ImageFilter.GaussianBlur(220))
    dark = Image.new("RGB", (W, H), (0, 0, 0)); canvas = Image.composite(canvas, dark, vg.point(lambda v: 110 + v * 145 // 255))
    if title:
        try: font = ImageFont.truetype(FONT, 64)
        except Exception: font = ImageFont.load_default()
        d = ImageDraw.Draw(canvas); lines = textwrap.wrap(title, 22)[:2]; y = 180
        for ln in lines:
            bbox = d.textbbox((0, 0), ln, font=font); tw = bbox[2] - bbox[0]
            d.rectangle(((W - tw) // 2 - 24, y - 12, (W + tw) // 2 + 24, y + 80), fill=(0, 0, 0, 160))
            d.text(((W - tw) // 2, y), ln, font=font, fill=(255, 255, 255)); y += 96
        d.rectangle((W // 2 - 60, y + 4, W // 2 + 60, y + 10), fill=accent)
    canvas.save(out, "JPEG", quality=90)


async def scenes(ctx, *, script_from: str = "script", dry_run: bool = True, **_):
    """One frame per beat. Sources, in order of preference: the beat's own image, the listing mockups,
    the design files, an AI b-roll still (if images are on), else a typographic card."""
    sc = ctx.get(script_from) or {}; beats = sc.get("beats") or [{"line": sc.get("voiceover", "")}]
    d = OUT / ctx["run_id"]; d.mkdir(parents=True, exist_ok=True)
    pool = list((ctx.get("assets") or {}).get("images") or []) + list((ctx.get("clip_order") or {}).get("images") or [])
    listing = ctx.get("listing") or {}
    if not listing and sc.get("kind") == "product" and ctx.get("_ledger") is not None:
        listing = latest_assets_from_listing(ctx["_ledger"])
    for m in (listing.get("mockups") or [])[:4]: pool.append(m)
    for f in (listing.get("designs") or [])[:2]: pool.append(f)
    # fetch remote mockups to disk
    local = []
    for i, p in enumerate(pool):
        if str(p).startswith("http"):
            try:
                import httpx
                r = httpx.get(p, timeout=30); lp = d / f"asset_{i}.jpg"; lp.write_bytes(r.content); local.append(str(lp))
            except Exception: pass
        else: local.append(str(p))
    frames = []; cost = 0.0
    for i, b in enumerate(beats):
        src = local[i % len(local)] if local else None
        if not src and not dry_run and config.IMAGE_API_KEY and config.IMAGE_PROVIDER != "none" and b.get("visual"):
            try:
                import httpx
                r = httpx.post("https://api.openai.com/v1/images/generations", headers={"Authorization": f"Bearer {config.IMAGE_API_KEY}"},
                               json={"model": "gpt-image-1", "prompt": b["visual"] + " Cinematic vertical photo, soft light, no text.", "n": 1, "size": "1024x1536", "quality": "low"}, timeout=120)
                if r.status_code == 200:
                    src = str(d / f"broll_{i}.png"); Path(src).write_bytes(base64.b64decode(r.json()["data"][0]["b64_json"])); cost += 0.02
            except Exception: pass
        out = d / f"scene_{i:02d}.jpg"
        _compose_frame(src, out, title=b.get("title") if i == 0 else None, fallback_text=None if src else b.get("line"), seed=i + len(ctx["run_id"]))
        frames.append(str(out))
    return {"frames": frames, "cost": round(cost, 3), "summary": f"{len(frames)} scene(s) composed" + (f" from {len(local)} product image(s)" if local else "")}


# ── 3. captions ──────────────────────────────────────────────────────────
def _ass(words, duration, path: Path, text_fallback: str):
    """Karaoke-style captions: 3–4 words per card, big, centred low, each word brightening as it is spoken."""
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,DejaVu Sans,78,&H00FFFFFF,&H0073FF3D,&H00000000,&H96000000,-1,0,0,0,100,100,1,0,1,6,2,2,60,60,420,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    def ts(t): h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60; return f"{h}:{m:02d}:{s:05.2f}"
    lines = []
    if words:
        chunk = []
        for w in words:
            chunk.append(w)
            if len(chunk) >= 4 or w["w"].strip().endswith((".", "!", "?", ",")):
                lines.append(chunk); chunk = []
        if chunk: lines.append(chunk)
        for ch in lines:
            s, e = ch[0]["s"], ch[-1]["e"] + 0.08
            parts = []
            for w in ch:
                k = max(1, int((w["e"] - w["s"]) * 100)); parts.append(f"{{\\kf{k}}}{w['w'].strip().upper()}")
            head += f"Dialogue: 0,{ts(s)},{ts(e)},Cap,,0,0,0,,{{\\fad(60,60)}}{' '.join(parts)}\n"
    else:
        ws = text_fallback.split(); n = max(1, len(ws) // 4); per = duration / n
        for i in range(n):
            s, e = i * per, (i + 1) * per
            head += f"Dialogue: 0,{ts(s)},{ts(e)},Cap,,0,0,0,,{{\\fad(60,60)}}{' '.join(ws[i*4:(i+1)*4]).upper()}\n"
    path.write_text(head, encoding="utf-8")


# ── 4. render ────────────────────────────────────────────────────────────
async def render(ctx, *, dry_run: bool = True, **_):
    if not _have_ffmpeg(): return {"summary": "ffmpeg missing", "incident": INSTALL_HINT, "cost": 0.0}
    vo = ctx.get("voiceover") or {}; sc = ctx.get("scenes") or {}; script = ctx.get("script") or {}
    d = OUT / ctx["run_id"]; d.mkdir(parents=True, exist_ok=True); out = d / "short.mp4"
    frames = sc.get("frames") or []; dur = float(vo.get("duration") or 15)
    if not frames:
        _compose_frame(None, d / "scene_00.jpg", title=script.get("title") or "Constantinople Station"); frames = [str(d / "scene_00.jpg")]
    n = len(frames); per = max(1.5, dur / n); xf = min(0.5, per / 4)
    _ass(vo.get("words"), dur, d / "captions.ass", script.get("voiceover") or " ".join(b.get("line", "") for b in script.get("beats", [])))
    # build filtergraph: each frame → Ken Burns clip of `per` seconds; chain with xfade
    inputs = []; filt = []
    for i, f in enumerate(frames):
        inputs += ["-loop", "1", "-t", f"{per + xf:.2f}", "-i", f]
        zoom_in = (i % 2 == 0)
        z = "min(zoom+0.0009,1.14)" if zoom_in else "if(eq(on,1),1.14,max(zoom-0.0009,1.0))"
        filt.append(f"[{i}:v]scale={W*2}:{H*2},zoompan=z='{z}':d={int((per+xf)*FPS)}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS},setsar=1,format=yuv420p[v{i}]")
    chain = "[v0]"; off = per - xf
    for i in range(1, n):
        filt.append(f"{chain}[v{i}]xfade=transition=fade:duration={xf:.2f}:offset={off:.2f}[x{i}]"); chain = f"[x{i}]"; off += per
    sub = str(d / "captions.ass").replace("\\", "/").replace(":", "\\:")
    filt.append(f"{chain}subtitles='{sub}',fade=t=in:st=0:d=0.4,fade=t=out:st={max(0.1,dur-0.5):.2f}:d=0.5[vout]")
    # audio: voice (+ optional music bed, ducked)
    a_in = ["-i", vo["file"]] if vo.get("file") else ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    music = None
    if MUSIC_DIR.exists():
        tracks = [p for p in MUSIC_DIR.glob("*.mp3")]
        if tracks: music = str(random.choice(tracks))
    if music:
        a_in += ["-stream_loop", "-1", "-i", music]
        filt.append(f"[{n}:a]aformat=sample_rates=48000:channel_layouts=stereo,loudnorm=I=-16:TP=-1.5[vo];[{n+1}:a]aformat=sample_rates=48000:channel_layouts=stereo,volume=0.18,atrim=0:{dur:.2f}[mu];[vo][mu]sidechaincompress=threshold=0.05:ratio=6:attack=20:release=300[duck];[duck]atrim=0:{dur:.2f}[aout]")
    else:
        filt.append(f"[{n}:a]aformat=sample_rates=48000:channel_layouts=stereo,loudnorm=I=-16:TP=-1.5,atrim=0:{dur:.2f}[aout]")
    try:
        _ffmpeg(*inputs, *a_in, "-filter_complex", ";".join(filt), "-map", "[vout]", "-map", "[aout]", "-t", f"{dur:.2f}", "-r", str(FPS), "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out))
        _ffmpeg("-ss", f"{min(1.0, dur/3):.2f}", "-i", str(out), "-frames:v", "1", "-q:v", "3", str(d / "thumb.jpg"))
    except Exception as e:
        return {"summary": "render failed", "incident": f"Render failed · {str(e)[:160]}", "cost": 0.0}
    size = out.stat().st_size / 1e6
    return {"file": str(out), "thumb": str(d / "thumb.jpg"), "duration": dur, "size_mb": round(size, 1), "cost": 0.0,
            "summary": f"rendered {dur:.0f}s · {n} scenes · captions {'word-timed' if vo.get('words') else 'estimated'} · {size:.1f} MB"}


async def package(ctx, *, dry_run: bool = True, **_):
    """Deliverable folder for a client order: the mp4, the thumbnail, the script and a caption text."""
    r = ctx.get("render") or {}; sc = ctx.get("script") or {}
    if not r.get("file"): return {"summary": "nothing to package", "cost": 0.0}
    dest = config.ROOT / "output" / "deliveries" / ctx["run_id"]; dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(r["file"], dest / "short.mp4")
    if r.get("thumb"): shutil.copy(r["thumb"], dest / "thumb.jpg")
    (dest / "script.txt").write_text(sc.get("voiceover", "") + "\n\n" + "\n".join(f"- {b.get('line','')}" for b in sc.get("beats", [])))
    (dest / "caption.txt").write_text((sc.get("caption") or sc.get("title") or "") + "\n" + " ".join("#" + h.strip("#") for h in sc.get("hashtags", [])))
    return {"folder": str(dest), "cost": 0.0, "summary": f"packaged in {dest.name}"}


def latest_assets_from_listing(L) -> dict:
    """The newest listing's mockups and designs, for the Clip Forge's product shorts."""
    arts = L.artifacts(kind_filter="listing", limit=1)
    if not arts: return {}
    p = arts[0]["payload"]; mb = p.get("mockup_build") or {}; dd = p.get("design_draft") or {}; ld = p.get("listing_draft") or {}
    return {"title": arts[0]["title"], "mockups": mb.get("mockups") or [], "designs": dd.get("files") or [], "description": ld.get("description", ""), "price": ld.get("price"), "concept": (p.get("trend_scan") or {}).get("concept")}
