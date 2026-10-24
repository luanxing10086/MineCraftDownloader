"""窗口图标（由 packaging/hopper.png 生成，勿手改）。

Dsh 的 hopper 图标 16x16 像素图放大到 32x32 后以 base64 内嵌，
打包成单文件 exe 后也能直接使用，不依赖外部资源文件。
"""

from __future__ import annotations

import base64
import tkinter as tk

PNG_DATA = (
    "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAABNklEQVR4nO1VQarCMBCdRpEKpVgp"
    "fBBciJ4jBxCPK64EoSfo/oMulKJYjJRCs1OYOouE+tPq4qfo2zwyDZnMmzcpwBefDse0Yb6Y395J"
    "sFqu/szB4J/h6AHOOVbs+R6uL+nlrQTDcIhcyAJ5s944dirAH5WHPyGuk32ibJRSNjrYdV1lPRqP"
    "kLe/W+Q4jh0rFOjqgfSUKjcm0M1NCMKg5CCoPNf3fSXOwNYpIHR6HeTJeAJ1cM2vyEKIklOhVB5F"
    "kaVTYHoP8iyHJiDlSAFyvQ4Gtv8LuKaE21fnWxZSeekIpsqtUaBbdyNVPvAG6odSGDiej5VKmMDA"
    "dg/oXphNZ1A19+SF5JDU6n37PKBXTF4g3okdvAIGbfHAMy+Q+5v2vr0e0L3QdO7b7wHdC1mWvdR7"
    "axT44g6gZXe2jD4rggAAAABJRU5ErkJggg=="
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
