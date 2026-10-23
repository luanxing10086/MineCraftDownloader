"""本地配置：%APPDATA%\\MCD\\config.json。

只存少量偏好（是否看过正版提示、自定义下载源、上次安装目录等），
不保存任何账号、令牌或隐私数据。
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict

APP_DIRNAME = "MCD"


def app_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~/.config")
    return os.path.join(base, APP_DIRNAME)


def config_path() -> str:
    return os.path.join(app_dir(), "config.json")


def load() -> Dict[str, Any]:
    path = config_path()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(data: Dict[str, Any]) -> None:
    path = config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def get(key: str, default: Any = None) -> Any:
    return load().get(key, default)


def set_value(key: str, value: Any) -> None:  # noqa: A003 - 与 dict 用法保持一致
    data = load()
    data[key] = value
    save(data)
