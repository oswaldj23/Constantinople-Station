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
    # No live scanner yet: hand SCOUT the category list and let it rank from what it knows about these niches.
    # (A real scanner that samples marketplace search results can be added here; respect each platform's API terms.)
    return {"listings": [], "categories": cats, "count": 0, "cost": 0.0, "summary": f"no live scanner · SCOUT ranking {len(cats)} evergreen categories from knowledge"}
