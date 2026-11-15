import json
from pathlib import Path
from typing import List, Dict, Any

DATA_DIR = Path.home() / ".astrbot" / "data" / "plugin_data" / "astrbot_plugin_lettergame"
PENDING_FILE = DATA_DIR / "pending_aliases.json"

class AliasApprovalManager:
    def __init__(self):
        self.pending: List[Dict[str, Any]] = []
        self.next_id: int = 1
        self.load()

    def load(self):
        if not PENDING_FILE.exists():
            self.pending = []
            self.next_id = 1
            return
        try:
            with open(PENDING_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.pending = data.get("pending", [])
            self.next_id = data.get("next_id", 1)
        except Exception:
            self.pending = []
            self.next_id = 1

    def save(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(PENDING_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "next_id": self.next_id,
                "pending": self.pending
            }, f, ensure_ascii=False, indent=2)

    def add(self, bank: str, title: str, alias: str, user: str) -> int:
        item = {
            "id": self.next_id,
            "bank": bank,
            "title": title,
            "alias": alias,
            "user": user
        }
        self.pending.append(item)
        self.next_id += 1
        self.save()
        return item["id"]

    def restore(self, item: Dict[str, Any]) -> bool:
        """把一条已经通过的申请放回待审。同样的申请已在待审里就跳过。"""

        bank = str(item.get("bank", ""))
        title = str(item.get("title", ""))
        alias = str(item.get("alias", ""))
        if not bank or not title or not alias:
            return False

        key = "".join(title.split()).lower()
        alias_key = alias.strip().lower()

        for x in self.pending:
            if (
                str(x.get("bank", "")).lower() == bank.lower()
                and "".join(str(x.get("title", "")).split()).lower() == key
                and str(x.get("alias", "")).strip().lower() == alias_key
            ):
                return False

        used = {x.get("id") for x in self.pending}
        aid = item.get("id")
        if not isinstance(aid, int) or aid in used:
            aid = self.next_id
            self.next_id += 1

        self.pending.append({
            "id": aid,
            "bank": bank,
            "title": title,
            "alias": alias,
            "user": str(item.get("user", "")),
        })
        self.save()
        return True

    def find_by_id(self, aid: int) -> Dict[str, Any] | None:
        for item in self.pending:
            if item["id"] == aid:
                return item
        return None

    def remove(self, item: Dict[str, Any]) -> None:
        self.pending.remove(item)
        self.save()

    def clear(self) -> int:
        count = len(self.pending)
        self.pending.clear()
        self.save()
        return count

    def list_all(self) -> List[Dict[str, Any]]:
        return self.pending[:]

    def is_empty(self) -> bool:
        return len(self.pending) == 0