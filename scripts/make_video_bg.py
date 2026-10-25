"""生成干净的视频背景图（1920x1080）：深色渐变 + 细网格 + 柔光，无文字。"""
from __future__ import annotations

import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

OUT_DIR = r"F:\aa02"
W, H = 1920, 1080

BASE = np.array([9, 12, 17], dtype=np.float64)       # 近黑蓝
GLOW = np.array([26, 62, 92], dtype=np.float64)      # 冷蓝柔光


def build() -> Image.Image:
    y, x = np.mgrid[0:H, 0:W].astype(np.float64)

    # 右上角柔光
    cx, cy = 0.84 * W, 0.10 * H
    dist = np.sqrt(((x - cx) / W) ** 2 + ((y - cy) / H) ** 2)
    glow = np.clip(1.0 - dist / 0.62, 0.0, 1.0) ** 2.2

    # 左下角一点点反光，避免整片死黑
    dist2 = np.sqrt(((x - 0.10 * W) / W) ** 2 + ((y - 0.95 * H) / H) ** 2)
    glow2 = np.clip(1.0 - dist2 / 0.45, 0.0, 1.0) ** 3.0

    rgb = BASE + glow[..., None] * GLOW * 0.9 + glow2[..., None] * np.array([14, 30, 44]) * 0.5

    # 暗角
    nx = (x - W / 2) / (W / 2)
    ny = (y - H / 2) / (H / 2)
    vignette = np.clip(1.0 - 0.30 * (nx ** 2 + ny ** 2) / 1.6, 0.55, 1.0)
    rgb *= vignette[..., None]

    img = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB")

    # 细网格（很淡）
    grid = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grid)
    step = 60
    for gx in range(0, W, step):
        gd.line([(gx, 0), (gx, H)], fill=(255, 255, 255, 7), width=1)
    for gy in range(0, H, step):
        gd.line([(0, gy), (W, gy)], fill=(255, 255, 255, 7), width=1)
    img = Image.alpha_composite(img.convert("RGBA"), grid).convert("RGB")

    # 顶部一层极淡的光晕，让画面不呆板
    haze = Image.new("RGB", (W, H), (0, 0, 0))
    hd = ImageDraw.Draw(haze)
    hd.ellipse([W * 0.45, -H * 0.55, W * 1.1, H * 0.45], fill=(24, 54, 80))
    haze = haze.filter(ImageFilter.GaussianBlur(220))
    img = Image.blend(img, Image.blend(img, haze, 0.35), 0.6)
    return img


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    img = build()
    png = os.path.join(OUT_DIR, "video-bg-1920x1080.png")
    img.save(png)
    jpg = os.path.join(OUT_DIR, "video-bg-1920x1080.jpg")
    img.save(jpg, quality=94)
    print(png, os.path.getsize(png) // 1024, "KB")
    print(jpg, os.path.getsize(jpg) // 1024, "KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
