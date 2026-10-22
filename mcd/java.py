"""Java 探测：为 Forge / NeoForge 的 installer 选出合适的运行时。

只做探测与选择，不下载 JDK（本项目只负责 Minecraft 相关文件）。
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import sys
from typing import List, Optional, Tuple

_JAVA_VERSION_RE = re.compile(r'version "(\d+)(?:\.(\d+))?')


def _exe(name: str) -> str:
    return name + ".exe" if sys.platform.startswith("win") else name


def java_major(path: str) -> Optional[int]:
    """执行 java -version 解析主版本号，失败返回 None。"""
    try:
        completed = subprocess.run(
            [path, "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = completed.stdout.decode("utf-8", "replace")
    match = _JAVA_VERSION_RE.search(output)
    if not match:
        return None
    major = int(match.group(1))
    if major == 1 and match.group(2):
        return int(match.group(2))
    return major


def candidates() -> List[str]:
    """按常见安装位置收集 java 可执行文件。"""
    found: List[str] = []
    exe = _exe("java")

    home = os.environ.get("JAVA_HOME")
    if home:
        found.append(os.path.join(home, "bin", exe))

    which = shutil.which("java")
    if which:
        found.append(which)

    patterns: List[str] = []
    if sys.platform.startswith("win"):
        patterns += [
            r"C:\Program Files\Java\*\bin\java.exe",
            r"C:\Program Files\Eclipse Adoptium\*\bin\java.exe",
            r"C:\Program Files\Microsoft\jdk*\bin\java.exe",
            r"C:\Program Files\Zulu\*\bin\java.exe",
            r"C:\Program Files\BellSoft\*\bin\java.exe",
            r"%LOCALAPPDATA%\Programs\Eclipse Adoptium\*\bin\java.exe",
        ]
        for pattern in patterns:
            expanded = os.path.expandvars(pattern)
            found.extend(glob.glob(expanded))
    else:
        found.extend(glob.glob("/usr/lib/jvm/*/bin/java"))
        found.extend(glob.glob("/Library/Java/JavaVirtualMachines/*/Contents/Home/bin/java"))

    seen = set()
    unique: List[str] = []
    for path in found:
        if not path:
            continue
        normalized = os.path.normcase(os.path.abspath(path))
        if normalized in seen or not os.path.exists(path):
            continue
        seen.add(normalized)
        unique.append(path)
    return unique


def inventory() -> List[Tuple[str, Optional[int]]]:
    return [(path, java_major(path)) for path in candidates()]


def pick(required: Optional[int] = None, explicit: Optional[str] = None) -> Optional[str]:
    """选一个够用的 Java：优先显式指定，其次满足要求的最小版本。"""
    if explicit:
        return explicit
    known = [(path, major) for path, major in inventory() if major]
    if not known:
        return None
    if required:
        usable = [(path, major) for path, major in known if major >= required]
        if usable:
            usable.sort(key=lambda item: item[1])
            return usable[0][0]
        known.sort(key=lambda item: item[1], reverse=True)
        return known[0][0]
    known.sort(key=lambda item: item[1], reverse=True)
    return known[0][0]
