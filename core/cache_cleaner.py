"""
渲染缓存清理

规则：
- 只处理 MANAGED_DIRS 白名单目录里的直接文件，不递归子目录
- 只删 .png，json 等数据文件一律放过
- 超过 MAX_AGE_DAYS 天，或单个目录数量超过 MAX_COUNT，就删最早的那些
- 带时间闸门，MIN_INTERVAL 秒内只真正扫一次目录

设计要点：
- 白名单目录，避免误伤 user_name_cache、aliases、presets 等数据
- 清理只删最早的，新生成的图永远排在最后，不会被误伤
- 删除失败静默跳过，绝不影响渲染
"""

import re
import time
from pathlib import Path

from astrbot.api import logger

PLUGIN_DATA_DIR = (
    Path.home()
    / ".astrbot"
    / "data"
    / "plugin_data"
    / "astrbot_plugin_lettergame"
)

CACHE_ROOT = PLUGIN_DATA_DIR / "cache"

# 要清理的目录（白名单），不递归
MANAGED_DIRS = (
    CACHE_ROOT / "boards",
    CACHE_ROOT / "help",
)

# 保留天数
MAX_AGE_DAYS = 7

# 单个目录最多保留的张数（兜底）
MAX_COUNT = 1000

# 时间闸门，单位秒
MIN_INTERVAL = 3600

_STAMP_FILE = CACHE_ROOT / ".cache_cleanup_stamp"

_TS_RE = re.compile(r"(?<!\d)(1\d{9})(?!\d)")


def _file_time(path: Path, fallback: float) -> float:
    """优先从文件名里取 10 位 unix 时间戳，取不到再退回传入的 mtime"""
    found = _TS_RE.findall(path.stem)
    if found:
        try:
            ts = int(found[-1])
            if 1000000000 <= ts <= 2000000000:
                return float(ts)
        except (ValueError, TypeError):
            pass
    return fallback


def cleanup_render_cache(force: bool = False) -> dict:
    """
    清理渲染缓存。
    force=True 时忽略时间闸门，强制扫一次。
    返回值只用于日志和排查，正常调用可以忽略。
    """
    now = time.time()

    if not force:
        try:
            if _STAMP_FILE.exists():
                last = float(_STAMP_FILE.read_text(encoding="utf-8").strip() or 0)
                if now - last < MIN_INTERVAL:
                    return {"skipped": True}
        except Exception:
            pass

    try:
        _STAMP_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STAMP_FILE.write_text(str(now), encoding="utf-8")
    except Exception:
        pass

    age_limit = now - MAX_AGE_DAYS * 86400
    removed = 0
    freed = 0

    for directory in MANAGED_DIRS:
        try:
            if not directory.is_dir():
                continue
            files = [
                f for f in directory.iterdir()
                if f.is_file() and f.suffix.lower() == ".png"
            ]
        except OSError:
            continue

        if not files:
            continue

        times = {}
        for f in files:
            try:
                mtime = f.stat().st_mtime
            except OSError:
                mtime = 0.0
            times[f] = _file_time(f, mtime)

        ordered = sorted(files, key=lambda f: times[f])

        expired = [f for f in ordered if times[f] < age_limit]
        alive = [f for f in ordered if times[f] >= age_limit]

        overflow = len(alive) - MAX_COUNT
        if overflow > 0:
            expired.extend(alive[:overflow])

        if not expired:
            continue

        for f in dict.fromkeys(expired):
            try:
                size = f.stat().st_size
                f.unlink()
                removed += 1
                freed += size
            except OSError:
                pass

    if removed:
        logger.info(
            f"[开字母] 缓存清理：删除 {removed} 个文件，"
            f"释放 {freed / 1048576:.1f} MB"
        )

    return {"removed": removed, "freed_bytes": freed}
