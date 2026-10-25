"""生成 MCD 简介图（1920x1080）：左「本体下载」右「整合包下载」。"""
from __future__ import annotations

import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont

OUT_DIR = r"F:\aa02"
REPO = r"F:\DSH-WORK\MineCraftDownloader"
W, H = 1920, 1080
BG = (9, 12, 17)
GLOW = (26, 62, 92)
ACCENT = (76, 194, 255)
TEXT = (243, 246, 250)
MUTED = (150, 160, 176)
PANEL = (21, 26, 33)
FONT_BOLD = r"C:\Windows\Fonts\msyhbd.ttc"
FONT_REG = r"C:\Windows\Fonts\msyh.ttc"


def font(path: str, size: int):
    return ImageFont.truetype(path, size)


def background() -> Image.Image:
    y, x = np.mgrid[0:H, 0:W].astype(np.float64)
    cx, cy = 0.84 * W, 0.10 * H
    dist = np.sqrt(((x - cx) / W) ** 2 + ((y - cy) / H) ** 2)
    glow = np.clip(1.0 - dist / 0.66, 0.0, 1.0) ** 2.2
    rgb = np.array(BG, dtype=np.float64) + glow[..., None] * np.array(GLOW, dtype=np.float64) * 0.95
    nx = (x - W / 2) / (W / 2)
    ny = (y - H / 2) / (H / 2)
    rgb *= np.clip(1.0 - 0.32 * (nx ** 2 + ny ** 2) / 1.6, 0.5, 1.0)[..., None]
    img = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB")

    grid = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grid)
    for gx in range(0, W, 60):
        gd.line([(gx, 0), (gx, H)], fill=(255, 255, 255, 6))
    for gy in range(0, H, 60):
        gd.line([(0, gy), (W, gy)], fill=(255, 255, 255, 6))
    return Image.alpha_composite(img.convert("RGBA"), grid).convert("RGB")


def draw_title(img: Image.Image) -> None:
    draw = ImageDraw.Draw(img)
    icon = Image.open(os.path.join(REPO, "packaging", "icon.ico")).convert("RGBA").resize((84, 84), Image.NEAREST)
    img.paste(icon, (100, 86), icon)
    draw.text((206, 78), "MCD", font=font(FONT_BOLD, 96), fill=TEXT)
    draw.text((560, 118), "轻量化下载器，无需改变启动器习惯", font=font(FONT_REG, 42), fill=MUTED)


def draw_panel(img: Image.Image, x: int, title: str, bullets: list[str]) -> None:
    draw = ImageDraw.Draw(img)
    y, w, h = 300, 780, 560
    draw.rounded_rectangle([x, y, x + w, y + h], 28, fill=PANEL, outline=(44, 52, 64), width=2)
    draw.text((x + 56, y + 48), title, font=font(FONT_BOLD, 62), fill=TEXT)
    draw.line([(x + 56, y + 140), (x + 236, y + 140)], fill=ACCENT, width=5)

    body = font(FONT_REG, 38)
    by = y + 196
    for item in bullets:
        draw.ellipse([x + 58, by + 18, x + 70, by + 30], fill=ACCENT)
        draw.text((x + 96, by), item, font=body, fill=MUTED)
        by += 78


def main() -> int:
    img = background()
    draw_title(img)
    draw_panel(img, 100, "本体下载", [
        "正式版 / 快照全量列表，支持搜索",
        "Fabric · Quilt · Forge · NeoForge",
        "版本隔离，PCL / HMCL 通用结构",
        "双进度条，随时可取消",
    ])
    draw_panel(img, 1040, "整合包下载", [
        "支持 Modrinth 的 .mrpack",
        "填 slug、贴链接，或直接拖入文件",
        "自动装好对应加载器",
        "overrides 一并解压到版本目录",
    ])
    draw = ImageDraw.Draw(img)
    draw.text((100, 930), "轻量化 · 免安装 · 开源 MIT", font=font(FONT_BOLD, 44), fill=TEXT)

    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, "intro-1920x1080.png")
    img.save(path)
    print(path, img.size, os.path.getsize(path) // 1024, "KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
