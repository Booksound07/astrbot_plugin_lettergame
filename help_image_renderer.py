import random
import math
import time
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
from pathlib import Path

from .image_renderer import load_font, round_corner

PLUGIN_NAME = "astrbot_plugin_lettergame"

PLUGIN_DATA_DIR = (
    Path.home()
    / ".astrbot"
    / "data"
    / "plugin_data"
    / PLUGIN_NAME
)

FONT_DIR = (
    PLUGIN_DATA_DIR
    / "fonts"
)

CACHE_DIR = (
    PLUGIN_DATA_DIR
    / "cache"
)

HELP_CACHE_DIR = (
    CACHE_DIR
    / "help"
)

FONT_DIR.mkdir(
    parents=True,
    exist_ok=True
)

CACHE_DIR.mkdir(
    parents=True,
    exist_ok=True
)

HELP_CACHE_DIR.mkdir(
    parents=True,
    exist_ok=True
)

FONT_NAME = "NotoSansSChineseMedium.ttf"
CARD_WIDTH = 880
CARD_HEIGHT = 70

LEFT_MARGIN = 40
TOP_MARGIN = 40

CARD_GAP = 12
SECTION_GAP = 35

HELP_DATA = [
    {
        "title": "开始游戏",
        "items": [
            ("/letter [可选数量]", "开始一局开字母，可指定题目数量，若不指定则默认在所有已启用题库中随机15题"),
            ("/daily [可选题库]", "开始每日开字母，共15题，可指定题库范围，若不指定则默认在所有内置题库中随机选取"),
            ("/letterload [编号]", "载入预设开字母，默认只有作者可开启\n作者可使用 /我的预设 进行开启人与可开启群聊权限设定")
        ]
    },

    {
        "title": "出题",
        "items": [
            ("/上传预设", "上传自己的开字母题，仅私聊可用"),
            ("/我的预设", "查看并编辑自己上传的题目")
        ]
    },

    {
        "title": "游戏中",
        "items": [
            ("/开 [字母]或/open [字母]", "揭开对应字母，注意命令和参数间需要加空格"),
            ("/猜 [题目]或/guess [题目]", "猜题，不需要加序号，支持别名和大模型二次判定，支持带序号直接回答（无需指令开头）"),
            ("/tip", "随机揭开一个未开且题目里包含的字母"),
            ("/end", "结束开字母，所有人可用")
        ]
    },

    {
        "title": "别名系统",
        "items": [
            ("/查曲 [曲目]", "查询曲目别名"),
            ("/加别名 [别名]", "添加曲目别名，需要先/查曲以指定曲目\n管理可直接添加，其他人需要审核"),
            ("/删别名 [别名]", "删除曲目别名，需要先/查曲以指定曲目\n仅管理可用"),
            ("/通过 [编号]", "通过第[编号]条别名申请，可批量通过\n仅管理可用"),
            ("/全部通过", "通过全部待审别名，仅管理可用"),
            ("/拒绝 [编号]", "拒绝第[编号]条别名申请，可批量拒绝\n仅管理可用"),
            ("/全部拒绝", "拒绝全部待审别名，仅管理可用"),
            ("/待审", "查看待审核别名列表，仅管理可用"),
            ("/导入别名 [题库名]或[自定义题库ID]", "仅私聊可用，导入别名，支持Excel和纯文本形式，仅管理可上传内置题库的别名"),
            ("/导出别名 [题库名]或[自定义题库ID]", "生成Excel表格，导出任意内置题库或自己上传的题库的别名，所有人可用")
        ]
    },
    
    {
        "title": "曲目管理",
        "items": [
            ("/立即获取曲目", "仅Phigros和Rizline，立即从B站官方最新20条动态内获取新增曲目，每周五21点自动进行一次\n仅管理可用"),
            ("/曲目待审", "查看曲目待审清单，按题库分组\n仅管理可用"),
            ("/通过曲目 [编号]", "将第[编号]条曲目写入题库，可批量通过\n仅管理可用"),
            ("/全部通过曲目", "通过全部待审曲目，仅管理可用"),
            ("/拒绝曲目 [编号]", "拒绝第[编号]条待审曲目\n仅管理可用"),
            ("/全部拒绝曲目", "拒绝全部待审曲目，仅管理可用")
        ]
    },
    
    {
        "title": "题库管理",
        "items": [
            ("/题库", "查看所有题库及个人启用/禁用状态"),
            ("/启用 [题库名]或[自定义题库ID]", "启用指定题库，不影响查曲和每日挑战"),
            ("/全部启用", "启用全部题库"),
            ("/禁用 [题库名]或[自定义题库ID]", "禁用指定题库，不影响查曲和每日挑战"),
            ("/全部禁用", "禁用全部题库"),
            ("/上传题库", "仅私聊可用，上传自定义题库，支持Excel和纯文本形式，上传的自定义题库仅自己可用"),
            ("/删除题库 [自定义题库ID]", "删除自定义题库，只能删除自己的题库"),
            ("/我的题库", "查看自定义题库列表，可进入编辑界面查看各级权限与进一步编辑的相应指令"),
            ("/题库信息 [自定义题库ID]", "查看自定义题库信息"),
            ("/改名 [自定义题库ID] [新名称]", "修改自定义题库名字，仅题库创建者可改名"),
            ("/共享题库 [用户QQ号] [自定义题库ID]", "仅创建者可用，将自定义题库共享给指定用户\n被共享者可 /查曲 自定义题库内容，可启用与禁用对应题库，可加与删别名"),
            ("/取消共享 [用户QQ号] [自定义题库ID]", "仅创建者可用，取消对指定用户的题库共享"),
            ("/共享列表 [自定义题库ID]", "仅创建者和共享者可用，查看当前题库的共享范围")
        ]
    },
    
    {
        "title": "其他",
        "items": [
            ("/查询 [题目]或[格式码]", "在已启用的所有题库范围内查找符合要求的曲目，支持自定义题库,支持批量查询\n批量查询规则：除 /查询 单独一行外，每行一个，需对查询的项标注序号，行内数据格式与单项查询规则一致，支持题目与格式码两种查询方法"),
            ("/切换查询模式 [0]或[1]或[2]或[3]", "切换查询模式，可以以不同规则查找符合要求的曲目，可选模式请使用“/切换查询模式”查看"),
            ("/比赛模式 [1]或[2]或[3]", "开启或关闭比赛模式，支持在预设题目下使用，存在计分机制，开启与关闭方法请使用“/比赛模式”查看"),
            ("/查看排行榜 [预设编号]", "查看预设题目排行榜")
        ]
    },
    
    {
        "title": "帮助",
        "items": [
            ("/letterhelp", "显示本帮助")
        ]
    }
]

def render_help_image() -> str:
    # 渲染前顺手清一次缓存（内部有时间闸门，绝大多数调用会直接返回）
    from .cache_cleaner import cleanup_render_cache
    cleanup_render_cache()

    width = CARD_WIDTH + LEFT_MARGIN * 2

    height = 250

    for section in HELP_DATA:
        height += 45
        height += len(section["items"]) * (CARD_HEIGHT + CARD_GAP)
        height += SECTION_GAP

    # 创建底图
    img = Image.new("RGBA", (width, height), (20, 20, 35))

    USE_BACKGROUND = False
    # ========= 背景：与 B22 完全一致 =========
    if USE_BACKGROUND:
        
        all_covers = list(ILLUSTRATION_DIR.glob("*.webp"))
        
        if all_covers:
            bg_path = random.choice(all_covers)
            bg_cover = Image.open(bg_path).convert("RGB")

            # 去色 + 高斯模糊
            bg_cover = bg_cover.resize((width, height))
            bg_cover = ImageEnhance.Color(bg_cover).enhance(0)
            bg_cover = bg_cover.filter(ImageFilter.GaussianBlur(radius=10))

            # 半透明黑色叠加层
            overlay = Image.new("RGBA", (width, height), (0, 0, 0, 90))
            bg_cover = bg_cover.convert("RGBA")
            bg_cover.alpha_composite(overlay)

            img.paste(bg_cover, (0, 0))

            # 渐变层（从上到下透明度 0→180）
            gradient = Image.new("L", (width, height))
            for y in range(height):
                alpha = int(y / height * 180)
                gradient.putpixel((0, y), alpha)
            gradient = gradient.resize((width, height))
            fade = Image.new("RGBA", (width, height), (0, 0, 0, 255))
            fade.putalpha(gradient)
            img.alpha_composite(fade)
        else:
            # 无曲绘时纯色后备
            draw = ImageDraw.Draw(img)
            draw.rectangle((0, 0, width, height), fill=(20, 20, 35))
    else:
        draw = ImageDraw.Draw(img)
        draw.rectangle(
            (0,0,width,height),
            fill=(20,20,35)
        )

    # ========= 绘制帮助卡片 =========
    draw = ImageDraw.Draw(img)

    title_font = load_font(40)
    section_font = load_font(26)
    cmd_font = load_font(20)

    # ===== 主标题 =====
    if PLUGIN_NAME:
        draw.text(
            (LEFT_MARGIN, 40),
            PLUGIN_NAME,
            fill="white",
            font=title_font
        )

        y = 120
    else:
        y = 50

    # ===== 分类 =====
    for section in HELP_DATA:

        # 左侧白色竖线
        draw.rounded_rectangle(
            (
                LEFT_MARGIN,
                y - 3,
                LEFT_MARGIN + 5,
                y + 29
            ),
            radius=2,
            fill=(255, 255, 255)
        )

        # 分类标题
        draw.text(
            (LEFT_MARGIN + 18, y),
            section["title"],
            fill=(255, 255, 255),
            font=section_font
        )

        y += 45

        for cmd, desc in section["items"]:

            card = Image.new(
                "RGBA",
                (CARD_WIDTH, CARD_HEIGHT),
                (40, 40, 70, 180)
            )

            card = round_corner(card, radius=16)

            draw_card = ImageDraw.Draw(card)

            draw_card.text(
                (20, 10),
                cmd,
                fill="white",
                font=cmd_font
            )
            
            for size in [16, 15, 14, 13, 12]:
                desc_font = load_font(size)

                bbox = draw_card.multiline_textbbox(
                    (0, 0),
                    desc,
                    font=desc_font,
                    spacing=2
                )

                text_height = bbox[3] - bbox[1]

                if text_height <= 24:
                    break

            draw_card.text(
                (20, 38),
                desc,
                fill=(220,220,220),
                font=desc_font
            )

            img.alpha_composite(
                card,
                (LEFT_MARGIN, y)
            )

            y += CARD_HEIGHT + CARD_GAP

        y += SECTION_GAP

    output_path = HELP_CACHE_DIR / f"help_{int(time.time())}.png"
    img.save(output_path)
    return str(output_path)