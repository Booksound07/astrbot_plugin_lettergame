"""回复结果构造。

2026-11-16 起停用引用：这个 bot 不在 astrbot 回复链路上，Reply 组件拼出来
引不到任何消息，反而可能让整条回复发不出去。函数名保留，内部一律退回
普通消息，将来平台支持了把 _USE_QUOTE 打开即可恢复。
"""

from astrbot.api import logger

_USE_QUOTE = False
_REPLY_ATTR = "message_id"


def _make_reply(event):
    """构造 Reply 组件，拿不到 id 就返回 None。"""
    if not _USE_QUOTE:
        return None
    msg_id = None
    try:
        message_obj = getattr(event, "message_obj", None)
        if message_obj is not None:
            msg_id = getattr(message_obj, _REPLY_ATTR, None)
    except Exception as e:
        logger.debug(f"[开字母] 读取 message_id 失败：{repr(e)}")
        return None

    if not msg_id:
        return None

    try:
        import astrbot.api.message_components as Comp
    except Exception as e:
        logger.debug(f"[开字母] 导入消息组件失败：{repr(e)}")
        return None

    try:
        return Comp.Reply(id=str(msg_id))
    except Exception as e:
        logger.debug(f"[开字母] 构造 Reply 组件失败：{repr(e)}")
        return None


def _with_quote(event, result):
    """把 Reply 组件插到结果链最前面。"""
    if result is None:
        return result

    component = _make_reply(event)
    if component is None:
        return result

    try:
        result.chain.insert(0, component)
    except Exception as e:
        logger.debug(f"[开字母] 插入 Reply 组件失败：{repr(e)}")

    return result


def quote_result(event, text):
    """带引用的纯文本结果。"""
    return _with_quote(event, event.plain_result(text))


async def quote_send(event, text):
    """直接发出带引用的纯文本。"""
    await event.send(quote_result(event, text))


def quote_image_result(event, image_path):
    """带引用的图片结果。"""
    return _with_quote(event, event.image_result(image_path))
