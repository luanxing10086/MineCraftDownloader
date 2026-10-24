"""生成三种比例的封面：16:9 / 4:3 / 竖版。"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

REPO = r"F:\DSH-WORK\MineCraftDownloader"
SHOT = os.path.join(REPO, "docs", "gui-downloading.png")
ICON = os.path.join(REPO, "packaging", "icon.ico")
OUT_DIR = r"F:\aa02"

BG = (14, 17, 22)
ACCENT = (76, 194, 255)
TEXT = (242, 245, 248)
MUTED = (154, 164, 178)
FONT_BOLD = r"C:\Windows\Fonts\msyhbd.ttc"
CHIPS = ["原版", "加载器", "整合包", "任意链接"]
FOOT = "轻量化 · 免安装 · 开源 MIT"


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_BOLD, size)


def background(w: int, h: int) -> Image.Image:
    canvas = Image.new("RGB", (w, h), BG)
    glow = Image.new("RGB", (w, h), BG)
    gd = ImageDraw.Draw(glow)
    gd.ellipse([w - 900, -500, w + 300, 700], fill=(20, 46, 66))
    glow = glow.filter(ImageFilter.GaussianBlur(180))
    return Image.blend(canvas, glow, 0.85)


def rounded(img: Image.Image, radius: int = 18) -> Image.Image:
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, img.size[0] - 1, img.size[1] - 1], radius, fill=255)
    out = img.convert("RGBA")
    out.putalpha(mask)
    return out


def paste_shot(canvas: Image.Image, box_w: int, box_h: int, left: int, top: int) -> tuple[int, int]:
    shot = Image.open(SHOT).convert("RGB")
    scale = min(box_w / shot.size[0], box_h / shot.size[1])
    size = (int(shot.size[0] * scale), int(shot.size[1] * scale))
    shot = rounded(shot.resize(size, Image.LANCZOS))
    x = left + (box_w - size[0]) // 2
    y = top + (box_h - size[1]) // 2
    shadow = Image.new("RGBA", (size[0] + 80, size[1] + 80), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([40, 40, size[0] + 40, size[1] + 40], 22, fill=(0, 0, 0, 170))
    shadow = shadow.filter(ImageFilter.GaussianBlur(26))
    canvas.paste(shadow, (x - 40, y - 40), shadow)
    canvas.paste(shot, (x, y), shot)
    ImageDraw.Draw(canvas).rounded_rectangle([x, y, x + size[0], y + size[1]], 18, outline=(46, 53, 64), width=2)
    return size


def draw_text_block(draw: ImageDraw.ImageDraw, x: int, top: int, big_size: int, chip_size: int,
                    foot_size: int, offset: int) -> int:
    """画 MC / 下载 / 标签 / 说明，返回整块高度。"""
    big = font(big_size)
    b1 = draw.textbbox((0, 0), "MC", font=big)
    b2 = draw.textbbox((0, 0), "下载", font=big)
    h1, h2 = b1[3] - b1[1], b2[3] - b2[1]
    chip_font = font(chip_size)
    foot_font = font(foot_size)
    bf = draw.textbbox((0, 0), FOOT, font=foot_font)
    hf = bf[3] - bf[1]

    y = top
    draw.text((x, y - b1[1]), "MC", font=big, fill=TEXT)
    y += h1 + 12
    draw.text((x + offset, y - b2[1]), "下载", font=big, fill=ACCENT)
    y += h2 + 56

    cx = x + 4
    for text in CHIPS:
        tw = draw.textlength(text, font=chip_font)
        cw = int(tw) + int(chip_size * 1.5)
        draw.rounded_rectangle([cx, y, cx + cw, y + chip_size * 1.95], chip_size, fill=(28, 34, 42),
                               outline=(52, 62, 76), width=2)
        draw.text((cx + chip_size * 0.75, y + chip_size * 0.38), text, font=chip_font, fill=TEXT)
        cx += cw + 14
    y += int(chip_size * 1.95) + 40

    draw.text((x + 4, y - bf[1]), FOOT, font=foot_font, fill=TEXT)
    return y + hf - top


def wide_169() -> Image.Image:
    W, H = 1920, 1080
    canvas = background(W, H)
    draw = ImageDraw.Draw(canvas)
    size = paste_shot(canvas, 1010, 900, 62, 90)
    x = 62 + size[0] + 80
    total = 300 + 262 + 12 + 56 + 62 + 40 + 60
    draw_text_block(draw, x, max(70, (H - total) // 2), 228, 32, 44, 92)
    icon = Image.open(ICON).convert("RGBA").resize((64, 64), Image.NEAREST)
    canvas.paste(icon, (76, H - 92), icon)
    draw.text((150, H - 88), "MCD", font=font(38), fill=TEXT)
    return canvas


def square_43() -> Image.Image:
    W, H = 1440, 1080
    canvas = background(W, H)
    draw = ImageDraw.Draw(canvas)
    size = paste_shot(canvas, 760, 700, 46, 190)
    x = 46 + size[0] + 56
    draw_text_block(draw, x, 300, 150, 26, 32, 60)
    icon = Image.open(ICON).convert("RGBA").resize((52, 52), Image.NEAREST)
    canvas.paste(icon, (56, H - 78), icon)
    draw.text((120, H - 74), "MCD", font=font(30), fill=TEXT)
    return canvas


def tall() -> Image.Image:
    W, H = 1080, 1440
    canvas = background(W, H)
    draw = ImageDraw.Draw(canvas)
    # 先算文字块高度，再让截图占满剩余空间
    probe = Image.new("RGB", (W, H))
    pd = ImageDraw.Draw(probe)
    big = 196
    b1 = pd.textbbox((0, 0), "MC", font=font(big))
    b2 = pd.textbbox((0, 0), "下载", font=font(big))
    chip_font = font(28)
    bf = pd.textbbox((0, 0), FOOT, font=font(34))
    text_h = (b1[3] - b1[1]) + 12 + (b2[3] - b2[1]) + 56 + int(28 * 1.95) + 40 + (bf[3] - bf[1])
    top = 70
    draw_text_block(draw, 80, top, big, 28, 34, 84)
    shot_top = top + text_h + 56
    avail_h = H - shot_top - 50
    paste_shot(canvas, W - 140, avail_h, 70, shot_top)
    return canvas


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    wide_169().save(os.path.join(OUT_DIR, "cover-16x9.png"))
    square_43().save(os.path.join(OUT_DIR, "cover-4x3.png"))
    tall().save(os.path.join(OUT_DIR, "cover-vertical.png"))
    for name in ("cover-16x9.png", "cover-4x3.png", "cover-vertical.png"):
        p = os.path.join(OUT_DIR, name)
        print(name, Image.open(p).size, os.path.getsize(p) // 1024, "KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
