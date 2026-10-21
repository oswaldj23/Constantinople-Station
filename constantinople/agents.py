"""Agent steps: a named crew member (SCOUT, FORGE, MINT, HERALD…) runs a prompt against the model and
returns JSON. Every call is costed from token usage and written to the ledger by the workflow runner.

With no ANTHROPIC_API_KEY, or DRY_RUN=true, each prompt returns a canned, plausible result so the whole
station can be exercised without spending anything."""
import json, random, re
from pathlib import Path
from typing import Any

from . import config

DOCTRINE = (config.PROMPTS_DIR / "doctrine.md").read_text() if (config.PROMPTS_DIR / "doctrine.md").exists() else ""

_client = None
def _anthropic():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


def _load_prompt(name: str) -> str:
    p = config.PROMPTS_DIR / name
    return p.read_text() if p.exists() else name


def _fill(template: str, ctx: dict) -> str:
    """{{key}} substitution; nested keys with dots, missing keys become 'n/a'."""
    def get(path):
        cur: Any = ctx
        for part in path.split("."):
            if isinstance(cur, dict) and part in cur: cur = cur[part]
            else: return "n/a"
        return json.dumps(cur, indent=2) if isinstance(cur, (dict, list)) else str(cur)
    return re.sub(r"{{\s*([\w.]+)\s*}}", lambda m: get(m.group(1)), template)


def cost_usd(tokens_in: int, tokens_out: int, model: str = "default") -> float:
    p = next((v for k, v in config.PRICES.items() if k != "default" and k in model), config.PRICES["default"])
    return tokens_in / 1e6 * p["in"] + tokens_out / 1e6 * p["out"]


def _create(client, model, system, prompt, max_tokens=1500):
    """Call the model; if the name is not accepted, walk the fallback list once."""
    import anthropic
    tried = [model] + [m for m in config.MODEL_FALLBACKS if m != model]
    last = None
    for m in tried:
        try:
            return client.messages.create(model=m, max_tokens=max_tokens, system=system, messages=[{"role": "user", "content": prompt}]), m
        except anthropic.NotFoundError as e:
            last = e; continue
    raise last


async def run_agent(agent: str, prompt_file: str, ctx: dict, *, dry_run: bool) -> tuple[dict, float, str]:
    """Returns (result_json, cost_usd, summary_line)."""
    try:
        from . import mission
        from . import memory
        ctx = {**ctx, "mission": mission.state(ctx["_ledger"]), "station": config.STATION_NAME, "_bays": ctx["_ledger"].bays(),
               "memory": memory.digest(ctx["_ledger"]), "winners": ctx["_ledger"].kv_get("winners") or "none yet",
               "season": __import__("constantinople.calendar", fromlist=["season_note"]).season_note(),
               "assigned_style": (lambda st: __import__("constantinople.styles", fromlist=["describe"]).describe(st))(__import__("constantinople.styles", fromlist=["next_style"]).next_style(ctx["_ledger"])),
               "style_library": __import__("constantinople.styles", fromlist=["library_text"]).library_text(),
               "style_results": __import__("constantinople.styles", fromlist=["style_performance"]).style_performance(ctx["_ledger"]), "our_results": __import__("constantinople.tools.signal", fromlist=["our_results"]).our_results(ctx["_ledger"]), "product_type": __import__("constantinople.tools.printify", fromlist=["next_product"]).next_product(ctx["_ledger"]),
               "last_experiment": ctx["_ledger"].kv_get("experiment") or "none yet",
               "recent_stock": [a["title"] for a in ctx["_ledger"].artifacts(kind_filter="stock", limit=8)] or "none yet",
               "recent_digital": [a["title"] for a in ctx["_ledger"].artifacts(kind_filter="digital", limit=8)] or "none yet",
               "mother": config.MOTHER_NAME, "assigned_format": (ctx.get("script") or {}).get("format") if isinstance(ctx.get("script"), dict) and (ctx.get("script") or {}).get("part_of") else __import__("constantinople.tools.signal", fromlist=["next_format"]).next_format(ctx["_ledger"]), "recent_clips": [c["title"] for c in __import__("constantinople.tools.signal", fromlist=["recent_clips"]).recent_clips(ctx["_ledger"], 10)] or "none yet",
               "latest_listing": (lambda a: {"title": a[0]["title"], "description": (a[0]["payload"].get("listing_draft") or {}).get("description", "")} if a else "none yet")(ctx["_ledger"].artifacts(kind_filter="listing", limit=1))}
    except Exception:
        pass
    prompt = _fill(_load_prompt(prompt_file), ctx)
    if dry_run or not config.ANTHROPIC_API_KEY:
        result = canned(prompt_file, ctx)
        return result, round(random.uniform(0.004, 0.03), 4), result.get("summary", f"{agent} finished")
    client = _anthropic()
    model = config.MOTHER_MODEL if agent == config.MOTHER_NAME else config.AGENT_MODEL
    msg, used = _create(client, model, _fill(DOCTRINE, ctx) + f"\n\nYou are {agent}. Reply with a single JSON object and nothing else.", prompt, 2000 if agent == config.MOTHER_NAME else 1500)
    text = "".join(getattr(b, "text", "") for b in msg.content)
    try:
        result = json.loads(re.search(r"\{.*\}", text, re.S).group(0))
    except Exception:
        result = {"summary": text[:200], "raw": text}
    result.setdefault("_model", used)
    c = cost_usd(msg.usage.input_tokens, msg.usage.output_tokens, used)
    return result, round(c, 5), result.get("summary", f"{agent} finished")


# ── canned results, keyed by prompt file ─────────────────────────────────
ADJ = ["cottagecore", "retro", "minimalist", "coastal", "western", "dark academia", "boho", "garden era", "cozy"]
SUBJ = ["mushroom", "wildflower", "moon phase", "cat mom", "trail", "coffee", "book club", "sourdough", "plant lady"]
PROD = ["tee", "sweatshirt", "mug", "tote", "candle"]

def canned(prompt_file: str, ctx: dict) -> dict:
    name = f"{random.choice(ADJ)} {random.choice(SUBJ)} {random.choice(PROD)}"
    if "research" in prompt_file:
        movers = [{"concept": f"{random.choice(ADJ)} {random.choice(SUBJ)} {random.choice(PROD)}",
                   "wow_change_pct": random.randint(12, 61), "price_band": [18, 34], "confidence": random.randint(76, 94)} for _ in range(5)]
        occ = (ctx.get("season") or "").split(" in ")[0].replace("Upcoming occasions (design for the nearest ones that are not too late): ", "") if "Upcoming" in (ctx.get("season") or "") else "none"
        return {"summary": f"{len(movers)} movers above threshold; top: {movers[0]['concept']} +{movers[0]['wow_change_pct']}%",
                "movers": movers, "brief": {"concept": movers[0]["concept"], "occasion": occ, "style": (ctx.get("assigned_style") or "botanical").split(" — ")[0], "text": (random.choice(["Plant Mom Era", "Dog Mom", "Coffee First", "Est. 1987", "Nurse Life", "Grateful"]) if "YES" in (ctx.get("assigned_style") or "") else None), "audience": "gift buyers, 25-44", "angle": "soft, hand-drawn, two-colour", "avoid": "any named brand, character or existing listing's art"}}
    if "trend" in prompt_file:
        brief = (ctx.get("research") or {}).get("brief") or {"concept": name}
        return {"summary": f"Brief locked: {brief['concept']} ({ctx.get('product_type','tee')} · {brief.get('style','botanical')})", "concept": brief["concept"], "occasion": brief.get("occasion", "none"), "style": brief.get("style", "botanical"), "text": brief.get("text"),
                "design_prompt": (f"bold lettering design with the exact words \"{brief['text']}\"" if brief.get("text") else f"flat hand-drawn illustration of a {brief['concept'].replace(' tee','').replace(' mug','')}, two-colour, cream and sage, lots of negative space, no text"),
                "products": [ctx.get("product_type", "tee")]}
    if "stock_brief" in prompt_file:
        theme = random.choice(["Soft gradient abstract backgrounds", "Autumn leaves macro textures", "Minimal desk flat-lays with copy space", "Watercolor paper textures"])
        return {"summary": f"Set: {theme}", "theme": theme, "images": [{"prompt": f"{theme.lower()}, variation {i+1}", "title": f"{theme} {i+1}", "keywords": ["background", "texture", "abstract", "copy space", "minimal", "design", "wallpaper"], "category": 8} for i in range(8)]}
    if "digital_brief" in prompt_file:
        kind = random.choice(["wall_art_set", "coloring_pages"]); theme = random.choice(["Soft Sage Botanical Trio", "Line Art Faces", "Retro Sunset National Parks", "Cozy Kitchen Herbs", "Little Forest Friends"])
        n = 8 if kind == "coloring_pages" else 3
        return {"summary": f"{kind}: {theme}", "kind": kind, "theme": theme, "buyer": "a renter decorating a first apartment", "use": "living room gallery wall" if kind == "wall_art_set" else "kids 4-8, rainy afternoons",
                "prompts": [f"{theme.lower()}, piece {i+1}, coordinated muted palette, full composition" for i in range(n)]}
    if "digital_listing" in prompt_file:
        b = ctx.get("digital_brief") or {}; wall = b.get("kind") != "coloring_pages"
        return {"summary": "Listing drafted", "title": f"{b.get('theme','Printable Set')} | Printable Wall Art Set of 3 | Digital Download" if wall else f"{b.get('theme','Colouring Pages')} | Printable Coloring Pages Set of 8 | Digital Download",
                "tags": ["printable wall art", "digital download", "gallery wall set", "boho decor", "instant download"] if wall else ["coloring pages", "printable coloring", "kids activity", "digital download", "rainy day"],
                "description": "What you get: " + ("3 prints at 8x10, 11x14, 16x20 and A4 as JPG and PDF." if wall else "8 pages as a US Letter PDF and PNGs.") + "\n\nPrint at home or at any print shop; files are 300 dpi.\n\nThis is a digital file; nothing will be shipped. Design created with AI tools from our own original prompts.",
                "price": 7.95 if wall else 4.95}
    if "digital_review" in prompt_file:
        ld = ctx.get("digital_listing") or {}; ok = "nothing will be shipped" in ld.get("description", "").lower() and "ai tools" in ld.get("description", "").lower()
        return {"summary": "Reviewed", "verdict": "approve" if ok else "reject", "reason": "coherent set, disclosure present" if ok else "missing disclosure"}
    if "shop_audit" in prompt_file:
        f = ctx.get("facts") or {}
        return {"summary": "Audit done", "score": 62, "gaps": [f"{f.get('live_publish_events',0)} listings live — a shop needs 30+ to be found", "Product mix leans on tees; sweatshirts and mugs underrepresented", "No listing yet targets Thanksgiving despite 'design now'"],
                "for_creator": ["Confirm shipping profile is United States only", "Add the shop icon and banner", "Fill the About section"]}
    if "seo_rewrite" in prompt_file:
        ls = (ctx.get("pick") or {}).get("listings") or []
        return {"summary": f"{len(ls)} rewritten", "rewrites": [{"product_id": l["product_id"], "title": f"Gift for {l.get('concept','Her').title()} Lover | {l.get('product') or 'Tee'} | Christmas Gift", "tags": ["gift for her", "christmas gift", "cozy sweatshirt", "plant mom gift", "nature lover", "made to order", "unisex tee", "birthday gift", "aesthetic shirt", "hand drawn", "gift idea", "soft tee", "for mom"]} for l in ls]}
    if "council" in prompt_file:
        return {"summary": "Council held", "allocation": {"etsy": 1.0, "clips": 1.0, "pins": 1.0, "signal": 1.0, "research": 1.0}, "reasons": "Shop is young; hold the line and let listings age.",
                "experiment": {"name": "Horror two-parters every day", "change": "clips: assign horror for 2 of 5 daily shorts, always with a part two", "metric": "average views per horror short vs others", "success": "horror avg views ≥ 1.5× the rest after 7 days"}, "note": "first council; baseline week"}
    if "comment_review" in prompt_file:
        rs = (ctx.get("comment_plan") or {}).get("replies") or []; ok = all("http" not in r.get("reply", "").lower() for r in rs)
        return {"summary": "Reviewed", "verdict": "approve" if ok else "reject", "reason": "specific, no links" if ok else "link in a reply"}
    if "comment_replies" in prompt_file:
        cs = (ctx.get("fetch") or {}).get("comments") or []
        return {"summary": f"{min(2, len(cs))} replies drafted", "replies": [{"comment_id": c["id"], "reply": "Part two goes up tonight — the camera footage is worse than the door." if "part" in c["text"].lower() else "Honestly? The lease was cheap and the cat seemed fine with it. For a while."} for c in cs[:2]]}
    if "longform_review" in prompt_file:
        c = ctx.get("compile") or {}; ok = bool(c.get("file")) and (c.get("stories") or 0) >= 6 and 240 <= float(c.get("duration") or 0) <= 1800
        return {"summary": "Reviewed: post it" if ok else "Reviewed: hold", "verdict": "approve" if ok else "reject", "reason": "stories, length and chapters in order" if ok else "too few stories or wrong length"}
    if "clip_review" in prompt_file:
        r = ctx.get("render") or {}
        ok = bool(r.get("file")) and 10 <= float(r.get("duration") or 0) <= 60
        return {"summary": "Reviewed: post it" if ok else "Reviewed: hold it", "verdict": "approve" if ok else "reject", "reason": "hook up front, nothing copyrighted, length in range" if ok else "render missing or wrong length", "fixes": []}
    if "clip_order" in prompt_file:
        o = ctx.get("clip_order") or {}
        niche = o.get("niche", "small business"); cta = o.get("cta", "Link in bio.")
        beats = [{"line": f"Here is the one thing most {niche} videos get wrong.", "visual": f"a {niche} scene, soft light", "title": "ONE THING"},
                 {"line": "They start with the explanation instead of the result.", "visual": f"close-up detail of {niche}"},
                 {"line": "Show the finished thing first, then how it happened.", "visual": "before and after, split frame"},
                 {"line": "Keep every sentence under ten words.", "visual": "bold caption card"},
                 {"line": cta, "visual": "logo card on dark background"}]
        return {"summary": f"Script drafted for {niche} order", "title": f"The {niche} mistake everyone makes", "kind": "order", "genre": niche, "voiceover": " ".join(b["line"] for b in beats), "beats": beats, "caption": o.get("brief", "")[:180] or f"A {niche} short.", "hashtags": ["#shorts", f"#{niche.replace(' ', '')}"]}
    if "clip" in prompt_file:
        sig = ctx.get("signal") or {}; picks = sig.get("picks") or [{"genre": "scary stories", "format": "horror"}]; pk = random.choice(picks)
        fmt = ctx.get("assigned_format") or pk.get("format") or "horror"; g = pk.get("genre", "scary stories")
        stories = {
            "horror": ("I found a second door in my apartment that isn't on the lease.", "A second door that isn't on the lease",
                       "I found a second door in my apartment that isn't on the lease. It's behind the water heater, painted the same beige as the wall, and the landlord swears the unit has one entrance. I only noticed because the cat sits in front of it every night at the same time. Last week I put a strip of tape across the gap at the bottom. In the morning the tape was on the floor, folded in half, neatly. I didn't open it. I bought a camera instead and pointed it at the door. The first night it recorded nothing for six hours, then the picture went black for four minutes. When it came back the cat was in the hallway, staring at the camera, not the door. Part two is on the channel.",
                       "Part one: a door behind my water heater that isn't on the lease, and a camera that went black for four minutes. I watched the clip frame by frame. The last frame before the blackout isn't black. It's the hallway, from a few inches lower than where I mounted the camera, as if someone had taken it off the wall and turned it around. The landlord came by today. He didn't look at the door. He looked at the cat, said he'd send someone, and left his keys on my counter by mistake. One of them is older than the rest. I haven't tried it yet."),
            "aita": ("AITA for leaving my sister's wedding before the first dance?", "AITA for leaving my sister's wedding early?",
                     "AITA for leaving my sister's wedding before the first dance? Context: I paid for her dress, about two thousand dollars, as my gift. At the reception the DJ did a toast and thanked her new husband's family for the dress. I let it go. Then she took the mic and did the same thing. My mom said don't make a scene. So I didn't. I finished my dinner, hugged my grandmother, and left before the first dance. Now the family group chat says I ruined the night and I owe her an apology. She says she just forgot. I think you don't forget two thousand dollars. So, am I the asshole?",
                     None),
            "revenge": ("My neighbor kept parking in my spot, so I made it his problem.", "He kept parking in my spot",
                        "My neighbor kept parking in my spot, so I made it his problem. Assigned spots, clearly numbered, and every Friday his truck was in mine. Notes didn't work. Building management didn't care. So I checked the lease. Guests can be towed from assigned spots at the owner's request, no warning needed. I didn't tow him. I did better. I started parking in his spot, every Friday, five minutes before he got home. He'd come find me, I'd say sorry, mine was taken, then move mine the moment his was free. Took three weeks. He never parked in my spot again, and he still thinks it was a coincidence.",
                        None),
            "story": ("A stranger paid for my groceries and left me a note I still have.", "The note a stranger left me",
                      "A stranger paid for my groceries and left me a note I still have. I was twenty, counting coins at the register, pretending I'd forgotten my card. The woman behind me said she had a coupon for exactly my total, which is not a thing. She paid, and she handed me a folded receipt. On the back, in pencil: you'll be the one behind someone in line one day. That was eleven years ago. Last month a kid in front of me was doing the coin thing. I had a coupon for exactly his total. I wrote the same thing on the back of the receipt. I hope he keeps it.",
                      None),
            "facts": ("Five things about sleep that sound fake but aren't.", "Sleep facts that sound fake",
                      "Five things about sleep that sound fake but aren't. One: you forget most of your dreams within ten minutes of waking. Two: humans are the only mammals that willingly delay sleep. Three: a cat sleeps roughly two thirds of its life. Four: before electric light, many people slept in two shifts with an hour awake in between. Five: the record for staying awake is eleven days, and the man who set it was a seventeen-year-old doing a school science project.",
                      None),
        }
        if fmt == "product":
            ll = ctx.get("latest_listing"); subject = (ll.get("title").split("|")[0].strip() if isinstance(ll, dict) and ll.get("title") else "the new design")
            beats = [{"line": f"This {subject.lower()} took three tries to get right.", "visual": f"the {subject} design flat on a cream tee"},
                     {"line": "The first one was too busy; nobody could read it from across a room.", "visual": "the design cropped tight"},
                     {"line": "The third kept the hand-drawn line and dropped everything else.", "visual": "final design, centred"},
                     {"line": f"It prints to order and ships in three to five days. The shop is {config.STATION_NAME.split()[0]}.", "visual": "shop name card"}]
            return {"summary": f"Script drafted: {subject}", "format": "product", "kind": "product", "genre": "etsy small business", "title": f"{subject}: three tries to get it right", "hook_card": "THREE TRIES",
                    "voiceover": " ".join(b["line"] for b in beats), "beats": beats, "caption": f"Made to order. {config.STATION_NAME}.", "hashtags": ["#shorts", "#etsy", "#smallbusiness"], "part2": None}
        hook, card, vo, p2 = stories.get(fmt, stories["story"])
        return {"summary": f"Script drafted ({fmt}): {card}", "format": fmt, "kind": "genre", "genre": g, "title": hook.rstrip(".") , "hook_card": card,
                "voiceover": vo, "beats": [{"line": vo}], "caption": hook + (" Part 1." if p2 else ""), "hashtags": ["#shorts", "#" + g.replace(" ", ""), "#storytime", "#" + fmt],
                "part2": ({"title": hook.rstrip(".") + " · Part 2", "hook_card": "Part 2 · " + card, "voiceover": p2, "caption": hook + " Part 2.", "hashtags": ["#shorts", "#" + fmt, "#part2"]} if p2 else None)}
    if "signal" in prompt_file:
        rows = (ctx.get("shorts_scan") or {}).get("genres") or [{"genre": "cozy aesthetic", "top_views": 1000000, "supply": 100}]
        fmap = {"scary": "horror", "creepy": "horror", "aita": "aita", "revenge": "revenge", "fact": "facts", "history": "facts", "etsy": "product"}
        picks = [{"genre": r["genre"], "format": next((v for k, v in fmap.items() if k in r["genre"]), "story"), "pattern": "first-person hook stating the whole premise", "why": f"{r.get('top_views',0):,} top views vs {r.get('supply',0):,} uploads", "hook": f"Nobody tells you this about {r['genre']}"} for r in rows[:3]]
        return {"summary": f"Picks: {', '.join(p['genre'] for p in picks)}", "picks": picks, "hooks": [p["hook"] for p in picks] + ["This took three tries", "The one thing most shops get wrong"],
                "avoid": ["gameplay footage we do not own", "trending audio", "reposted posts or clips", "real names"], "product_angle": "none"}
    if "listing_review" in prompt_file:
        return {"summary": "Reviewed: ship it", "verdict": random.choice(["approve", "approve", "approve", "reject"]), "reason": "concept matches the brief; title is specific; disclosure present", "fixes": []}
    if "listing" in prompt_file:
        concept = (ctx.get("trend_scan") or {}).get("concept", name); plabel = (ctx.get("mockup_build") or {}).get("product", "Tee"); occ = (ctx.get("trend_scan") or {}).get("occasion") or "none"
        return {"summary": f"Listing drafted: \"{concept.title()}\"", "title": f"{concept.title()} {plabel}" + (f" | {occ} Gift" if occ and occ != "none" else " | Illustrated Gift") + " | Soft Unisex",
                "tags": ["gift for her", "cottagecore", "hand drawn", "botanical", "cozy", "nature lover", "unisex tee", "minimalist", "plant lover", "birthday gift", "aesthetic", "illustrated", "soft"],
                "description": f"A soft, illustrated {concept} printed on a unisex tee. Made to order, shipped in 3-5 days. Design created with AI tools from our own original prompts and printed on demand.", "price": 24.95}
    if "score" in prompt_file:
        return {"summary": "Scored 6 candidates; picked 3", "picks": [0, 2, 4], "scores": [91, 74, 88, 69, 86, 72]}
    if "thumbnail" in prompt_file:
        order = ctx.get("order") or {}
        return {"summary": f"Prompt built for {order.get('niche','finance')} thumbnail ×{order.get('qty',1)}",
                "prompt": f"YouTube thumbnail, split screen, left: {order.get('niche','finance')} scene, right: shocked presenter face, bold 3-word headline, high contrast, red arrow",
                "headlines": ["HIDDEN FEE", "NEVER AGAIN", "THE $7 MEAL"]}
    if "triage" in prompt_file:
        msg = str((ctx.get("incident") or {}).get("msg", "")).lower(); n = int(ctx.get("retries") or 0)
        if "not installed" in msg or "missing" in msg: return {"action": "escalate", "reason": "a program is missing on the server; only the Creator can install it"}
        if "re-render" in msg or "unusable" in msg: return {"action": "retry" if n < 2 else "escalate", "reason": "render failed; running the batch again"}
        if "similarity" in msg or "discarded" in msg or ("rejected" in msg and "approval" not in msg): return {"action": "rebrief", "reason": "design too close to an existing listing"}
        if "approval" in msg: return {"action": "watch", "reason": "creator declined; nothing to fix"}
        if "stalled" in msg: return {"action": "retry" if n < 2 else "hold", "reason": "bay stopped completing runs"}
        if "cap" in msg or "account" in msg or "payout" in msg: return {"action": "escalate", "reason": "money or account standing involved"}
        if "timeout" in msg or "rate limit" in msg or "latency" in msg or "network" in msg: return {"action": "retry" if n < 3 else "hold", "reason": "transient upstream failure"}
        return {"action": "watch", "reason": "logged; no repeat yet"}
    if "mission" in prompt_file:
        m = ctx.get("mission") or {}
        leg = m.get("leg", 1); nxt = (m.get("next_waypoint") or {}).get("name", "the next waypoint")
        opts = [f"Leg {leg:02d}: Production carries the mission to {nxt}. Research feeds it one brief per sol; Treasury releases a boost only when trailing margin clears 60%.",
                f"Leg {leg:02d}: Every sol without a new listing is a sol lost. Launch Bay posts twice; Comms keeps the reply window under 60 seconds.",
                f"Leg {leg:02d}: Widen the front toward {nxt}. Research scouts a second product line; Prototype Cell stays on standby until it finds one worth building.",
                f"Leg {leg:02d}: Protect the hull. No boosts this leg; incidents reviewed within the hour; the similarity rule is not negotiable."]
        return {"summary": "Mission reviewed", "directive": random.choice(opts), "priorities": ["production", "research", "launch"], "note": random.choice(["", "", "Listings with a clear subject sell; abstract ones do not.", "Hold off boosts until the first real sale lands."])}
    if "reply" in prompt_file:
        m = ctx.get("message") or {}
        return {"summary": f"Reply drafted ({m.get('category','question')})", "category": m.get("category", "question"),
                "reply": "Thanks for reaching out! Yes — that's available in XL, and I've linked the size chart below. Let me know if you'd like me to swap your order.", "needs_human": False}
    if "pin_caption" in prompt_file:
        ll = ctx.get("latest_listing"); t = (ll.get("title") if isinstance(ll, dict) else None) or "Made to order gift"
        return {"summary": "Pin drafted", "title": t.split("|")[0].strip()[:100], "description": "Made to order and shipped in days. A gift that says you noticed."}
    if "caption" in prompt_file:
        return {"summary": "Caption drafted in station voice", "caption": "New in the Production Bay this week. Hand-drawn, made to order, shipped in 3-5 days.", "hashtags": ["#handdrawn", "#smallshop"]}
    return {"summary": "done"}
