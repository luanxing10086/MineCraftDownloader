"""libraries 规则求值与 maven 坐标处理。

Mojang 的规则模型：
    没有 rules          -> 允许
    有 rules            -> 默认拒绝，按顺序命中后以该条 action 覆盖
    命中条件            -> os.name / os.arch / os.version / features 全部匹配
"""

from __future__ import annotations

import platform
import re
from dataclasses import dataclass, field
from typing import Dict, Optional

_WINDOWS = "windows"
_OSX = "osx"
_LINUX = "linux"


def current_os() -> str:
    system = platform.system().lower()
    if system.startswith("win"):
        return _WINDOWS
    if system == "darwin":
        return _OSX
    return _LINUX


def current_arch() -> str:
    machine = platform.machine().lower()
    if machine in ("amd64", "x86_64", "x64"):
        return "x86_64"
    if machine in ("x86", "i386", "i686"):
        return "x86"
    if machine in ("aarch64", "arm64"):
        return "arm64"
    return machine


@dataclass
class Context:
    """求值上下文；features 默认全 False（等价于“只下载必需文件”）。"""

    os_name: str = field(default_factory=current_os)
    arch: str = field(default_factory=current_arch)
    os_version: str = field(default_factory=platform.release)
    features: Dict[str, bool] = field(default_factory=dict)

    def feature(self, key: str) -> bool:
        return bool(self.features.get(key, False))


def _matches(rule: Dict, ctx: Context) -> bool:
    os_rule = rule.get("os")
    if os_rule:
        if "name" in os_rule and os_rule["name"] != ctx.os_name:
            return False
        if "arch" in os_rule and os_rule["arch"] not in ("", None) and os_rule["arch"] != ctx.arch:
            return False
        if "version" in os_rule and os_rule["version"]:
            try:
                if not re.search(os_rule["version"], ctx.os_version):
                    return False
            except re.error:
                return False
    features = rule.get("features")
    if features:
        for key, expected in features.items():
            if ctx.feature(key) != bool(expected):
                return False
    return True


def allowed(library: Dict, ctx: Optional[Context] = None) -> bool:
    """判断某个 library 是否需要在当前平台下载。"""
    ctx = ctx or Context()
    rules = library.get("rules")
    if not rules:
        return True
    verdict = False
    for rule in rules:
        if _matches(rule, ctx):
            verdict = rule.get("action") == "allow"
    return verdict


def native_classifier(library: Dict, ctx: Optional[Context] = None) -> Optional[str]:
    """老版本（1.19 之前）用 natives 字典 + classifiers 描述本地库。"""
    ctx = ctx or Context()
    natives = library.get("natives")
    if not natives:
        return None
    template = natives.get(ctx.os_name)
    if not template:
        return None
    bits = "64" if ctx.arch in ("x86_64", "arm64") else "32"
    return template.replace("${arch}", bits)


def maven_path(coordinate: str) -> str:
    """net.fabricmc:fabric-loader:0.15.11 -> net/fabricmc/fabric-loader/0.15.11/fabric-loader-0.15.11.jar"""
    extension = "jar"
    coordinate = coordinate.strip()
    if "@" in coordinate:
        coordinate, extension = coordinate.rsplit("@", 1)
    parts = coordinate.split(":")
    if len(parts) < 3:
        raise ValueError("无法解析 maven 坐标：%r" % coordinate)
    group, artifact, version = parts[0], parts[1], parts[2]
    classifier = parts[3] if len(parts) > 3 else None
    filename = "%s-%s%s.%s" % (artifact, version, ("-" + classifier) if classifier else "", extension)
    return "%s/%s/%s/%s" % (group.replace(".", "/"), artifact, version, filename)
