"""图形界面：版本 + 加载器 + 整合包 + 自定义下载（tkinter，标准库）。

所有网络与磁盘操作都在后台线程，界面通过队列回传日志与进度。

版本隔离只影响“下载内容写到哪”（建出和 PCL/HMCL 隔离模式相同的目录结构），
不涉及启动时的存档/配置重定向——那部分由启动器负责。
"""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
import traceback
import webbrowser
from typing import Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import font as tkfont
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from . import __version__, config, modpack, mods, sources, vanilla
from . import loaders as loader_mod
from .mirror import BMCLAPI, OFFICIAL, Mirror
from .net import (DownloadCancelled, DownloadError, created_files, fetch_json, human_size,
                  request_cancel, reset_cancel, reset_created)
from .rules import Context

APP_TITLE = "MCD"
HEADER_TEXT = "Minecraft 下载器"
DIR_PLACEHOLDER = "未选择"

AUTO_RELEASE = "最新正式版（自动）"
AUTO_BETA = "最新测试版（自动）"
AUTO_LATEST = "最新（自动）"
UNIQUE_SUFFIX = " - 唯一"

LOADER_CHOICES = [("none", "无（仅原版）"), ("fabric", "Fabric"), ("quilt", "Quilt"),
                  ("forge", "Forge"), ("neoforge", "NeoForge")]

LICENSE_URL = "https://www.minecraft.net/zh-hans/store/minecraft-java-bedrock-edition-pc"
LICENSE_TEXT = (
    "MCD 仅为正版 Minecraft 用户提供下载服务。\n\n"
    "本工具不提供账号登录、不破解、不绕过正版验证；下载的游戏文件均来自 "
    "Mojang 与各加载器的官方渠道。\n\n"
    "如果你还没有购买 Minecraft，请先通过官方渠道获取正版授权。"
)


# ---------------------------------------------------------------- 路径与工具


def launcher_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def probe_writable(directory: str) -> Tuple[bool, str]:
    """目录是否可写；不可写时返回具体原因（区分“建不出来”和“建得出但写不进”）。"""
    if not os.path.isdir(directory):
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError as exc:
            return False, "无法创建目录 %s（错误 %s：%s）" % (
                directory, getattr(exc, "winerror", None) or exc.errno, exc.strerror or exc)
    probe = os.path.join(directory, ".mcd-write-test")
    try:
        with open(probe, "w", encoding="utf-8") as handle:
            handle.write("ok")
    except OSError as exc:
        return False, "目录存在但不可写 %s（错误 %s：%s）" % (
            directory, getattr(exc, "winerror", None) or exc.errno, exc.strerror or exc)
    finally:
        try:
            os.remove(probe)
        except OSError:
            pass
    return True, ""


def write_error_tip() -> str:
    return (
        "常见原因与处理：\n"
        "  · 选到了 Program Files 等受保护目录 → 换到非系统盘或用户目录；\n"
        "  · Windows 安全中心的“受控文件夹访问”拦了写入 → 允许本程序或换个目录；\n"
        "  · 目录属于其他账户 / 只读盘 → 换到当前用户可写的位置；\n"
        "  · 便携版放在 U 盘中且被写保护 → 去掉写保护后重试。"
    )


def open_external(url: str) -> bool:
    """用系统默认程序打开链接；失败时返回 False，由调用方给出可复制的地址。"""
    try:
        if sys.platform.startswith("win"):
            os.startfile(url)  # type: ignore[attr-defined]
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        return webbrowser.open(url)
    except Exception:  # noqa: BLE001
        return False


def find_minecraft_dirs(folder: str, depth: int = 2) -> List[str]:
    """在给定目录的 1~depth 层子目录里找 .minecraft（用于“选了启动器根目录”的场景）。"""
    folder = os.path.abspath(folder)
    if not os.path.isdir(folder):
        return []
    if os.path.basename(os.path.normpath(folder)).lower() == ".minecraft":
        return [os.path.normpath(folder)]
    found: List[str] = []

    def scan(base: str, level: int) -> None:
        try:
            names = sorted(os.listdir(base))
        except OSError:
            return
        for name in names:
            path = os.path.join(base, name)
            if not os.path.isdir(path):
                continue
            if name.lower() == ".minecraft":
                found.append(os.path.normpath(path))
            elif level < depth:
                scan(path, level + 1)

    scan(folder, 1)
    return found


def default_game_dir() -> Tuple[str, Optional[str]]:
    """默认 <启动器目录>\\.minecraft；不可写则回退 %APPDATA%\\.minecraft 并说明原因。"""
    base = launcher_dir()
    candidate = os.path.join(base, ".minecraft")
    ok, reason = probe_writable(base)
    if ok:
        return candidate, None
    fallback = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), ".minecraft")
    return fallback, "启动器所在目录不可写：%s；已改用 %s" % (reason, fallback)


def normalize_keyword(text: str) -> str:
    """中文输入法容易打出全角句点，统一成半角，保证能搜 1.20.1。"""
    return (text or "").replace("。", ".").replace("．", ".").replace("·", ".")


def detect_isolation(game_dir: str) -> Tuple[Optional[bool], str]:
    """按目录特征判断启动器是否开启版本隔离。返回 (是否隔离, 依据)。"""
    versions = os.path.join(game_dir, "versions")
    isolated_evidence = None
    if os.path.isdir(versions):
        for name in sorted(os.listdir(versions)):
            version_path = os.path.join(versions, name)
            if not os.path.isdir(version_path):
                continue
            if os.path.isdir(os.path.join(version_path, ".minecraft")):
                return True, "versions/%s/.minecraft（HMCL 隔离结构）" % name
            for sub in ("mods", "config", "saves", "resourcepacks", "shaderpacks"):
                if os.path.isdir(os.path.join(version_path, sub)):
                    isolated_evidence = "versions/%s/%s" % (name, sub)
                    break
            if isolated_evidence:
                break
    if isolated_evidence:
        return True, isolated_evidence
    if os.path.isdir(os.path.join(game_dir, "mods")):
        return False, "根目录有 mods，且各版本目录没有隔离结构"
    if not os.path.isdir(versions):
        return None, "目录里还没有 versions 子目录"
    return None, "没有找到可判断的特征目录"


def expected_version_id(loader: str, loader_version: Optional[str], game: str) -> str:
    if not loader or loader == "none" or not loader_version:
        return game
    if loader == "fabric":
        return "fabric-loader-%s-%s" % (loader_version, game)
    if loader == "quilt":
        return "quilt-loader-%s-%s" % (loader_version, game)
    if loader == "forge":
        return "%s-forge-%s" % (game, loader_version)
    return "neoforge-%s" % loader_version


def content_root(game_dir: str, version_id: Optional[str], isolate: bool) -> str:
    if isolate and version_id:
        return os.path.join(game_dir, "versions", version_id)
    return game_dir


# ---------------------------------------------------------------- 进度适配


class GuiReporter:
    def __init__(self, emit):
        self._emit = emit
        self.total_files = 0
        self.done_files = 0
        self.total_bytes = 0
        self.skipped_files = 0
        self.expected_bytes = 0
        self.done_bytes = 0

    def expect(self, size: int) -> None:
        """登记接下来要下载的字节数，作为总进度的分母。"""
        if size and size > 0:
            self.expected_bytes += int(size)
            self._emit(("total", self._overall()))

    def _overall(self) -> float:
        # 已知工作量太少时先不推进，否则“1 个文件下完”就会显示 100%
        if self.total_files < 5 and self.expected_bytes < 8 * 1024 * 1024:
            return 0.0
        if self.expected_bytes:
            value = max(0.0, min(self.done_bytes / self.expected_bytes, 1.0))
        elif self.total_files:
            value = max(0.0, min(self.done_files / self.total_files, 1.0))
        else:
            value = 0.0
        # 分母可能随后续阶段增大，这里保持单调，避免进度条倒退
        self._last_overall = max(getattr(self, "_last_overall", 0.0), value)
        return self._last_overall

    def start(self, total_files: int) -> None:
        self.total_files += total_files
        self._emit(("file", 0.0, "准备中"))
        self._emit(("total", self._overall()))

    def progress(self, label: str, got: int, total: int) -> None:
        ratio = (got / total) if total else None
        self._emit(("file", ratio, "%s  %s" % (label, human_size(got))))
        self._emit(("total", self._overall()))

    def done(self, label: str, size: int) -> None:
        self.done_files += 1
        self.done_bytes += int(size or 0)
        self.total_bytes += size
        self._emit(("log", "[%d/%d] %s  (%s)" % (self.done_files, max(self.total_files, self.done_files),
                                                 label, human_size(size))))
        self._emit(("total", self._overall()))

    def skipped(self, size: int) -> None:
        self.done_files += 1
        self.done_bytes += int(size or 0)
        self.skipped_files += 1
        self._emit(("total", self._overall()))

    def flush(self) -> None:
        pass


class _Stream:
    def __init__(self, sink):
        self._sink = sink

    def write(self, text: str) -> int:
        if text and text.strip():
            self._sink(("log", text.rstrip()))
        return len(text)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return False


# ---------------------------------------------------------------- 主窗口


class App:
    def __init__(self, root: tk.Tk, self_test: bool = False, auto_close_ms: Optional[int] = None):
        self.root = root
        self.self_test = self_test
        self.queue: "queue.Queue[tuple]" = queue.Queue()
        self.manifest: Optional[dict] = None
        self.versions: List[dict] = []
        self.busy = False
        self._loader_seq = 0
        self._search_job = None
        self._loader_cache: Dict[Tuple[str, str], Tuple[List[Tuple[str, bool]], bool]] = {}
        self._fabric_cache: Dict[str, List[dict]] = {}
        self.settings = config.load()
        self.custom_sources = sources.load_sources()

        game_dir, self.dir_warning = default_game_dir()
        self.default_dir = game_dir
        saved = str(self.settings.get("game_dir") or "")
        # 只有“上次确实选过且仍然存在”的目录才预填；否则显示“未选择”
        self.initial_dir = saved if saved and os.path.isdir(saved) else ""

        self.root.title(APP_TITLE)
        self._apply_dpi_scale()
        self.root.minsize(int(940 * self.scale), int(720 * self.scale))
        self._init_style()
        self._build_ui()
        if self.dir_warning:
            self._append_log(self.dir_warning)

        self.root.after(80, self._drain_queue)
        self._load_manifest_async()
        self.root.after(300, self._maybe_show_license_notice)
        if auto_close_ms:
            self.root.after(auto_close_ms, self._finish_self_test)

    # ---- 外观 -------------------------------------------------------

    def _apply_dpi_scale(self) -> None:
        try:
            self.scale = max(1.0, self.root.winfo_fpixels("1i") / 96.0)
        except tk.TclError:
            self.scale = 1.0
        self.root.geometry("%dx%d" % (int(1080 * self.scale), int(920 * self.scale)))
        self.root.minsize(int(960 * self.scale), int(780 * self.scale))

    def _init_style(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass
        family = "Microsoft YaHei UI"
        if family in tkfont.families():
            tkfont.nametofont("TkDefaultFont").configure(family=family, size=10)
            tkfont.nametofont("TkTextFont").configure(family=family, size=9)
        style.configure("H1.TLabel", font=(family, 15, "bold"))
        style.configure("Hint.TLabel", foreground="#666666")
        style.configure("Warn.TLabel", foreground="#a15c00")
        style.configure("Accent.TButton", font=(family, 10, "bold"))

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x")
        ttk.Label(header, text=HEADER_TEXT, style="H1.TLabel").pack(side="left")

        self.notebook = ttk.Notebook(outer)
        self.notebook.pack(fill="both", expand=True, pady=(10, 8))
        self.tab_version = ttk.Frame(self.notebook, padding=10)
        self.tab_pack = ttk.Frame(self.notebook, padding=10)
        self.tab_custom = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.tab_version, text="  版本与加载器  ")
        self.notebook.add(self.tab_pack, text="  整合包  ")
        self.notebook.add(self.tab_custom, text="  自定义下载  ")
        self.notebook.bind("<<NotebookTabChanged>>", lambda _e: self._update_action_text())

        self._build_version_tab()
        self._build_pack_tab()
        self._build_custom_tab()
        self._build_options(outer)
        self._build_log(outer)

    # ---- 版本与加载器 ------------------------------------------------

    def _build_version_tab(self) -> None:
        box = ttk.LabelFrame(self.tab_version, text="1. 选择游戏版本", padding=8)
        box.pack(fill="both", expand=True)

        bar = ttk.Frame(box)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Label(bar, text="类型").pack(side="left")
        self.var_type = tk.StringVar(value="正式版")
        combo_type = ttk.Combobox(bar, textvariable=self.var_type, width=8, state="readonly",
                                  values=["正式版", "快照", "全部"])
        combo_type.pack(side="left", padx=(6, 12))
        combo_type.bind("<<ComboboxSelected>>", lambda _e: self._refresh_version_list())

        ttk.Label(bar, text="搜索").pack(side="left")
        self.var_search = tk.StringVar()
        self.var_search.trace_add("write", lambda *_a: self._schedule_search())
        ttk.Entry(bar, textvariable=self.var_search, width=18).pack(side="left", padx=(6, 12))

        ttk.Button(bar, text="刷新版本列表", command=self._load_manifest_async).pack(side="left")
        self.lbl_versions = ttk.Label(bar, text="正在加载版本列表…", style="Hint.TLabel")
        self.lbl_versions.pack(side="right")

        table = ttk.Frame(box)
        table.pack(fill="both", expand=True)
        columns = ("id", "type", "time")
        self.tree = ttk.Treeview(table, columns=columns, show="headings", height=8, selectmode="browse")
        self.tree.heading("id", text="版本")
        self.tree.heading("type", text="类型")
        self.tree.heading("time", text="发布日期")
        self.tree.column("id", width=220, anchor="w")
        self.tree.column("type", width=100, anchor="center")
        self.tree.column("time", width=140, anchor="center")
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_version_selected)
        self.tree.bind("<Double-1>", lambda _e: self._start())

        loader = ttk.LabelFrame(self.tab_version, text="2. 选择加载器（可选）", padding=8)
        loader.pack(fill="x", pady=(8, 0))

        row = ttk.Frame(loader)
        row.pack(fill="x")
        ttk.Label(row, text="加载器").pack(side="left")
        self.var_loader = tk.StringVar(value="无（仅原版）")
        self.combo_loader = ttk.Combobox(row, textvariable=self.var_loader, width=16, state="readonly",
                                         values=[label for _, label in LOADER_CHOICES])
        self.combo_loader.pack(side="left", padx=(6, 16))
        self.combo_loader.bind("<<ComboboxSelected>>", lambda _e: self._on_loader_changed())

        ttk.Label(row, text="加载器版本").pack(side="left")
        self.var_loader_version = tk.StringVar(value=AUTO_LATEST)
        self.combo_loader_version = ttk.Combobox(row, textvariable=self.var_loader_version, width=26,
                                                 state="readonly", values=[AUTO_LATEST])
        self.combo_loader_version.pack(side="left", padx=(6, 16))

        self.fabric_frame = ttk.Frame(loader)
        self.var_fabric_api = tk.BooleanVar(value=False)
        self.chk_fabric_api = ttk.Checkbutton(self.fabric_frame, text="同时安装 Fabric API",
                                              variable=self.var_fabric_api,
                                              command=self._on_fabric_api_toggle)
        self.chk_fabric_api.pack(side="left")
        self.var_fabric_api_version = tk.StringVar(value="最新")
        self.combo_fabric_api = ttk.Combobox(self.fabric_frame, textvariable=self.var_fabric_api_version,
                                             width=22, state="disabled", values=["最新"])
        self.combo_fabric_api.pack(side="left", padx=6)

        self.lbl_loader_hint = ttk.Label(
            loader, text="选择加载器后会联网列出可用版本；Forge / NeoForge 需要本机有 Java 17 或 21。",
            style="Hint.TLabel")
        self.lbl_loader_hint.pack(anchor="w", pady=(6, 0))

    # ---- 整合包 ------------------------------------------------------

    def _build_pack_tab(self) -> None:
        box = ttk.LabelFrame(self.tab_pack, text="从 Modrinth 安装整合包", padding=8)
        box.pack(fill="both", expand=True)

        ttk.Label(box, text="项目 slug、页面链接，或本地 .mrpack 文件").pack(anchor="w")
        row = ttk.Frame(box)
        row.pack(fill="x", pady=(4, 8))
        self.var_pack = tk.StringVar()
        ttk.Entry(row, textvariable=self.var_pack).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="选择文件…", command=self._browse_pack).pack(side="left", padx=6)

        ttk.Label(box, text="示例：fabulously-optimized、fabulously-optimized@14.1.1、"
                            "https://modrinth.com/modpack/xxx", style="Hint.TLabel").pack(anchor="w")

        reason = (
            "为什么不支持 CurseForge 整合包：\n"
            "  · CurseForge 的官方 API 需要单独申请 API Key，条款要求说明用途并接受审核；\n"
            "    个人工具很难长期持有授权，把密钥内置在开源客户端里也不合适；\n"
            "  · 包里每个文件的下载地址由该 API 动态签发，缺 Key 时连 mod 文件都解析不出来；\n"
            "  · 抓网页或走非授权镜像属于绕过限制，本项目不做。\n"
            "\n"
            "替代方案：多数 CF 整合包同时发布在 Modrinth，可直接搜到；只有 CF 版本时，\n"
            "可先用 CurseForge App 下载，或请作者导出 .mrpack 后在本页“选择文件”安装。"
        )
        ttk.Label(box, text=reason, style="Hint.TLabel", justify="left").pack(anchor="w", pady=(12, 0))

    # ---- 自定义下载 --------------------------------------------------

    def _build_custom_tab(self) -> None:
        box = ttk.LabelFrame(self.tab_custom, text="任意链接下载（类似 PCL 的自定义下载）", padding=8)
        box.pack(fill="both", expand=True)

        ttk.Label(box, text="下载链接（http / https，可直接粘贴文件直链）").pack(anchor="w")
        self.var_custom_url = tk.StringVar()
        ttk.Entry(box, textvariable=self.var_custom_url).pack(fill="x", pady=(4, 10))

        path_row = ttk.Frame(box)
        path_row.pack(fill="x")
        ttk.Label(path_row, text="保存位置").pack(side="left")
        self.var_custom_dest = tk.StringVar(value="")
        ttk.Entry(path_row, textvariable=self.var_custom_dest).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(path_row, text="选择目录…", command=self._browse_custom_dest).pack(side="left")

        name_row = ttk.Frame(box)
        name_row.pack(fill="x", pady=(8, 0))
        ttk.Label(name_row, text="文件名").pack(side="left")
        self.var_custom_name = tk.StringVar(value="")
        ttk.Entry(name_row, textvariable=self.var_custom_name, width=40).pack(side="left", padx=6)
        ttk.Label(name_row, text="留空则用链接里的文件名", style="Hint.TLabel").pack(side="left")

        note = (
            "说明：\n"
            "  · 保存位置留空时存到 <安装目录>/downloads；\n"
            "  · 下载的是 .mrpack 时会额外询问是否直接按整合包安装；\n"
            "  · 不校验哈希、不判断文件用途，请确认链接来源可信。"
        )
        ttk.Label(box, text=note, style="Hint.TLabel", justify="left").pack(anchor="w", pady=(12, 0))

    # ---- 选项 --------------------------------------------------------

    def _build_options(self, parent: ttk.Frame) -> None:
        box = ttk.LabelFrame(parent, text="下载选项", padding=8)
        box.pack(fill="x")

        line1 = ttk.Frame(box)
        line1.pack(fill="x")
        ttk.Label(line1, text="安装目录").pack(side="left")
        self.var_dir = tk.StringVar(value=self.initial_dir or DIR_PLACEHOLDER)
        self.entry_dir = ttk.Entry(line1, textvariable=self.var_dir)
        self.entry_dir.pack(side="left", fill="x", expand=True, padx=6)
        self.entry_dir.bind("<FocusIn>", self._on_dir_focus_in)
        self.entry_dir.bind("<FocusOut>", self._on_dir_focus_out)
        ttk.Button(line1, text="浏览…", command=self._browse_dir).pack(side="left")
        ttk.Button(line1, text="打开", command=self._open_dir).pack(side="left", padx=(6, 0))

        self.lbl_dir_hint = ttk.Label(
            box, text="请选择启动器同目录下的 .minecraft；如果你选的是启动器根目录，"
                      "会自动在它的子目录里找 .minecraft 并询问是否切换。",
            style="Hint.TLabel", justify="left")
        self.lbl_dir_hint.pack(anchor="w", pady=(4, 8))
        if self.dir_warning:
            self.lbl_dir_hint.configure(text=self.dir_warning, style="Warn.TLabel")

        line2 = ttk.Frame(box)
        line2.pack(fill="x")
        ttk.Label(line2, text="下载源").pack(side="left")
        self.var_mirror = tk.StringVar(value=self.settings.get("mirror") or "bmclapi")
        ttk.Radiobutton(line2, text="BMCLAPI 镜像（国内推荐）", value="bmclapi",
                        variable=self.var_mirror).pack(side="left", padx=(6, 8))
        ttk.Radiobutton(line2, text="Mojang 官方", value="official",
                        variable=self.var_mirror).pack(side="left", padx=(0, 12))
        ttk.Radiobutton(line2, text="自定义源", value="custom",
                        variable=self.var_mirror).pack(side="left")
        self.var_custom_source = tk.StringVar(value=self.custom_sources[0]["name"] if self.custom_sources else "")
        self.combo_source = ttk.Combobox(line2, textvariable=self.var_custom_source, width=18, state="readonly",
                                         values=[item["name"] for item in self.custom_sources])
        self.combo_source.pack(side="left", padx=6)
        ttk.Button(line2, text="导入…", command=self._import_source).pack(side="left")

        line3 = ttk.Frame(box)
        line3.pack(fill="x", pady=(8, 0))
        self.var_isolate = tk.BooleanVar(value=bool(self.settings.get("isolate", False)))
        ttk.Checkbutton(line3, text="版本隔离", variable=self.var_isolate,
                        command=self._on_isolate_toggled).pack(side="left")
        self.var_skip_assets = tk.BooleanVar(value=False)
        ttk.Checkbutton(line3, text="跳过资源文件（assets）", variable=self.var_skip_assets,
                        command=self._update_skip_hint).pack(side="left", padx=16)
        ttk.Label(line3, text="并发").pack(side="left", padx=(8, 0))
        self.var_threads = tk.IntVar(value=int(self.settings.get("threads") or 8))
        ttk.Spinbox(line3, from_=1, to=32, width=4, textvariable=self.var_threads).pack(side="left", padx=4)

        self.lbl_iso_hint = ttk.Label(box, text="", style="Hint.TLabel", justify="left")
        self.lbl_iso_hint.pack(anchor="w", pady=(4, 0))
        self.lbl_skip_hint = ttk.Label(box, text="", style="Warn.TLabel", justify="left")
        self.lbl_skip_hint.pack(anchor="w")
        self._on_isolate_toggled(silent=True)

    def _build_log(self, parent: ttk.Frame) -> None:
        controls = ttk.Frame(parent)
        controls.pack(side="bottom", fill="x", pady=(8, 0))
        self.lbl_status = ttk.Label(controls, text="就绪", anchor="w")
        self.lbl_status.pack(side="left")
        self.btn_start = ttk.Button(controls, text="开始下载", style="Accent.TButton", command=self._start)
        self.btn_start.pack(side="right")
        # 取消按钮：初始隐藏，下载开始后再显示在“开始下载”左边
        self.btn_cancel = ttk.Button(controls, text="取消", command=self._cancel)

        bars = ttk.Frame(parent)
        bars.pack(side="bottom", fill="x", pady=(6, 0))
        row_file = ttk.Frame(bars)
        row_file.pack(fill="x")
        ttk.Label(row_file, text="当前文件", width=9, anchor="w").pack(side="left")
        self.progress_file = ttk.Progressbar(row_file, mode="determinate", maximum=100)
        self.progress_file.pack(side="left", fill="x", expand=True)
        row_total = ttk.Frame(bars)
        row_total.pack(fill="x", pady=(3, 0))
        ttk.Label(row_total, text="总进度", width=9, anchor="w").pack(side="left")
        self.progress_total = ttk.Progressbar(row_total, mode="determinate", maximum=100)
        self.progress_total.pack(side="left", fill="x", expand=True)

        box = ttk.LabelFrame(parent, text="日志", padding=6)
        box.pack(fill="both", expand=True, pady=(8, 0))
        self.log = ScrolledText(box, height=7, wrap="none", state="disabled")
        self.log.pack(fill="both", expand=True)

    # ---- 队列与状态 --------------------------------------------------

    def _emit(self, message: tuple) -> None:
        self.queue.put(message)

    def _drain_queue(self) -> None:
        try:
            while True:
                kind, *rest = self.queue.get_nowait()
                if kind == "log":
                    self._append_log(rest[0])
                elif kind == "file":
                    ratio, label = rest
                    self.progress_file["value"] = (ratio or 0.0) * 100
                    if label:
                        self.lbl_status.configure(text=str(label)[-70:])
                elif kind == "total":
                    self.progress_total["value"] = float(rest[0]) * 100
                elif kind == "status":
                    self.lbl_status.configure(text=str(rest[0])[-60:])
                elif kind == "state":
                    self._set_busy(bool(rest[0]))
                elif kind == "refresh_versions":
                    self._refresh_version_list()
                elif kind == "loader_versions":
                    self._apply_loader_versions(*rest)
                elif kind == "fabric_api":
                    self._apply_fabric_api(*rest)
                elif kind == "ask_mrpack":
                    self._ask_install_mrpack(rest[0])
                elif kind == "done":
                    self._on_finished(rest[0])
        except queue.Empty:
            pass
        self.root.after(80, self._drain_queue)

    def _append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _reset_progress(self) -> None:
        self.progress_file["value"] = 0
        self.progress_total["value"] = 0

    def _complete_progress(self) -> None:
        self.progress_file["value"] = 100
        self.progress_total["value"] = 100

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.btn_start.configure(state="disabled" if busy else "normal",
                                 text="下载中…" if busy else self._action_text())
        if busy:
            self.btn_cancel.configure(state="normal", text="取消")
            self.btn_cancel.pack(side="right", padx=(0, 6))
        else:
            self.btn_cancel.pack_forget()

    def _cancel(self) -> None:
        if not self.busy:
            return
        self.btn_cancel.configure(state="disabled", text="正在取消…")
        self._append_log("已请求取消，等待当前文件结束…")
        request_cancel()

    def _cleanup_created(self) -> None:
        """取消后删掉本次下载新建的文件；此前已存在的文件一律不动。"""
        paths = created_files()
        removed = 0
        for path in paths:
            try:
                os.remove(path)
                removed += 1
            except OSError:
                continue
        reset_created()
        if paths:
            self._append_log("已清理本次新建的 %d 个文件（此前的文件未动）" % removed)

    def _action_text(self) -> str:
        index = self.notebook.index(self.notebook.select())
        return {0: "开始下载", 1: "下载整合包", 2: "开始下载"}.get(index, "开始下载")

    def _update_action_text(self) -> None:
        if not self.busy:
            self.btn_start.configure(text=self._action_text())
        if self.notebook.index(self.notebook.select()) == 2 and not self.var_custom_dest.get():
            base = self._dir_value() or self.default_dir
            self.var_custom_dest.set(os.path.join(os.path.abspath(base), "downloads"))

    def _update_skip_hint(self) -> None:
        if self.var_skip_assets.get():
            self.lbl_skip_hint.configure(
                text="已跳过 assets：游戏内声音、语言文件、字体与部分贴图会缺失或异常；"
                     "仅建议在网络极差、只需要版本文件（做服务端/查崩溃）时使用。")
        else:
            self.lbl_skip_hint.configure(text="")

    def _on_isolate_toggled(self, silent: bool = False) -> None:
        if self.var_isolate.get():
            text = ("隔离开启：整合包与 Fabric API 的内容会写到 versions/<版本>/（mods、config 等），"
                    "与 PCL、HMCL 的“版本隔离”目录结构一致。\n"
                    "注意：请让启动器里的版本隔离设置与这里保持一致，否则可能加载不到模组。")
        else:
            text = "隔离关闭：内容写到游戏根目录（mods、config 等），使用全局配置。"
        self.lbl_iso_hint.configure(text=text)
        if not silent:
            self._append_log("版本隔离：" + ("开启" if self.var_isolate.get() else "关闭"))

    # ---- 目录 --------------------------------------------------------

    def _dir_value(self) -> str:
        value = self.var_dir.get().strip()
        return "" if value in ("", DIR_PLACEHOLDER) else value

    def _on_dir_focus_in(self, _event=None) -> None:
        """未选择目录时，点一下输入框等同于点“浏览…”。"""
        if self.var_dir.get().strip() != DIR_PLACEHOLDER:
            return
        if getattr(self, "_dir_browsing", False):
            return
        self._dir_browsing = True
        try:
            chosen = filedialog.askdirectory(initialdir=self.default_dir or os.getcwd(),
                                             title="选择安装目录")
        finally:
            self._dir_browsing = False
        if chosen:
            self.var_dir.set(os.path.normpath(chosen))
            self._apply_dir_choice()
        elif not self.var_dir.get().strip():
            self.var_dir.set(DIR_PLACEHOLDER)

    def _on_dir_focus_out(self, _event=None) -> None:
        if not self.var_dir.get().strip():
            self.var_dir.set(DIR_PLACEHOLDER)
            return
        self._apply_dir_choice()

    def _on_dir_changed(self) -> None:
        raw = self._dir_value()
        if not raw:
            return
        path = os.path.abspath(raw)
        isolated, reason = detect_isolation(path)
        if isolated is None:
            self._append_log("无法判断该目录的版本隔离状态（%s），保持当前设置。" % reason)
            return
        current = bool(self.var_isolate.get())
        if isolated != current:
            self.var_isolate.set(isolated)
            self._on_isolate_toggled(silent=True)
            self._append_log("检测到目录特征：%s → 已自动%s版本隔离。" % (reason, "开启" if isolated else "关闭"))
        else:
            self._append_log("目录特征：%s（版本隔离已与检测结果一致）" % reason)

    def _browse_dir(self) -> None:
        initial = self._dir_value() or self.default_dir or os.getcwd()
        chosen = filedialog.askdirectory(initialdir=initial)
        if chosen:
            self.var_dir.set(os.path.normpath(chosen))
            self._apply_dir_choice()

    def _apply_dir_choice(self) -> None:
        """选了非 .minecraft 目录时，向下找 .minecraft 并询问是否切换。"""
        if getattr(self, "_dir_prompting", False):
            return
        raw = self._dir_value()
        if not raw:
            return
        path = os.path.abspath(raw)
        if not os.path.isdir(path):
            return
        if os.path.basename(os.path.normpath(path)).lower() == ".minecraft":
            self._last_dir = path
            self._on_dir_changed()
            return
        if path == getattr(self, "_dir_prompted_for", None):
            return
        found = find_minecraft_dirs(path, depth=2)
        if not found:
            # 既不是 .minecraft，子目录里也没有：让用户确认是否仍然下载到这里
            self._dir_prompting = True
            try:
                self._dir_prompted_for = path
                keep = messagebox.askyesno(
                    "未找到 .minecraft 文件夹",
                    "在 %s\n\n没有找到 .minecraft 文件夹。\n\n是否仍然下载到这个文件夹内？" % path)
            finally:
                self._dir_prompting = False
            if keep:
                self._last_dir = path
            else:
                self.var_dir.set(getattr(self, "_last_dir", "") or DIR_PLACEHOLDER)
            self._on_dir_changed()
            return
        target = found[0]
        extra = "" if len(found) == 1 else "（共找到 %d 个，先列出第一个）" % len(found)
        self._dir_prompting = True
        try:
            self._dir_prompted_for = path
            if messagebox.askyesno(
                    "发现 .minecraft",
                    "在 %s\n\n找到了 .minecraft 目录%s。\n要切换到这个目录吗？" % (target, extra)):
                self.var_dir.set(target)
                self._dir_prompted_for = target
        finally:
            self._dir_prompting = False
        self._on_dir_changed()

    def _browse_custom_dest(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.var_custom_dest.get() or os.getcwd())
        if chosen:
            self.var_custom_dest.set(os.path.normpath(chosen))

    def _browse_pack(self) -> None:
        chosen = filedialog.askopenfilename(filetypes=[("Modrinth 整合包", "*.mrpack"), ("压缩包", "*.zip")])
        if chosen:
            self.var_pack.set(chosen)
            self.notebook.select(self.tab_pack)

    def _open_dir(self) -> None:
        raw = self._dir_value()
        if not raw:
            messagebox.showinfo("未选择目录", "还没有选择安装目录。请先点“浏览…”选择，或直接开始下载。")
            return
        path = os.path.abspath(raw)
        if not os.path.isdir(path):
            messagebox.showinfo("目录不存在", "该目录还不存在，下载完成后会自动创建：\n%s" % path)
            return
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("打开失败", str(exc))

    # ---- 自定义源 ----------------------------------------------------

    def _import_source(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("下载源配置", "*.json"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
            sources.add_source(raw)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("导入失败", "%s\n\n已生成示例文件：%s" % (exc, sources.write_example()))
            return
        self.custom_sources = sources.load_sources()
        self.combo_source.configure(values=[item["name"] for item in self.custom_sources])
        self.var_custom_source.set(raw["name"])
        self.var_mirror.set("custom")
        self._append_log("已导入下载源：%s" % raw["name"])

    def _selected_mirror(self) -> Mirror:
        choice = self.var_mirror.get()
        if choice == "custom":
            name = self.var_custom_source.get()
            for item in self.custom_sources:
                if item.get("name") == name:
                    return sources.to_mirror(item)
            return Mirror(BMCLAPI)
        return Mirror(OFFICIAL if choice == "official" else BMCLAPI)

    # ---- 版本列表 ----------------------------------------------------

    def _schedule_search(self) -> None:
        if self._search_job:
            try:
                self.root.after_cancel(self._search_job)
            except tk.TclError:
                pass
        self._search_job = self.root.after(180, self._refresh_version_list)

    def _load_manifest_async(self) -> None:
        self.lbl_versions.configure(text="正在加载版本列表…")
        game_dir = os.path.abspath(self._dir_value() or self.default_dir)
        mirror = self._selected_mirror()

        def work():
            try:
                # 缓存放 %APPDATA%\MCD\cache，避免在用户确认安装目录前就创建 .minecraft
                manifest = vanilla.load_manifest(game_dir, mirror, refresh=True,
                                                 cache_dir=config.cache_dir())
                self.manifest = manifest
                self._emit(("log", "版本列表已更新：共 %d 个版本" % len(manifest.get("versions", []))))
                self._emit(("refresh_versions",))
            except Exception as exc:  # noqa: BLE001
                self._emit(("log", "版本列表加载失败：%s" % exc))
                self._emit(("status", "版本列表加载失败"))

        threading.Thread(target=work, daemon=True).start()

    def _refresh_version_list(self) -> None:
        if not self.manifest:
            return
        kind = {"正式版": "release", "快照": "snapshot", "全部": "all"}.get(self.var_type.get(), "release")
        keyword = normalize_keyword(self.var_search.get()).strip().lower()
        items = [v for v in self.manifest.get("versions", [])
                 if (kind == "all" or v.get("type") == kind)]
        if keyword:
            items = [v for v in items if keyword in str(v.get("id", "")).lower()]

        self.versions = items
        self.tree.delete(*self.tree.get_children())
        for entry in items[:500]:
            self.tree.insert("", "end", values=(entry.get("id"), entry.get("type"),
                                                (entry.get("releaseTime") or "")[:10]))
        latest = (self.manifest.get("latest") or {}).get("release")
        self.lbl_versions.configure(text="共 %d 个版本（最新正式版 %s）" % (len(items), latest))
        if items and not self.tree.selection():
            first = self.tree.get_children()
            if first:
                self.tree.selection_set(first[0])
                self.tree.focus(first[0])

    def _on_version_selected(self, _event=None) -> None:
        self._on_loader_changed()

    def _selected_version(self) -> Optional[str]:
        selection = self.tree.selection()
        if not selection:
            return None
        return str(self.tree.item(selection[0], "values")[0])

    # ---- 加载器 ------------------------------------------------------

    def _loader_key(self) -> str:
        label = self.var_loader.get()
        for key, text in LOADER_CHOICES:
            if text == label:
                return key
        return "none"

    def _on_loader_changed(self) -> None:
        key = self._loader_key()
        self._loader_seq += 1
        seq = self._loader_seq
        self.var_loader_version.set(AUTO_LATEST)
        self.combo_loader_version.configure(values=[AUTO_LATEST], state="readonly")

        if key == "fabric":
            self.fabric_frame.pack(fill="x", pady=(6, 0))
        else:
            self.fabric_frame.pack_forget()
            self.var_fabric_api.set(False)

        if key == "none":
            self.lbl_loader_hint.configure(text="选择加载器后会联网列出可用版本；Forge / NeoForge 需要本机有 Java 17 或 21。")
            return

        game = self._selected_version()
        if not game:
            return
        self.lbl_loader_hint.configure(text="正在查询 %s 支持 %s 的版本…" % (key, game))
        mirror = self._selected_mirror()

        def work():
            try:
                items, has_stability = self._fetch_loader_versions(key, game, mirror)
            except Exception as exc:  # noqa: BLE001
                items, has_stability = [], False
                self._emit(("log", "查询加载器版本失败：%s" % exc))
            if key == "fabric":
                try:
                    self._emit(("fabric_api", game, mods.list_fabric_api(game)))
                except Exception as exc:  # noqa: BLE001
                    self._emit(("log", "查询 Fabric API 版本失败：%s" % exc))
            if seq != self._loader_seq:
                return
            self._emit(("loader_versions", key, game, items, has_stability))

        threading.Thread(target=work, daemon=True).start()

    def _fetch_loader_versions(self, key: str, game: str, mirror: Mirror) -> Tuple[List[Tuple[str, bool]], bool]:
        """返回 ([(版本号, 是否稳定)], 是否能区分正式/测试)。"""
        cached = self._loader_cache.get((key, game))
        if cached:
            return cached

        items: List[Tuple[str, bool]] = []
        has_stability = False

        if key == "fabric":
            data = fetch_json(["https://meta.fabricmc.net/v2/versions/loader/%s" % game])
            for item in data:
                info = item.get("loader") or {}
                if info.get("version"):
                    items.append((info["version"], bool(info.get("stable", True))))
            has_stability = True
        elif key == "quilt":
            data = fetch_json(["https://meta.quiltmc.org/v3/versions/loader/%s" % game])
            for item in data:
                info = item.get("loader") or {}
                if info.get("version"):
                    items.append((info["version"], True))
            has_stability = False
        elif key == "forge":
            promos = fetch_json([loader_mod.FORGE_PROMOS]).get("promos", {})
            recommended = promos.get("%s-recommended" % game)
            latest = promos.get("%s-latest" % game)
            if latest:
                items.append((latest, latest == recommended))
            if recommended and recommended != latest:
                items.append((recommended, True))
            has_stability = bool(latest and recommended and latest != recommended)
        elif key == "neoforge":
            for version in loader_mod.list_neoforge_versions(game, mirror):
                items.append((version, "-" not in version))
            has_stability = any("-" in version for version, _stable in items)

        result = (items, has_stability)
        self._loader_cache[(key, game)] = result
        return result

    def _apply_loader_versions(self, key: str, game: str, items: List[Tuple[str, bool]], has_stability: bool) -> None:
        if self._loader_key() != key or self._selected_version() != game:
            return
        versions = [version for version, _stable in items]

        if len(versions) == 1:
            label = versions[0] + UNIQUE_SUFFIX
            self.combo_loader_version.configure(values=[label], state="readonly")
            self.var_loader_version.set(label)
            self.lbl_loader_hint.configure(text="该游戏版本只有 %s 一个可选加载器版本。" % versions[0])
            return
        if not versions:
            self.combo_loader_version.configure(values=[AUTO_LATEST], state="readonly")
            self.var_loader_version.set(AUTO_LATEST)
            self.lbl_loader_hint.configure(text="没有查到可用版本，将按“%s”自动选择。" % AUTO_LATEST)
            return

        autos = [AUTO_BETA, AUTO_RELEASE] if has_stability else [AUTO_LATEST]
        self.combo_loader_version.configure(values=autos + versions, state="readonly")
        # 顺序上测试版在上，但默认仍选正式版，避免新用户默认装到测试版
        self.var_loader_version.set(AUTO_RELEASE if has_stability else AUTO_LATEST)
        if has_stability:
            stable = [version for version, is_stable in items if is_stable]
            unstable = [version for version, is_stable in items if not is_stable]
            parts = []
            if stable:
                parts.append("正式版最新 %s" % stable[0])
            if unstable:
                parts.append("测试版最新 %s" % unstable[0])
            self.lbl_loader_hint.configure(
                text="共 %d 个可选版本（%s）；Forge、NeoForge 安装需要 Java 17 或 21。"
                     % (len(items), "，".join(parts) or "无"))
        else:
            self.lbl_loader_hint.configure(
                text="共 %d 个版本；该来源无法区分正式/测试版。" % len(items))

    def _resolve_loader_version(self, key: str, game: str, choice: str) -> Optional[str]:
        if choice.endswith(UNIQUE_SUFFIX):
            return choice[: -len(UNIQUE_SUFFIX)]
        if choice not in (AUTO_RELEASE, AUTO_BETA, AUTO_LATEST):
            return choice or None
        items = self._loader_cache.get((key, game), ([], False))[0]
        if not items:
            return None
        if choice == AUTO_BETA:
            for version, stable in items:
                if not stable:
                    return version
        if choice == AUTO_RELEASE:
            for version, stable in items:
                if stable:
                    return version
        return items[0][0]

    # ---- Fabric API --------------------------------------------------

    def _on_fabric_api_toggle(self) -> None:
        self.combo_fabric_api.configure(state="readonly" if self.var_fabric_api.get() else "disabled")

    def _apply_fabric_api(self, game: str, items: List[dict]) -> None:
        if self._selected_version() != game or self._loader_key() != "fabric":
            return
        self._fabric_cache[game] = items
        if not items:
            self.combo_fabric_api.configure(values=["最新"], state="disabled")
            self.var_fabric_api_version.set("最新")
            self.var_fabric_api.set(False)
            return
        self.combo_fabric_api.configure(values=["最新"] + [item["version_number"] for item in items])
        self.var_fabric_api_version.set("最新")
        if self.var_fabric_api.get():
            self.combo_fabric_api.configure(state="readonly")

    def _fabric_api_choice(self, game: str) -> Optional[str]:
        if not self.var_fabric_api.get():
            return None
        choice = self.var_fabric_api_version.get()
        return None if choice in ("", "最新") else choice

    # ---- 开始下载 ----------------------------------------------------

    def _start(self) -> None:
        if self.busy:
            return
        index = self.notebook.index(self.notebook.select())
        if index == 2:
            self._start_custom()
            return

        if index == 1:
            source = self.var_pack.get().strip()
            if not source:
                messagebox.showwarning("缺少整合包", "请填写 Modrinth 项目 slug / 链接，或选择 .mrpack 文件。")
                return
            job = {"kind": "pack", "source": source}
        else:
            game = self._selected_version()
            if not game:
                messagebox.showwarning("未选择版本", "请先在列表里选中一个 Minecraft 版本。")
                return
            loader = self._loader_key()
            loader_version = self._resolve_loader_version(loader, game, self.var_loader_version.get()) \
                if loader != "none" else None
            job = {"kind": "version", "game": game, "loader": loader, "loader_version": loader_version,
                   "fabric_api": self._fabric_api_choice(game) if loader == "fabric" else None}

        raw = self._dir_value()
        if not raw:
            answer = messagebox.askyesnocancel(
                "未选择安装目录",
                "还没有选择安装目录。\n\n是否使用启动器同目录下的：\n%s\n\n"
                "选“是”用这个目录，“否”手动浏览，“取消”返回。" % self.default_dir)
            if answer is None:
                return
            if answer:
                raw = self.default_dir
                self.var_dir.set(raw)
            else:
                chosen = filedialog.askdirectory(initialdir=self.default_dir or os.getcwd())
                if not chosen:
                    return
                raw = os.path.normpath(chosen)
                self.var_dir.set(raw)
            self._apply_dir_choice()
            raw = self._dir_value()
            if not raw:
                return

        self._on_dir_changed()
        game_dir = os.path.abspath(raw)
        ok, reason = probe_writable(game_dir)
        if not ok:
            fallback = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "MCD", "minecraft")
            if messagebox.askyesno(
                    "目录不可写",
                    "%s\n\n%s\n\n是否改用 %s ？" % (reason, write_error_tip(), fallback)):
                ok_fallback, reason_fallback = probe_writable(fallback)
                if not ok_fallback:
                    messagebox.showerror("依然不可写", reason_fallback)
                    return
                game_dir = fallback
                self.var_dir.set(game_dir)
                self._append_log("安装目录不可写，已改用 %s" % fallback)
            else:
                return

        job["isolate"] = bool(self.var_isolate.get())
        options = dict(game_dir=game_dir, mirror=self._selected_mirror(),
                       threads=max(1, int(self.var_threads.get() or 8)),
                       skip_assets=bool(self.var_skip_assets.get()))
        self._remember_settings(game_dir, options)
        reset_cancel()
        reset_created()
        self._set_busy(True)
        self._reset_progress()
        self._append_log("=" * 60)
        self._append_log("目标目录：%s" % game_dir)
        self._append_log("下载源：%s" % options["mirror"].label)
        self._append_log("版本隔离：%s" % ("开启" if job["isolate"] else "关闭"))
        threading.Thread(target=self._run_job, args=(job, options), daemon=True).start()

    def _remember_settings(self, game_dir: str, options: Dict) -> None:
        try:
            self.settings.update({"game_dir": game_dir, "mirror": self.var_mirror.get(),
                                  "threads": options["threads"],
                                  "isolate": bool(self.var_isolate.get())})
            config.save(self.settings)
        except Exception:  # noqa: BLE001
            pass

    def _run_job(self, job: Dict, options: Dict) -> None:
        reporter = GuiReporter(self._emit)
        isolate = bool(job.get("isolate"))
        try:
            if job["kind"] == "pack":
                result = modpack.install(
                    job["source"], game_dir=options["game_dir"], mirror=options["mirror"],
                    threads=options["threads"], reporter=reporter, skip_assets=options["skip_assets"],
                    content_root=None if not isolate else self._guess_pack_root(job["source"], options["game_dir"]),
                )
            else:
                game = job["game"]
                vanilla.install(game, options["game_dir"], mirror=options["mirror"],
                                threads=options["threads"], reporter=reporter,
                                skip_assets=options["skip_assets"], context=Context())
                result = {"version": game}
                loader = job["loader"]
                loader_version = job.get("loader_version")
                if loader != "none":
                    if loader == "fabric":
                        info = loader_mod.install_fabric(game, loader_version, options["game_dir"],
                                                        options["mirror"], None, options["threads"],
                                                        reporter, options["skip_assets"])
                    elif loader == "quilt":
                        info = loader_mod.install_quilt(game, loader_version, options["game_dir"],
                                                       options["mirror"], None, options["threads"],
                                                       reporter, options["skip_assets"])
                    elif loader == "forge":
                        info = loader_mod.install_forge(game, loader_version, options["game_dir"],
                                                       options["mirror"], None, None,
                                                       options["threads"], reporter, options["skip_assets"])
                    else:
                        info = loader_mod.install_neoforge(game, loader_version, options["game_dir"],
                                                          options["mirror"], None, None,
                                                          options["threads"], reporter, options["skip_assets"])
                    result.update(info)

                    if loader == "fabric" and job.get("fabric_api") is not None:
                        mods_dir = os.path.join(content_root(options["game_dir"], info.get("id"), isolate), "mods")
                        api = mods.install_fabric_api(game, mods_dir, job.get("fabric_api"), reporter=reporter)
                        result["fabric_api"] = api["fabric_api"]

            result["bytes"] = reporter.total_bytes
            result["files"] = reporter.done_files
            self._emit(("log", "完成。"))
            self._emit(("done", result))
        except (vanilla.InstallError, loader_mod.InstallError, modpack.ModpackError,
                DownloadError, RuntimeError) as exc:
            self._emit(("log", "错误：%s" % exc))
            self._emit(("done", {"error": str(exc)}))
        except Exception as exc:  # noqa: BLE001
            self._emit(("log", "未预期错误：%s\n%s" % (exc, traceback.format_exc())))
            self._emit(("done", {"error": str(exc)}))

    def _guess_pack_root(self, source: str, game_dir: str) -> Optional[str]:
        """整合包隔离开启时，内容写到 versions/<加载器版本>；解析失败则不隔离。"""
        try:
            zip_path, _meta = modpack.resolve_source(source, game_dir, reporter=None)
            index = modpack.read_index(zip_path)
            dependencies = index.get("dependencies") or {}
            loader, loader_version = modpack.loader_from_dependencies(dependencies)
            game = dependencies.get("minecraft", "")
            version_id = expected_version_id(loader or "none", loader_version, game)
            return content_root(game_dir, version_id, True)
        except Exception:  # noqa: BLE001
            return None

    # ---- 自定义下载 --------------------------------------------------

    def _start_custom(self) -> None:
        url = self.var_custom_url.get().strip()
        if not url:
            messagebox.showwarning("缺少链接", "请先填写要下载的链接。")
            return
        dest_dir = self.var_custom_dest.get().strip() or os.path.join(
            os.path.abspath(self._dir_value() or self.default_dir), "downloads")
        filename = self.var_custom_name.get().strip()
        dest = os.path.join(dest_dir, filename) if filename else dest_dir
        reset_cancel()
        reset_created()
        self._set_busy(True)
        self._reset_progress()
        threading.Thread(target=self._run_custom, args=(url, dest), daemon=True).start()

    def _run_custom(self, url: str, dest: str) -> None:
        reporter = GuiReporter(self._emit)
        try:
            path = mods.download_url(url, dest, reporter=reporter)
            self._emit(("log", "已保存：%s" % path))
            if mods.read_mrpack_index(path):
                self._emit(("ask_mrpack", path))
            else:
                self._emit(("done", {"custom": path, "bytes": reporter.total_bytes}))
        except Exception as exc:  # noqa: BLE001
            self._emit(("log", "下载失败：%s" % exc))
            self._emit(("done", {"error": str(exc)}))

    def _ask_install_mrpack(self, path: str) -> None:
        self._set_busy(False)
        if messagebox.askyesno("这是整合包", "下载完成：\n%s\n\n要直接按整合包安装到当前目录吗？" % path):
            self._set_busy(True)
            options = dict(game_dir=os.path.abspath(self._dir_value() or self.default_dir),
                           mirror=self._selected_mirror(),
                           threads=max(1, int(self.var_threads.get() or 8)),
                           skip_assets=bool(self.var_skip_assets.get()))
            threading.Thread(target=self._run_job,
                             args=({"kind": "pack", "source": path, "isolate": bool(self.var_isolate.get())},
                                   options), daemon=True).start()
        else:
            self._reset_progress()
            self.lbl_status.configure(text="完成")

    # ---- 结束 --------------------------------------------------------

    def _on_finished(self, result: Dict) -> None:
        self._set_busy(False)
        reset_cancel()
        if result.get("error"):
            self._reset_progress()
            if "取消" in str(result["error"]):
                self.lbl_status.configure(text="已取消")
                self._cleanup_created()
                self._append_log("已取消。")
                return
            self.lbl_status.configure(text="失败")
            messagebox.showerror("下载失败", result["error"])
            return
        self._complete_progress()
        self.lbl_status.configure(text="完成")
        if result.get("custom"):
            self._append_log("保存位置：%s" % result["custom"])
            return
        target = result.get("dir") or os.path.abspath(self._dir_value() or self.default_dir)
        lines = [("目录", target)]
        for key in ("version", "loader", "loader_version", "fabric_api", "id", "pack", "files"):
            if result.get(key):
                lines.append((key, result[key]))
        if result.get("bytes"):
            lines.append(("大小", human_size(result["bytes"])))
        text = "\n".join("%s：%s" % (k, v) for k, v in lines)
        self._append_log(text)
        if not self.self_test:
            if messagebox.askyesno("下载完成", text + "\n\n要打开目录吗？"):
                self._open_dir()

    # ---- 首次启动提示 ------------------------------------------------

    def _maybe_show_license_notice(self) -> None:
        if self.self_test or self.settings.get("license_notice"):
            return
        window = tk.Toplevel(self.root)
        window.title(APP_TITLE)
        window.resizable(False, False)
        window.transient(self.root)
        frame = ttk.Frame(window, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="使用提示", style="H1.TLabel").pack(anchor="w")
        ttk.Label(frame, text=LICENSE_TEXT, justify="left", wraplength=460).pack(anchor="w", pady=(10, 16))

        def close() -> None:
            self.settings["license_notice"] = True
            try:
                config.save(self.settings)
            except Exception:  # noqa: BLE001
                pass
            try:
                window.grab_release()
            except tk.TclError:
                pass
            window.destroy()

        def get_original() -> None:
            if not open_external(LICENSE_URL):
                messagebox.showinfo("请手动打开", "没能自动打开浏览器，请手动访问：\n%s" % LICENSE_URL)
            close()

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="获取正版", command=get_original).pack(side="left")
        ttk.Button(buttons, text="我是正版用户", command=close).pack(side="right")
        window.protocol("WM_DELETE_WINDOW", close)
        window.update_idletasks()
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - window.winfo_width()) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - window.winfo_height()) // 3)
        window.geometry("+%d+%d" % (x, y))
        try:
            window.grab_set()
        except tk.TclError:
            pass

    # ---- 自检 --------------------------------------------------------

    def _finish_self_test(self) -> None:
        print("SELF-TEST OK: versions=%d tabs=%d dir=%s isolate=%s" % (
            len(self.versions), len(self.notebook.tabs()), self.var_dir.get(), self.var_isolate.get()))
        self.root.destroy()


# ---------------------------------------------------------------- 入口


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    self_test = "--self-test" in argv
    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            pass

    root = tk.Tk()
    app = App(root, self_test=self_test, auto_close_ms=1500 if self_test else None)
    try:
        root.lift()
        root.attributes("-topmost", True)
        root.after(800, lambda: root.attributes("-topmost", False))
    except tk.TclError:
        pass
    if not self_test:
        sys.stdout = _Stream(app._emit)  # type: ignore[assignment]
        sys.stderr = _Stream(app._emit)  # type: ignore[assignment]
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
