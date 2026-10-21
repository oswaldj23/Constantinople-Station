"""The Press: upload-ready coloring books for Amazon KDP. One book a week: a themed set of 40 line-art pages
as a print interior PDF (8.5x11, single-sided with blank backs so markers don't bleed through), a full-wrap
cover PDF sized to KDP's spec for the page count, and the metadata KDP asks for (title, subtitle, description,
7 keywords, categories, AI disclosure). KDP has no API, so the Creator uploads the package (10–15 minutes);
the book then earns royalties for years. The same pages double as an Etsy digital pack."""
import io, json, math, random, shutil, zipfile
from pathlib import Path
from .. import config

OUT = config.ROOT / "output" / "press"
PAGE_W, PAGE_H = 8.5, 11.0          # inches, KDP standard for coloring books
DPI = 300
PAPER_FACTOR = 0.002252              # KDP white paper: spine inches per page
BLEED = 0.125
FONT_B = "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf"
FONT_R = "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"


def _gen(prompt: str) -> bytes | None:
    import base64, httpx
    r = httpx.post("https://api.openai.com/v1/images/generations", headers={"Authorization": f"Bearer {config.IMAGE_API_KEY}"},
                   json={"model": "gpt-image-1", "prompt": prompt, "n": 1, "size": "1024x1536", "quality": "medium", "background": "opaque", "output_format": "png"}, timeout=240)
    return base64.b64decode(r.json()["data"][0]["b64_json"]) if r.status_code == 200 else None


def _lineart(im):
    """Force crisp black-on-white line art: grayscale, threshold, remove grey, slight thickening."""
    from PIL import Image, ImageFilter, ImageOps
    g = ImageOps.autocontrast(im.convert("L"))
    bw = g.point(lambda v: 0 if v < 140 else 255).filter(ImageFilter.MinFilter(3)).point(lambda v: 0 if v < 128 else 255)
    return bw.convert("RGB")


def _placeholder_page(seed: int):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (1024, 1536), "white"); d = ImageDraw.Draw(im); r = random.Random(seed)
    for _ in range(14):
        x, y, rad = r.randint(100, 924), r.randint(100, 1436), r.randint(40, 160); d.ellipse((x - rad, y - rad, x + rad, y + rad), outline="black", width=6)
    return im


def _fit_page(im):
    from PIL import Image
    W, H = int(PAGE_W * DPI), int(PAGE_H * DPI)
    margin = int(0.5 * DPI)   # KDP wants ≥0.25" margins; 0.5" keeps art off the gutter
    box_w, box_h = W - 2 * margin, H - 2 * margin
    s = min(box_w / im.width, box_h / im.height); art = im.resize((int(im.width * s), int(im.height * s)), Image.LANCZOS)
    page = Image.new("RGB", (W, H), "white"); page.paste(art, ((W - art.width) // 2, (H - art.height) // 2))
    return page


async def render_pages(ctx, *, pages: int = 40, dry_run: bool = True, **_):
    b = ctx.get("book_brief") or {}; prompts = b.get("page_prompts") or []
    d = OUT / ctx["run_id"]; d.mkdir(parents=True, exist_ok=True)
    from PIL import Image
    files = []; cost = 0.0; style = b.get("line_style") or "clean bold outlines, medium detail, no shading"
    for i in range(pages):
        pr = prompts[i % max(1, len(prompts))] if prompts else b.get("theme", "cute animals")
        prompt = f"Coloring book page: {pr}. {style}. Pure black line art on a pure white background, no grey, no shading, no text, no signature, every shape closed, generous white space, suitable for crayons and markers, portrait orientation."
        raw = None if (dry_run or not config.IMAGE_API_KEY) else _gen(prompt)
        im = Image.open(io.BytesIO(raw)).convert("RGB") if raw else _placeholder_page(i + len(ctx["run_id"]))
        if raw: cost += 0.04
        im = _lineart(im)
        f = d / f"page_{i+1:02d}.png"; im.save(f); files.append(str(f))
    return {"files": files, "cost": round(cost, 2), "summary": f"{len(files)} line-art pages rendered"}


async def build_book(ctx, *, dry_run: bool = True, **_):
    """Interior PDF (each art page followed by a blank page), full-wrap cover PDF, metadata, zip."""
    from PIL import Image, ImageDraw, ImageFont
    b = ctx.get("book_brief") or {}; r = ctx.get("render_pages") or {}; files = r.get("files") or []
    if not files: return {"summary": "no pages", "incident": "Press: no pages rendered", "cost": 0.0}
    d = OUT / ctx["run_id"]; W, H = int(PAGE_W * DPI), int(PAGE_H * DPI)
    blank = Image.new("RGB", (W, H), "white")
    title_page = Image.new("RGB", (W, H), "white"); td = ImageDraw.Draw(title_page)
    try: f_t = ImageFont.truetype(FONT_B, 150); f_s = ImageFont.truetype(FONT_R, 70)
    except Exception: f_t = f_s = ImageFont.load_default()
    title = b.get("title", "Coloring Book"); sub = b.get("subtitle", "")
    tw = td.textbbox((0, 0), title, font=f_t)[2]; td.text(((W - tw) // 2, H // 2 - 200), title, font=f_t, fill="black")
    if sub: sw = td.textbbox((0, 0), sub, font=f_s)[2]; td.text(((W - sw) // 2, H // 2), sub, font=f_s, fill="black")
    copy_page = Image.new("RGB", (W, H), "white"); cd = ImageDraw.Draw(copy_page)
    cd.text((int(0.75 * DPI), H - int(1.6 * DPI)), f"© {__import__('datetime').date.today().year} {config.STATION_NAME.split()[0]} Press. All rights reserved.\nThis book belongs to: ________________________\n\nIllustrations created with AI tools from our own original prompts and finished by hand.", font=f_s, fill="black", spacing=18)
    pages = [title_page, copy_page]
    for f in files:
        pages.append(_fit_page(Image.open(f).convert("RGB"))); pages.append(blank.copy())
    interior = d / "interior.pdf"; pages[0].save(interior, "PDF", resolution=DPI, save_all=True, append_images=pages[1:])
    n_pages = len(pages)
    # cover: full wrap, KDP spec: width = bleed + back + spine + front + bleed ; height = bleed + 11 + bleed
    spine = n_pages * PAPER_FACTOR
    cw, chh = int((2 * BLEED + 2 * PAGE_W + spine) * DPI), int((2 * BLEED + PAGE_H) * DPI)
    palette = random.Random(len(ctx["run_id"])).choice([((246, 196, 60), (30, 30, 30)), ((120, 180, 220), (20, 30, 50)), ((235, 120, 110), (40, 20, 20)), ((140, 200, 150), (20, 40, 30)), ((200, 160, 220), (40, 20, 50))])
    cover = Image.new("RGB", (cw, chh), palette[0]); c = ImageDraw.Draw(cover)
    front_x = int((BLEED + PAGE_W + spine) * DPI)
    # front: title + a framed sample page
    try: f_c = ImageFont.truetype(FONT_B, 190); f_cs = ImageFont.truetype(FONT_R, 80); f_sp = ImageFont.truetype(FONT_B, 60)
    except Exception: f_c = f_cs = f_sp = ImageFont.load_default()
    import textwrap
    y = int(0.9 * DPI)
    for ln in textwrap.wrap(title, 16)[:3]:
        lw = c.textbbox((0, 0), ln, font=f_c)[2]; c.text((front_x + (int(PAGE_W * DPI) - lw) // 2, y), ln, font=f_c, fill=palette[1]); y += 230
    if sub:
        lw = c.textbbox((0, 0), sub, font=f_cs)[2]; c.text((front_x + (int(PAGE_W * DPI) - lw) // 2, y + 20), sub, font=f_cs, fill=palette[1])
    sample = Image.open(files[0]).convert("RGB"); sh = int(5.4 * DPI); s = sh / sample.height; sample = sample.resize((int(sample.width * s), sh))
    sx = front_x + (int(PAGE_W * DPI) - sample.width) // 2; sy = int(PAGE_H * DPI) - sh - int(0.8 * DPI)
    c.rectangle((sx - 40, sy - 40, sx + sample.width + 40, sy + sample.height + 40), fill="white"); cover.paste(sample, (sx, sy))
    # spine text (only if ≥ 79 pages per KDP; otherwise leave blank)
    if n_pages >= 79:
        sp = Image.new("RGB", (int(PAGE_H * DPI), int(spine * DPI)), palette[0]); spd = ImageDraw.Draw(sp); spd.text((int(0.5 * DPI), int(spine * DPI) // 2 - 30), title, font=f_sp, fill=palette[1])
        cover.paste(sp.rotate(-90, expand=True), (int((BLEED + PAGE_W) * DPI), int(BLEED * DPI)))
    # back: blurb, leave the lower-right 2x1.2" clear for KDP's barcode
    bx = int((BLEED + 0.7) * DPI); by = int(1.2 * DPI)
    for ln in textwrap.wrap(b.get("back_blurb") or f"{len(files)} original pages to color.", 42)[:14]:
        c.text((bx, by), ln, font=f_cs, fill=palette[1]); by += 100
    cover_pdf = d / "cover.pdf"; cover.save(cover_pdf, "PDF", resolution=DPI)
    meta = {"title": title, "subtitle": sub, "author": b.get("author") or f"{config.STATION_NAME.split()[0]} Press", "description": b.get("description", ""), "keywords": (b.get("keywords") or [])[:7],
            "categories": b.get("categories") or ["Crafts, Hobbies & Home > Crafts & Hobbies > Coloring Books for Grown-Ups"], "trim": "8.5 x 11 in", "pages": n_pages, "paper": "white", "ink": "black & white",
            "ai_disclosure": "Images: AI-generated, with some editing. Text: none / human-written.", "suggested_price_usd": b.get("price", 7.99), "spine_inches": round(spine, 3), "cover_size_inches": [round(cw / DPI, 3), round(chh / DPI, 3)]}
    (d / "kdp_metadata.json").write_text(json.dumps(meta, indent=2))
    (d / "UPLOAD_STEPS.txt").write_text(f"""KDP upload (kdp.amazon.com → Create → Paperback):
1. Details: title / subtitle / author / description / keywords / categories from kdp_metadata.json. Tick "AI-generated content" and paste the disclosure line.
2. Content: trim 8.5 x 11, bleed OFF (interior has margins), paper white, ink black & white. Upload interior.pdf. Upload cover.pdf as a print-ready cover (not Cover Creator).
3. Launch previewer, check the cover wraps; approve.
4. Pricing: ${meta['suggested_price_usd']} USD, 60% royalty, expanded distribution off. Publish.
Royalty per copy at that price ≈ $2.5–3.5 after Amazon's print cost.
""")
    z = d / "kdp_package.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in (interior, cover_pdf, d / "kdp_metadata.json", d / "UPLOAD_STEPS.txt"): zf.write(f, f.name)
    thumb = cover.crop((front_x, 0, cw, chh)).resize((600, int(600 * chh / (cw - front_x)))); thumb.save(d / "cover_front.jpg", quality=88)
    ready = config.ROOT / "output" / "press" / "ready"; ready.mkdir(parents=True, exist_ok=True); shutil.copy(z, ready / f"{ctx['run_id']}.zip")
    return {"zip": str(z), "url": f"/output/press/{ctx['run_id']}/kdp_package.zip", "cover": str(d / "cover_front.jpg"), "pages": n_pages, "spine": round(spine, 3), "meta": meta, "cost": 0.0,
            "summary": f"book built · {n_pages} pages · spine {spine:.3f} in · cover {cw/DPI:.2f}x{chh/DPI:.2f} in"}


async def handoff(ctx, *, dry_run: bool = True, **_):
    bb = ctx.get("build_book") or {}; m = bb.get("meta") or {}
    if not bb.get("zip"): return {"summary": "nothing to hand off", "cost": 0.0}
    draft = f"📚 KDP book ready: {m.get('title')}\n{m.get('subtitle','')}\n\nDownload: {config.PUBLIC_URL or 'your dashboard address'}{bb['url']}\nUpload steps are inside (10–15 min). Suggested price ${m.get('suggested_price_usd')}."
    return {"draft": draft, "image": bb.get("cover"), "url": bb["url"], "cost": 0.0, "summary": f"package sent to the bridge · {m.get('title')}"}
