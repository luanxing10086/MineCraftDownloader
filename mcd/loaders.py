"""加载器安装。

    Fabric / Quilt  读取官方 meta 的 profile JSON，直接落盘（无需 Java）
    Forge / NeoForge  下载官方 installer 并用 Java 执行 --installClient

Fabric/Quilt 的 profile JSON 里 inheritsFrom 指向原版，所以先确保原版已就绪。
Forge/NeoForge 的 installer 自己会写版本 JSON 与补丁后的客户端，这里只负责
调用与校验。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.parse
import zipfile
from typing import Dict, List, Optional, Set

from . import java, vanilla
from .mirror import BMCLAPI_BASE, Mirror
from .net import DownloadError, Reporter, download, download_many, fetch_bytes, fetch_json
from .rules import Context

FABRIC_META = "https://meta.fabricmc.net/v2"
QUILT_META = "https://meta.quiltmc.org/v3"
FORGE_MAVEN = "https://maven.minecraftforge.net"
FORGE_PROMOS = "https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json"
NEOFORGE_MAVEN = "https://maven.neoforged.net/releases"
NEOFORGE_GROUP = "net/neoforged/neoforge"


class InstallError(RuntimeError):
    """加载器安装失败。"""


# ---------------------------------------------------------------- 公共


def _ensure_vanilla(
    game: str,
    game_dir: str,
    mirror: Mirror,
    proxy: Optional[str],
    threads: int,
    reporter: Optional[Reporter],
    skip_assets: bool,
    refresh_manifest: bool = False,
) -> dict:
    local = vanilla.load_local_version(game_dir, game)
    if local and os.path.exists(vanilla.version_jar_path(game_dir, game)):
        return local
    vanilla.install(
        game,
        game_dir,
        mirror=mirror,
        proxy=proxy,
        threads=threads,
        reporter=reporter,
        skip_assets=skip_assets,
    )
    loaded = vanilla.load_local_version(game_dir, game)
    if not loaded:
        raise InstallError("原版 %s 安装后仍找不到版本 JSON" % game)
    return loaded


def _install_profile_libraries(
    profile: dict,
    game_dir: str,
    proxy: Optional[str],
    threads: int,
    reporter: Optional[Reporter],
    context: Context,
) -> List[Dict]:
    libraries = vanilla.collect_libraries(profile, game_dir, context)
    failures = download_many(libraries, proxy=proxy, threads=threads, reporter=reporter)
    if failures:
        raise InstallError("加载器依赖下载失败：\n  " + "\n  ".join(failures[:5]))
    return libraries


# ---------------------------------------------------------------- Fabric


def resolve_fabric_loader(game: str, proxy: Optional[str] = None) -> str:
    data = fetch_json(["%s/versions/loader/%s" % (FABRIC_META, game)], proxy=proxy)
    if not data:
        raise InstallError("Fabric 没有支持 Minecraft %s 的 loader" % game)
    return data[0]["loader"]["version"]


def install_fabric(
    game: str,
    loader_version: Optional[str] = None,
    game_dir: str = "minecraft",
    mirror: Optional[Mirror] = None,
    proxy: Optional[str] = None,
    threads: int = 8,
    reporter: Optional[Reporter] = None,
    skip_assets: bool = False,
    context: Optional[Context] = None,
) -> Dict:
    mirror = mirror or Mirror()
    context = context or Context()
    _ensure_vanilla(game, game_dir, mirror, proxy, threads, reporter, skip_assets)

    loader_version = loader_version or resolve_fabric_loader(game, proxy)
    url = "%s/versions/loader/%s/%s/profile/json" % (FABRIC_META, game, loader_version)
    profile = fetch_json([url], proxy=proxy)
    profile.setdefault("id", "fabric-loader-%s-%s" % (loader_version, game))

    vanilla.write_version_json(game_dir, profile["id"], profile)
    libraries = _install_profile_libraries(profile, game_dir, proxy, threads, reporter, context)
    return {
        "loader": "fabric",
        "id": profile["id"],
        "loader_version": loader_version,
        "libraries": len(libraries),
    }


# ---------------------------------------------------------------- Quilt


def resolve_quilt_loader(game: str, proxy: Optional[str] = None) -> str:
    data = fetch_json(["%s/versions/loader/%s" % (QUILT_META, game)], proxy=proxy)
    if not data:
        raise InstallError("Quilt 没有支持 Minecraft %s 的 loader" % game)
    return data[0]["loader"]["version"]


def install_quilt(
    game: str,
    loader_version: Optional[str] = None,
    game_dir: str = "minecraft",
    mirror: Optional[Mirror] = None,
    proxy: Optional[str] = None,
    threads: int = 8,
    reporter: Optional[Reporter] = None,
    skip_assets: bool = False,
    context: Optional[Context] = None,
) -> Dict:
    mirror = mirror or Mirror()
    context = context or Context()
    _ensure_vanilla(game, game_dir, mirror, proxy, threads, reporter, skip_assets)

    loader_version = loader_version or resolve_quilt_loader(game, proxy)
    url = "%s/versions/loader/%s/%s/profile/json" % (QUILT_META, game, loader_version)
    profile = fetch_json([url], proxy=proxy)
    profile.setdefault("id", "quilt-loader-%s-%s" % (loader_version, game))

    vanilla.write_version_json(game_dir, profile["id"], profile)
    libraries = _install_profile_libraries(profile, game_dir, proxy, threads, reporter, context)
    return {
        "loader": "quilt",
        "id": profile["id"],
        "loader_version": loader_version,
        "libraries": len(libraries),
    }


# ---------------------------------------------------------------- Forge


def resolve_forge_version(game: str, preferred: str = "recommended", proxy: Optional[str] = None) -> str:
    promos = fetch_json([FORGE_PROMOS], proxy=proxy)
    table = promos.get("promos") or {}
    for key in ("%s-%s" % (game, preferred), "%s-recommended" % game, "%s-latest" % game):
        if key in table:
            return table[key]
    raise InstallError("Forge 没有 Minecraft %s 的推荐版本，请用 --loader-version 指定" % game)


def _looks_like_forge_dir(name: str, game: str) -> bool:
    lowered = name.lower()
    return lowered.startswith(game.lower() + "-forge") or lowered.startswith("forge-")


def _snapshot_versions(game_dir: str) -> Set[str]:
    root = os.path.join(game_dir, "versions")
    if not os.path.isdir(root):
        return set()
    return {name for name in os.listdir(root) if os.path.isdir(os.path.join(root, name))}


def _detect_installed(game_dir: str, before: Set[str], game: str, hint: str) -> Optional[str]:
    after = _snapshot_versions(game_dir)
    fresh = [name for name in after - before if os.path.exists(vanilla.version_json_path(game_dir, name))]
    if len(fresh) == 1:
        return fresh[0]
    if hint in after and os.path.exists(vanilla.version_json_path(game_dir, hint)):
        return hint
    forge_like = [name for name in after if _looks_like_forge_dir(name, game)]
    if forge_like:
        forge_like.sort(key=lambda n: os.path.getmtime(vanilla.version_json_path(game_dir, n)))
        return forge_like[-1]
    return None


def _ensure_launcher_profiles(game_dir: str) -> None:
    """Forge/NeoForge 的 installer 会检查官方启动器的 profiles 文件，没有就直接报错退出。"""
    path = os.path.join(game_dir, "launcher_profiles.json")
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return
    payload = {
        "profiles": {},
        "selectedProfile": "",
        "clientToken": "",
        "authenticationDatabase": {},
        "launcherVersion": {"name": "", "format": 0},
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def _run_installer_tolerant(
    java_exe: Optional[str],
    jar_path: str,
    game_dir: str,
    proxy: Optional[str],
    expected_id: str,
) -> None:
    """installer 在“Injecting profile”阶段经常失败（会把 launcher_profiles.json 截断），
    但此时版本 JSON 与补丁后的 jar 已经写好，对下载器来说安装其实已经完成。"""
    try:
        run_installer(java_exe, jar_path, game_dir, proxy=proxy)
    except InstallError as exc:
        if os.path.exists(vanilla.version_json_path(game_dir, expected_id)):
            print("    installer 报错（launcher_profiles 注入失败），但版本文件已生成，继续。")
        else:
            raise exc
    finally:
        _ensure_launcher_profiles(game_dir)


def prefetch_installer_libraries(
    jar_path: str,
    game_dir: str,
    mirror: Mirror,
    proxy: Optional[str],
    threads: int,
    reporter: Optional[Reporter],
) -> int:
    """把 installer 内 install_profile.json 列出的依赖先下到 libraries/。

    Forge/NeoForge 的 installer 只有在文件缺失时才会联网；提前备齐后，
    即使 maven.neoforged.net 不可达也能完成安装（处理器都在本地跑）。
    """
    with zipfile.ZipFile(jar_path) as archive:
        names = archive.namelist()
        profile_name = "install_profile.json" if "install_profile.json" in names else None
        if not profile_name:
            return 0
        profile = json.loads(archive.read(profile_name).decode("utf-8"))

    tasks = []
    for library in profile.get("libraries") or []:
        artifact = (library.get("downloads") or {}).get("artifact")
        if not artifact or not artifact.get("url"):
            continue
        relative = artifact.get("path")
        if not relative:
            continue
        tasks.append({
            "dest": os.path.join(game_dir, "libraries", relative),
            "urls": mirror.urls(artifact["url"]),
            "sha1": artifact.get("sha1"),
            "size": artifact.get("size"),
            "label": relative,
        })
    if not tasks:
        return 0
    failures = download_many(tasks, proxy=proxy, threads=threads, reporter=reporter)
    if failures:
        hint = ""
        if mirror.is_mirror and any("403" in item for item in failures):
            hint = (
                "\n提示：BMCLAPI 的 /maven 没有完整代理 net.neoforged 依赖（返回 403），"
                "NeoForge 仍需 --proxy 或能直连 maven.neoforged.net 的网络。"
            )
        raise InstallError("installer 依赖预取失败：" + hint + "\n  " + "\n  ".join(failures[:5]))
    return len(tasks)


def run_installer(
    java_exe: Optional[str],
    jar_path: str,
    game_dir: str,
    proxy: Optional[str] = None,
    timeout: int = 1800,
) -> None:
    """执行 Forge / NeoForge installer 的客户端安装模式。"""
    if not java_exe:
        raise InstallError(
            "没有找到 Java。Forge/NeoForge 需要运行官方 installer，请安装 JDK（17 或 21）"
            "或用 --java 指定 java.exe 路径。"
        )
    command = [java_exe]
    if proxy:
        parsed = urllib.parse.urlparse(proxy)
        if parsed.hostname:
            for scheme in ("http", "https"):
                command.append("-D%s.proxyHost=%s" % (scheme, parsed.hostname))
                command.append("-D%s.proxyPort=%s" % (scheme, parsed.port or 8080))
    command += ["-jar", jar_path, "--installClient", game_dir]

    process = subprocess.Popen(
        command,
        cwd=game_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    assert process.stdout is not None
    lines: List[str] = []
    try:
        for raw in iter(process.stdout.readline, b""):
            line = raw.decode("utf-8", "replace").rstrip()
            if line:
                lines.append(line)
                print("    " + line)
        code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        raise InstallError("installer 超时（%ss）" % timeout)
    finally:
        process.stdout.close()

    if code != 0:
        tail = "\n".join(lines[-12:])
        raise InstallError("installer 退出码 %s\n%s" % (code, tail))


def install_forge(
    game: str,
    loader_version: Optional[str] = None,
    game_dir: str = "minecraft",
    mirror: Optional[Mirror] = None,
    proxy: Optional[str] = None,
    java_path: Optional[str] = None,
    threads: int = 8,
    reporter: Optional[Reporter] = None,
    skip_assets: bool = False,
) -> Dict:
    mirror = mirror or Mirror()
    version_json = _ensure_vanilla(game, game_dir, mirror, proxy, threads, reporter, skip_assets)
    forge_version = loader_version or resolve_forge_version(game, proxy=proxy)
    full = forge_version if forge_version.startswith(game + "-") else "%s-%s" % (game, forge_version)
    if not re.match(r"^%s-[0-9]" % re.escape(game), full):
        raise InstallError("Forge 版本号应形如 %s-47.4.10（收到 %r）" % (game, forge_version))

    url = "%s/net/minecraftforge/forge/%s/forge-%s-installer.jar" % (FORGE_MAVEN, full, full)
    jar_path = os.path.join(game_dir, ".mcd", "installers", "forge-%s-installer.jar" % full)
    download(jar_path, mirror.urls(url), proxy=proxy, reporter=reporter,
             label="installers/forge-%s-installer.jar" % full)
    if mirror.is_mirror:
        prefetched = prefetch_installer_libraries(jar_path, game_dir, mirror, proxy, threads, reporter)
        if prefetched:
            print("    预取 installer 依赖：%d 个文件（避免 installer 直连官方 maven）" % prefetched)

    required = (version_json.get("javaVersion") or {}).get("majorVersion")
    chosen_java = java.pick(required, java_path)
    before = _snapshot_versions(game_dir)
    _ensure_launcher_profiles(game_dir)
    print("    使用 Java：%s（需要 %s）" % (chosen_java, required or "未知"))
    expected_id = "%s-forge-%s" % (game, full[len(game) + 1:])
    _run_installer_tolerant(chosen_java, jar_path, game_dir, proxy, expected_id)

    installed = _detect_installed(game_dir, before, game, expected_id)
    if not installed:
        raise InstallError("installer 执行完毕但没找到新版本目录，请检查上面的输出")
    return {
        "loader": "forge",
        "id": installed,
        "loader_version": forge_version,
        "java": chosen_java,
    }


# ---------------------------------------------------------------- NeoForge


def _version_key(text: str):
    parts = []
    for piece in text.split("."):
        if not piece.isdigit():
            return None
        parts.append(int(piece))
    return tuple(parts)


def resolve_neoforge_version(
    game: str,
    mirror: Optional[Mirror] = None,
    proxy: Optional[str] = None,
    include_beta: bool = False,
) -> str:
    """NeoForge 版本号与游戏版本对应：1.21.1 -> 21.1.x。"""
    mirror = mirror or Mirror()
    pieces = game.split(".")
    if pieces[0] == "1" and len(pieces) >= 3:
        # 旧体系：1.21.1 -> 21.1.x
        prefix = "%s.%s." % (pieces[1], pieces[2])
    else:
        # 新体系（2026 起）：26.3 -> 26.3.x.y
        prefix = game + "."
    if len(pieces) < 2:
        raise InstallError("无法从 %r 推断 NeoForge 版本，请用 --loader-version 指定" % game)

    names: List[str] = []
    if mirror.is_mirror:
        detail = fetch_json(
            ["%s/neoforge/meta/api/maven/details/releases/%s" % (BMCLAPI_BASE, NEOFORGE_GROUP)],
            proxy=proxy,
        )
        names = [
            item.get("name", "")
            for item in detail.get("files", [])
            if item.get("type") in ("DIRECTORY", "FILE") and not item.get("name", "").startswith("maven-metadata")
        ]
    else:
        xml = fetch_bytes(["%s/%s/maven-metadata.xml" % (NEOFORGE_MAVEN, NEOFORGE_GROUP)], proxy=proxy).decode(
            "utf-8", "replace"
        )
        names = re.findall(r"<version>([^<]+)</version>", xml)

    usable = []
    for name in names:
        if not name.startswith(prefix):
            continue
        key = _version_key(name)
        if key is None and not include_beta:
            continue
        usable.append((key or (0,), name))
    if not usable:
        raise InstallError("NeoForge 没有对应 %s 的版本（前缀 %s）" % (game, prefix))
    usable.sort()
    return usable[-1][1]


def install_neoforge(
    game: str,
    loader_version: Optional[str] = None,
    game_dir: str = "minecraft",
    mirror: Optional[Mirror] = None,
    proxy: Optional[str] = None,
    java_path: Optional[str] = None,
    threads: int = 8,
    reporter: Optional[Reporter] = None,
    skip_assets: bool = False,
) -> Dict:
    mirror = mirror or Mirror()
    version_json = _ensure_vanilla(game, game_dir, mirror, proxy, threads, reporter, skip_assets)
    neoforge_version = loader_version or resolve_neoforge_version(game, mirror, proxy)

    if mirror.is_mirror:
        base = BMCLAPI_BASE + "/maven"
    else:
        base = NEOFORGE_MAVEN
    url = "%s/%s/%s/neoforge-%s-installer.jar" % (base, NEOFORGE_GROUP, neoforge_version, neoforge_version)
    jar_path = os.path.join(game_dir, ".mcd", "installers", "neoforge-%s-installer.jar" % neoforge_version)
    try:
        download(jar_path, mirror.urls(url), proxy=proxy, reporter=reporter,
                 label="installers/neoforge-%s-installer.jar" % neoforge_version)
    except DownloadError as exc:
        raise InstallError(
            "NeoForge installer 下载失败。若直连 maven.neoforged.net 不通，请加 --mirror bmclapi。\n%s" % exc
        )
    if mirror.is_mirror:
        prefetched = prefetch_installer_libraries(jar_path, game_dir, mirror, proxy, threads, reporter)
        if prefetched:
            print("    预取 installer 依赖：%d 个文件（避免 installer 直连官方 maven）" % prefetched)

    required = (version_json.get("javaVersion") or {}).get("majorVersion")
    chosen_java = java.pick(required, java_path)
    before = _snapshot_versions(game_dir)
    _ensure_launcher_profiles(game_dir)
    print("    使用 Java：%s（需要 %s）" % (chosen_java, required or "未知"))
    hint = "neoforge-%s" % neoforge_version
    _run_installer_tolerant(chosen_java, jar_path, game_dir, proxy, hint)

    installed = _detect_installed(game_dir, before, game, hint)
    if not installed:
        raise InstallError("installer 执行完毕但没找到新版本目录，请检查上面的输出")
    return {
        "loader": "neoforge",
        "id": installed,
        "loader_version": neoforge_version,
        "java": chosen_java,
    }


LOADERS = ("fabric", "quilt", "forge", "neoforge")
