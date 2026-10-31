from PIL import Image, ImageDraw
from pathlib import Path
import time
from .image_renderer import load_font

# 缓存目录
CACHE_DIR = Path.home() / ".astrbot" / "data" / "plugin_data" / "astrbot_plugin_lettergame" / "cache" / "boards"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

def render_board_image(questions, open_chars=None, width=800, font_size=20, line_height=30, margin=20):
    """
    生成题面图片
    :param questions: 题目列表，每个元素包含 type, mask, text 等
    :param open_chars: 已开字母列表
    :param width: 图片宽度
    :param font_size: 字号
    :param line_height: 行高
    :param margin: 边距
    :return: 图片文件路径
    """
    # 渲染前顺手清一次缓存（内部有时间闸门，绝大多数调用会直接返回）
    from .cache_cleaner import cleanup_render_cache
    cleanup_render_cache()

    # 构建文本行
    lines = []
    if open_chars is not None:
        lines.append("guessed: " + "".join(open_chars))
    for i, q in enumerate(questions, 1):
        if q.get("type") == "decor":
            lines.append(f"{i}. {q['text']}")
        else:
            lines.append(f"{i}. {q['mask']}")

    # 计算图片高度
    height = margin * 2 + len(lines) * line_height
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    font = load_font(font_size)
    y = margin
    for line in lines:
        draw.text((margin, y), line, fill="black", font=font)
        y += line_height

    # 保存图片
    filename = f"board_{int(time.time())}_{hash(str(lines))}.png"
    path = CACHE_DIR / filename
    img.save(path)
    return str(path)