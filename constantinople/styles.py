"""The design style library. A shop that only makes one kind of design only reaches one kind of buyer; most
print-on-demand sales on Etsy are text designs. Research assigns a style per listing — rotating through all of
them until the shop has sales data, then weighting toward what sells — and Treasury keeps score per style."""
import json, os, random

STYLES = {
    "typo_saying":   {"name": "Bold typographic saying", "text": True,  "sells": "the biggest POD category: a funny or proud 4–6 word line for an identity (dog mom, nurse, teacher, gym, coffee)",
                      "rules": "Bold condensed sans-serif or chunky serif lettering, 2–4 lines stacked, tight kerning, one accent colour, no illustration or one tiny icon. The text IS the design."},
    "retro_varsity": {"name": "Retro varsity / collegiate", "text": True, "sells": "cities, states, 'Est.' years, clubs, sports moms, 'Mama' — a staple that sells year-round",
                      "rules": "Arched collegiate lettering with a thick outline/shadow, 1970s palette (cream, mustard, rust, navy), optional small banner or year. Slight vintage texture."},
    "retro_sunset":  {"name": "Retro sunset stripes", "text": True, "sells": "places, hobbies (hiking, surfing, camping), 'summer' and travel gifts",
                      "rules": "Horizontal sunset stripe gradient in 70s colours behind a simple silhouette (mountains, pines, waves, a van), rounded retro lettering under it."},
    "vintage_badge": {"name": "Distressed vintage badge", "text": True, "sells": "dad gifts, trades, outdoors, 'Since YEAR', fishing/grilling/woodworking humour",
                      "rules": "Circular or shield emblem, two-tone, distressed grunge texture, text on an arc around a central icon, old-print feel."},
    "groovy":        {"name": "Groovy 70s lettering", "text": True, "sells": "'in my ___ era', 'mama', 'bride', teacher and nurse crowd, trend-driven",
                      "rules": "Wavy bubbly 1970s psychedelic lettering, warm colours (orange, pink, mustard, brown), optional daisy or smiley, lots of flow."},
    "script_quote":  {"name": "Elegant script quote", "text": True, "sells": "faith, encouragement, wedding/bridesmaid, mom, grief and memorial gifts",
                      "rules": "A single line of elegant brush script with one small ornament (sprig, heart, line), one ink colour, generous spacing."},
    "kawaii":        {"name": "Cute kawaii character", "text": True, "sells": "cats, frogs, mushrooms, boba, cute food — young buyers, matching sets",
                      "rules": "One cute rounded character with simple dot eyes and blush, pastel palette, a very short phrase (1–3 words) under or around it."},
    "line_minimal":  {"name": "Minimalist line art", "text": False, "sells": "aesthetic buyers: single-line faces, cats, plants, moons, abstract shapes",
                      "rules": "One continuous or few-line drawing, single ink colour, no fill, no text, large negative space."},
    "watercolor":    {"name": "Soft watercolour", "text": False, "sells": "florals, animals, landscapes for gifts; mugs and totes especially",
                      "rules": "Loose watercolour subject with soft edges and bleeds, 3–5 muted colours, no text, isolated on transparent."},
    "botanical":     {"name": "Hand-drawn botanical", "text": False, "sells": "cottagecore and plant-lover gifts; our original style",
                      "rules": "Flat hand-drawn illustration, two to three colours (cream, sage, rust), lots of negative space, no text."},
    "pet_humor":     {"name": "Pet humour", "text": True, "sells": "dog/cat owners buying for themselves and each other — one of Etsy's deepest niches",
                      "rules": "A simple cartoon dog or cat (no breed-specific likeness of a famous character) with a short funny line in bold rounded type."},
}
ORDER = [s.strip() for s in (os.getenv("DESIGN_STYLES") or ",".join(STYLES)).split(",") if s.strip() in STYLES] or list(STYLES)


def style_performance(L) -> dict:
    """Listings, sales and revenue per style, from the archive + sale events (same matching as listing_performance)."""
    try:
        from . import memory
        rows = memory.listing_performance(L)
    except Exception:
        rows = []
    per = {}
    for r in rows:
        st = r.get("style") or "botanical"
        d = per.setdefault(st, {"listings": 0, "sales": 0, "revenue": 0.0})
        d["listings"] += 1; d["sales"] += r.get("sales", 0); d["revenue"] += r.get("revenue", 0.0)
    for d in per.values(): d["revenue"] = round(d["revenue"], 2); d["sales_per_listing"] = round(d["sales"] / d["listings"], 2) if d["listings"] else 0
    return per


def next_style(L) -> str:
    """Rotate through every style until the shop has data (10+ listings and 3+ sales); then two picks in three
    go to the styles with the best sales per listing, one in three to the least-tried style."""
    try:
        n = L.db.execute("SELECT COUNT(*) c FROM artifacts WHERE kind='listing'").fetchone()["c"]
    except Exception:
        n = 0
    per = style_performance(L) if n >= 10 else {}
    total_sales = sum(d["sales"] for d in per.values())
    if per and total_sales >= 3:
        if n % 3 == 2:
            tried = {s: per.get(s, {}).get("listings", 0) for s in ORDER}
            return min(tried, key=tried.get)
        rnd = random.Random(n)
        weights = [0.2 + per.get(s, {}).get("sales_per_listing", 0) for s in ORDER]
        return rnd.choices(ORDER, weights=weights, k=1)[0]
    return ORDER[n % len(ORDER)]


def describe(style_id: str) -> str:
    s = STYLES.get(style_id, STYLES["botanical"])
    return f"{style_id} — {s['name']}. Rules: {s['rules']} Text in the design: {'YES, required' if s['text'] else 'NO text at all'}. Sells for: {s['sells']}"


def library_text() -> str:
    return "\n".join(f"- {k}: {v['name']} ({'text' if v['text'] else 'no text'}) — sells for: {v['sells']}" for k, v in STYLES.items())
