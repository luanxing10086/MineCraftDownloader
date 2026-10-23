"""附加内容：通过 Modrinth 安装 Fabric API；以及任意 URL 的自定义下载。"""

from __future__ import annotations

import json
import os
import urllib.parse
from typing import Dict, List, Optional

from .net import DownloadError, Reporter, download, fetch_json

MODRINTH_API = "https://api.modrinth.com/v2"
FABRIC_API_SLUG = "fabric-api"


# ---------------------------------------------------------------- Fabric API


def list_fabric_api(game: str, proxy: Optional[str] = None) -> List[Dict]:
    """返回该游戏版本可用的 Fabric API 列表（新到旧）；查不到时返回空列表。"""
    filters = "game_versions=%s&loaders=%s" % (
        urllib.parse.quote('["%s"]' % game, safe=""),
        urllib.parse.quote('["fabric"]', safe=""),
    )
    url = "%s/project/%s/version?%s" % (MODRINTH_API, FABRIC_API_SLUG, filters)
    try:
        versions = fetch_json([url], proxy=proxy)
    except DownloadError:
        return []
    result = []
    for item in versions:
        file_info = None
        for candidate in item.get("files", []):
            if candidate.get("primary") or candidate.get("filename", "").endswith(".jar"):
                file_info = candidate
                break
        if not file_info:
            continue
        result.append({
            "version_number": item.get("version_number") or item.get("name"),
            "url": file_info["url"],
            "filename": file_info.get("filename") or os.path.basename(file_info["url"]),
            "sha1": (file_info.get("hashes") or {}).get("sha1"),
            "size": file_info.get("size"),
        })
    return result


def install_fabric_api(
    game: str,
    mods_dir: str,
    version_number: Optional[str] = None,
    proxy: Optional[str] = None,
    reporter: Optional[Reporter] = None,
) -> Dict:
    versions = list_fabric_api(game, proxy=proxy)
    if not versions:
        raise DownloadError("Modrinth 上找不到适用于 %s 的 Fabric API" % game)
    chosen = versions[0]
    if version_number and version_number not in ("最新", "自动"):
        for item in versions:
            if item["version_number"] == version_number:
                chosen = item
                break
    os.makedirs(mods_dir, exist_ok=True)
    dest = os.path.join(mods_dir, chosen["filename"])
    download(dest, [chosen["url"]], sha1=chosen["sha1"], size=chosen.get("size"),
             proxy=proxy, reporter=reporter, label="mods/" + chosen["filename"])
    return {"fabric_api": chosen["version_number"], "path": dest}


# ---------------------------------------------------------------- 自定义下载


def guess_filename(url: str) -> str:
    path = urllib.parse.urlsplit(url).path
    name = os.path.basename(path.rstrip("/"))
    return name or "download.bin"


def download_url(
    url: str,
    dest: str,
    proxy: Optional[str] = None,
    reporter: Optional[Reporter] = None,
) -> str:
    """把任意 URL 下载到 dest；dest 是目录时自动用 URL 里的文件名。"""
    if url.startswith("//"):
        url = "https:" + url
    if not (url.startswith("http://") or url.startswith("https://")):
        raise DownloadError("只支持 http/https 链接：%s" % url)
    if os.path.isdir(dest) or dest.endswith(os.sep):
        dest = os.path.join(dest, guess_filename(url))
    download(dest, [url], proxy=proxy, reporter=reporter, label=os.path.basename(dest))
    return dest


def read_mrpack_index(path: str) -> Optional[dict]:
    """如果是 .mrpack，返回 index；否则 None。"""
    if not path.lower().endswith(".mrpack"):
        return None
    import zipfile

    try:
        with zipfile.ZipFile(path) as archive:
            if "modrinth.index.json" in archive.namelist():
                return json.loads(archive.read("modrinth.index.json").decode("utf-8"))
    except (OSError, ValueError):
        return None
    return None
