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
FOOTAGE_DIR = config.ROOT / "footage"        # drop YOUR OWN recorded gameplay / satisfying footage here (.mp4); random segments become backgrounds

# What kind of short this is decides the voice, the pacing, the length window and the background.
FORMATS = {
    "horror":  {"voice": "ash",   "speed": 0.97, "len": (45, 90),  "bg": "dark",   "accent": "&H005E4FFF",
                "instructions": "Low, calm, unsettling narrator telling a true-feeling scary story. Slow down at the reveal. Breathy pauses. Never shout."},
    "aita":    {"voice": "nova",  "speed": 1.06, "len": (45, 90),  "bg": "warm",   "accent": "&H0073FF3D",
                "instructions": "Conversational, slightly exasperated, like reading a confession out loud to a friend. Natural rhythm, light emphasis on the twist."},
    "revenge": {"voice": "echo",  "speed": 1.04, "len": (45, 90),  "bg": "warm",   "accent": "&H004DD2FF",
                "instructions": "Dry, confident storyteller with a smirk. Build to the payoff, land it flat."},
    "story":   {"voice": "coral", "speed": 1.04, "len": (40, 80),  "bg": "warm",   "accent": "&H00F0D945",
                "instructions": "Warm, candid story-time voice. Curious, a little amused, present tense energy."},
    "facts":   {"voice": "onyx",  "speed": 1.08, "len": (25, 50),  "bg": "cool",   "accent": "&H0073FF3D",
                "instructions": "Crisp documentary narrator. Short sentences, confident, no filler."},
    "product": {"voice": "onyx",  "speed": 1.04, "len": (15, 35),  "bg": "scenes", "accent": "&H0073FF3D",
                "instructions": "Warm, confident, unhurried narrator for a short product video. Natural pauses. No shouting."},
}
def fmt_of(sc: dict) -> dict:
    return FORMATS.get((sc or {}).get("format") or ("product" if (sc or {}).get("kind") == "product" else "story"), FORMATS["story"])
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
    F = fmt_of(sc)
    if dry_run or not config.IMAGE_API_KEY:
        # silent placeholder of a plausible length so timing code runs
        dur = max(8, min(90, len(text.split()) / 2.6))
        _ffmpeg("-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", f"{dur:.1f}", "-q:a", "9", str(mp3))
        return {"file": str(mp3), "duration": dur, "words": None, "cost": 0.0, "summary": f"voiceover placeholder · {dur:.0f}s"}
    import httpx
    voice = voice or sc.get("voice") or F["voice"] or config.TTS_VOICE
    async with httpx.AsyncClient(timeout=180) as c:
        r = await c.post("https://api.openai.com/v1/audio/speech", headers={"Authorization": f"Bearer {config.IMAGE_API_KEY}"},
                         json={"model": config.TTS_MODEL, "voice": voice, "input": text, "response_format": "mp3", "speed": F["speed"],
                               "instructions": F["instructions"]})
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
    if fmt_of(sc)["bg"] != "scenes":
        return {"frames": [], "cost": 0.0, "summary": "story format · background video instead of scenes"}
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


# ── 2b. background video (story formats) ────────────────────────────────
def _footage_segment(dur: float, out: Path, exclude: str | None = None) -> str | None:
    """A random slice of the Creator's own footage, cropped to 9:16. Returns the source name or None."""
    if not FOOTAGE_DIR.exists(): return None
    files = [p for p in FOOTAGE_DIR.iterdir() if p.suffix.lower() in (".mp4", ".mov", ".mkv", ".webm")]
    if not files: return None
    src = random.choice(files); total = _ffprobe_duration(src)
    if total < dur + 2:
        # too short: loop it
        _ffmpeg("-stream_loop", "-1", "-i", str(src), "-t", f"{dur:.2f}", "-an", "-vf", f"scale=-2:{H},crop={W}:{H},eq=brightness=-0.04,fps={FPS}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p", str(out))
    else:
        start = random.uniform(1, total - dur - 1)
        _ffmpeg("-ss", f"{start:.2f}", "-t", f"{dur:.2f}", "-i", str(src), "-an", "-vf", f"scale=-2:{H},crop={W}:{H},eq=brightness=-0.04,fps={FPS}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p", str(out))
    return src.name


def _procedural_bg(style: str, dur: float, out: Path):
    """Station-made motion backgrounds we own outright: a slow fractal dive for dark stories, a drifting
    colour field for warm ones, a cool version for facts. ~1x realtime to render."""
    if style == "dark":
        src = "mandelbrot=size=540x960:rate=30:maxiter=160:start_scale=3:end_scale=0.05:end_pts=800:inner=convergence:outer=normalized_iteration_count"
        vf = f"scale={W}:{H}:flags=lanczos,hue=H=t*0.12:s=0.55,eq=contrast=1.05:brightness=-0.22:gamma=0.85"
    elif style == "cool":
        src = "gradients=size=270x480:rate=30:speed=0.015:nb_colors=4:c0=#061a2b:c1=#0b3d4f:c2=#1f8c45:c3=#12233b:type=spiral"
        vf = f"scale={W}:{H}:flags=bicubic,gblur=sigma=30,hue=H=t*0.1,noise=alls=5:allf=t,eq=brightness=-0.08"
    else:
        src = "gradients=size=270x480:rate=30:speed=0.015:nb_colors=5:c0=#120f2b:c1=#3a1c71:c2=#b8336a:c3=#ff7a59:c4=#0b3d4f:type=spiral"
        vf = f"scale={W}:{H}:flags=bicubic,gblur=sigma=30,hue=H=t*0.15,noise=alls=6:allf=t,eq=brightness=-0.1:saturation=1.1"
    _ffmpeg("-f", "lavfi", "-i", src, "-t", f"{dur:.2f}", "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", str(out), timeout=900)


async def background(ctx, *, dry_run: bool = True, **_):
    """Pick the moving background for a story short: the Creator's own footage if any is in footage/, else a
    station-generated one. Product shorts use composed scenes instead and skip this."""
    sc = ctx.get("script") or {}; F = fmt_of(sc)
    if F["bg"] == "scenes": return {"file": None, "cost": 0.0, "summary": "product format · composed scenes"}
    if not _have_ffmpeg(): return {"summary": "ffmpeg missing", "incident": INSTALL_HINT, "cost": 0.0}
    vo = ctx.get("voiceover") or {}; dur = float(vo.get("duration") or 30) + 0.6
    d = OUT / ctx["run_id"]; d.mkdir(parents=True, exist_ok=True); out = d / "bg.mp4"
    try:
        name = _footage_segment(dur, out)
        if name: return {"file": str(out), "source": f"footage/{name}", "cost": 0.0, "summary": f"background: your footage ({name})"}
        _procedural_bg(F["bg"], dur, out)
        return {"file": str(out), "source": f"generated:{F['bg']}", "cost": 0.0, "summary": f"background: station-generated ({F['bg']}) · drop your own gameplay in footage/ to use it instead"}
    except Exception as e:
        return {"summary": "background failed", "incident": f"Background render failed · {str(e)[:160]}", "cost": 0.0}


# ── 3. captions ──────────────────────────────────────────────────────────
def _ass(words, duration, path: Path, text_fallback: str, title: str | None = None, accent: str = "&H0073FF3D", story: bool = False):
    """Karaoke-style captions: 3 words per card, big, centred, each word lighting up as it is spoken.
    Story formats get a title card (the hook) for the first seconds and captions in the middle of the frame."""
    marginv = 880 if story else 420
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,DejaVu Sans,72,&H00FFFFFF,{accent},&H00000000,&H96000000,-1,0,0,0,100,100,1,0,1,7,3,2,80,80,{marginv},1
Style: Title,DejaVu Sans,60,&H00FFFFFF,&H00FFFFFF,&H00000000,&HA0000000,-1,0,0,0,100,100,0,0,3,14,0,8,90,90,210,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    def ts(t): h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60; return f"{h}:{m:02d}:{s:05.2f}"
    lines = []
    if title:
        tw = textwrap.wrap(title, 24)[:3]
        head += f"Dialogue: 1,{ts(0)},{ts(min(4.5, duration))},Title,,0,0,0,,{{\\fad(120,300)}}{'\\N'.join(tw)}\n"
    if words:
        chunk = []
        for w in words:
            chunk.append(w)
            if len(chunk) >= 3 or w["w"].strip().endswith((".", "!", "?", ",")) or sum(len(x["w"]) for x in chunk) > 22:
                lines.append(chunk); chunk = []
        if chunk: lines.append(chunk)
        for ch in lines:
            s, e = ch[0]["s"], ch[-1]["e"] + 0.08
            parts = []
            for w in ch:
                k = max(1, int((w["e"] - w["s"]) * 100)); parts.append(f"{{\\kf{k}}}{w['w'].strip().upper()}")
            head += f"Dialogue: 0,{ts(s)},{ts(e)},Cap,,0,0,0,,{{\\fad(60,60)}}{' '.join(parts)}\n"
    else:
        ws = text_fallback.split(); n = max(1, len(ws) // 3); per = duration / n
        for i in range(n):
            s, e = i * per, (i + 1) * per
            head += f"Dialogue: 0,{ts(s)},{ts(e)},Cap,,0,0,0,,{{\\fad(60,60)}}{' '.join(ws[i*3:(i+1)*3]).upper()}\n"
    path.write_text(head, encoding="utf-8")


# ── 4. render ────────────────────────────────────────────────────────────
async def render(ctx, *, dry_run: bool = True, **_):
    if not _have_ffmpeg(): return {"summary": "ffmpeg missing", "incident": INSTALL_HINT, "cost": 0.0}
    vo = ctx.get("voiceover") or {}; sc = ctx.get("scenes") or {}; script = ctx.get("script") or {}
    d = OUT / ctx["run_id"]; d.mkdir(parents=True, exist_ok=True); out = d / "short.mp4"
    frames = sc.get("frames") or []; dur = float(vo.get("duration") or 15)
    F = fmt_of(script); bg = (ctx.get("background") or {}).get("file")
    story = F["bg"] != "scenes"
    if story and not bg:
        # no background step ran (or it failed quietly): make one now rather than falling back to a black card
        try: _procedural_bg(F["bg"], dur + 0.6, d / "bg.mp4"); bg = str(d / "bg.mp4")
        except Exception: bg = None
    if not frames and not bg:
        _compose_frame(None, d / "scene_00.jpg", title=script.get("title") or "Constantinople Station"); frames = [str(d / "scene_00.jpg")]
    _ass(vo.get("words"), dur, d / "captions.ass", script.get("voiceover") or " ".join(b.get("line", "") for b in script.get("beats", [])),
         title=(script.get("hook_card") or script.get("title")) if story else None, accent=F["accent"], story=story)
    sub = str(d / "captions.ass").replace("\\", "/").replace(":", "\\:")
    inputs = []; filt = []
    if bg:
        n = 1; inputs = ["-i", bg]
        filt.append(f"[0:v]scale={W}:{H},setsar=1,format=yuv420p,subtitles='{sub}',fade=t=in:st=0:d=0.4,fade=t=out:st={max(0.1,dur-0.5):.2f}:d=0.5[vout]")
    n = 1 if bg else len(frames); per = max(1.5, dur / n); xf = min(0.5, per / 4)
    # build filtergraph: each frame → Ken Burns clip of `per` seconds; chain with xfade
    for i, f in (enumerate(frames) if not bg else []):
        inputs += ["-loop", "1", "-t", f"{per + xf:.2f}", "-i", f]
        zoom_in = (i % 2 == 0)
        z = "min(zoom+0.0009,1.14)" if zoom_in else "if(eq(on,1),1.14,max(zoom-0.0009,1.0))"
        filt.append(f"[{i}:v]scale={W*2}:{H*2},zoompan=z='{z}':d={int((per+xf)*FPS)}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS},setsar=1,format=yuv420p[v{i}]")
    if not bg:
        chain = "[v0]"; off = per - xf
        for i in range(1, n):
            filt.append(f"{chain}[v{i}]xfade=transition=fade:duration={xf:.2f}:offset={off:.2f}[x{i}]"); chain = f"[x{i}]"; off += per
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
    return {"file": str(out), "thumb": str(d / "thumb.jpg"), "duration": dur, "size_mb": round(size, 1), "format": script.get("format") or ("product" if script.get("kind") == "product" else "story"), "cost": 0.0,
            "summary": f"rendered {dur:.0f}s · {'background video' if bg else str(n) + ' scenes'} · captions {'word-timed' if vo.get('words') else 'estimated'} · {size:.1f} MB"}


async def queue_part2(ctx, *, dry_run: bool = True, **_):
    """If REEL wrote a part two, hand it to the Forge's queue as a ready script so the next run renders it
    (the bay's `fanout: {part2_seeds: clips}` delivers it; the script step is skipped because the seed already has one)."""
    sc = ctx.get("script") or {}; p2 = sc.get("part2")
    if not p2 or not isinstance(p2, dict) or not p2.get("voiceover"): return {"part2_seeds": [], "cost": 0.0, "summary": "no part two"}
    seed = {"format": sc.get("format"), "genre": sc.get("genre"), "kind": sc.get("kind", "genre"), "title": p2.get("title") or (sc.get("title", "") + " · Part 2"),
            "hook_card": p2.get("hook_card") or "Part 2", "voiceover": p2["voiceover"], "beats": [{"line": p2["voiceover"]}], "caption": p2.get("caption") or (sc.get("caption", "") + " Part 2"),
            "hashtags": p2.get("hashtags") or sc.get("hashtags") or ["#shorts"], "part_of": ctx.get("run_id"), "summary": "part two script (queued)"}
    return {"part2_seeds": [seed], "cost": 0.0, "summary": "part two queued for the next run"}


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
