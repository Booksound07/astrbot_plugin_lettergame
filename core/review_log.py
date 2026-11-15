"""审核操作日志。



记录最近 MAX_KEEP 次别名库 / 曲库的写入操作，供 /别名日志、/曲目日志 查看，

并支持 /回退别名更改、/回退曲目更改 把上 N 次写入退回待审。



存储：plugin_data/astrbot_plugin_lettergame/review_log.json

{

  "alias": {"next_seq": 3, "entries": [...]},

  "song":  {"next_seq": 2, "entries": [...]}

}



单条 entry：

  seq      递增序号，回退时用它标记

  action   approve / revert

  at       时间戳

  by       操作者

  note     操作来源，如“全部通过”

  count    本次涉及条数

  items    完整条目快照，回退时原样使用

  reverted 是否已被回退

"""



import json

import time

from pathlib import Path



DATA_DIR = Path.home() / ".astrbot" / "data" / "plugin_data" / "astrbot_plugin_lettergame"

LOG_FILE = DATA_DIR / "review_log.json"



# 只保留最近多少次操作

MAX_KEEP = 10



KIND_ALIAS = "alias"

KIND_SONG = "song"



_KINDS = (KIND_ALIAS, KIND_SONG)





def _empty():

    return {k: {"next_seq": 1, "entries": []} for k in _KINDS}





def _load():

    if not LOG_FILE.exists():

        return _empty()



    try:

        with open(LOG_FILE, "r", encoding="utf-8") as f:

            data = json.load(f)

    except Exception:

        return _empty()



    base = _empty()

    for k in _KINDS:

        part = data.get(k) or {}

        try:

            base[k]["next_seq"] = int(part.get("next_seq", 1) or 1)

        except Exception:

            base[k]["next_seq"] = 1

        entries = part.get("entries")

        base[k]["entries"] = entries if isinstance(entries, list) else []

    return base





def _save(data):

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    tmp = LOG_FILE.with_suffix(".json.tmp")

    with open(tmp, "w", encoding="utf-8") as f:

        json.dump(data, f, ensure_ascii=False, indent=2)

    tmp.replace(LOG_FILE)





def log(kind, action, items, by="", note="", count=None):

    """追一条记录。items 传条目字典列表，会在内部做浅拷贝。"""



    if kind not in _KINDS:

        return None



    items = [dict(x) for x in (items or [])]



    data = _load()

    bucket = data[kind]



    entry = {

        "seq": bucket["next_seq"],

        "action": action,

        "at": int(time.time()),

        "by": str(by or ""),

        "note": str(note or ""),

        "count": len(items) if count is None else int(count),

        "items": items,

        "reverted": False,

    }



    bucket["next_seq"] += 1

    bucket["entries"].append(entry)

    # 只留最近 MAX_KEEP 次，老的丢掉

    bucket["entries"] = bucket["entries"][-MAX_KEEP:]



    _save(data)

    return entry





def entries(kind, limit=None):

    """按从新到旧返回。"""



    if kind not in _KINDS:

        return []



    data = _load()

    out = list(reversed(data[kind]["entries"]))



    if limit:

        try:

            out = out[: int(limit)]

        except Exception:

            pass



    return out





def revertable(kind):

    """还能回退的次数。"""



    return len([

        e for e in entries(kind)

        if e.get("action") == "approve" and not e.get("reverted")

    ])





def recent_writes(kind, n=1):

    """取最近 n 次尚未回退的写入，新到旧。"""



    try:

        n = max(1, int(n))

    except Exception:

        n = 1



    picked = []

    for e in entries(kind):

        if e.get("action") != "approve" or e.get("reverted"):

            continue

        picked.append(e)

        if len(picked) >= n:

            break



    return picked





def mark_reverted(kind, seqs):

    """把这几次写入标记为已回退，避免重复回退同一批。"""



    if kind not in _KINDS:

        return 0



    want = set()

    for x in (seqs or []):

        try:

            want.add(int(x))

        except Exception:

            continue

    if not want:

        return 0



    data = _load()

    hit = 0

    for e in data[kind]["entries"]:

        if e.get("seq") in want and not e.get("reverted"):

            e["reverted"] = True

            hit += 1



    if hit:

        _save(data)



    return hit



_ACTION_LABEL = {"approve": "通过", "revert": "回退"}


def format_text(kind, label="别名"):
    """给 /别名日志、/曲目日志 用的纯文本输出。"""

    ents = entries(kind)
    if not ents:
        return "%s库还没有改动记录。" % label

    lines = ["%s库最近 %d 次改动（自新至旧）：" % (label, len(ents))]
    for e in ents:
        import time as _t
        stamp = _t.strftime("%m-%d %H:%M", _t.localtime(e.get("at", 0) or 0))
        act = _ACTION_LABEL.get(e.get("action"), e.get("action") or "?")
        note = e.get("note") or ""
        head = "#%s %s %s %s 条" % (e.get("seq"), stamp, act, e.get("count", 0))
        if note and note != act:
            head += "（%s）" % note
        if e.get("reverted"):
            head += "｜已回退"
        lines.append(head)

        items = e.get("items") or []
        for it in items[:5]:
            if kind == KIND_ALIAS:
                lines.append("  · %s → %s" % (it.get("title"), it.get("alias")))
            else:
                lines.append("  · %s：%s" % (it.get("game"), it.get("title")))
        if len(items) > 5:
            lines.append("  · ……还有 %d 条" % (len(items) - 5))

    n = revertable(kind)
    lines.append("")
    lines.append("可回退 %d 次" % n if n else "没有可回退的改动")
    return "\n".join(lines)
