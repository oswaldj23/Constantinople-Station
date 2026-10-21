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
AGENT_MODEL       = os.getenv("AGENT_MODEL", "claude-sonnet-4-5")       # the crew
MOTHER_MODEL      = os.getenv("MOTHER_MODEL", "claude-opus-4-1")        # the overseer: strongest tier, few calls a day
MODEL_FALLBACKS   = [m for m in os.getenv("MODEL_FALLBACKS", "claude-sonnet-4-5,claude-3-5-sonnet-latest").split(",") if m]
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
REPORT_HOUR        = int(os.getenv("REPORT_HOUR", "11"))       # local hour for the daily report
TELEGRAM_VERBOSITY = os.getenv("TELEGRAM_VERBOSITY", "quiet").lower()   # quiet: approvals, escalations, sales, new listings, drafts, daily report · normal: + incidents, waypoints
REPORT_UTC_OFFSET  = int(os.getenv("REPORT_UTC_OFFSET", "-4"))  # New York in summer is -4, winter -5
MAIL_IMAP_HOST = os.getenv("MAIL_IMAP_HOST") or None           # e.g. imap.gmail.com
MAIL_USER      = os.getenv("MAIL_USER") or None
MAIL_PASSWORD  = os.getenv("MAIL_PASSWORD") or None            # Gmail: an App Password, not your login password
# Clip Forge + Signal Deck
TTS_VOICE      = os.getenv("TTS_VOICE", "onyx")                # OpenAI voices: alloy ash coral echo fable onyx nova sage shimmer
TTS_MODEL      = os.getenv("TTS_MODEL", "gpt-4o-mini-tts")
YOUTUBE_API_KEY       = os.getenv("YOUTUBE_API_KEY") or None   # Data API v3 key: read-only trend scanning (Signal Deck)
YOUTUBE_CLIENT_ID     = os.getenv("YOUTUBE_CLIENT_ID") or None # OAuth desktop client: uploading (Clip Forge)
YOUTUBE_CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET") or None
YOUTUBE_REFRESH_TOKEN = os.getenv("YOUTUBE_REFRESH_TOKEN") or None
YOUTUBE_CHANNEL       = os.getenv("YOUTUBE_CHANNEL") or None   # filled by youtube-auth
CLIP_PRICE     = float(os.getenv("CLIP_PRICE", "35"))          # what one made-to-order short sells for
LISTINGS_PER_DAY = float(os.getenv("LISTINGS_PER_DAY", "2"))
CLIPS_PER_DAY    = float(os.getenv("CLIPS_PER_DAY", "3"))   # Etsy listings a day (each ~$0.20 fee + ~$0.10 images)
PRODUCT_ROTATION = os.getenv("PRODUCT_ROTATION", "tee,sweatshirt,mug,poster,tee,tote,hoodie")
DESIGN_STYLES    = os.getenv("DESIGN_STYLES", "")
PINTEREST_ACCESS_TOKEN = os.getenv("PINTEREST_ACCESS_TOKEN") or None
STOCK_SFTP_USER = os.getenv("STOCK_SFTP_USER") or None
PUBLIC_URL      = (os.getenv("PUBLIC_URL") or "").rstrip("/")   # how you reach the dashboard, e.g. http://100.x.y.z:8787 — used in links Mother sends you                # comma list to restrict the style library; empty = all
SIGNAL_GENRES  = [g.strip() for g in os.getenv("SIGNAL_GENRES", "scary stories,reddit stories,aita,story time,revenge stories,creepypasta,true scary stories,minecraft parkour,satisfying,facts,history,motivation,cozy aesthetic,ai art,etsy small business,day in the life").split(",") if g.strip()]

def integrations() -> dict:
    """What is actually wired up, for the dashboard's setup checklist."""
    return {"model": bool(ANTHROPIC_API_KEY), "images": IMAGE_PROVIDER if IMAGE_PROVIDER != "none" and IMAGE_API_KEY else None,
            "printify": bool(PRINTIFY_API_KEY and PRINTIFY_SHOP_ID), "etsy": bool(ETSY_ACCESS_TOKEN and ETSY_SHOP_ID), "etsy_pending": bool(ETSY_API_KEY and not ETSY_ACCESS_TOKEN),
            "fiverr": False, "dry_run": DRY_RUN, "auto_approve": AUTO_APPROVE,
            "autonomy": AUTONOMY, "daily_cap": DAILY_SPEND_CAP, "mother": MOTHER_NAME, "creator": CREATOR,
            "telegram": bool(TELEGRAM_BOT_TOKEN), "mail": bool(MAIL_IMAP_HOST and MAIL_USER and MAIL_PASSWORD),
            "auto_retire": AUTO_RETIRE, "auto_price": AUTO_PRICE,
            "youtube_scan": bool(YOUTUBE_API_KEY), "youtube_upload": bool(YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET and YOUTUBE_REFRESH_TOKEN),
            "tts": bool(IMAGE_API_KEY), "ffmpeg": __import__("shutil").which("ffmpeg") is not None,
            "listings_per_day": LISTINGS_PER_DAY, "clips_per_day": CLIPS_PER_DAY, "product_rotation": PRODUCT_ROTATION, "pinterest": bool(PINTEREST_ACCESS_TOKEN), "stock": bool(STOCK_SFTP_USER and os.getenv("STOCK_SFTP_PASSWORD"))}

# USD per 1M tokens, used to cost every agent step. Adjust to the model you run.
PRICES = {   # matched by substring of the model name
    "opus": {"in": 15.0, "out": 75.0},
    "sonnet": {"in": 3.0, "out": 15.0},
    "haiku": {"in": 0.8, "out": 4.0},
    "default": {"in": 3.0, "out": 15.0},
}
IMAGE_COST_USD = 0.04   # per generated image, rough; override per provider in tools/images.py

BAYS_DIR    = ROOT / "bays"
PROMPTS_DIR = ROOT / "prompts"
DASH_DIR    = ROOT / "dashboard"
