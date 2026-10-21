"""The station cleans up after itself: render intermediates are deleted after a week, finished videos and
thumbnails are kept, and if the disk runs low the oldest finished clips go too (and the Creator hears once).
`health()` is the one-line status for the morning report."""
import os, shutil, time
from pathlib import Path
from . import config

OUT = config.ROOT / "output"
INTERMEDIATE = ("bg", "bg_", "seg_", "gap_", "scene_", "cap_", "broll_", "asset_", "list.txt", "captions.ass")
KEEP_DAYS = 7
LOW_GB = 5


def _old(p: Path, days: float) -> bool:
    try: return (time.time() - p.stat().st_mtime) > days * 86400
    except Exception: return False


def tidy(L=None) -> dict:
    freed = 0; removed = 0
    for d in (OUT / "clips").glob("*/"):
        for f in d.iterdir():
            if f.is_file() and f.name.startswith(INTERMEDIATE) and _old(f, KEEP_DAYS):
                try: freed += f.stat().st_size; f.unlink(); removed += 1
                except Exception: pass
    for sub in ("stock", "digital"):
        for d in (OUT / sub).glob("*/"):
            if _old(d, 45):
                try: freed += sum(f.stat().st_size for f in d.rglob("*") if f.is_file()); shutil.rmtree(d, ignore_errors=True); removed += 1
                except Exception: pass
    free_gb = shutil.disk_usage(str(config.ROOT)).free / 1e9
    if free_gb < LOW_GB:
        # oldest finished clips first, until there is room
        clips = sorted((d for d in (OUT / "clips").glob("*/") if d.is_dir()), key=lambda d: d.stat().st_mtime)
        for d in clips:
            if shutil.disk_usage(str(config.ROOT)).free / 1e9 >= LOW_GB * 2: break
            try: freed += sum(f.stat().st_size for f in d.rglob("*") if f.is_file()); shutil.rmtree(d, ignore_errors=True); removed += 1
            except Exception: pass
        if L is not None and (L.kv_get("low_disk_warned") or "") != time.strftime("%Y-%m-%d"):
            L.kv_set("low_disk_warned", time.strftime("%Y-%m-%d"))
            L.emit("core", "incident", f"Disk was down to {free_gb:.1f} GB free · cleared old renders · if this repeats, the server needs a bigger disk", agent=config.MOTHER_NAME)
    return {"removed": removed, "freed_gb": round(freed / 1e9, 2), "free_gb": round(shutil.disk_usage(str(config.ROOT)).free / 1e9, 1)}


def health() -> str:
    free_gb = shutil.disk_usage(str(config.ROOT)).free / 1e9
    mem = {}
    try:
        for line in open("/proc/meminfo"):
            k, v = line.split(":"); mem[k] = int(v.split()[0]) / 1024 / 1024
        ram = f"RAM {mem['MemTotal']-mem['MemAvailable']:.1f}/{mem['MemTotal']:.1f} GB"
        swap = f"swap {mem.get('SwapTotal',0)-mem.get('SwapFree',0):.1f}/{mem.get('SwapTotal',0):.1f} GB"
    except Exception:
        ram = "RAM n/a"; swap = ""
    load = os.getloadavg()[0] if hasattr(os, "getloadavg") else 0
    return f"🖥 disk {free_gb:.0f} GB free · {ram} · {swap} · load {load:.1f} · {os.cpu_count()} cores".replace(" ·  ·", " ·")
