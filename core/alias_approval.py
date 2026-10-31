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