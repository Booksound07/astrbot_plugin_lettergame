from pathlib import Path
import json

DATA_DIR = (
    Path.home()
    / ".astrbot"
    / "data"
    / "plugin_data"
    / "astrbot_plugin_lettergame"
)

DATA_DIR.mkdir(
    parents=True,
    exist_ok=True
)

ALIAS_DIR = DATA_DIR / "aliases"

ALIAS_DIR.mkdir(
    parents=True,
    exist_ok=True
)

PENDING_FILE = DATA_DIR / "pending_aliases.json"



def get_alias_file(bank_name):

    return (
        ALIAS_DIR
        / f"{bank_name.lower()}.json"
    )

def load_aliases(bank_name):

    alias_file = get_alias_file(
        bank_name
    )

    if not alias_file.exists():
        return {}

    with open(
        alias_file,
        "r",
        encoding="utf-8"
    ) as f:

        return json.load(f)

def save_aliases(
    bank_name,
    data
):

    alias_file = get_alias_file(
        bank_name
    )

    with open(
        alias_file,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )
        
def get_aliases(
    bank_name,
    title
):

    aliases = load_aliases(
        bank_name
    )

    return aliases.get(
        title,
        []
    )

def get_shared_aliases(title, bank_manager, user_id=None):
    """
    获取某首曲目的所有别名（内置 + 自定义，如果提供了 user_id）
    """
    from .custom_bank_manager import get_all_custom_aliases_for_song
    result = []

    # 1. 内置别名（遍历所有内置题库）
    for bank in bank_manager.get_bank_names():
        aliases = get_aliases(bank, title)
        result.extend(aliases)

    # 2. 自定义别名（如果提供了 user_id）
    if user_id:
        custom_aliases = get_all_custom_aliases_for_song(user_id, title)
        result.extend(custom_aliases)

    # 去重（保持顺序）
    seen = set()
    unique = []
    for alias in result:
        if alias not in seen:
            seen.add(alias)
            unique.append(alias)
    return unique

def _norm_title(title):
    """曲名归一化：去所有空白、转小写，只用于比对不用于存储"""
    return "".join(str(title).split()).lower()


def _iter_bank_songs():
    banks_root = Path(__file__).parent.parent / "banks"
    if not banks_root.is_dir():
        return
    for d in sorted(banks_root.iterdir()):
        if not d.is_dir():
            continue
        f = d / "songs.json"
        if not f.is_file():
            continue
        try:
            with open(f, "r", encoding="utf-8") as fp:
                songs = json.load(fp)
        except Exception:
            continue
        yield d.name.lower(), songs


def get_banks_with_title(title):
    """返回 [(题库名, 该库里这首歌的实际写法), ...]，按题库名排序"""
    key = _norm_title(title)
    out = []
    for bank, songs in _iter_bank_songs():
        for s in songs:
            t = s.get("title") if isinstance(s, dict) else s
            if t is None:
                continue
            if _norm_title(t) == key:
                out.append((bank, str(t)))
                break
    return out


def _resolve_targets(bank_name, title):
    """要写/删的全部目标；bank_name 永远排在第一个"""
    targets = get_banks_with_title(title)
    names = [b for b, _ in targets]
    if bank_name and bank_name.lower() not in names:
        targets.insert(0, (bank_name.lower(), title))
    return targets


def _add_alias_single(bank_name, title, alias):

    aliases = load_aliases(
        bank_name
    )

    aliases.setdefault(
        title,
        []
    )

    if alias.lower() not in [
        x.lower()
        for x in aliases[title]
    ]:

        aliases[title].append(
            alias
        )

        save_aliases(
            bank_name,
            aliases
        )
        return True

    save_aliases(
        bank_name,
        aliases
    )
    return False


def add_alias_to_file(
    bank_name,
    title,
    alias
):
    """写到所有含这首曲的题库，各存一份"""

    targets = _resolve_targets(bank_name, title)

    for bank, actual_title in targets:
        _add_alias_single(bank, actual_title, alias)

    return targets


def _find_alias_key(aliases, title):
    if title in aliases:
        return title
    key = _norm_title(title)
    for k in aliases:
        if _norm_title(k) == key:
            return k
    return None


def _remove_alias_single(bank_name, title, alias):

    aliases = load_aliases(
        bank_name
    )

    key = _find_alias_key(aliases, title)

    if key is None:
        return False

    before = len(aliases[key])

    aliases[key] = [
        x
        for x in aliases[key]
        if x.lower() != alias.lower()
    ]

    if len(aliases[key]) == before:
        return False

    save_aliases(
        bank_name,
        aliases
    )
    return True


def remove_alias_from_file(
    bank_name,
    title,
    alias
):
    """从所有含这首曲的题库各删一份，删一处等于全删"""

    targets = _resolve_targets(bank_name, title)

    hit = 0
    for bank, actual_title in targets:
        if _remove_alias_single(bank, actual_title, alias):
            hit += 1

    return hit


def sync_aliases_for_title(title):
    """把该曲在其它题库已有的别名取并集，补写到所有含它的题库。
    新增曲目、新增题库、导入题库之后调用。"""
    targets = get_banks_with_title(title)
    if not targets:
        return []

    pool = []
    seen = set()
    for bank, actual_title in targets:
        for a in get_aliases(bank, actual_title):
            if a.lower() == _norm_title(actual_title):
                continue
            if a.lower() not in seen:
                seen.add(a.lower())
                pool.append(a)

    if not pool:
        return []

    for bank, actual_title in targets:
        for a in pool:
            _add_alias_single(bank, actual_title, a)

    return pool


def load_pending_aliases():
    global pending_aliases
    global next_alias_id

    if not PENDING_FILE.exists():
        pending_aliases = []
        next_alias_id = 1
        return

    with open(
         PENDING_FILE,
        "r",
         encoding="utf-8"
    ) as f:
        try:
            data = json.load(f)
        except Exception:
            pending_aliases = []
            next_alias_id = 1
            return

    pending_aliases = data.get(
        "pending",
        []
    )

    next_alias_id = data.get(
        "next_id",
        1
    )
    
def save_pending_aliases():

    with open(
        PENDING_FILE,
         "w",
         encoding="utf-8"
    ) as f:

        json.dump(
            {
                "next_id": next_alias_id,
                "pending": pending_aliases
            },
            f,
            ensure_ascii=False,
            indent=2
        )