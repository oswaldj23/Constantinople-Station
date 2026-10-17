"""Market scan. Real implementation: query marketplace search pages / APIs for the categories in
bays/research.yaml and return raw listing samples for SCOUT to rank. Dry run returns a synthetic sample."""
import random
from .. import config

CATEGORIES = ["botanical tees", "cottagecore mugs", "cat mom sweatshirts", "hiking totes", "book club candles"]

async def scan(ctx, *, categories=None, sample: int = 200, dry_run: bool = True, **_):
    cats = categories or CATEGORIES
    if dry_run:
        listings = [{"category": c, "price": round(random.uniform(14, 44), 2), "favorites_7d": random.randint(0, 220), "reviews": random.randint(0, 900)}
                    for c in cats for _ in range(sample // len(cats))]
        return {"listings": listings, "count": len(listings), "cost": 0.0, "summary": f"{len(listings)} listings sampled across {len(cats)} categories"}
    raise NotImplementedError("Add a marketplace search client here (respect robots.txt and the platform's API terms).")
