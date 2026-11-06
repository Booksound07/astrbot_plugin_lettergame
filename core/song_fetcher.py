# core/song_fetcher.py
"""从 B 站官方动态抓新曲，产出待审清单。只负责"发现"，不直接改题库。"""

import json
import re
import time
import random
import hashlib
import urllib.parse
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None

try:
    from .matcher import strip_trailing_brackets
except Exception:
    def strip_trailing_brackets(t):
        return str(t).strip()

from .paths import BANK_DIR
DATA_DIR = (
    Path.home() / ".astrbot" / "data" / "plugin_data"
    / "astrbot_plugin_lettergame"
)
PENDING_FILE = DATA_DIR / "pending_songs.json"

BILI_UIDS = {
    "phigros": 414149787,
    "rizline": 1148546890,
}

OPUS_API = "https://api.bilibili.com/x/polymer/web-dynamic/v1/opus/feed/space"

_MIXIN_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]

_TITLE_RE = re.compile(r"[\u300c\uff62]([^\u300d\uff63]{1,80})[\u300d\uff63]\s*[Bb][Yy]\s*[:\uff1a]")


def norm_title(title):
    """曲名归一化，只用于比对"""
    return "".join(str(title).split()).lower()


def _new_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.bilibili.com/",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    try:
        r = s.get("https://api.bilibili.com/x/frontend/finger/spi", timeout=8)
        d = r.json().get("data", {})
        if d.get("b_3"):
            s.cookies.set("buvid3", d["b_3"], domain=".bilibili.com")
        if d.get("b_4"):
            s.cookies.set("buvid4", d["b_4"], domain=".bilibili.com")
    except Exception:
        pass
    return s


def _mixin_key(session):
    r = session.get("https://api.bilibili.com/x/web-interface/nav", timeout=8)
    wbi = (r.json().get("data") or {}).get("wbi_img") or {}
    if not wbi:
        return None
    raw = (
        wbi["img_url"].rsplit("/", 1)[-1].split(".")[0]
        + wbi["sub_url"].rsplit("/", 1)[-1].split(".")[0]
    )
    return "".join(raw[i] for i in _MIXIN_TAB)[:32]


def _signed_url(session, base, params):
    mixin = _mixin_key(session)
    if not mixin:
        return None
    params = dict(params)
    params["wts"] = int(time.time())
    query = re.sub(
        r"[!'()*]",
        "",
        urllib.parse.urlencode(sorted(params.items())),
    )
    w_rid = hashlib.md5((query + mixin).encode()).hexdigest()
    return base + "?" + query + "&w_rid=" + w_rid


def fetch_opus(game, pages=1, retries=3):
    """返回该游戏官方号最近若干页的动态正文列表"""
    uid = BILI_UIDS.get(game)
    if not uid or requests is None:
        return []

    texts = []
    for page in range(1, pages + 1):
        ok = False
        for attempt in range(retries):
            session = _new_session()
            url = _signed_url(
                session, OPUS_API,
                {"host_mid": uid, "page": page, "type": "all"},
            )
            if not url:
                time.sleep(2)
                continue
            try:
                r = session.get(url, timeout=15)
                j = r.json()
            except Exception:
                time.sleep(2 + random.random())
                continue
            if j.get("code") != 0:
                time.sleep(3 + random.random() * 2)
                continue
            data = j.get("data") or {}
            for it in data.get("items") or []:
                content = it.get("content")
                if content:
                    texts.append({
                        "text": str(content),
                        "opus_id": it.get("opus_id"),
                        "pub_time": it.get("pub_time"),
                    })
            ok = bool(data.get("has_more")) or True
            break
        if not ok:
            continue
        time.sleep(1 + random.random())
    return texts


_VERSION_RE = re.compile(
    r"^(?:iOS|iPadOS|Android|HarmonyOS|Windows|macOS|\u9e3f\u8499)\s*[\d.]",
    re.I,
)
_NUM_RE = re.compile(r"^\d+(?:\.\d+)*$")


def _is_noise(title):
    """「」里混进来的版本号、系统要求之类，不是曲名"""
    t = title.strip()
    if not t:
        return True
    if _VERSION_RE.match(t):
        return True
    if _NUM_RE.match(t):
        return True
    if t.lower() in {"by:", "by"}:
        return True
    return False


def extract_titles(text):
    """只认「曲名」 by: 这种；「与音乐游戏「X」联动」里的 X 是游戏名，不带 by，天然被排除"""
    out = []
    for raw in _TITLE_RE.findall(str(text)):
        t = raw.strip()
        if not t:
            continue
        if t.lower().startswith("by:"):
            continue
        if _is_noise(t):
            continue
        out.append(t)
    return out


def load_bank_titles():
    """所有内置题库里已有曲名的归一化集合"""
    titles = set()
    if not BANK_DIR.is_dir():
        return titles
    for d in BANK_DIR.iterdir():
        f = d / "songs.json"
        if not d.is_dir() or not f.is_file():
            continue
        try:
            with open(f, "r", encoding="utf-8") as fp:
                for s in json.load(fp):
                    t = s.get("title") if isinstance(s, dict) else s
                    if t:
                        titles.add(norm_title(t))
        except Exception:
            continue
    return titles


def load_bank_titles_by_game():
    """{题库名: 该库已有曲名归一化集合}，去重必须分库比，不能拿全库并集"""
    out = {}
    if not BANK_DIR.is_dir():
        return out
    for d in BANK_DIR.iterdir():
        f = d / "songs.json"
        if not d.is_dir() or not f.is_file():
            continue
        titles = set()
        try:
            with open(f, "r", encoding="utf-8") as fp:
                for s in json.load(fp):
                    t = s.get("title") if isinstance(s, dict) else s
                    if t:
                        titles.add(norm_title(t))
        except Exception:
            continue
        out[d.name.lower()] = titles
    return out


def load_pending():
    if not PENDING_FILE.exists():
        return {"next_id": 1, "pending": [], "rejected": [], "updated_at": None}
    try:
        with open(PENDING_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"next_id": 1, "pending": [], "rejected": [], "updated_at": None}
    data.setdefault("next_id", 1)
    data.setdefault("pending", [])
    data.setdefault("rejected", [])
    return data


def save_pending(data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(PENDING_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def rejected_keys(data, game=None):
    keys = set()
    for r in data.get("rejected", []):
        if game and r.get("game") != game:
            continue
        keys.add((r.get("game"), norm_title(r.get("title", ""))))
    return keys


def backfill_derived():
    """给现有待审里的标准项补生成去括号版"""
    data = load_pending()
    by_game = load_bank_titles_by_game()
    existing = {(x.get("game"), norm_title(x.get("title", ""))) for x in data["pending"]}
    rej = rejected_keys(data)
    added = []
    for x in list(data["pending"]):
        if not x.get("is_standard", True):
            continue
        title = x.get("title", "")
        stripped = strip_trailing_brackets(title)
        skey = norm_title(stripped) if stripped else ""
        if not skey or skey == norm_title(title):
            continue
        game = x.get("game")
        if skey in by_game.get(game, set()):
            continue
        if (game, skey) in existing or (game, skey) in rej:
            continue
        entry = {
            "id": data["next_id"],
            "game": game,
            "title": stripped,
            "is_standard": False,
            "source": "derived",
            "derived_from": title,
            "found_at": int(time.time()),
        }
        data["next_id"] += 1
        data["pending"].append(entry)
        existing.add((game, skey))
        added.append(entry)
    save_pending(data)
    return added


def run_once(pages=1):
    """跑一次抓取，新曲进待审。返回统计"""
    if requests is None:
        return {"ok": False, "reason": "requests 不可用", "added": 0}

    data = load_pending()
    known_by_game = load_bank_titles_by_game()
    pending_keys = {
        (x.get("game"), norm_title(x.get("title", "")))
        for x in data["pending"]
    }
    rej = rejected_keys(data)

    added = []
    per_game = {}

    for game in BILI_UIDS:
        items = fetch_opus(game, pages=pages)
        game_known = known_by_game.get(game, set())
        hit = 0
        for item in items:
            for title in extract_titles(item["text"]):
                key = norm_title(title)
                if not key or key in game_known:
                    continue
                if (game, key) in pending_keys or (game, key) in rej:
                    continue
                pending_keys.add((game, key))
                entry = {
                    "id": data["next_id"],
                    "game": game,
                    "title": title,
                    "is_standard": True,
                    "source": "bilibili",
                    "opus_id": item.get("opus_id"),
                    "pub_time": item.get("pub_time"),
                    "found_at": int(time.time()),
                }
                data["next_id"] += 1
                data["pending"].append(entry)
                added.append(entry)
                hit += 1

                # 结尾带括号的曲，额外挂一条去括号版：is_standard=False，
                # 只给 /查询 和开字母的括号容错用，不参与出题
                stripped = strip_trailing_brackets(title)
                skey = norm_title(stripped) if stripped else ""
                if (
                    skey
                    and skey != key
                    and skey not in game_known
                    and (game, skey) not in pending_keys
                    and (game, skey) not in rej
                ):
                    pending_keys.add((game, skey))
                    derived = {
                        "id": data["next_id"],
                        "game": game,
                        "title": stripped,
                        "is_standard": False,
                        "source": "derived",
                        "derived_from": title,
                        "opus_id": item.get("opus_id"),
                        "pub_time": item.get("pub_time"),
                        "found_at": int(time.time()),
                    }
                    data["next_id"] += 1
                    data["pending"].append(derived)
                    added.append(derived)
        per_game[game] = hit

    data["updated_at"] = int(time.time())
    save_pending(data)
    return {"ok": True, "added": len(added), "per_game": per_game, "items": added}
