"""Market scan. Real implementation: query marketplace search pages / APIs for the categories in
bays/research.yaml and return raw listing samples for SCOUT to rank. Dry run returns a synthetic sample."""
import random
from .. import config

# Niche seeds: who buys print-on-demand gifts on Etsy, by identity, job, hobby, pet, humour and moment. SCOUT
# picks from these (and beyond them) and must name the buyer, the recipient and the moment. Replaced by live
# search demand once the Etsy API is approved.
CATEGORIES = [
    "dog mom / dog dad", "cat mom", "plant mom", "nurse", "teacher", "therapist / social worker", "accountant / tax season humour", "engineer", "truck driver",
    "new mom / first Mother's Day", "grandma / nana", "dad jokes / grandpa", "bride / bridesmaid / bachelorette", "wedding anniversary",
    "retirement", "graduation", "birthday milestones (30 / 40 / 50)", "retro 'Est. YEAR' birth year",
    "hiking / national parks", "camping", "fishing", "golf", "pickleball", "running / marathon", "gym and lifting humour", "yoga", "cycling",
    "reading / book lover", "crochet and knitting", "gardening", "baking / sourdough", "coffee addict", "tea lover", "wine o'clock", "beer and BBQ",
    "gamer / cozy gaming", "D&D and tabletop (no brand names)", "horror movie fan (generic)", "true crime fan", "anime aesthetic (original, no characters)",
    "cowgirl / western", "coastal / beach town", "lake life", "mountain town", "midwest / southern sayings", "city pride (no sports teams)",
    "mental health / anxiety humour", "introvert humour", "sarcastic office humour", "christian faith / scripture", "spooky season", "cozy autumn", "christmas family matching",
    "pride / ally", "neurodivergent pride", "nurse / teacher appreciation week", "sports mom (baseball, soccer, dance)", "homeschool mom", "small business owner",
]

async def scan(ctx, *, categories=None, sample: int = 200, dry_run: bool = True, **_):
    cats = categories or CATEGORIES
    if dry_run:
        listings = [{"category": c, "price": round(random.uniform(14, 44), 2), "favorites_7d": random.randint(0, 220), "reviews": random.randint(0, 900)}
                    for c in cats for _ in range(sample // len(cats))]
        return {"listings": listings, "count": len(listings), "cost": 0.0, "summary": f"{len(listings)} listings sampled across {len(cats)} categories"}
    # Live demand probe: what buyers actually type. Public autocomplete (Google, Amazon) returns the phrases
    # people search for a niche — "gift for nurse" → "gift for nurse practitioner", "nurse gift basket" …
    # These are real demand signals and the exact words titles and tags should use. Etsy's own data arrives with the API.
    phrases = await demand_probe(random.sample(cats, min(10, len(cats))))
    return {"listings": [], "categories": cats, "search_phrases": phrases, "count": 0, "cost": 0.0,
            "summary": f"demand probe · {sum(len(v) for v in phrases.values())} buyer search phrases across {len(phrases)} niches" if phrases else f"no live scanner · SCOUT ranking {len(cats)} categories from knowledge"}


async def demand_probe(niches: list, per: int = 8) -> dict:
    """Autocomplete suggestions per niche, from Google and Amazon, de-duplicated. Empty dict if unreachable."""
    import asyncio, httpx, json as _j
    out = {}
    seeds = []
    for n in niches:
        base = n.split("/")[0].split("(")[0].strip()
        seeds.append((n, f"{base} gift")); seeds.append((n, f"{base} shirt")); seeds.append((n, f"gift for {base}"))
    async def one(c, niche, q):
        found = []
        try:
            r = await c.get("https://suggestqueries.google.com/complete/search", params={"client": "firefox", "q": q}, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200: found += [x for x in r.json()[1] if isinstance(x, str)]
        except Exception: pass
        try:
            r = await c.get("https://completion.amazon.com/api/2017/suggestions", params={"mid": "ATVPDKIKX0DER", "alias": "aps", "prefix": q}, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200: found += [s.get("value") for s in r.json().get("suggestions", []) if s.get("value")]
        except Exception: pass
        return niche, found
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            res = await asyncio.gather(*(one(c, n, q) for n, q in seeds))
    except Exception:
        return {}
    for niche, found in res:
        if not found: continue
        bucket = out.setdefault(niche, [])
        for f in found:
            f = f.strip().lower()
            if f and f not in bucket: bucket.append(f)
        out[niche] = bucket[: per * 3]
    return out
