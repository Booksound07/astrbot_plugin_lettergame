from pathlib import Path
import shutil

PLUGIN_DIR = Path(__file__).resolve().parent.parent

PLUGIN_DATA_DIR = (
    Path.home()
    / ".astrbot"
    / "data"
    / "plugin_data"
    / "astrbot_plugin_lettergame"
)

# 运行期题库目录：所有读写都走这里
BANK_DIR = PLUGIN_DATA_DIR / "banks"

# 插件自带的只读题库模板，只在首次初始化时被复制
BUNDLED_BANK_DIR = PLUGIN_DIR / "banks"

ALIAS_DIR = PLUGIN_DATA_DIR / "aliases"

# shutil.rmtree 之外，任何落盘路径都必须落在 PLUGIN_DATA_DIR 里
PLUGIN_DATA_ROOT = PLUGIN_DATA_DIR.resolve()


def iter_bundled_banks():
    """遍历插件自带的内置题库目录（只读）"""
    if not BUNDLED_BANK_DIR.is_dir():
        return
    for d in sorted(BUNDLED_BANK_DIR.iterdir()):
        if d.is_dir() and (d / "songs.json").is_file():
            yield d


def ensure_banks(force: bool = False) -> list:
    """首次启动时把内置题库复制到 plugin_data。

    只要运行期题库目录已存在且非空，就不再读插件目录，
    避免插件升级覆盖用户改过的数据。
    """
    if not force:
        try:
            if BANK_DIR.is_dir() and any(BANK_DIR.iterdir()):
                return []
        except OSError:
            return []

    BANK_DIR.mkdir(parents=True, exist_ok=True)
    copied = []
    for src in iter_bundled_banks():
        dst_dir = BANK_DIR / src.name
        dst_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / "songs.json", dst_dir / "songs.json")
        copied.append(src.name)
    return copied


# 模块导入即保证题库就位，之后任何 load() 都不会再碰插件目录
try:
    _BOOT_COPIED = ensure_banks()
except Exception:
    _BOOT_COPIED = []
