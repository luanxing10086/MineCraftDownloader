"""原版（vanilla）安装：完全按照 Mojang 的 launcher 目录规范落盘。

产出结构：
    <dir>/versions/<id>/<id>.json
    <dir>/versions/<id>/<id>.jar
    <dir>/versions/<id>/natives/            (仅老版本的原生库)
    <dir>/libraries/<maven 路径>
    <dir>/assets/indexes/<assetIndex.id>.json
    <dir>/assets/objects/<hh>/<hash>
    <dir>/assets/log_configs/<logging 文件名>
    <dir>/assets/virtual/<id>/...           (pre-1.6 的虚拟资源)
    <dir>/resources/...                     (极老版本的 map_to_resources)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
import zipfile
from typing import Dict, List, Optional

from .mirror import Mirror
from .net import DownloadError, Reporter, download, download_many, fetch_json, open_url
from .rules import Context, allowed, maven_path, native_classifier

MANIFEST_OFFICIAL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
ASSET_BASE = "https://resources.download.minecraft.net"


class InstallError(RuntimeError):
    """安装流程无法继续。"""


# ---------------------------------------------------------------- 路径helper


def version_dir(game_dir: str, version_id: str) -> str:
    return os.path.join(game_dir, "versions", version_id)


def version_json_path(game_dir: str, version_id: str) -> str:
    return os.path.join(version_dir(game_dir, version_id), version_id + ".json")


def version_jar_path(game_dir: str, version_id: str) -> str:
    return os.path.join(version_dir(game_dir, version_id), version_id + ".jar")


def load_local_version(game_dir: str, version_id: str) -> Optional[dict]:
    path = version_json_path(game_dir, version_id)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def rename_version(game_dir: str, old_id: str, new_id: str) -> str:
    """把已装好的版本改名为 new_id（目录、json 文件名、json 里的 id、jar 名一起改）。

    启动器要求 “版本目录名 == json 里的 id”，所以这三处必须一起改。
    """
    old_id = (old_id or "").strip()
    new_id = (new_id or "").strip()
    if not old_id or not new_id:
        raise InstallError("版本名不能为空")
    if old_id == new_id:
        return version_dir(game_dir, old_id)
    if re.search(r'[<>:"/\\|?*]', new_id) or new_id in (".", ".."):
        raise InstallError("版本名不能包含 \\ / : * ? \" < > | 这些字符")
    old_dir = version_dir(game_dir, old_id)
    new_dir = version_dir(game_dir, new_id)
    if not os.path.isdir(old_dir):
        raise InstallError("找不到要改名的版本目录：%s" % old_dir)
    if os.path.exists(new_dir):
        raise InstallError("目标版本名已存在：%s" % new_id)

    os.rename(old_dir, new_dir)

    old_json = os.path.join(new_dir, old_id + ".json")
    if os.path.exists(old_json):
        with open(old_json, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        data["id"] = new_id
        with open(os.path.join(new_dir, new_id + ".json"), "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        os.remove(old_json)

    old_jar = os.path.join(new_dir, old_id + ".jar")
    if os.path.exists(old_jar):
        os.replace(old_jar, os.path.join(new_dir, new_id + ".jar"))
    return new_dir


def write_version_json(game_dir: str, version_id: str, data: dict) -> str:
    path = version_json_path(game_dir, version_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    return path


# ---------------------------------------------------------------- 版本清单


def _manifest_cache_path(game_dir: str) -> str:
    return os.path.join(game_dir, ".mcd", "version_manifest_v2.json")


def load_manifest(
    game_dir: str,
    mirror: Mirror,
    proxy: Optional[str] = None,
    max_age: int = 3600,
    refresh: bool = False,
    cache_dir: Optional[str] = None,
) -> dict:
    """带 1 小时缓存的版本清单，离线时回退到旧缓存。

    cache_dir 用于把缓存放到别处（GUI 在用户还没确认安装目录时用），
    避免仅仅为了拉清单就把 .minecraft 目录建出来。
    """
    cache = (os.path.join(cache_dir, "version_manifest_v2.json")
             if cache_dir else _manifest_cache_path(game_dir))
    if not refresh and os.path.exists(cache) and time.time() - os.path.getmtime(cache) < max_age:
        try:
            with open(cache, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except ValueError:
            pass

    urls = mirror.manifest_urls()
    try:
        manifest = fetch_json(urls, proxy=proxy)
    except DownloadError:
        if os.path.exists(cache):
            with open(cache, "r", encoding="utf-8") as handle:
                return json.load(handle)
        raise

    # 缓存写不进去不影响使用（例如系统禁止程序写系统盘时）
    try:
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        with open(cache, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle)
    except OSError:
        pass
    return manifest


def find_version_entry(manifest: dict, version_id: str) -> dict:
    for entry in manifest.get("versions", []):
        if entry.get("id") == version_id:
            return entry
    raise InstallError("版本清单里没有 %r（可用 mcd list 查看）" % version_id)


def list_versions(manifest: dict, kind: str = "release") -> List[dict]:
    versions = manifest.get("versions", [])
    if kind == "all":
        return versions
    if kind in ("release", "snapshot"):
        return [item for item in versions if item.get("type") == kind]
    raise InstallError("未知版本类型 %r（release / snapshot / all）" % kind)


# ---------------------------------------------------------------- libraries


def collect_libraries(version: dict, game_dir: str, context: Context) -> List[Dict]:
    """展开要下载的库，附带目标路径；natives 单独标记以便解压。"""
    targets: List[Dict] = []
    seen = set()

    def add(target: Dict) -> None:
        if target["dest"] in seen:
            return
        seen.add(target["dest"])
        targets.append(target)

    for library in version.get("libraries", []):
        if not allowed(library, context):
            continue
        artifact = (library.get("downloads") or {}).get("artifact")
        if artifact and artifact.get("url"):
            add({
                "name": artifact.get("path") or maven_path(library["name"]),
                "dest": os.path.join(game_dir, "libraries", artifact["path"]),
                "urls": [artifact["url"]],
                "sha1": artifact.get("sha1"),
                "size": artifact.get("size"),
            })
        elif library.get("url") and library.get("name"):
            # Fabric / Quilt 风格：url 是仓库根，sha1 直接挂在 library 上
            relative = maven_path(library["name"])
            add({
                "name": relative,
                "dest": os.path.join(game_dir, "libraries", relative),
                "urls": [library["url"].rstrip("/") + "/" + relative],
                "sha1": library.get("sha1"),
                "size": library.get("size"),
            })

    for library in version.get("libraries", []):
        if not allowed(library, context):
            continue
        classifier = native_classifier(library, context)
        if not classifier:
            continue
        downloads = (library.get("downloads") or {}).get("classifiers") or {}
        classified = downloads.get(classifier)
        if not classified:
            continue
        relative = classified.get("path") or maven_path("%s:%s" % (library["name"], classifier))
        add({
            "name": relative,
            "dest": os.path.join(game_dir, "libraries", relative),
            "urls": [classified["url"]],
            "sha1": classified.get("sha1"),
            "size": classified.get("size"),
            "extract_to": os.path.join(version_dir(game_dir, version["id"]), "natives"),
            "exclude": (library.get("extract") or {}).get("exclude") or [],
        })
    return targets


def extract_natives(targets: List[Dict], reporter: Optional[Reporter] = None) -> int:
    extracted = 0
    for target in targets:
        if not target.get("extract_to"):
            continue
        destination = target["extract_to"]
        os.makedirs(destination, exist_ok=True)
        excluded = target.get("exclude") or []
        with zipfile.ZipFile(target["dest"]) as archive:
            for member in archive.namelist():
                if member.endswith("/") or member.startswith("META-INF"):
                    continue
                if any(member.startswith(prefix) for prefix in excluded):
                    continue
                archive.extract(member, destination)
                extracted += 1
    return extracted


# ---------------------------------------------------------------- assets


def install_assets(
    version: dict,
    game_dir: str,
    mirror: Mirror,
    proxy: Optional[str],
    reporter: Optional[Reporter],
    threads: int,
) -> Dict:
    index_info = version.get("assetIndex") or {}
    if not index_info.get("url"):
        return {"objects": 0, "bytes": 0}

    index_id = index_info.get("id") or index_info.get("sha1") or version["id"]
    index_path = os.path.join(game_dir, "assets", "indexes", index_id + ".json")
    # 资源索引没有被 BMCLAPI 镜像，直接用官方地址（仍保留回退顺序）
    download(
        index_path,
        mirror.urls(index_info["url"]),
        sha1=index_info.get("sha1"),
        size=index_info.get("size"),
        proxy=proxy,
        reporter=reporter,
        label="assets/indexes/%s.json" % index_id,
    )
    with open(index_path, "r", encoding="utf-8") as handle:
        index = json.load(handle)

    objects = index.get("objects") or {}

    # BMCLAPI 的 /assets 会 302 到境外节点（实测 0.3 文件/秒），官方源是 9 文件/秒。
    # 先探测一次官方源是否可用，可用就把它排在前面，不通再退回镜像。
    official_first = False
    if mirror.is_mirror and objects:
        probe_hash = next(iter(objects.values()))["hash"]
        probe_url = "%s/%s/%s" % (ASSET_BASE, probe_hash[:2], probe_hash)
        try:
            with open_url(probe_url, proxy=proxy, timeout=8) as response:
                response.read(1)
            official_first = True
        except Exception:  # noqa: BLE001 - 探测失败就用镜像
            official_first = False

    tasks = []
    for name, info in objects.items():
        digest = info["hash"]
        official_url = "%s/%s/%s" % (ASSET_BASE, digest[:2], digest)
        urls = mirror.urls(official_url)
        if official_first:
            urls = [official_url] + [item for item in urls if item != official_url]
        tasks.append({
            "dest": os.path.join(game_dir, "assets", "objects", digest[:2], digest),
            "urls": urls,
            "sha1": digest,
            "size": info.get("size"),
            "label": "objects/" + digest[:8],
        })

    failures = download_many(tasks, proxy=proxy, threads=max(threads, 16), reporter=reporter)
    if failures:
        raise InstallError("资源下载失败：\n  " + "\n  ".join(failures[:5]))

    _materialize_legacy_assets(version, game_dir, index_id, objects)
    return {"objects": len(tasks), "bytes": sum(item.get("size") or 0 for item in objects.values())}


def _materialize_legacy_assets(version: dict, game_dir: str, index_id: str, objects: Dict) -> None:
    """pre-1.6 需要把 objects 复制成按名字索引的目录结构。"""
    virtual_root = None
    if index_id == "legacy" or version.get("assets") == "pre-1.6":
        virtual_root = os.path.join(game_dir, "assets", "virtual", index_id)
    if virtual_root:
        for name, info in objects.items():
            source = os.path.join(game_dir, "assets", "objects", info["hash"][:2], info["hash"])
            target = os.path.join(virtual_root, name)
            if not os.path.exists(target) and os.path.exists(source):
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copy2(source, target)

    if version.get("map_to_resources"):
        for name, info in objects.items():
            source = os.path.join(game_dir, "assets", "objects", info["hash"][:2], info["hash"])
            target = os.path.join(game_dir, "resources", name)
            if not os.path.exists(target) and os.path.exists(source):
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copy2(source, target)


# ---------------------------------------------------------------- 日志配置


def install_logging(version: dict, game_dir: str, mirror: Mirror, proxy: Optional[str],
                    reporter: Optional[Reporter]) -> None:
    logging_config = ((version.get("logging") or {}).get("client") or {}).get("file")
    if not logging_config or not logging_config.get("url"):
        return
    name = logging_config.get("id") or os.path.basename(logging_config["url"])
    download(
        os.path.join(game_dir, "assets", "log_configs", name),
        mirror.urls(logging_config["url"]),
        sha1=logging_config.get("sha1"),
        size=logging_config.get("size"),
        proxy=proxy,
        reporter=reporter,
        label="assets/log_configs/" + name,
    )


# ---------------------------------------------------------------- 主流程


def install(
    version_id: str,
    game_dir: str,
    mirror: Optional[Mirror] = None,
    proxy: Optional[str] = None,
    threads: int = 8,
    reporter: Optional[Reporter] = None,
    skip_assets: bool = False,
    skip_client: bool = False,
    manifest: Optional[dict] = None,
    context: Optional[Context] = None,
) -> Dict:
    """下载一个原版版本到 game_dir，返回统计信息。"""
    mirror = mirror or Mirror()
    context = context or Context()
    os.makedirs(game_dir, exist_ok=True)

    manifest = manifest or load_manifest(game_dir, mirror, proxy=proxy)
    entry = find_version_entry(manifest, version_id)
    version_urls = mirror.version_json_urls(version_id, entry["url"])
    if mirror.is_mirror:
        # 镜像的 /version/<id>/json 会 302 到境外节点（实测 ~3s），官方通常更快
        official = entry["url"]
        try:
            with open_url(official, proxy=proxy, timeout=8) as response:
                response.read(1)
            version_urls = [official] + [item for item in version_urls if item != official]
        except Exception:  # noqa: BLE001 - 不通就继续用镜像
            pass
    version = fetch_json(version_urls, proxy=proxy)
    version["id"] = version.get("id") or version_id

    written = write_version_json(game_dir, version_id, version)
    if reporter:
        reporter.done("versions/%s/%s.json" % (version_id, version_id), os.path.getsize(written))

    stats = {"version": version_id, "files": 0, "bytes": 0, "skipped": 0, "assets": None}

    # 先把这一版的已知体积登记给进度条（库 + 资源），再开始下载，
    # 这样总进度不会因为阶段切换而先满后退。
    libraries = collect_libraries(version, game_dir, context)
    if reporter is not None and hasattr(reporter, "expect"):
        estimate = sum(int(item.get("size") or 0) for item in libraries)
        if not skip_assets:
            estimate += int((version.get("assetIndex") or {}).get("totalSize") or 0)
        reporter.expect(estimate)

    # 客户端主 jar
    if not skip_client:
        client = (version.get("downloads") or {}).get("client")
        if client and client.get("url"):
            download(
                version_jar_path(game_dir, version_id),
                mirror.client_urls(version_id, client["url"]),
                sha1=client.get("sha1"),
                size=client.get("size"),
                proxy=proxy,
                reporter=reporter,
                label="versions/%s/%s.jar" % (version_id, version_id),
            )

    # 依赖库 + 原生库
    failures = download_many(libraries, proxy=proxy, threads=threads, reporter=reporter)
    if failures:
        raise InstallError("依赖库下载失败：\n  " + "\n  ".join(failures[:5]))
    if extract_natives(libraries, reporter):
        pass

    # 资源
    if not skip_assets:
        stats["assets"] = install_assets(version, game_dir, mirror, proxy, reporter, threads)
    install_logging(version, game_dir, mirror, proxy, reporter)

    if reporter:
        stats["files"] = reporter.done_files
        stats["bytes"] = reporter.total_bytes
        stats["skipped"] = reporter.skipped_files
    return stats
