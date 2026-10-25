"""生成视频用图：干净背景 + 三张卡片（下载功能缺失 / 本体展示 / 整合包展示）。"""
from __future__ import annotations

import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT_DIR = r"F:\aa02"
W, H = 1920, 1080

BASE = np.array([9, 12, 17], dtype=np.float64)
GLOW = np.array([26, 62, 92], dtype=np.float64)
ACCENT = (76, 194, 255)
TEXT = (243, 246, 250)
MUTED = (150, 160, 176)
FONT_BOLD = r"C:\Windows\Fonts\msyhbd.ttc"
FONT_REG = r"C:\Windows\Fonts\msyh.ttc"


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def background() -> Image.Image:
    y, x = np.mgrid[0:H, 0:W].astype(np.float64)
    cx, cy = 0.84 * W, 0.10 * H
    dist = np.sqrt(((x - cx) / W) ** 2 + ((y - cy) / H) ** 2)
    glow = np.clip(1.0 - dist / 0.66, 0.0, 1.0) ** 2.2
    dist2 = np.sqrt(((x - 0.10 * W) / W) ** 2 + ((y - 0.95 * H) / H) ** 2)
    glow2 = np.clip(1.0 - dist2 / 0.45, 0.0, 1.0) ** 3.0
    rgb = BASE + glow[..., None] * GLOW * 0.95 + glow2[..., None] * np.array([12, 26, 40]) * 0.6

    nx = (x - W / 2) / (W / 2)
    ny = (y - H / 2) / (H / 2)
    vignette = np.clip(1.0 - 0.32 * (nx ** 2 + ny ** 2) / 1.6, 0.5, 1.0)
    rgb *= vignette[..., None]
    rgb = np.clip(rgb, 0, 255).astype(np.uint8)

    img = Image.fromarray(rgb, "RGB")
    grid = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grid)
    for gx in range(0, W, 60):
        gd.line([(gx, 0), (gx, H)], fill=(255, 255, 255, 6), width=1)
    for gy in range(0, H, 60):
        gd.line([(0, gy), (W, gy)], fill=(255, 255, 255, 6), width=1)
    return Image.alpha_composite(img.convert("RGBA"), grid).convert("RGB")


def corner_mark(canvas: Image.Image, text: str = "MCD") -> None:
    draw = ImageDraw.Draw(canvas)
    icon = Image.open(os.path.join(r"F:\DSH-WORK\MineCraftDownloader", "packaging", "icon.ico"))
    icon = icon.convert("RGBA").resize((44, 44), Image.NEAREST)
    canvas.paste(icon, (W - 132, H - 74), icon)
    draw.text((W - 82, H - 72), text, font=font(FONT_BOLD, 28), fill=(120, 130, 146))


def card_missing() -> Image.Image:
    img = background()
    draw = ImageDraw.Draw(img)
    title = font(FONT_BOLD, 96)
    draw.text((110, 250), "三方启动器", font=title, fill=TEXT)
    draw.text((110, 370), "下载功能缺失", font=title, fill=ACCENT)
    draw.line([(110, 500), (300, 500)], fill=ACCENT, width=4)

    body = font(FONT_REG, 40)
    lines = [
        "CurseForge 收紧 API，第三方启动器陆续移除下载",
    ]
    y = 556
    for line in lines:
        draw.ellipse([112, y + 16, 124, y + 28], fill=ACCENT)
        draw.text((150, y), line, font=body, fill=MUTED)
        y += 70
    corner_mark(img)
    return img


def card_showcase(title: str, subtitle: str) -> Image.Image:
    img = background()
    draw = ImageDraw.Draw(img)
    big = font(FONT_BOLD, 150)
    box = draw.textbbox((0, 0), title, font=big)
    tw = box[2] - box[0]
    x = (W - tw) // 2
    y = (H - (box[3] - box[1])) // 2 - 60
    draw.text((x, y - box[1]), title, font=big, fill=TEXT)

    sub = font(FONT_REG, 44)
    sb = draw.textbbox((0, 0), subtitle, font=sub)
    draw.text(((W - (sb[2] - sb[0])) // 2, y + 210), subtitle, font=sub, fill=MUTED)

    # 标题下方一条细线
    line_w = 220
    draw.line([((W - line_w) // 2, y + 175), ((W + line_w) // 2, y + 175)], fill=ACCENT, width=3)
    corner_mark(img)
    return img


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    items = {
        "card-1-download-missing.png": card_missing(),
        "card-2-vanilla.png": card_showcase("本体下载展示", "原版 · Fabric · Forge · NeoForge"),
        "card-3-modpack.png": card_showcase("整合包下载展示", ".mrpack · Modrinth"),
        "video-bg-1920x1080.png": background(),
    }
    for name, img in items.items():
        path = os.path.join(OUT_DIR, name)
        img.save(path)
        print(name, img.size, os.path.getsize(path) // 1024, "KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
