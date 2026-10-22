"""从 PyPI 镜像的 simple 索引直接取 wheel 并解包（pip 不可用时的兜底）。

用法：
    python fetch_wheels.py --dest-wheels D:\\build\\wheels --dest-lib D:\\build\\pylib

解包后的目录配合 PYTHONPATH 即可使用 PyInstaller，无需安装到 site-packages。
"""
from __future__ import annotations

import argparse
import os
import re
import time
import urllib.parse
import urllib.request
import zipfile

MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"
PACKAGES = ["pyinstaller", "pyinstaller-hooks-contrib", "altgraph", "pefile", "pywin32-ctypes", "packaging"]
UA = {"User-Agent": "mcd-build/1.0"}


def version_key(text: str):
    parts = []
    for piece in re.split(r"[._-]", text):
        parts.append((1, int(piece)) if piece.isdigit() else (0, piece))
    return tuple(parts)


def compatible(filename: str) -> bool:
    if not filename.endswith(".whl"):
        return False
    lower = filename.lower()
    if "win_amd64" not in lower and not lower.endswith("-none-any.whl"):
        return False
    if "cp3" in lower and "cp311" not in lower:
        return False
    return True


def fetch(package: str, dest: str) -> str:
    index = "%s/%s/" % (MIRROR, package)
    html = urllib.request.urlopen(urllib.request.Request(index, headers=UA), timeout=30).read().decode("utf-8", "replace")
    prefix = package.lower().replace("-", "_") + "-"
    best = None
    for link in re.findall(r'href="([^"]+)"', html):
        filename = urllib.parse.urlsplit(link).path.rstrip("/").split("/")[-1]
        if not filename.lower().startswith(prefix) or not compatible(filename):
            continue
        version = filename[len(prefix):].split("-")[0]
        if not version:
            continue
        key = version_key(version)
        if best is None or key > best[0]:
            best = (key, filename, urllib.parse.urljoin(index, link.split("#")[0]))
    if not best:
        raise SystemExit("找不到 %s 的兼容 wheel" % package)
    _, filename, url = best
    target = os.path.join(dest, filename)
    if not os.path.exists(target):
        started = time.time()
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as response:
            data = response.read()
        with open(target, "wb") as handle:
            handle.write(data)
        print("  %-46s %7.1f KB  %.1fs" % (filename, len(data) / 1024, time.time() - started))
    else:
        print("  %-46s cached" % filename)
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dest-wheels", required=True)
    parser.add_argument("--dest-lib", required=True)
    args = parser.parse_args()
    os.makedirs(args.dest_wheels, exist_ok=True)
    os.makedirs(args.dest_lib, exist_ok=True)
    print("下载 wheel：")
    files = [fetch(name, args.dest_wheels) for name in PACKAGES]
    print("解包到 %s" % args.dest_lib)
    for path in files:
        with zipfile.ZipFile(path) as archive:
            archive.extractall(args.dest_lib)
    print("完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
