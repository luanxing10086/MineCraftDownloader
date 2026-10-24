"""本地配置与缓存目录。

默认放 %APPDATA%\\MCD，但某些机器上不允许未受信任签名的程序写系统盘，
所以这里会依次探测候选位置，全都不可写时退到“程序同目录\\data”（便携模式）。
只存少量偏好（是否看过正版提示、自定义下载源、上次安装目录等），
不保存任何账号、令牌或隐私数据。
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List, Optional

APP_DIRNAME = "MCD"
_APP_DIR: Optional[str] = None


def _writable(directory: str) -> bool:
    try:
        os.makedirs(directory, exist_ok=True)
        probe = os.path.join(directory, ".mcd-write-test")
        with open(probe, "w", encoding="utf-8") as handle:
            handle.write("ok")
        os.remove(probe)
        return True
    except OSError:
        return False


def program_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def candidates() -> List[str]:
    items: List[str] = []
    override = os.environ.get("MCD_DATA_DIR")
    if override:
        items.append(override)
    for base in (os.environ.get("APPDATA"), os.environ.get("LOCALAPPDATA")):
        if base:
            items.append(os.path.join(base, APP_DIRNAME))
    items.append(os.path.join(program_dir(), "data"))
    items.append(os.path.join(os.environ.get("TEMP") or os.path.expanduser("~"), APP_DIRNAME))
    return items


def app_dir() -> str:
    """第一个可写的候选目录；结果缓存，避免每次读写都探测。"""
    global _APP_DIR
    if _APP_DIR:
        return _APP_DIR
    for path in candidates():
        if _writable(path):
            _APP_DIR = path
            return path
    # 理论上到不了这里；真到了就返回首选路径，由调用方决定怎么处理
    _APP_DIR = candidates()[0]
    return _APP_DIR


def config_path() -> str:
    return os.path.join(app_dir(), "config.json")


def cache_dir() -> str:
    """与安装目录无关的缓存位置（版本清单等），避免在用户选定目录前就落盘。"""
    return os.path.join(app_dir(), "cache")


def load() -> Dict[str, Any]:
    """读配置；优先读可写目录，也兼容历史位置。"""
    for path in [config_path()] + [os.path.join(item, "config.json") for item in candidates()]:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                return data
        except (OSError, ValueError):
            continue
    return {}


def save(data: Dict[str, Any]) -> None:
    directory = app_dir()
    path = os.path.join(directory, "config.json")
    os.makedirs(directory, exist_ok=True)
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
