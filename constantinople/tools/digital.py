"""Digital products: printable wall-art sets and colouring-page packs. No print cost, instant delivery,
~95% margin. The station renders the set, builds print-ready files at the sizes buyers expect, composes a
framed mockup for the listing photo, writes the copy, and either lists it on Etsy (once the API key has
listings_w) or hands the finished pack to the bridge for a one-click manual listing."""
import base64, io, json, random, shutil, zipfile
from pathlib import Path
from .. import config

OUT = config.ROOT / "output" / "digital"
SIZES_IN = {"8x10": (8, 10), "11x14": (11, 14), "16x20": (16, 20), "A4": (8.27, 11.69)}
DPI = 300


def _gen(prompt: str, size: str = "1024x1536", quality: str = "high") -> bytes | None:
    import httpx
    r = httpx.post("https://api.openai.com/v1/images/generations", headers={"Authorization": f"Bearer {config.IMAGE_API_KEY}"},
                   json={"model": "gpt-image-1", "prompt": prompt, "n": 1, "size": size, "quality": quality, "background": "opaque", "output_format": "png"}, timeout=240)
    return base64.b64decode(r.json()["data"][0]["b64_json"]) if r.status_code == 200 else None


def _placeholder(w, h, seed):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (w, h), (240, 234, 222)); d = ImageDraw.Draw(im); r = random.Random(seed)
    for _ in range(6):
        x, y, rad = r.randint(0, w), r.randint(0, h), r.randint(80, 400); d.ellipse((x - rad, y - rad, x + rad, y + rad), fill=(r.randint(120, 200), r.randint(120, 180), r.randint(100, 160)))
    return im


def _fit(im, w_in, h_in):
    """Resize + centre-crop to a print size at 300 dpi."""
    from PIL import Image
    W, H = int(w_in * DPI), int(h_in * DPI)
    s = max(W / im.width, H / im.height); im2 = im.resize((max(W, int(im.width * s)), max(H, int(im.height * s))), Image.LANCZOS)
    x = (im2.width - W) // 2; y = (im2.height - H) // 2
    return im2.crop((x, y, x + W, y + H))


async def render(ctx, *, dry_run: bool = True, **_):
    """Make the images for the pack: 3 coordinated pieces for a wall-art set, 8 pages for a colouring pack."""
    from PIL import Image
    b = ctx.get("digital_brief") or {}; kind = b.get("kind", "wall_art_set"); prompts = b.get("prompts") or []
    d = OUT / ctx["run_id"]; d.mkdir(parents=True, exist_ok=True)
    n = 8 if kind == "coloring_pages" else 3
    files = []; cost = 0.0
    for i in range(n):
        p = prompts[i] if i < len(prompts) else (prompts[-1] if prompts else b.get("theme", "soft watercolour botanical"))
        if kind == "coloring_pages":
            p = p + " Clean black line art on pure white, no shading, no grey, no text, printable colouring page, bold even lines, every region closed."
        else:
            p = p + " Full-bleed wall art, complete composition filling the canvas, print quality, no text, no watermark, no frame, no border."
        raw = None if (dry_run or not config.IMAGE_API_KEY) else _gen(p)
        if raw: im = Image.open(io.BytesIO(raw)).convert("RGB"); cost += 0.08
        else: im = _placeholder(1024, 1536, i + len(ctx["run_id"]))
        if kind == "coloring_pages":
            im = im.convert("L").point(lambda v: 255 if v > 150 else 0).convert("RGB")   # force crisp black/white
        f = d / f"piece_{i+1:02d}.png"; im.save(f); files.append(str(f))
    return {"files": files, "kind": kind, "cost": round(cost, 2), "summary": f"{len(files)} {'colouring pages' if kind == 'coloring_pages' else 'wall-art pieces'} rendered"}


async def package(ctx, *, dry_run: bool = True, **_):
    """Print-ready files: for wall art, each piece at 8x10 / 11x14 / 16x20 / A4 as JPG + one PDF per size; for
    colouring pages, US-Letter PDF + PNGs. Zipped, with a README. Plus a framed mockup for the listing photo."""
    from PIL import Image, ImageDraw, ImageFont
    r = ctx.get("render") or {}; files = r.get("files") or []; kind = r.get("kind", "wall_art_set")
    if not files: return {"summary": "nothing to package", "incident": "Digital pack has no images", "cost": 0.0}
    d = OUT / ctx["run_id"]; pack = d / "pack"; pack.mkdir(exist_ok=True)
    made = []
    if kind == "coloring_pages":
        pages = [Image.open(f).convert("RGB") for f in files]
        pages = [_fit(p, 8.5, 11) for p in pages]
        pdf = pack / "coloring-pages-letter.pdf"; pages[0].save(pdf, "PDF", resolution=DPI, save_all=True, append_images=pages[1:]); made.append(str(pdf))
        for i, p in enumerate(pages):
            f = pack / f"page-{i+1:02d}.png"; p.save(f, dpi=(DPI, DPI)); made.append(str(f))
    else:
        for i, f in enumerate(files):
            im = Image.open(f).convert("RGB")
            for name, (w_in, h_in) in SIZES_IN.items():
                out = pack / f"print-{i+1}-{name}.jpg"; _fit(im, w_in, h_in).save(out, "JPEG", quality=92, dpi=(DPI, DPI)); made.append(str(out))
        for name, (w_in, h_in) in SIZES_IN.items():
            pages = [_fit(Image.open(f).convert("RGB"), w_in, h_in) for f in files]
            pdf = pack / f"set-{name}.pdf"; pages[0].save(pdf, "PDF", resolution=DPI, save_all=True, append_images=pages[1:]); made.append(str(pdf))
    (pack / "README.txt").write_text("Thank you for your purchase!\n\nThese are digital files; nothing will be shipped. Print at home or at any print shop at the size you bought (files are 300 dpi).\nPersonal use only; please do not resell or redistribute the files.\n\nDesign created with AI tools from our own original prompts.\n")
    zpath = d / "pack.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in made + [str(pack / "README.txt")]: z.write(f, Path(f).name)
    # mockup: a framed print (or a fan of pages) on a soft wall
    wall = Image.new("RGB", (2000, 2000), (235, 229, 218)); dr = ImageDraw.Draw(wall)
    dr.rectangle((0, 1500, 2000, 2000), fill=(214, 200, 182))
    if kind == "coloring_pages":
        for i, f in enumerate(files[:3]):
            pg = _fit(Image.open(f).convert("RGB"), 8.5, 11).resize((640, 828)); x = 380 + i * 300; y = 420 + i * 60
            dr.rectangle((x - 6, y - 6, x + 646, y + 834), fill=(200, 194, 184)); wall.paste(pg, (x, y))
    else:
        n = len(files); fw = 520; gap = 90; x0 = (2000 - (n * fw + (n - 1) * gap)) // 2
        for i, f in enumerate(files):
            art = _fit(Image.open(f).convert("RGB"), 8, 10).resize((fw, int(fw * 1.25))); x = x0 + i * (fw + gap); y = 520
            dr.rectangle((x - 50, y - 50, x + fw + 50, y + art.height + 50), fill=(40, 36, 34)); dr.rectangle((x - 28, y - 28, x + fw + 28, y + art.height + 28), fill=(250, 248, 244)); wall.paste(art, (x, y))
    mock = d / "mockup.jpg"; wall.save(mock, "JPEG", quality=90)
    return {"zip": str(zpath), "files": made, "mockup": str(mock), "kind": kind, "cost": 0.0, "summary": f"pack ready · {len(made)} files · mockup composed"}


async def publish(ctx, *, dry_run: bool = True, **_):
    """List on Etsy as a digital download when the API allows (listings_w); otherwise hand the pack and the
    copy to the bridge so the Creator can list it in two minutes."""
    pk = ctx.get("package") or {}; ld = ctx.get("digital_listing") or {}
    if not pk.get("zip"): return {"summary": "nothing to publish", "cost": 0.0}
    dest = config.ROOT / "output" / "digital" / "ready" / ctx["run_id"]; dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(pk["zip"], dest / "pack.zip"); shutil.copy(pk["mockup"], dest / "mockup.jpg")
    (dest / "listing.json").write_text(json.dumps(ld, indent=2))
    draft = f"{ld.get('title','')}\n\nPrice: ${ld.get('price', 4.95)}\nTags: {', '.join(ld.get('tags', []))}\n\n{ld.get('description','')}"
    if config.ETSY_ACCESS_TOKEN and config.ETSY_SHOP_ID and not dry_run:
        try:
            from . import etsy
            res = await etsy.create_digital_listing(ctx, title=ld.get("title", ""), description=ld.get("description", ""), tags=ld.get("tags", []), price=float(ld.get("price", 4.95)), files=[pk["zip"]], image=pk["mockup"])
            if res.get("listing_id"):
                return {"listing_id": res["listing_id"], "url": res.get("url"), "cost": 0.20, "summary": f"listed on Etsy as a digital download · {ld.get('title','')[:60]}"}
            draft = "(Etsy API could not list it: " + str(res.get("error", ""))[:100] + ")\n\n" + draft
        except Exception as e:
            draft = f"(Etsy API error {type(e).__name__})\n\n" + draft
    return {"folder": str(dest), "draft": draft, "image": pk["mockup"], "cost": 0.0, "summary": f"pack ready for listing · {ld.get('title','')[:60]} (sent to the bridge)"}
