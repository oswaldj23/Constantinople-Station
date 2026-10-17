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
    p = config.PRICES.get(model, config.PRICES["default"])
    return tokens_in / 1e6 * p["in"] + tokens_out / 1e6 * p["out"]


async def run_agent(agent: str, prompt_file: str, ctx: dict, *, dry_run: bool) -> tuple[dict, float, str]:
    """Returns (result_json, cost_usd, summary_line)."""
    try:
        from . import mission
        ctx = {**ctx, "mission": mission.state(ctx["_ledger"]), "station": config.STATION_NAME, "_bays": ctx["_ledger"].bays()}
    except Exception:
        pass
    prompt = _fill(_load_prompt(prompt_file), ctx)
    if dry_run or not config.ANTHROPIC_API_KEY:
        result = canned(prompt_file, ctx)
        return result, round(random.uniform(0.004, 0.03), 4), result.get("summary", f"{agent} finished")
    client = _anthropic()
    msg = client.messages.create(
        model=config.AGENT_MODEL, max_tokens=1500,
        system=_fill(DOCTRINE, ctx) + f"\n\nYou are {agent}. Reply with a single JSON object and nothing else.",
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(getattr(b, "text", "") for b in msg.content)
    try:
        result = json.loads(re.search(r"\{.*\}", text, re.S).group(0))
    except Exception:
        result = {"summary": text[:200], "raw": text}
    c = cost_usd(msg.usage.input_tokens, msg.usage.output_tokens)
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
        return {"summary": f"{len(movers)} movers above threshold; top: {movers[0]['concept']} +{movers[0]['wow_change_pct']}%",
                "movers": movers, "brief": {"concept": movers[0]["concept"], "audience": "gift buyers, 25-44", "angle": "soft, hand-drawn, two-colour", "avoid": "any named brand, character or existing listing's art"}}
    if "trend" in prompt_file:
        brief = (ctx.get("research") or {}).get("brief") or {"concept": name}
        return {"summary": f"Brief locked: {brief['concept']}", "concept": brief["concept"],
                "design_prompt": f"flat hand-drawn illustration of a {brief['concept'].replace(' tee','').replace(' mug','')}, two-colour, cream and sage, lots of negative space, no text",
                "products": ["tee", "mug", "tote"]}
    if "listing" in prompt_file:
        concept = (ctx.get("trend_scan") or {}).get("concept", name)
        return {"summary": f"Listing drafted: \"{concept.title()}\"", "title": f"{concept.title()} | Illustrated Gift Tee | Soft Unisex",
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
        return {"summary": "Mission reviewed", "directive": random.choice(opts), "priorities": ["production", "research", "launch"]}
    if "reply" in prompt_file:
        m = ctx.get("message") or {}
        return {"summary": f"Reply drafted ({m.get('category','question')})", "category": m.get("category", "question"),
                "reply": "Thanks for reaching out! Yes — that's available in XL, and I've linked the size chart below. Let me know if you'd like me to swap your order.", "needs_human": False}
    if "caption" in prompt_file:
        return {"summary": "Caption drafted in station voice", "caption": "New in the Production Bay this week. Hand-drawn, made to order, shipped in 3-5 days.", "hashtags": ["#handdrawn", "#smallshop"]}
    return {"summary": "done"}
