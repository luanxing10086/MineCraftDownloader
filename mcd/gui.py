"""图形界面：选游戏版本 + 选加载器 + 一键下载（tkinter，标准库，无第三方依赖）。

设计目标对齐 PCL 的“版本选择”体验：左边是版本列表，右边选加载器，底部是下载选项与日志。
所有网络与磁盘操作都在后台线程里跑，界面通过队列回传日志与进度。
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import traceback
from typing import Dict, List, Optional

import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import font as tkfont
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from . import __version__, java, modpack, vanilla
from . import loaders as loader_mod
from .mirror import BMCLAPI, OFFICIAL, Mirror
from .net import DownloadError, human_size
from .rules import Context

APP_TITLE = "MCD · Minecraft 下载器"
LOADER_CHOICES = [("none", "无（仅原版）"), ("fabric", "Fabric"), ("quilt", "Quilt"),
                  ("forge", "Forge"), ("neoforge", "NeoForge")]
AUTO = "自动（推荐）"


# ---------------------------------------------------------------- 进度适配


class GuiReporter:
    """把 net.Reporter 的终端输出改写成队列消息，供界面消费。"""

    def __init__(self, emit):
        self._emit = emit
        self.total_files = 0
        self.done_files = 0
        self.total_bytes = 0
        self.skipped_files = 0

    def start(self, total_files: int) -> None:
        self.total_files += total_files
        self._emit(("progress", 0.0, "准备中"))

    def progress(self, label: str, got: int, total: int) -> None:
        ratio = (got / total) if total else None
        if ratio is None:
            self._emit(("status", "%s  %s" % (label, human_size(got))))
        else:
            self._emit(("progress", min(ratio, 1.0), "%s  %s / %s" % (label, human_size(got), human_size(total))))

    def done(self, label: str, size: int) -> None:
        self.done_files += 1
        self.total_bytes += size
        self._emit(("log", "[%d/%d] %s  (%s)" % (self.done_files, max(self.total_files, self.done_files),
                                                 label, human_size(size))))

    def skipped(self, size: int) -> None:
        self.done_files += 1
        self.skipped_files += 1

    def flush(self) -> None:
        pass


class _Stream:
    """替代 sys.stdout/stderr：窗口程序没有控制台，把输出接进日志框。"""

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

        self.root.title("%s  v%s" % (APP_TITLE, __version__))
        self._apply_dpi_scale()
        self.root.minsize(int(900 * self.scale), int(640 * self.scale))
        self._init_style()
        self._build_ui()

        self.root.after(80, self._drain_queue)
        self._load_manifest_async()
        if auto_close_ms:
            self.root.after(auto_close_ms, self._finish_self_test)

    # ---- 外观 -------------------------------------------------------

    def _apply_dpi_scale(self) -> None:
        """高分屏下 Tk 默认按 96 DPI 排版，窗口会显得很小；按实际 DPI 放大。"""
        try:
            self.scale = max(1.0, self.root.winfo_fpixels("1i") / 96.0)
        except tk.TclError:
            self.scale = 1.0
        self.root.geometry("%dx%d" % (int(1020 * self.scale), int(780 * self.scale)))

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
        style.configure("Accent.TButton", font=(family, 10, "bold"))

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x")
        ttk.Label(header, text="Minecraft 下载器", style="H1.TLabel").pack(side="left")
        ttk.Label(header, text="只下载，不启动 · 落盘结构兼容 PCL / HMCL / Prism",
                  style="Hint.TLabel").pack(side="left", padx=12)

        self.notebook = ttk.Notebook(outer)
        self.notebook.pack(fill="both", expand=True, pady=(10, 8))
        self.tab_version = ttk.Frame(self.notebook, padding=10)
        self.tab_pack = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.tab_version, text="  版本与加载器  ")
        self.notebook.add(self.tab_pack, text="  整合包  ")
        self.notebook.bind("<<NotebookTabChanged>>", lambda _e: self._update_action_text())

        self._build_version_tab()
        self._build_pack_tab()
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
        entry_search = ttk.Entry(bar, textvariable=self.var_search, width=18)
        entry_search.pack(side="left", padx=(6, 12))
        entry_search.bind("<KeyRelease>", lambda _e: self._refresh_version_list())

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
        self.var_loader_version = tk.StringVar(value=AUTO)
        self.combo_loader_version = ttk.Combobox(row, textvariable=self.var_loader_version, width=26,
                                                 values=[AUTO])
        self.combo_loader_version.pack(side="left", padx=(6, 16))

        self.lbl_loader_hint = ttk.Label(loader, text="选择加载器后会联网列出可用版本；Forge / NeoForge 需要本机有 Java 17 或 21。",
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

        tips = (
            "说明：\n"
            "· 会先按整合包声明的 Minecraft 版本下载原版，再装对应加载器，最后拉取 mods / 配置与 overrides。\n"
            "· 整合包里的文件直接落到“下载目录”下，可直接用启动器打开该目录。\n"
            "· CurseForge 格式（manifest.json）暂不支持，会给出提示。"
        )
        ttk.Label(box, text=tips, style="Hint.TLabel", justify="left").pack(anchor="w", pady=(10, 0))

    # ---- 选项 --------------------------------------------------------

    def _build_options(self, parent: ttk.Frame) -> None:
        box = ttk.LabelFrame(parent, text="下载选项", padding=8)
        box.pack(fill="x")

        line1 = ttk.Frame(box)
        line1.pack(fill="x")
        ttk.Label(line1, text="安装目录").pack(side="left")
        self.var_dir = tk.StringVar(value=os.path.abspath("minecraft"))
        ttk.Entry(line1, textvariable=self.var_dir).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(line1, text="浏览…", command=self._browse_dir).pack(side="left")
        ttk.Button(line1, text="打开", command=self._open_dir).pack(side="left", padx=(6, 0))

        line2 = ttk.Frame(box)
        line2.pack(fill="x", pady=(8, 0))
        ttk.Label(line2, text="下载源").pack(side="left")
        self.var_mirror = tk.StringVar(value="bmclapi")
        ttk.Radiobutton(line2, text="BMCLAPI 镜像（国内推荐）", value="bmclapi",
                        variable=self.var_mirror).pack(side="left", padx=(6, 10))
        ttk.Radiobutton(line2, text="Mojang 官方", value="official",
                        variable=self.var_mirror).pack(side="left")

        self.var_skip_assets = tk.BooleanVar(value=False)
        ttk.Checkbutton(line2, text="跳过资源文件（assets，体积最大）",
                        variable=self.var_skip_assets).pack(side="left", padx=16)

        ttk.Label(line2, text="并发").pack(side="left", padx=(8, 0))
        self.var_threads = tk.IntVar(value=8)
        ttk.Spinbox(line2, from_=1, to=32, width=4, textvariable=self.var_threads).pack(side="left", padx=4)

    def _build_log(self, parent: ttk.Frame) -> None:
        # 先占住底部操作条，日志框再用剩余空间，避免按钮被挤出窗口
        bottom = ttk.Frame(parent)
        bottom.pack(side="bottom", fill="x", pady=(8, 0))
        self.progress = ttk.Progressbar(bottom, mode="determinate", maximum=100)
        self.progress.pack(side="left", fill="x", expand=True)
        self.lbl_status = ttk.Label(bottom, text="就绪", width=42, anchor="w")
        self.lbl_status.pack(side="left", padx=10)
        self.btn_start = ttk.Button(bottom, text="开始下载", style="Accent.TButton", command=self._start)
        self.btn_start.pack(side="right")

        box = ttk.LabelFrame(parent, text="日志", padding=6)
        box.pack(fill="both", expand=True, pady=(8, 0))

        self.log = ScrolledText(box, height=8, wrap="none", state="disabled")
        self.log.pack(fill="both", expand=True)

    # ---- 辅助 --------------------------------------------------------

    def _emit(self, message: tuple) -> None:
        self.queue.put(message)

    def _drain_queue(self) -> None:
        try:
            while True:
                kind, *rest = self.queue.get_nowait()
                if kind == "log":
                    self._append_log(rest[0])
                elif kind == "progress":
                    ratio, label = rest
                    self.progress["value"] = ratio * 100
                    self.lbl_status.configure(text=label[-60:])
                elif kind == "status":
                    self.lbl_status.configure(text=str(rest[0])[-60:])
                elif kind == "state":
                    self._set_busy(bool(rest[0]))
                elif kind == "refresh_versions":
                    self._refresh_version_list()
                elif kind == "loader_versions":
                    self._apply_loader_versions(*rest)
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

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.btn_start.configure(state=state, text="下载中…" if busy else "开始下载")

    def _update_action_text(self) -> None:
        if self.busy:
            return
        is_pack = self.notebook.index(self.notebook.select()) == 1
        self.btn_start.configure(text="下载整合包" if is_pack else "开始下载")

    def _browse_dir(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.var_dir.get() or os.getcwd())
        if chosen:
            self.var_dir.set(os.path.normpath(chosen))

    def _browse_pack(self) -> None:
        chosen = filedialog.askopenfilename(filetypes=[("Modrinth 整合包", "*.mrpack"), ("压缩包", "*.zip")])
        if chosen:
            self.var_pack.set(chosen)
            self.notebook.select(self.tab_pack)

    def _open_dir(self) -> None:
        path = os.path.abspath(self.var_dir.get())
        os.makedirs(path, exist_ok=True)
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("打开失败", str(exc))

    # ---- 版本列表 ----------------------------------------------------

    def _load_manifest_async(self) -> None:
        self.lbl_versions.configure(text="正在加载版本列表…")

        def work():
            mirror = Mirror(OFFICIAL if self.var_mirror.get() == "official" else BMCLAPI)
            try:
                manifest = vanilla.load_manifest(os.path.abspath(self.var_dir.get()), mirror, refresh=True)
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
        keyword = self.var_search.get().strip().lower()
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

    # ---- 加载器版本 --------------------------------------------------

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
        self.var_loader_version.set(AUTO)
        self.combo_loader_version.configure(values=[AUTO], state="readonly")

        if key == "none":
            self.lbl_loader_hint.configure(text="选择加载器后会联网列出可用版本；Forge / NeoForge 需要本机有 Java 17 或 21。")
            return

        game = self._selected_version()
        if not game:
            return
        self.lbl_loader_hint.configure(text="正在查询 %s 支持 %s 的版本…" % (key, game))

        def work():
            mirror = Mirror(BMCLAPI if self.var_mirror.get() == "bmclapi" else OFFICIAL)
            try:
                values = self._list_loader_versions(key, game, mirror)
            except Exception as exc:  # noqa: BLE001
                values = []
                self._emit(("log", "查询加载器版本失败：%s" % exc))
            if seq != self._loader_seq:
                return
            self._emit(("loader_versions", key, game, values))

        threading.Thread(target=work, daemon=True).start()

    def _list_loader_versions(self, key: str, game: str, mirror: Mirror) -> List[str]:
        from .net import fetch_json

        if key == "fabric":
            data = fetch_json(["https://meta.fabricmc.net/v2/versions/loader/%s" % game])
            return [item["loader"]["version"] for item in data][:40]
        if key == "quilt":
            data = fetch_json(["https://meta.quiltmc.org/v3/versions/loader/%s" % game])
            return [item["loader"]["version"] for item in data][:40]
        if key == "forge":
            promos = fetch_json([loader_mod.FORGE_PROMOS]).get("promos", {})
            values = []
            for suffix in ("recommended", "latest"):
                value = promos.get("%s-%s" % (game, suffix))
                if value and value not in values:
                    values.append(value)
            return values
        if key == "neoforge":
            return [loader_mod.resolve_neoforge_version(game, mirror)]
        return []

    def _apply_loader_versions(self, key: str, game: str, values: List[str]) -> None:
        if self._loader_key() != key or self._selected_version() != game:
            return
        if not values:
            self.combo_loader_version.configure(values=[AUTO], state="readonly")
            self.lbl_loader_hint.configure(text="没有查到可用版本，将使用“%s”自动选择。" % AUTO)
            return
        self.combo_loader_version.configure(values=[AUTO] + values, state="readonly")
        self.lbl_loader_hint.configure(text="共 %d 个可选版本；Forge / NeoForge 安装需要 Java 17 或 21。" % len(values))

    # ---- 开始下载 ----------------------------------------------------

    def _start(self) -> None:
        if self.busy:
            return
        is_pack = self.notebook.index(self.notebook.select()) == 1
        if is_pack:
            source = self.var_pack.get().strip()
            if not source:
                messagebox.showwarning("缺少整合包", "请填写 Modrinth 项目 slug / 链接，或选择 .mrpack 文件。")
                return
            job = dict(kind="pack", source=source)
        else:
            game = self._selected_version()
            if not game:
                messagebox.showwarning("未选择版本", "请先在列表里选中一个 Minecraft 版本。")
                return
            job = dict(kind="version", game=game, loader=self._loader_key(),
                       loader_version=self.var_loader_version.get())

        game_dir = os.path.abspath(self.var_dir.get().strip() or "minecraft")
        try:
            os.makedirs(game_dir, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("目录不可用", "无法创建目录：\n%s\n%s" % (game_dir, exc))
            return

        options = dict(
            game_dir=game_dir,
            mirror=Mirror(BMCLAPI if self.var_mirror.get() == "bmclapi" else OFFICIAL),
            threads=max(1, int(self.var_threads.get() or 8)),
            skip_assets=bool(self.var_skip_assets.get()),
        )
        self._set_busy(True)
        self.progress["value"] = 0
        self._append_log("=" * 60)
        self._append_log("目标目录：%s" % game_dir)
        self._append_log("下载源：%s" % options["mirror"].label)
        threading.Thread(target=self._run_job, args=(job, options), daemon=True).start()

    def _run_job(self, job: Dict, options: Dict) -> None:
        reporter = GuiReporter(self._emit)
        try:
            if job["kind"] == "pack":
                result = modpack.install(
                    job["source"],
                    game_dir=options["game_dir"],
                    mirror=options["mirror"],
                    threads=options["threads"],
                    reporter=reporter,
                    skip_assets=options["skip_assets"],
                )
            else:
                game = job["game"]
                vanilla.install(game, options["game_dir"], mirror=options["mirror"],
                                threads=options["threads"], reporter=reporter,
                                skip_assets=options["skip_assets"], context=Context())
                result = {"version": game}
                loader = job["loader"]
                loader_version = job["loader_version"]
                if loader_version == AUTO:
                    loader_version = None
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

            result["bytes"] = reporter.total_bytes
            result["files"] = reporter.done_files
            self._emit(("log", "完成。"))
            self._emit(("done", result))
        except (vanilla.InstallError, loader_mod.InstallError, modpack.ModpackError,
                DownloadError, RuntimeError) as exc:
            self._emit(("log", "错误：%s" % exc))
            self._emit(("done", {"error": str(exc)}))
        except Exception as exc:  # noqa: BLE001 - 未预期错误也要回传界面
            self._emit(("log", "未预期错误：%s\n%s" % (exc, traceback.format_exc())))
            self._emit(("done", {"error": str(exc)}))

    def _on_finished(self, result: Dict) -> None:
        self._set_busy(False)
        if result.get("error"):
            self.progress["value"] = 0
            self.lbl_status.configure(text="失败")
            messagebox.showerror("下载失败", result["error"])
            return
        self.progress["value"] = 100
        self.lbl_status.configure(text="完成")
        target = result.get("dir") or os.path.abspath(self.var_dir.get())
        lines = [("目录", target)]
        for key in ("version", "loader", "loader_version", "id", "pack", "files"):
            if result.get(key):
                lines.append((key, result[key]))
        if result.get("bytes"):
            lines.append(("大小", human_size(result["bytes"])))
        text = "\n".join("%s：%s" % (k, v) for k, v in lines)
        self._append_log(text)
        if not self.self_test:
            if messagebox.askyesno("下载完成", text + "\n\n要打开目录吗？"):
                self._open_dir()

    # ---- 自检 --------------------------------------------------------

    def _finish_self_test(self) -> None:
        print("SELF-TEST OK: versions=%d, tab=%s, dir=%s" % (
            len(self.versions), self.notebook.index(self.notebook.select()), self.var_dir.get()))
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
    app = App(root, self_test=self_test, auto_close_ms=1200 if self_test else None)
    try:
        root.lift()
        root.attributes("-topmost", True)
        root.after(800, lambda: root.attributes("-topmost", False))
    except tk.TclError:
        pass
    if not self_test:
        # 窗口程序的 stdout 不可用，重定向到日志框
        sys.stdout = _Stream(app._emit)  # type: ignore[assignment]
        sys.stderr = _Stream(app._emit)  # type: ignore[assignment]
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
