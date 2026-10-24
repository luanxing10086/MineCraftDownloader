"""从 hopper.png 生成 exe 图标（.ico）与窗口图标（内嵌 base64 PNG）。"""
from __future__ import annotations

import base64
import io
import os

from PIL import Image

SRC = r"F:\DSH-WORK\hopper.png"
REPO = r"F:\DSH-WORK\MineCraftDownloader"
ICO = os.path.join(REPO, "packaging", "icon.ico")
ICON_MODULE = os.path.join(REPO, "mcd", "icon.py")


def main() -> int:
    src = Image.open(SRC).convert("RGBA")
    print("源图尺寸:", src.size)

    os.makedirs(os.path.dirname(ICO), exist_ok=True)
    # 像素风放大用 NEAREST，保持边缘干净
    sizes = [16, 24, 32, 48, 64, 128, 256]
    frames = [src.resize((s, s), Image.NEAREST) for s in sizes]
    frames[-1].save(ICO, format="ICO", sizes=[(s, s) for s in sizes])
    print("ICO:", ICO, os.path.getsize(ICO), "bytes")

    # 窗口图标用 32x32 PNG，内嵌成 base64，避免打包后找不到文件
    buf = io.BytesIO()
    src.resize((32, 32), Image.NEAREST).save(buf, format="PNG")
    data = base64.b64encode(buf.getvalue()).decode()
    module = '''"""窗口图标（由 packaging/hopper.png 生成，勿手改）。

Dsh 的 hopper 图标 16x16 像素图放大到 32x32 后以 base64 内嵌，
打包成单文件 exe 后也能直接使用，不依赖外部资源文件。
"""

from __future__ import annotations

import base64
import tkinter as tk

PNG_DATA = (
%s
)


def window_icon(root: tk.Tk) -> bool:
    """给窗口设置标题栏/任务栏图标；失败时静默忽略。"""
    try:
        image = tk.PhotoImage(data=PNG_DATA)
        root.iconphoto(True, image)
        root._mcd_icon = image  # 防止被垃圾回收
        return True
    except Exception:  # noqa: BLE001
        return False
''' % "\n".join('    "%s"' % data[i:i + 76] for i in range(0, len(data), 76))
    with open(ICON_MODULE, "w", encoding="utf-8") as handle:
        handle.write(module)
    print("ICON module:", ICON_MODULE, os.path.getsize(ICON_MODULE), "bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
