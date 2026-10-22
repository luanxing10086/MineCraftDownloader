"""整合包下载：支持 Modrinth 的 .mrpack。

支持的输入：
    * 本地 .mrpack 文件
    * .mrpack 直链（https://cdn.modrinth.com/...）
    * Modrinth 项目 slug          e.g. fabulously-optimized
    * slug@版本号                 e.g. fabulously-optimized@1.2.3
    * modrinth.com 项目页面链接

流程：按 dependencies 安装原版 → 安装对应加载器 → 按 index 下载文件 → 解包 overrides。
"""

from __future__ import annotations

import json
import os
import shutil
import zipfile
from typing import Dict, Optional, Tuple

from . import loaders as loader_mod
from . import vanilla
from .mirror import Mirror
from .net import Reporter, download, download_many, fetch_json
from .rules import Context

MODRINTH_API = "https://api.modrinth.com/v2"
UA_NOTE = "application/json"


class ModpackError(RuntimeError):
    """整合包无法安装。"""


# ---------------------------------------------------------------- 来源解析


def _download_pack(url: str, target: str, proxy: Optional[str], reporter: Optional[Reporter]) -> str:
    download(target, [url], proxy=proxy, reporter=reporter, label=os.path.basename(target))
    return target


def _pick_modrinth_version(versions, want: Optional[str]):
    if not versions:
        raise ModpackError("Modrinth 项目没有任何版本")
    if want:
        for item in versions:
            if item.get("id") == want or item.get("version_number") == want:
                return item
        raise ModpackError("找不到整合包版本 %r" % want)
    for item in versions:
        if item.get("version_type") == "release" and item.get("files"):
            return item
    return versions[0]


def _mrpack_file(version: dict) -> str:
    for item in version.get("files", []):
        if item.get("filename", "").endswith(".mrpack"):
            return item["url"]
    raise ModpackError("该 Modrinth 版本没有 .mrpack 文件")


def resolve_source(
    source: str,
    game_dir: str,
    proxy: Optional[str] = None,
    reporter: Optional[Reporter] = None,
) -> Tuple[str, Dict]:
    """返回 (本地 zip 路径, 元信息)。元信息用于日志与结果展示。"""
    cache_dir = os.path.join(game_dir, ".mcd", "packs")
    os.makedirs(cache_dir, exist_ok=True)

    if os.path.isfile(source):
        return source, {"source": "file", "name": os.path.basename(source), "version": ""}

    if source.startswith("http://") or source.startswith("https://"):
        if source.endswith(".mrpack") or "cdn.modrinth.com" in source:
            name = os.path.basename(source.split("?")[0]) or "pack.mrpack"
            target = os.path.join(cache_dir, name)
            _download_pack(source, target, proxy, reporter)
            return target, {"source": "url", "name": name, "version": ""}
        slug = _slug_from_url(source)
        return _from_modrinth(slug, None, cache_dir, proxy, reporter)

    if "@" in source:
        slug, want = source.split("@", 1)
        return _from_modrinth(slug, want, cache_dir, proxy, reporter)

    return _from_modrinth(source, None, cache_dir, proxy, reporter)


def _slug_from_url(url: str) -> str:
    parts = [piece for piece in url.split("/") if piece]
    if "modpack" in parts:
        index = parts.index("modpack")
        if index + 1 < len(parts):
            return parts[index + 1]
    raise ModpackError("无法从链接解析 Modrinth 项目：%s" % url)


def _from_modrinth(slug: str, want: Optional[str], cache_dir: str,
                   proxy: Optional[str], reporter: Optional[Reporter]) -> Tuple[str, Dict]:
    project = fetch_json(["%s/project/%s" % (MODRINTH_API, slug)], proxy=proxy)
    versions = fetch_json(["%s/project/%s/version" % (MODRINTH_API, slug)], proxy=proxy)
    chosen = _pick_modrinth_version(versions, want)
    url = _mrpack_file(chosen)
    filename = os.path.basename(url.split("?")[0])
    target = os.path.join(cache_dir, filename)
    _download_pack(url, target, proxy, reporter)
    return target, {
        "source": "modrinth",
        "name": project.get("title") or slug,
        "slug": slug,
        "version": chosen.get("version_number") or chosen.get("id"),
    }


# ---------------------------------------------------------------- 解析 index


def read_index(zip_path: str) -> dict:
    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        if "modrinth.index.json" not in names:
            if "manifest.json" in names:
                raise ModpackError(
                    "这是 CurseForge 格式的整合包。CurseForge 下载需要 API Key，"
                    "建议改用 Modrinth 版本，或先用启动器导出为 .mrpack。"
                )
            raise ModpackError("压缩包里没有 modrinth.index.json，不是 .mrpack 整合包")
        return json.loads(archive.read("modrinth.index.json").decode("utf-8"))


def loader_from_dependencies(dependencies: Dict) -> Tuple[Optional[str], Optional[str]]:
    for key, name in (
        ("fabric-loader", "fabric"),
        ("quilt-loader", "quilt"),
        ("forge", "forge"),
        ("neoforge", "neoforge"),
    ):
        if dependencies.get(key):
            return name, str(dependencies[key])
    return None, None


# ---------------------------------------------------------------- 解包 overrides


def _safe_target(root: str, relative: str) -> str:
    candidate = os.path.abspath(os.path.join(root, relative))
    root_abs = os.path.abspath(root)
    if not (candidate == root_abs or candidate.startswith(root_abs + os.sep)):
        raise ModpackError("压缩包内路径越界：%s" % relative)
    return candidate


def extract_overrides(zip_path: str, game_dir: str) -> int:
    """把 overrides/ 与 client-overrides/ 铺到实例目录；返回文件数。"""
    count = 0
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            if member.is_dir():
                continue
            name = member.filename
            relative = None
            for prefix in ("overrides/", "client-overrides/"):
                if name.startswith(prefix):
                    relative = name[len(prefix):]
                    break
            if not relative:
                continue
            target = _safe_target(game_dir, relative)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with archive.open(member) as source, open(target, "wb") as handle:
                shutil.copyfileobj(source, handle)
            count += 1
    return count


# ---------------------------------------------------------------- 安装


def install(
    source: str,
    game_dir: str = "minecraft",
    mirror: Optional[Mirror] = None,
    proxy: Optional[str] = None,
    threads: int = 8,
    reporter: Optional[Reporter] = None,
    skip_assets: bool = False,
    java_path: Optional[str] = None,
    dry_run: bool = False,
    context: Optional[Context] = None,
) -> Dict:
    mirror = mirror or Mirror()
    context = context or Context()
    os.makedirs(game_dir, exist_ok=True)

    zip_path, meta = resolve_source(source, game_dir, proxy=proxy, reporter=reporter)
    index = read_index(zip_path)
    dependencies = index.get("dependencies") or {}
    game = dependencies.get("minecraft")
    if not game:
        raise ModpackError("index 里没有写 dependencies.minecraft")
    loader_name, loader_version = loader_from_dependencies(dependencies)

    files = [item for item in index.get("files", []) if (item.get("env") or {}).get("client") != "unsupported"]
    total_size = sum(int(item.get("fileSize") or 0) for item in files)

    if dry_run:
        return {
            "pack": meta.get("name"),
            "version": meta.get("version"),
            "minecraft": game,
            "loader": loader_name,
            "loader_version": loader_version,
            "files": len(files),
            "bytes": total_size,
            "dry_run": True,
            "index": index,
        }

    # 1) 原版
    vanilla.install(
        game, game_dir, mirror=mirror, proxy=proxy, threads=threads,
        reporter=reporter, skip_assets=skip_assets, context=context,
    )

    # 2) 加载器
    loader_result = None
    if loader_name == "fabric":
        loader_result = loader_mod.install_fabric(
            game, loader_version, game_dir, mirror, proxy, threads, reporter, skip_assets, context=context)
    elif loader_name == "quilt":
        loader_result = loader_mod.install_quilt(
            game, loader_version, game_dir, mirror, proxy, threads, reporter, skip_assets, context=context)
    elif loader_name == "forge":
        loader_result = loader_mod.install_forge(
            game, loader_version, game_dir, mirror, proxy, java_path, threads, reporter, skip_assets)
    elif loader_name == "neoforge":
        loader_result = loader_mod.install_neoforge(
            game, loader_version, game_dir, mirror, proxy, java_path, threads, reporter, skip_assets)

    # 3) 整合包内文件（mods / config / resourcepacks ...）
    tasks = []
    for item in files:
        downloads = item.get("downloads") or []
        if not downloads:
            continue
        hashes = item.get("hashes") or {}
        tasks.append({
            "dest": _safe_target(game_dir, item["path"]),
            "urls": downloads,
            "sha1": hashes.get("sha1"),
            "size": item.get("fileSize"),
            "label": item["path"],
        })
    failures = download_many(tasks, proxy=proxy, threads=threads, reporter=reporter)
    if failures:
        raise ModpackError("整合包文件下载失败：\n  " + "\n  ".join(failures[:8]))

    # 4) overrides
    extracted = extract_overrides(zip_path, game_dir)

    # 5) 留一份 index 便于追溯与后续更新
    index_copy = os.path.join(game_dir, "modrinth.index.json")
    with open(index_copy, "w", encoding="utf-8") as handle:
        json.dump(index, handle, ensure_ascii=False, indent=2)

    return {
        "pack": meta.get("name"),
        "version": meta.get("version"),
        "minecraft": game,
        "loader": loader_name,
        "loader_version": loader_version,
        "loader_id": (loader_result or {}).get("id"),
        "files": len(files),
        "bytes": total_size,
        "overrides": extracted,
        "dir": os.path.abspath(game_dir),
    }
