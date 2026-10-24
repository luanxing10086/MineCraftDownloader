"""生成宣传用封面图（1920x1080）：左侧界面截图，右侧两行大字“MC下载”。"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

REPO = r"F:\DSH-WORK\MineCraftDownloader"
SHOT = os.path.join(REPO, "docs", "gui-downloading.png")
ICON = os.path.join(REPO, "packaging", "icon.ico")
OUT = os.path.join(REPO, "packaging", "store", "cover-1920x1080.png")

W, H = 1920, 1080
BG = (14, 17, 22)
ACCENT = (76, 194, 255)
TEXT = (242, 245, 248)
FONT_BOLD = r"C:\Windows\Fonts\msyhbd.ttc"


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def rounded(img: Image.Image, radius: int) -> Image.Image:
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, img.size[0] - 1, img.size[1] - 1], radius, fill=255)
    out = img.convert("RGBA")
    out.putalpha(mask)
    return out


def autocrop_window(img: Image.Image, threshold: int = 180, ratio: float = 0.3) -> Image.Image:
    """按“亮像素密度”找到窗口实际边界，裁掉四周残留的桌面。"""
    gray = img.convert("L")
    w, h = gray.size
    px = gray.load()
    cols = [sum(1 for y in range(0, h, 3) if px[x, y] > threshold) for x in range(w)]
    rows = [sum(1 for x in range(0, w, 3) if px[x, y] > threshold) for y in range(h)]
    col_thr, row_thr = max(cols) * ratio, max(rows) * ratio
    left = next((x for x, v in enumerate(cols) if v > col_thr), 0)
    right = next((x for x in range(w - 1, -1, -1) if cols[x] > col_thr), w - 1)
    top = next((y for y, v in enumerate(rows) if v > row_thr), 0)
    bottom = next((y for y in range(h - 1, -1, -1) if rows[y] > row_thr), h - 1)
    return img.crop((left, top, right + 1, bottom + 1))


def main() -> int:
    canvas = Image.new("RGB", (W, H), BG)
    glow = Image.new("RGB", (W, H), BG)
    gd = ImageDraw.Draw(glow)
    gd.ellipse([W - 900, -500, W + 300, 700], fill=(20, 46, 66))
    glow = glow.filter(ImageFilter.GaussianBlur(180))
    canvas = Image.blend(canvas, glow, 0.85)
    draw = ImageDraw.Draw(canvas)

    # 左侧截图
    shot = Image.open(SHOT).convert("RGB")
    shot = autocrop_window(shot)
    target_h = 880
    scale = target_h / shot.size[1]
    shot = shot.resize((int(shot.size[0] * scale), target_h), Image.LANCZOS)
    shot = rounded(shot, 18)
    print("截图:", shot.size)

    sx, sy = 72, 100
    shadow = Image.new("RGBA", (shot.size[0] + 80, shot.size[1] + 80), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([40, 40, shot.size[0] + 40, shot.size[1] + 40], 22, fill=(0, 0, 0, 170))
    shadow = shadow.filter(ImageFilter.GaussianBlur(26))
    canvas.paste(shadow, (sx - 40, sy - 40), shadow)
    canvas.paste(shot, (sx, sy), shot)
    draw.rounded_rectangle([sx, sy, sx + shot.size[0], sy + shot.size[1]], 18, outline=(46, 53, 64), width=2)

    # 右侧：两行大字 + 标签 + 说明，整体垂直居中
    x = sx + shot.size[0] + 80
    big = font(FONT_BOLD, 228)
    chip_font = font(FONT_BOLD, 32)
    foot_font = font(FONT_BOLD, 44)
    chips = ["原版", "加载器", "整合包", "任意链接"]
    foot_text = "轻量化 · 免安装 · 开源 MIT"

    def tbox(text: str, f):
        return draw.textbbox((0, 0), text, font=f)

    gap_mc, gap_chips, gap_foot = 12, 64, 44
    b1, b2, bf = tbox("MC", big), tbox("下载", big), tbox(foot_text, foot_font)
    h1, h2, hf = b1[3] - b1[1], b2[3] - b2[1], bf[3] - bf[1]
    total = h1 + gap_mc + h2 + gap_chips + 62 + gap_foot + hf
    top = max(70, (H - total) // 2)

    draw.text((x, top - b1[1]), "MC", font=big, fill=TEXT)
    y2 = top + h1 + gap_mc
    draw.text((x + 92, y2 - b2[1]), "下载", font=big, fill=ACCENT)
    cy = y2 + h2 + gap_chips

    # 特性标签
    cx = x + 4
    for text in chips:
        tw = draw.textlength(text, font=chip_font)
        cw = int(tw) + 48
        draw.rounded_rectangle([cx, cy, cx + cw, cy + 62], 31, fill=(28, 34, 42), outline=(52, 62, 76), width=2)
        draw.text((cx + 24, cy + 12), text, font=chip_font, fill=TEXT)
        cx += cw + 14

    # 底部说明
    draw.text((x + 4, cy + 62 + gap_foot - bf[1]), foot_text, font=foot_font, fill=TEXT)

    # 左下角品牌
    icon = Image.open(ICON).convert("RGBA")
    icon = icon.resize((64, 64), Image.NEAREST)
    canvas.paste(icon, (76, H - 92), icon)
    draw.text((150, H - 88), "MCD", font=font(FONT_BOLD, 38), fill=TEXT)

    canvas.save(OUT)
    print("封面:", OUT, os.path.getsize(OUT) // 1024, "KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
