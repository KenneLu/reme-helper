# -*- coding: utf-8 -*-
"""reme 图标像素链（自 main.py 挪构建侧；运行时零绘制，tray_icons 只加载）。

make_icon/make_taskbar_icon/icon_font 逐字节等价迁移（坐标全按比例——同一函数
既要喂 16px 帧也要喂 256px 基图）。构建期经 appconfig.ICON_STATE_ARTISTS 消费；
exe/taskbar ico 仍由 main.py --make-icon（write_app_icon）调用本件产出。
"""
from PIL import Image, ImageDraw, ImageFont


def icon_font(size: int):
    """托盘「R」用的字体：高分辨率内嵌 TrueType，退回可缩放默认字体。"""
    try:
        return ImageFont.truetype("seguisb.ttf", size)
    except OSError:
        pass
    try:
        return ImageFont.load_default(size)     # Pillow ≥ 10.1 的可缩放默认字体
    except TypeError:
        return ImageFont.load_default()


def make_icon(running: bool = True, tunnels: bool = False, size: int = 64) -> Image.Image:
    """状态托盘图标：圆底 + 「R」+ 可选隧道点（4 形态全量图的唯一来源）。"""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    color = "#26a269" if running else "#6c757d"
    margin = max(1, round(size * 0.035))
    ring = max(1, round(size * 0.04))
    draw.ellipse((margin, margin, size - margin - 1, size - margin - 1),
                 fill=color, outline="#f6f5f4", width=ring)
    font = icon_font(max(9, round(size * 0.67)))
    left, top, right, bottom = draw.textbbox((0, 0), "R", font=font)
    draw.text(((size - (right - left)) / 2 - left, (size - (bottom - top)) / 2 - top),
              "R", font=font, fill="white")
    if tunnels:
        dot = max(4, round(size * 0.26))
        draw.ellipse((size - dot - 1, size - dot - 1, size - 1, size - 1),
                     fill="#f5c211", outline="#ffffff", width=max(1, round(size * 0.03)))
    return image


def make_taskbar_icon(size: int = 64) -> Image.Image:
    """Taskbar/titlebar asset with small-size geometry that fills the available pixels."""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = max(1, round(size * 0.035))
    ring = max(1, round(size * 0.04))
    draw.ellipse((margin, margin, size - margin - 1, size - margin - 1),
                 fill="#26a269", outline="#ffffff", width=ring)
    font = icon_font(max(9, round(size * 0.67)))
    left, top, right, bottom = draw.textbbox((0, 0), "R", font=font)
    draw.text(((size - (right - left)) / 2 - left, (size - (bottom - top)) / 2 - top),
              "R", font=font, fill="white")
    return image
