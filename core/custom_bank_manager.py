import json
import re
import time
import shutil
from pathlib import Path

PLUGIN_DATA_DIR = Path.home() / ".astrbot" / "data" / "plugin_data" / "astrbot_plugin_lettergame"
# ========== 目录安全防护 ==========
_SAFE_SEG = re.compile(r"^[0-9A-Za-z_.\-]{1,64}$")


def _check_segment(seg) -> str:
    """只允许字母数字下划线点和短横；拦住 ../ 和绝对路径，防目录穿越"""
    text = str(seg)
    if text in (".", "..") or not _SAFE_SEG.match(text) or "/" in text or "\\" in text:
        raise ValueError("非法的题库路径片段: %r" % text)
    return text


class _SafeBankRoot:
    """CUSTOM_BANK_DIR 的安全包装：每一次路径拼接都校验片段"""

    __slots__ = ("_path",)

    def __init__(self, path):
        object.__setattr__(self, "_path", path)

    def __truediv__(self, other):
        return _SafeBankRoot(self._path / _check_segment(other))

    def __fspath__(self):
        return str(self._path)

    def __str__(self):
        return str(self._path)

    def __eq__(self, other):
        return self._path == other

    def __hash__(self):
        return hash(self._path)

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_path"), name)

    def __repr__(self):
        return f"_SafeBankRoot({self._path!r})"


def safe_rmtree(target):
    """删除题库目录前，先确认目标确实落在 plugin_data 内"""
    p = Path(target)
    try:
        resolved = p.resolve()
    except OSError:
        return False
    root = PLUGIN_DATA_DIR.resolve()
    if resolved == root or root not in resolved.parents:
        raise ValueError("拒绝删除 plugin_data 之外的路径: %s" % resolved)
    if p.exists():
        safe_rmtree(p)
        return True
    return False


CUSTOM_BANK_DIR = _SafeBankRoot(PLUGIN_DATA_DIR / "custom_banks")

GLOBAL_INDEX_FILE = CUSTOM_BANK_DIR / "index.json"

# ========== 确保目录存在 ==========
CUSTOM_BANK_DIR.mkdir(parents=True, exist_ok=True)

# ========== 全局索引操作 ==========
def _get_global_index() -> dict:
    """读取全局索引"""
    if not GLOBAL_INDEX_FILE.exists():
        return {"next_id": 1, "banks": []}
    with open(GLOBAL_INDEX_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def _save_global_index(index: dict):
    """保存全局索引"""
    with open(GLOBAL_INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

def _get_user_dir(user_id: str) -> Path:
    """获取用户题库目录（user_id 是纯数字，直接作为目录名）"""
    path = CUSTOM_BANK_DIR / user_id
    path.mkdir(parents=True, exist_ok=True)
    return path

def _build_format_code(title: str) -> str:
    return "-".join(str(len(word)) for word in title.split())

# ========== 权限检查 ==========
def _can_view_bank(user_id: str, bank_entry: dict) -> bool:
    """检查用户是否可以查看此题库（创建者或被共享）"""
    if bank_entry.get("uploader") == user_id:
        return True
    shared_with = bank_entry.get("shared_with", [])
    return user_id in shared_with

def _can_edit_bank(user_id: str, bank_entry: dict) -> str:
    """
    检查用户对题库的编辑权限
    返回: "owner" - 创建者（完全权限）
         "shared" - 共享者（仅别名权限）
         None - 无权限
    """
    if bank_entry.get("uploader") == user_id:
        return "owner"
    shared_with = bank_entry.get("shared_with", [])
    if user_id in shared_with:
        return "shared"
    return None

# ========== 题库操作 ==========
def create_bank(user_id: str, name: str, songs: list, meta_info: dict) -> int:
    """创建自定义题库，返回新题库ID（全局唯一）"""
    index = _get_global_index()
    bank_id = index["next_id"]
    index["next_id"] += 1

    # 创建用户目录（如果不存在）
    user_dir = _get_user_dir(user_id)
    bank_dir = user_dir / str(bank_id)
    bank_dir.mkdir(parents=True, exist_ok=True)

    # 保存 songs.json
    with open(bank_dir / "songs.json", "w", encoding="utf-8") as f:
        json.dump(songs, f, ensure_ascii=False, indent=2)

    # 保存 meta.json（用户自己的元数据，存储额外信息）
    meta = {
        "id": bank_id,
        "name": name,
        "uploader": user_id,
        "upload_time": int(time.time()),
        "title_column": meta_info.get("title_column", "曲名"),
        "standard_column": meta_info.get("standard_column", "是否是标准曲名"),
        "is_excel": meta_info.get("is_excel", True),
        "song_count": len(songs),
        "duplicates": meta_info.get("duplicates", [])
    }
    with open(bank_dir / "meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    # 更新全局索引
    index["banks"].append({
        "id": bank_id,
        "name": name,
        "uploader": user_id,
        "upload_time": meta["upload_time"],
        "song_count": len(songs),
        "shared_with": []
    })
    _save_global_index(index)

    # 与内置题库同名曲对齐：把已积累的别名并集带进新题库
    try:
        seed = {}
        for s in songs:
            t = s.get("title") if isinstance(s, dict) else s
            if not t:
                continue
            t = str(t)
            pool = _builtin_aliases_for_title(t)
            pool = [x for x in pool if x.lower() != _norm_title(t)]
            if pool:
                seed[t] = pool
        if seed:
            alias_path = user_dir / str(bank_id) / "aliases.json"
            with open(alias_path, "w", encoding="utf-8") as f:
                json.dump(seed, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    return bank_id

def overwrite_bank(user_id: str, bank_id: int, name: str, songs: list, meta_info: dict) -> bool:
    """覆盖旧题库（保留ID），保留别名文件"""
    index = _get_global_index()
    
    # 查找题库
    bank_entry = None
    for b in index["banks"]:
        if b["id"] == bank_id:
            bank_entry = b
            break
    if not bank_entry:
        return False
    
    # 权限检查：只有创建者可以覆盖
    if bank_entry.get("uploader") != user_id:
        return False

    bank_dir = CUSTOM_BANK_DIR / str(bank_entry["uploader"]) / str(bank_id)
    if not bank_dir.exists():
        return False

    # 备份别名文件
    alias_backup = None
    alias_file = bank_dir / "aliases.json"
    if alias_file.exists():
        with open(alias_file, "r", encoding="utf-8") as f:
            alias_backup = json.load(f)

    # 删除旧数据
    safe_rmtree(bank_dir)
    bank_dir.mkdir(parents=True, exist_ok=True)

    # 保存 songs.json
    with open(bank_dir / "songs.json", "w", encoding="utf-8") as f:
        json.dump(songs, f, ensure_ascii=False, indent=2)

    # 保存 meta.json
    meta = {
        "id": bank_id,
        "name": name,
        "uploader": user_id,
        "upload_time": int(time.time()),
        "title_column": meta_info.get("title_column", "曲名"),
        "standard_column": meta_info.get("standard_column", "是否是标准曲名"),
        "is_excel": meta_info.get("is_excel", True),
        "song_count": len(songs),
        "duplicates": meta_info.get("duplicates", [])
    }
    with open(bank_dir / "meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    # 恢复别名文件
    if alias_backup:
        with open(bank_dir / "aliases.json", "w", encoding="utf-8") as f:
            json.dump(alias_backup, f, ensure_ascii=False, indent=2)

    # 更新全局索引
    bank_entry["name"] = name
    bank_entry["song_count"] = len(songs)
    bank_entry["upload_time"] = meta["upload_time"]
    _save_global_index(index)

    return True

def get_bank(user_id: str, bank_id: int):
    """获取完整题库数据（meta + songs），检查权限"""
    index = _get_global_index()
    
    # 查找题库
    bank_entry = None
    for b in index["banks"]:
        if b["id"] == bank_id:
            bank_entry = b
            break
    if not bank_entry:
        return None
    
    # 权限检查
    if not _can_view_bank(user_id, bank_entry):
        return None
    
    # 读取数据
    uploader = bank_entry["uploader"]
    bank_dir = CUSTOM_BANK_DIR / uploader / str(bank_id)
    if not bank_dir.exists():
        return None
    
    meta_file = bank_dir / "meta.json"
    songs_file = bank_dir / "songs.json"
    if not meta_file.exists() or not songs_file.exists():
        return None
    
    with open(meta_file, "r", encoding="utf-8") as f:
        meta = json.load(f)
    with open(songs_file, "r", encoding="utf-8") as f:
        songs = json.load(f)
    
    # 返回时增加 role 字段
    role = "owner" if bank_entry["uploader"] == user_id else "shared"
    return {"meta": meta, "songs": songs, "role": role}

def get_banks_list(user_id: str) -> list:
    """获取用户所有可用的自定义题库简要列表（自己的 + 共享的）"""
    index = _get_global_index()
    result = []
    for b in index["banks"]:
        is_shared = b["uploader"] != user_id
        if _can_view_bank(user_id, b):
            result.append({
                "id": b["id"],
                "name": b["name"],
                "uploader": b["uploader"],
                "upload_time": b["upload_time"],
                "song_count": b["song_count"],
                "is_shared": is_shared
            })
    return result

def delete_bank(user_id: str, bank_id: int) -> bool:
    """删除自定义题库，返回是否成功（仅创建者）"""
    index = _get_global_index()
    
    # 查找题库
    bank_entry = None
    for b in index["banks"]:
        if b["id"] == bank_id:
            bank_entry = b
            break
    if not bank_entry:
        return False
    
    # 权限检查：只有创建者可以删除
    if bank_entry.get("uploader") != user_id:
        return False
    
    # 删除目录
    bank_dir = CUSTOM_BANK_DIR / user_id / str(bank_id)
    if bank_dir.exists():
        safe_rmtree(bank_dir)
    
    # 从全局索引移除
    index["banks"] = [b for b in index["banks"] if b["id"] != bank_id]
    _save_global_index(index)
    return True

def rename_bank(user_id: str, bank_id: int, new_name: str) -> tuple:
    """修改题库名称，返回 (是否成功, 错误信息)（仅创建者）"""
    index = _get_global_index()
    
    # 查找题库
    bank_entry = None
    for b in index["banks"]:
        if b["id"] == bank_id:
            bank_entry = b
            break
    if not bank_entry:
        return False, "题库不存在"
    
    # 权限检查：只有创建者可以改名
    if bank_entry.get("uploader") != user_id:
        return False, "只有题库创建者可以改名"
    
    # 检查是否与其他题库重名（仅检查同一用户的题库）
    for b in index["banks"]:
        if b["id"] != bank_id and b["uploader"] == user_id and b["name"] == new_name:
            return False, "该名称已被使用"
    
    # 更新全局索引
    bank_entry["name"] = new_name
    _save_global_index(index)
    
    # 同时更新 meta.json
    bank_dir = CUSTOM_BANK_DIR / user_id / str(bank_id)
    meta_file = bank_dir / "meta.json"
    if meta_file.exists():
        with open(meta_file, "r", encoding="utf-8") as f:
            meta = json.load(f)
        meta["name"] = new_name
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    
    return True, ""

def get_custom_songs(user_id: str) -> list:
    """获取用户所有可用自定义题库的歌曲列表（自己的 + 共享的）"""
    all_songs = []
    banks = get_banks_list(user_id)
    for bank in banks:
        bank_id = bank["id"]
        uploader = bank["uploader"]
        bank_dir = CUSTOM_BANK_DIR / uploader / str(bank_id)
        songs_file = bank_dir / "songs.json"
        if not songs_file.exists():
            continue
        with open(songs_file, "r", encoding="utf-8") as f:
            songs = json.load(f)
        for song in songs:
            song_with_info = song.copy()
            song_with_info["bank"] = f"custom_{uploader}_{bank_id}"
            song_with_info["bank_id"] = bank_id
            song_with_info["uploader"] = uploader
            title = song_with_info.get("title", "")
            song_with_info["format_code"] = _build_format_code(title)
            all_songs.append(song_with_info)
    return all_songs

def get_custom_bank_id_by_song(user_id: str, title: str) -> int:
    """查找包含某首曲目的第一个自定义题库ID（自己的优先）"""
    banks = get_banks_list(user_id)
    for bank in banks:
        # 先看自己的，再看共享的（保持之前的逻辑：自己的优先）
        if bank["is_shared"]:
            continue
        bank_dir = CUSTOM_BANK_DIR / bank["uploader"] / str(bank["id"])
        songs_file = bank_dir / "songs.json"
        if not songs_file.exists():
            continue
        with open(songs_file, "r", encoding="utf-8") as f:
            songs = json.load(f)
        for song in songs:
            if song["title"] == title:
                return bank["id"]
    # 如果没有自己的，再找共享的
    for bank in banks:
        if not bank["is_shared"]:
            continue
        bank_dir = CUSTOM_BANK_DIR / bank["uploader"] / str(bank["id"])
        songs_file = bank_dir / "songs.json"
        if not songs_file.exists():
            continue
        with open(songs_file, "r", encoding="utf-8") as f:
            songs = json.load(f)
        for song in songs:
            if song["title"] == title:
                return bank["id"]
    return None

# ========== 别名操作 ==========
def _get_alias_file(user_id: str, bank_id: int) -> Path:
    """获取别名文件路径（需要先验证权限）"""
    index = _get_global_index()
    bank_entry = None
    for b in index["banks"]:
        if b["id"] == bank_id:
            bank_entry = b
            break
    if not bank_entry:
        return None
    uploader = bank_entry["uploader"]
    return CUSTOM_BANK_DIR / uploader / str(bank_id) / "aliases.json"

def _norm_title(title: str) -> str:
    return "".join(str(title).split()).lower()


def _bank_titles(user_id: str, bank_id: int) -> list:
    entry = _get_bank_entry(bank_id)
    if not entry:
        return []
    f = CUSTOM_BANK_DIR / entry["uploader"] / str(bank_id) / "songs.json"
    if not f.exists():
        return []
    try:
        with open(f, "r", encoding="utf-8") as fp:
            songs = json.load(fp)
    except Exception:
        return []
    out = []
    for s in songs:
        t = s.get("title") if isinstance(s, dict) else s
        if t:
            out.append(str(t))
    return out


def _editable_banks_with_title(user_id: str, title: str) -> list:
    """该用户可编辑、且含同曲名的自定义题库 -> [(uploader, bank_id, 实际曲名)]"""
    key = _norm_title(title)
    out = []
    for bank in get_banks_list(user_id):
        if not _can_edit_alias(user_id, bank["id"]):
            continue
        for t in _bank_titles(user_id, bank["id"]):
            if _norm_title(t) == key:
                out.append((bank["uploader"], bank["id"], t))
                break
    return out


def _builtin_aliases_for_title(title: str) -> list:
    """内置题库里同名曲的别名并集"""
    from .alias_manager import get_banks_with_title, get_aliases
    pool, seen = [], set()
    for bank, actual in get_banks_with_title(title):
        for a in get_aliases(bank, actual):
            if a.lower() not in seen:
                seen.add(a.lower())
                pool.append(a)
    return pool


def _can_edit_alias(user_id: str, bank_id: int) -> bool:
    """检查用户是否可以编辑别名（创建者或共享者）"""
    index = _get_global_index()
    for b in index["banks"]:
        if b["id"] == bank_id:
            return _can_edit_bank(user_id, b) is not None
    return False

def get_custom_aliases(user_id: str, bank_id: int, title: str) -> list:
    """获取自定义题库中某首曲目的别名（需要查看权限）"""
    entry = _get_bank_entry(bank_id)
    if not entry or not _can_view_bank(user_id, entry):
        return []
    alias_file = _get_alias_file(user_id, bank_id)
    if not alias_file or not alias_file.exists():
        return []
    with open(alias_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get(title, [])

def _get_bank_entry(bank_id: int) -> dict:
    """根据 bank_id 获取全局索引中的条目"""
    index = _get_global_index()
    for b in index["banks"]:
        if b["id"] == bank_id:
            return b
    return None

def add_custom_alias(user_id: str, bank_id: int, title: str, alias: str) -> bool:
    """添加自定义题库别名；同名曲在该用户其它自建题库里也各写一份"""
    if not _can_edit_alias(user_id, bank_id):
        return False

    targets = _editable_banks_with_title(user_id, title)
    entry = _get_bank_entry(bank_id)
    if not any(bid == bank_id for _, bid, _ in targets):
        targets.insert(0, (entry["uploader"] if entry else user_id, bank_id, title))

    changed = False
    for uploader, bid, actual in targets:
        alias_file = CUSTOM_BANK_DIR / uploader / str(bid) / "aliases.json"
        alias_file.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if alias_file.exists():
            try:
                with open(alias_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
        data.setdefault(actual, [])
        if alias.lower() in [x.lower() for x in data[actual]]:
            continue
        data[actual].append(alias)
        with open(alias_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        changed = True
    return changed

def remove_custom_alias(user_id: str, bank_id: int, title: str, alias: str) -> bool:
    """删除自定义题库别名；同名曲在该用户其它自建题库里的那一份一并删掉"""
    if not _can_edit_alias(user_id, bank_id):
        return False

    targets = _editable_banks_with_title(user_id, title)
    entry = _get_bank_entry(bank_id)
    if not any(bid == bank_id for _, bid, _ in targets):
        targets.insert(0, (entry["uploader"] if entry else user_id, bank_id, title))

    changed = False
    for uploader, bid, actual in targets:
        alias_file = CUSTOM_BANK_DIR / uploader / str(bid) / "aliases.json"
        if not alias_file.exists():
            continue
        try:
            with open(alias_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        if actual not in data:
            continue
        kept = [x for x in data[actual] if x.lower() != alias.lower()]
        if len(kept) == len(data[actual]):
            continue
        if kept:
            data[actual] = kept
        else:
            del data[actual]
        with open(alias_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        changed = True
    return changed

def get_all_custom_aliases(user_id: str) -> dict:
    """获取用户所有可用自定义题库的别名（自己的 + 共享的）"""
    result = {}
    banks = get_banks_list(user_id)
    for bank in banks:
        alias_file = CUSTOM_BANK_DIR / bank["uploader"] / str(bank["id"]) / "aliases.json"
        if alias_file.exists():
            with open(alias_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                for title, aliases in data.items():
                    if title not in result:
                        result[title] = []
                    result[title].extend(aliases)
    # 去重
    for title in result:
        result[title] = list(dict.fromkeys(result[title]))
    return result

def get_all_custom_aliases_for_song(user_id: str, title: str) -> list:
    """获取用户所有可用自定义题库中某首曲目的别名（合并去重）"""
    result = []
    banks = get_banks_list(user_id)
    for bank in banks:
        alias_file = CUSTOM_BANK_DIR / bank["uploader"] / str(bank["id"]) / "aliases.json"
        if alias_file.exists():
            with open(alias_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if title in data:
                    result.extend(data[title])
    return list(dict.fromkeys(result))

# ========== 共享管理 ==========
def share_bank(user_id: str, bank_id: int, target_user_id: str) -> tuple:
    """
    共享题库给目标用户
    返回: (是否成功, 错误信息)
    """
    index = _get_global_index()
    
    bank_entry = None
    for b in index["banks"]:
        if b["id"] == bank_id:
            bank_entry = b
            break
    if not bank_entry:
        return False, "题库不存在"
    
    if bank_entry["uploader"] != user_id:
        return False, "只有题库创建者可以共享"
    
    if target_user_id == user_id:
        return False, "不能共享给自己"
    
    shared_with = bank_entry.get("shared_with", [])
    if target_user_id in shared_with:
        return False, f"已共享给用户 {target_user_id}"
    
    shared_with.append(target_user_id)
    bank_entry["shared_with"] = shared_with
    _save_global_index(index)
    return True, f"已成功共享给用户 {target_user_id}"

def unshare_bank(user_id: str, bank_id: int, target_user_id: str) -> tuple:
    """
    取消共享
    返回: (是否成功, 错误信息)
    """
    index = _get_global_index()
    
    bank_entry = None
    for b in index["banks"]:
        if b["id"] == bank_id:
            bank_entry = b
            break
    if not bank_entry:
        return False, "题库不存在"
    
    if bank_entry["uploader"] != user_id:
        return False, "只有题库创建者可以取消共享"
    
    shared_with = bank_entry.get("shared_with", [])
    if target_user_id not in shared_with:
        return False, f"用户 {target_user_id} 不在共享列表中"
    
    shared_with.remove(target_user_id)
    bank_entry["shared_with"] = shared_with
    _save_global_index(index)
    return True, f"已取消对用户 {target_user_id} 的共享"

def get_shared_with(user_id: str, bank_id: int) -> tuple:
    """
    获取题库的共享用户列表
    返回: (是否成功, 列表或错误信息)
    """
    bank_entry = _get_bank_entry(bank_id)
    if not bank_entry:
        return False, "题库不存在"
    
    if not _can_view_bank(user_id, bank_entry):
        return False, "你没有权限查看此题库"
    
    shared_with = bank_entry.get("shared_with", [])
    return True, shared_with

def is_bank_shared_with_user(bank_id: int, user_id: str) -> bool:
    """检查题库是否共享给了某个用户"""
    bank_entry = _get_bank_entry(bank_id)
    if not bank_entry:
        return False
    shared_with = bank_entry.get("shared_with", [])
    return user_id in shared_with

# ========== 导入导出 ==========
def import_custom_aliases(user_id: str, bank_id: int, alias_data: dict) -> tuple:
    """导入别名数据（创建者或共享者均可）"""
    if not _can_edit_alias(user_id, bank_id):
        return 0, "没有权限编辑此题库的别名"
    
    alias_file = _get_alias_file(user_id, bank_id)
    if not alias_file:
        return 0, "题库不存在"
    
    existing = {}
    if alias_file.exists():
        with open(alias_file, "r", encoding="utf-8") as f:
            existing = json.load(f)
    
    success = 0
    failed = 0
    for title, aliases in alias_data.items():
        if title not in existing:
            existing[title] = []
        for alias in aliases:
            if not alias:
                continue
            if alias.lower() == title.lower():
                failed += 1
                continue
            if alias not in existing[title]:
                existing[title].append(alias)
                success += 1
            else:
                failed += 1
    
    with open(alias_file, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    return success, failed

def export_custom_aliases(user_id: str, bank_id: int) -> dict:
    """导出自定义题库别名（需要查看权限）"""
    bank_entry = _get_bank_entry(bank_id)
    if not bank_entry or not _can_view_bank(user_id, bank_entry):
        return {}
    
    alias_file = _get_alias_file(user_id, bank_id)
    if not alias_file or not alias_file.exists():
        return {}
    with open(alias_file, "r", encoding="utf-8") as f:
        return json.load(f)

def parse_alias_text(text: str, songs: list) -> dict:
    """解析纯文本别名，返回 {title: [aliases]}"""
    result = {}
    lines = text.strip().splitlines()
    for idx, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        if idx >= len(songs):
            break
        title = songs[idx]["title"]
        aliases = [a.strip() for a in line.split("，") if a.strip()]
        if aliases:
            result[title] = aliases
    return result