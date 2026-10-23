"""第三方下载源：导入、校验、转换为 Mirror。

格式（JSON，保存到 %APPDATA%\\MCD\\config.json 的 sources 数组）：

    {
      "name": "我的镜像",
      "base": "https://mirror.example.com",
      "templates": {
        "manifest":     "{base}/mc/game/version_manifest_v2.json",
        "version_json": "{base}/version/{id}/json",
        "client":       "{base}/version/{id}/client"
      },
      "rules": [
        ["https://resources.download.minecraft.net/", "{base}/assets/"],
        ["https://libraries.minecraft.net/", "{base}/maven/"]
      ]
    }

templates / rules 都是可选的：缺哪个就回退官方地址；规则命中 404 时也会自动回退。
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from . import config
from .mirror import CUSTOM, Mirror

EXAMPLE: Dict[str, Any] = {
    "name": "示例镜像",
    "base": "https://mirror.example.com",
    "templates": {
        "manifest": "{base}/mc/game/version_manifest_v2.json",
        "version_json": "{base}/version/{id}/json",
        "client": "{base}/version/{id}/client",
    },
    "rules": [
        ["https://resources.download.minecraft.net/", "{base}/assets/"],
        ["https://libraries.minecraft.net/", "{base}/maven/"],
    ],
}


def example_path() -> str:
    return os.path.join(config.app_dir(), "source-example.json")


def write_example() -> str:
    path = example_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(EXAMPLE, handle, ensure_ascii=False, indent=2)
    return path


def validate(raw: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    if not isinstance(raw, dict):
        return ["源文件必须是 JSON 对象"]
    if not str(raw.get("name") or "").strip():
        errors.append("缺少 name")
    base = str(raw.get("base") or "").strip()
    if not base:
        errors.append("缺少 base（镜像根地址）")
    elif not (base.startswith("http://") or base.startswith("https://")):
        errors.append("base 必须以 http:// 或 https:// 开头")
    templates = raw.get("templates") or {}
    if templates and not isinstance(templates, dict):
        errors.append("templates 必须是对象")
    else:
        for key in ("manifest", "version_json", "client"):
            template = templates.get(key)
            if template and "{base}" not in template:
                errors.append("templates.%s 里缺少 {base}" % key)
            if template and key in ("version_json", "client") and "{id}" not in template:
                errors.append("templates.%s 里缺少 {id}" % key)
    rules = raw.get("rules") or []
    if rules and not isinstance(rules, list):
        errors.append("rules 必须是数组")
    else:
        for index, rule in enumerate(rules):
            if not (isinstance(rule, list) and len(rule) == 2 and all(isinstance(x, str) for x in rule)):
                errors.append("rules[%d] 必须是 [前缀, 替换] 两个字符串" % index)
    return errors


def load_sources() -> List[Dict[str, Any]]:
    data = config.load().get("sources") or []
    return [item for item in data if isinstance(item, dict) and item.get("name")]


def save_sources(items: List[Dict[str, Any]]) -> None:
    data = config.load()
    data["sources"] = items
    config.save(data)


def add_source(raw: Dict[str, Any]) -> None:
    errors = validate(raw)
    if errors:
        raise ValueError("；".join(errors))
    items = [item for item in load_sources() if item.get("name") != raw["name"]]
    items.append(raw)
    save_sources(items)


def remove_source(name: str) -> None:
    save_sources([item for item in load_sources() if item.get("name") != name])


def to_mirror(raw: Dict[str, Any]) -> Mirror:
    rules = [(rule[0], rule[1]) for rule in (raw.get("rules") or [])]
    return Mirror(
        CUSTOM,
        base=str(raw.get("base") or ""),
        templates=raw.get("templates") or {},
        rules=rules,
        label="自定义源：%s" % raw.get("name"),
    )
