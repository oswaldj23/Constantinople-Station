"""The shop calendar. Etsy buyers shop for an occasion weeks ahead and print-on-demand needs ~10 days to
make and ship, so a design has to be live well before the day. `upcoming()` tells Research, Production
and the Signal Deck what is coming, how many days are left, and whether it is still worth designing for."""
from datetime import date, timedelta

PRODUCTION_DAYS = 12   # print + ship for POD; orders placed later than this before the day arrive late


def _nth_weekday(year, month, weekday, n):
    d = date(year, month, 1); off = (weekday - d.weekday()) % 7
    return d + timedelta(days=off + 7 * (n - 1))


def _easter(y):
    a = y % 19; b = y // 100; c = y % 100; d = b // 4; e = b % 4; f = (b + 8) // 25; g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30; i = c // 4; k = c % 4; l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451; mo = (h + l - 7 * m + 114) // 31; da = (h + l - 7 * m + 114) % 31 + 1
    return date(y, mo, da)


def occasions(year: int) -> list[dict]:
    """(date, name, lead_days, what sells). lead_days = how far ahead buyers start shopping."""
    return [
        {"date": date(year, 1, 1),  "name": "New Year", "lead": 20, "sells": "fresh-start, goals, dry January, planners"},
        {"date": date(year, 2, 14), "name": "Valentine's Day", "lead": 35, "sells": "couples, anniversary, galentines, cat/dog love, self-love"},
        {"date": date(year, 3, 17), "name": "St. Patrick's Day", "lead": 25, "sells": "lucky, shamrock, Irish pride, party tees"},
        {"date": _easter(year),      "name": "Easter", "lead": 30, "sells": "spring, bunnies, pastel, family brunch"},
        {"date": _nth_weekday(year, 5, 6, 2), "name": "Mother's Day", "lead": 40, "sells": "mom, grandma, plant mom, dog mom, first Mother's Day — the biggest gift day after Christmas"},
        {"date": date(year, 5, 6),  "name": "Nurses Week", "lead": 25, "sells": "nurse appreciation, healthcare humour"},
        {"date": _nth_weekday(year, 5, 1, 1), "name": "Teacher Appreciation Week", "lead": 25, "sells": "teacher gifts, end of school year"},
        {"date": date(year, 6, 1),  "name": "Graduation season", "lead": 30, "sells": "class of {year}, grad gifts, proud parent"},
        {"date": _nth_weekday(year, 6, 6, 3), "name": "Father's Day", "lead": 35, "sells": "dad, grandpa, fishing/grilling/dad jokes, first Father's Day"},
        {"date": date(year, 6, 15), "name": "Pride Month", "lead": 25, "sells": "pride, ally, rainbow — tasteful, not corporate"},
        {"date": date(year, 7, 4),  "name": "4th of July", "lead": 25, "sells": "retro Americana, lake days, summer party"},
        {"date": date(year, 8, 20), "name": "Back to school", "lead": 30, "sells": "teacher, first day, college move-in, dorm"},
        {"date": date(year, 10, 31), "name": "Halloween", "lead": 40, "sells": "spooky season, cozy autumn, witchy, ghost humour, matching family"},
        {"date": _nth_weekday(year, 11, 3, 4), "name": "Thanksgiving", "lead": 30, "sells": "grateful, pie, family matching, friendsgiving"},
        {"date": _nth_weekday(year, 11, 3, 4) + timedelta(days=1), "name": "Black Friday / Cyber Monday", "lead": 20, "sells": "the shop should be fully stocked; buyers are gift-hunting"},
        {"date": date(year, 12, 25), "name": "Christmas", "lead": 55, "sells": "gifts for every relationship, family matching PJs/tees, mugs, ornaments-style art, cozy winter — the biggest season of the year"},
        {"date": date(year, 12, 15), "name": "Hanukkah (approx.)", "lead": 35, "sells": "menorah, latkes humour, family"},
        {"date": date(year, 12, 31), "name": "New Year's Eve", "lead": 20, "sells": "party, countdown, year in review"},
    ]


def upcoming(today: date | None = None, horizon_days: int = 75) -> list[dict]:
    """Occasions inside the horizon, with days left and a verdict: 'design now', 'last call', or 'too late'."""
    today = today or date.today(); out = []
    for y in (today.year, today.year + 1):
        for o in occasions(y):
            days = (o["date"] - today).days
            if -3 <= days <= horizon_days:
                ship_by = days - PRODUCTION_DAYS
                verdict = "too late to list for it (ship time)" if ship_by <= 2 else ("last call — list this week" if ship_by <= 10 else ("design now" if days <= o["lead"] + 21 else "soon — design within a week or two"))
                out.append({"name": o["name"], "date": o["date"].isoformat(), "days_left": days, "order_by_days": max(0, ship_by), "verdict": verdict, "sells": o["sells"].replace("{year}", str(y))})
    out.sort(key=lambda o: o["days_left"])
    return out


def season_note(today: date | None = None) -> str:
    """One paragraph for prompts."""
    ups = [o for o in upcoming(today) if "too late" not in o["verdict"]]
    if not ups: return "No gift occasion inside the next ten weeks; design evergreen gifts (birthday, 'for her/him', hobbies, pets)."
    return "Upcoming occasions (design for the nearest ones that are not too late): " + "; ".join(f"{o['name']} in {o['days_left']} days — {o['verdict']} — sells: {o['sells']}" for o in ups[:5])
