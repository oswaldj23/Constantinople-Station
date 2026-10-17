import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

def _bool(v, d=False):
    if v is None: return d
    return str(v).strip().lower() in ("1","true","yes","on")

DRY_RUN       = _bool(os.getenv("DRY_RUN"), True)
AUTO_APPROVE  = _bool(os.getenv("AUTO_APPROVE"), False)
HOST          = os.getenv("HOST", "127.0.0.1")
PORT          = int(os.getenv("PORT", "8787"))
DB_PATH       = str(ROOT / os.getenv("DB_PATH", "constantinople.db"))
SPEED         = float(os.getenv("SPEED", "1.0"))

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY") or None
AGENT_MODEL       = os.getenv("AGENT_MODEL", "claude-sonnet-4-5")
IMAGE_PROVIDER    = os.getenv("IMAGE_PROVIDER", "none")
IMAGE_API_KEY     = os.getenv("IMAGE_API_KEY") or None
PRINTIFY_API_KEY  = os.getenv("PRINTIFY_API_KEY") or None
PRINTIFY_SHOP_ID  = os.getenv("PRINTIFY_SHOP_ID") or None
ETSY_API_KEY      = os.getenv("ETSY_API_KEY") or None
ETSY_ACCESS_TOKEN = os.getenv("ETSY_ACCESS_TOKEN") or None
ETSY_SHOP_ID      = os.getenv("ETSY_SHOP_ID") or None
ETSY_REFRESH_TOKEN = os.getenv("ETSY_REFRESH_TOKEN") or None
ETSY_TOKEN_EXPIRES = int(os.getenv("ETSY_TOKEN_EXPIRES") or 0)

STATION_NAME   = os.getenv("STATION_NAME", "Constantinople Station")
CALLSIGN       = os.getenv("CALLSIGN", STATION_NAME.split()[0].upper())
MISSION_TARGET = float(os.getenv("MISSION_TARGET", "1e12"))
CREATOR        = os.getenv("CREATOR", "the Creator")
MOTHER_NAME    = os.getenv("MOTHER_NAME", "MOTHER")
AUTONOMY       = os.getenv("AUTONOMY", "assist").lower()     # assist: gates wait for you · full: Mother decides within caps
DAILY_SPEND_CAP = float(os.getenv("DAILY_SPEND_CAP", "10"))
MAX_RETRIES    = int(os.getenv("MAX_RETRIES", "3"))
AUTO_RETIRE    = _bool(os.getenv("AUTO_RETIRE"), False)      # Treasury may unpublish listings with no sales after 30 days
AUTO_PRICE     = _bool(os.getenv("AUTO_PRICE"), False)       # Treasury may raise winners' prices 10%
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or None
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID") or None
REPORT_HOUR        = int(os.getenv("REPORT_HOUR", "8"))        # local hour for the morning report
REPORT_UTC_OFFSET  = int(os.getenv("REPORT_UTC_OFFSET", "-4"))  # New York in summer is -4, winter -5
MAIL_IMAP_HOST = os.getenv("MAIL_IMAP_HOST") or None           # e.g. imap.gmail.com
MAIL_USER      = os.getenv("MAIL_USER") or None
MAIL_PASSWORD  = os.getenv("MAIL_PASSWORD") or None            # Gmail: an App Password, not your login password

def integrations() -> dict:
    """What is actually wired up, for the dashboard's setup checklist."""
    return {"model": bool(ANTHROPIC_API_KEY), "images": IMAGE_PROVIDER if IMAGE_PROVIDER != "none" and IMAGE_API_KEY else None,
            "printify": bool(PRINTIFY_API_KEY and PRINTIFY_SHOP_ID), "etsy": bool(ETSY_ACCESS_TOKEN and ETSY_SHOP_ID), "etsy_pending": bool(ETSY_API_KEY and not ETSY_ACCESS_TOKEN),
            "fiverr": False, "dry_run": DRY_RUN, "auto_approve": AUTO_APPROVE,
            "autonomy": AUTONOMY, "daily_cap": DAILY_SPEND_CAP, "mother": MOTHER_NAME, "creator": CREATOR,
            "telegram": bool(TELEGRAM_BOT_TOKEN), "mail": bool(MAIL_IMAP_HOST and MAIL_USER and MAIL_PASSWORD),
            "auto_retire": AUTO_RETIRE, "auto_price": AUTO_PRICE}

# USD per 1M tokens, used to cost every agent step. Adjust to the model you run.
PRICES = {
    "default": {"in": 3.0, "out": 15.0},
}
IMAGE_COST_USD = 0.04   # per generated image, rough; override per provider in tools/images.py

BAYS_DIR    = ROOT / "bays"
PROMPTS_DIR = ROOT / "prompts"
DASH_DIR    = ROOT / "dashboard"
