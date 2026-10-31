from astrbot.api.event import AstrMessageEvent
import datetime

def require_group_at(event: AstrMessageEvent) -> bool:
    """如果群聊且未被 @，则返回 True（表示应忽略该消息）"""
    if event.get_group_id() and not event.is_at_or_wake_command:
        return True
    return False

def get_game_state(event, gm):
    group_id = event.get_group_id()
    if not group_id:
        group_id = f"private_{event.get_sender_id()}"
    group_id = str(group_id)
    st = gm.get_state(group_id)
    return group_id, st

_PLUGIN_ADMINS = set()


def set_plugin_admins(ids) -> None:
    """由主插件在加载配置时调用，写入“插件管理员”QQ号列表。"""
    global _PLUGIN_ADMINS
    try:
        _PLUGIN_ADMINS = {str(x).strip() for x in (ids or []) if str(x).strip()}
    except Exception:
        _PLUGIN_ADMINS = set()


def is_admin(event: AstrMessageEvent) -> bool:
    # bot 管理员永远有权限（无论是否写进插件管理员列表）
    try:
        if event.is_admin():
            return True
    except Exception:
        pass
    if getattr(event, "role", None) == "admin":
        return True
    # 写进插件管理员列表的人也有权限
    return str(event.get_sender_id()) in _PLUGIN_ADMINS

def exact_command(event: AstrMessageEvent, *cmds) -> bool:
    """检查消息是否完全等于某个命令（不带参数）"""
    text = event.message_str.strip().lower()
    text = text.lstrip("/")
    return text in [c.lower() for c in cmds]

def extract_args(event: AstrMessageEvent) -> str:
    """提取命令后的参数（去除命令本身）"""
    parts = event.message_str.strip().split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""

from .board_builder import build_question_board

async def send_question_board(event, st, extra_text=""):
    """
    根据题目数量决定发送文本还是图片
    :param event: 事件对象
    :param st: 游戏状态
    :param extra_text: 额外附加的文本（如开启人、猜题提示），会显示在题面前
    """
    # 计算真实题目数（排除装饰行）
    question_count = sum(1 for q in st["questions"] if q.get("type") != "decor")
    if question_count > 15:
        # 先发送额外文字（如果有）
        if extra_text:
            await event.send(event.plain_result(extra_text))
        # 生成图片
        from .board_image_renderer import render_board_image
        img_path = render_board_image(st["questions"], st.get("open_chars", []))
        await event.send(event.image_result(img_path))
    else:
        board = build_question_board(st)
        if extra_text:
            board = extra_text + "\n" + board
        await event.send(event.plain_result(board))
        
def get_daily_seed_date() -> datetime.date:
    """获取每日挑战的种子日期。凌晨4点前用前一天，4点后用当天"""
    now = datetime.datetime.now()
    if now.hour < 4:
        return (datetime.date.today() - datetime.timedelta(days=1))
    else:
        return datetime.date.today()

# ===== 获取当天凌晨4点的时间戳 =====
def get_daily_expire_timestamp() -> int:
    """返回当天凌晨4点的时间戳（每日挑战过期时间）"""
    now = datetime.datetime.now()
    expire = datetime.datetime(
        now.year, now.month, now.day, 4, 0, 0
    )
    # 如果当前时间已经过了4点，过期时间是明天4点
    if now >= expire:
        expire += datetime.timedelta(days=1)
    return int(expire.timestamp())
