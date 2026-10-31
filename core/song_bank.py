from pathlib import Path
import json
import time

BANK_DIR = (
    Path.home()
    / ".astrbot"
    / "data"
    / "plugins"
    / "astrbot_plugin_lettergame"
    / "banks"
)

ALIAS_DIR = (
    Path.home()
    / ".astrbot"
    / "data"
    / "plugin_data"
    / "astrbot_plugin_lettergame"
    / "aliases"
)

class SongBankManager:

    def __init__(self):
        self.song_banks = {}
        self.last_load_time = 0
        self.load()
        
    def build_format_code(self, title):

        return "-".join(
            str(len(word))
            for word in title.split()
        )
            
    def normalize_song(self, song, bank_name):

        if isinstance(song, str):

            song = {
                "title": song
            }

        title = str(
            song.get(
                "title",
                ""
            )
        ).strip()

        return {
            **song,
            "title": title,
            "bank": bank_name,
            "artist": song.get("artist", ""),
            "charter": song.get("charter", ""),
            "illustrator": song.get("illustrator", ""),
            "duration": song.get("duration"),
            "bpm": song.get("bpm"),
            "chapter": song.get("chapter", ""),
            "package": song.get("package", ""),
            "is_standard": song.get("is_standard", True),
            "format_code": song.get(
                "format_code",
                self.build_format_code(title)
            )
        }
    
    def ensure_alias_file(
        self,
        bank_name,
        songs
    ):

        ALIAS_DIR.mkdir(
            parents=True,
            exist_ok=True
        )

        alias_file = (
            ALIAS_DIR
            / f"{bank_name}.json"
        )

        # 已存在就不动
        if alias_file.exists():
            return

        alias_data = {}

        for song in songs:

            if isinstance(song, str):

                title = song.strip()

            else:

                title = str(
                    song.get(
                        "title",
                        ""
                    )
                ).strip()

            if title:

                alias_data[title] = []

        with open(
            alias_file,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                alias_data,
                f,
                ensure_ascii=False,
                indent=2
            )
                
    def load(self):

        self.song_banks.clear()

        if not BANK_DIR.exists():
            self.last_load_time = time.time()
            return

        for game_dir in BANK_DIR.iterdir():

            if not game_dir.is_dir():
                continue

            song_file = game_dir / "songs.json"

            if not song_file.exists():
                continue

            try:

                with open(
                    song_file,
                    "r",
                    encoding="utf-8"
                ) as f:

                    raw_songs = json.load(f)

                self.ensure_alias_file(
                    game_dir.name.lower(),
                    raw_songs
                )

                songs = [
                    self.normalize_song(
                        song,
                        game_dir.name.lower()
                    )
                    for song in raw_songs
                ]

                self.song_banks[
                    game_dir.name.lower()
                ] = songs

            except Exception as e:

                raise RuntimeError(
                    f"读取题库失败: {song_file}"
                ) from e
        self.last_load_time = time.time()
        
    def auto_reload(self):

        now = time.time()

        if now - self.last_load_time < 15:
            return

        self.load()

    def get_bank(self, name):

        self.auto_reload()

        return self.song_banks.get(
            name.lower(),
            []
        )

    def get_all_songs(self):

        self.auto_reload()

        result = []

        for songs in self.song_banks.values():
            result.extend(songs)

        return result

    def get_bank_names(self):

        self.auto_reload()

        return list(
            self.song_banks.keys()
        )
    def force_reload(self):

        self.load()
