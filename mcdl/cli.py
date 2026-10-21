"""命令行入口：mcdl list / install / modpack / doctor。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Dict, List, Optional

from . import __version__, java, modpack, vanilla
from . import loaders as loader_mod
from .mirror import NAMES, Mirror
from .net import Reporter, human_size, open_url
from .rules import Context

DEFAULT_DIR = "minecraft"

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2


# ---------------------------------------------------------------- 输出helper


def _print_header(title: str) -> None:
    print("== %s" % title)


def _print_summary(payload: Dict) -> None:
    print()
    _print_header("完成")
    for key, value in payload.items():
        if key in ("index", "dry_run") or value is None:
            continue
        if key == "bytes":
            print("  %-14s %s" % (key, human_size(value)))
        else:
            print("  %-14s %s" % (key, value))


class _Fatal(Exception):
    pass


# ---------------------------------------------------------------- 子命令


def cmd_list(args: argparse.Namespace) -> int:
    mirror = Mirror(args.mirror)
    manifest = vanilla.load_manifest(
        args.dir, mirror, proxy=args.proxy, refresh=args.refresh
    )
    versions = vanilla.list_versions(manifest, args.type)
    latest = manifest.get("latest") or {}
    if args.limit:
        versions = versions[: args.limit]

    if args.json:
        print(json.dumps({"latest": latest, "versions": versions}, ensure_ascii=False, indent=2))
        return EXIT_OK

    print("最新正式版：%s    最新快照：%s" % (latest.get("release"), latest.get("snapshot")))
    print("下载源：%s    共 %d 个版本" % (mirror.label, len(versions)))
    for entry in versions:
        print("  %-16s %-10s %s" % (entry["id"], entry.get("type"), (entry.get("releaseTime") or "")[:10]))
    return EXIT_OK


def cmd_install(args: argparse.Namespace) -> int:
    mirror = Mirror(args.mirror)
    reporter = Reporter(enabled=not args.json)
    context = Context()
    game_dir = args.dir

    manifest = vanilla.load_manifest(game_dir, mirror, proxy=args.proxy, refresh=args.refresh)
    version_id = args.version
    if version_id in ("latest", "release"):
        version_id = (manifest.get("latest") or {}).get("release")
    elif version_id == "snapshot":
        version_id = (manifest.get("latest") or {}).get("snapshot")
    if not version_id:
        raise _Fatal("无法确定要下载的版本，请显式给出，例如 mcdl install 1.20.1")

    print("目标目录：%s" % os.path.abspath(game_dir))
    print("下载源：%s" % mirror.label)

    result: Dict = {"version": version_id}
    if args.loader:
        vanilla.install(
            version_id, game_dir, mirror=mirror, proxy=args.proxy, threads=args.threads,
            reporter=reporter, skip_assets=args.no_assets, manifest=manifest, context=context,
        )
        if args.loader == "fabric":
            loader_info = loader_mod.install_fabric(
                version_id, args.loader_version, game_dir, mirror, args.proxy,
                args.threads, reporter, args.no_assets, context=context)
        elif args.loader == "quilt":
            loader_info = loader_mod.install_quilt(
                version_id, args.loader_version, game_dir, mirror, args.proxy,
                args.threads, reporter, args.no_assets, context=context)
        elif args.loader == "forge":
            loader_info = loader_mod.install_forge(
                version_id, args.loader_version, game_dir, mirror, args.proxy,
                args.java, args.threads, reporter, args.no_assets)
        elif args.loader == "neoforge":
            loader_info = loader_mod.install_neoforge(
                version_id, args.loader_version, game_dir, mirror, args.proxy,
                args.java, args.threads, reporter, args.no_assets)
        else:  # pragma: no cover - argparse 已限制
            raise _Fatal("未知加载器 %r" % args.loader)
        result.update(loader_info)
    else:
        stats = vanilla.install(
            version_id, game_dir, mirror=mirror, proxy=args.proxy, threads=args.threads,
            reporter=reporter, skip_assets=args.no_assets, manifest=manifest, context=context,
        )
        result.update({"files": stats.get("files"), "bytes": stats.get("bytes")})

    result["dir"] = os.path.abspath(game_dir)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_summary(result)
    return EXIT_OK


def cmd_modpack(args: argparse.Namespace) -> int:
    mirror = Mirror(args.mirror)
    reporter = Reporter(enabled=not args.json)
    result = modpack.install(
        args.source,
        game_dir=args.dir,
        mirror=mirror,
        proxy=args.proxy,
        threads=args.threads,
        reporter=reporter,
        skip_assets=args.no_assets,
        java_path=args.java,
        dry_run=args.dry_run,
    )
    if args.json:
        payload = {k: v for k, v in result.items() if k != "index"}
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return EXIT_OK

    if args.dry_run:
        _print_header("整合包预览（--dry-run，未下载）")
        print("  整合包      %s %s" % (result.get("pack"), result.get("version") or ""))
        print("  Minecraft   %s" % result.get("minecraft"))
        print("  加载器      %s %s" % (result.get("loader"), result.get("loader_version") or ""))
        print("  文件数      %d（%s）" % (result.get("files", 0), human_size(result.get("bytes", 0))))
        return EXIT_OK

    _print_summary(result)
    return EXIT_OK


def cmd_doctor(args: argparse.Namespace) -> int:
    targets = [
        ("Mojang 版本清单", "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"),
        ("BMCLAPI 版本清单", "https://bmclapi2.bangbang93.com/mc/game/version_manifest_v2.json"),
        ("Fabric meta", "https://meta.fabricmc.net/v2/versions/loader"),
        ("Quilt meta", "https://meta.quiltmc.org/v3/versions/loader"),
        ("Forge 推广信息", "https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json"),
        ("Forge maven", "https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml"),
        ("NeoForge maven", "https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml"),
        ("Modrinth API", "https://api.modrinth.com/v2/project/fabric-api"),
    ]
    print("mcdl %s    Python %s" % (__version__, sys.version.split()[0]))
    print()
    _print_header("网络")
    for label, url in targets:
        ok, detail = _probe(url, args.timeout)
        print("  %-16s %s" % (label, "OK" if ok else "FAIL  " + detail))
    print()
    _print_header("Java（Forge / NeoForge 需要）")
    inventory = java.inventory()
    if not inventory:
        print("  未找到 java，可用 --java 指定路径")
    for path, major in inventory:
        print("  Java %-4s %s" % (major or "?", path))
    print()
    print("提示：国内网络建议加 --mirror bmclapi；NeoForge 的 maven 可能仍需代理。")
    return EXIT_OK


def _probe(url: str, timeout: int = 8):
    try:
        with open_url(url, timeout=timeout) as response:
            response.read(1)
        return True, ""
    except Exception as exc:  # noqa: BLE001 - 诊断输出
        return False, str(exc)[:70]


# ---------------------------------------------------------------- 参数解析


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mcdl",
        description="独立的 Minecraft 下载器：原版 / 带加载器的版本 / 整合包（只下载，不启动）",
    )
    parser.add_argument("--version", action="version", version="mcdl %s" % __version__)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--dir", default=DEFAULT_DIR, help="游戏目录，默认 ./%s" % DEFAULT_DIR)
    common.add_argument("--mirror", choices=NAMES, default="official",
                        help="下载源：official（官方）或 bmclapi（国内镜像）")
    common.add_argument("--proxy", default=os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY"),
                        help="HTTP(S) 代理，例如 http://127.0.0.1:7890")
    common.add_argument("--threads", type=int, default=8, help="并发下载数，默认 8")
    common.add_argument("--no-assets", action="store_true", help="跳过资源文件（assets，体积最大）")
    common.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    common.add_argument("--refresh", action="store_true", help="忽略缓存的版本清单，强制刷新")

    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("list", parents=[common], help="列出可下载的版本")
    listing.add_argument("--type", choices=("release", "snapshot", "all"), default="release")
    listing.add_argument("--limit", type=int, default=20, help="最多显示多少个，0 表示全部")
    listing.set_defaults(func=cmd_list)

    install = sub.add_parser("install", parents=[common],
                             help="下载原版；加 --loader 则下载带加载器的版本")
    install.add_argument("version", help="版本号，如 1.20.1；也可用 latest / snapshot")
    install.add_argument("--loader", choices=loader_mod.LOADERS, help="同时安装加载器")
    install.add_argument("--loader-version", help="加载器版本，默认取最新/推荐")
    install.add_argument("--java", help="Java 路径（Forge/NeoForge installer 需要）")
    install.set_defaults(func=cmd_install)

    pack = sub.add_parser("modpack", parents=[common],
                          help="下载整合包（Modrinth slug / 链接 / 本地 .mrpack）")
    pack.add_argument("source", help="slug、slug@版本、modrinth 链接或 .mrpack 路径")
    pack.add_argument("--java", help="Java 路径（Forge/NeoForge 整合包需要）")
    pack.add_argument("--dry-run", action="store_true", help="只解析并展示计划，不下载")
    pack.set_defaults(func=cmd_modpack)

    doctor = sub.add_parser("doctor", help="检查网络与 Java 环境")
    doctor.add_argument("--timeout", type=int, default=8)
    doctor.set_defaults(func=cmd_doctor)
    return parser


def _print_welcome(parser: argparse.ArgumentParser) -> None:
    """无参数启动（通常是双击）时的提示页；控制台里停住，避免窗口一闪而过。"""
    print("mcdl %s —— 独立的 Minecraft 下载器（只下载，不启动）" % __version__)
    print()
    parser.print_help()
    print()
    print("常用示例：")
    print("  mcdl install 1.20.1 --mirror bmclapi")
    print("  mcdl install 1.20.1 --loader fabric --mirror bmclapi")
    print("  mcdl modpack fabulously-optimized --dir .\\fo --mirror bmclapi")
    print()
    print("提示：在开始菜单搜索 PowerShell，cd 到本文件所在目录后运行，例如 .\\mcdl.exe doctor")
    try:
        if sys.stdin and sys.stdin.isatty():
            input("按回车键退出...")
    except (EOFError, OSError):
        pass


def _setup_console() -> None:
    """Windows 控制台默认 GBK，会把手写的中文输出变成乱码；统一切到 UTF-8。"""
    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except Exception:  # noqa: BLE001 - 无控制台（被重定向）时忽略
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv: Optional[List[str]] = None) -> int:
    _setup_console()
    parser = build_parser()
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        _print_welcome(parser)
        return EXIT_OK
    args = parser.parse_args(argv)
    if getattr(args, "limit", None) == 0:
        args.limit = None
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\n已中断", file=sys.stderr)
        return 130
    except (_Fatal, vanilla.InstallError, loader_mod.InstallError,
            modpack.ModpackError, RuntimeError) as exc:
        print("\n错误：%s" % exc, file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
