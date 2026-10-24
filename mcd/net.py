"""HTTP 层：只用标准库，支持重试、镜像回退、sha1 校验、并发下载与进度显示。"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Iterable, List, Optional, Sequence

USER_AGENT = "MCD/0.1 (Minecraft downloader; +https://github.com/luanxing10086/MineCraftDownloader)"
CHUNK = 256 * 1024
TIMEOUT = 30


class DownloadError(RuntimeError):
    """下载失败（网络、校验或磁盘）。"""


class DownloadCancelled(DownloadError):
    """用户主动取消。"""


_CANCEL = threading.Event()
_CREATED: "set[str]" = set()
_CREATED_LOCK = threading.Lock()


def reset_created() -> None:
    """开始一次新任务前清空“本次新建文件”的记录。"""
    with _CREATED_LOCK:
        _CREATED.clear()


def created_files() -> List[str]:
    """本次任务新建的文件（取消时用于清理，不影响此前已存在的文件）。"""
    with _CREATED_LOCK:
        return sorted(_CREATED)


def _remember_created(path: str) -> None:
    with _CREATED_LOCK:
        _CREATED.add(path)


def reset_cancel() -> None:
    _CANCEL.clear()


def request_cancel() -> None:
    _CANCEL.set()


def is_cancelled() -> bool:
    return _CANCEL.is_set()


def raise_if_cancelled() -> None:
    if _CANCEL.is_set():
        raise DownloadCancelled("已取消")


# ---------------------------------------------------------------- 基础工具


def current_proxy() -> Optional[str]:
    """读取 HTTPS_PROXY / HTTP_PROXY，便于在受限网络里走代理。"""
    for key in ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY"):
        value = os.environ.get(key)
        if value:
            return value
    return None


def open_url(url: str, proxy: Optional[str] = None, timeout: int = TIMEOUT):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    handlers = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    opener = urllib.request.build_opener(*handlers)
    return opener.open(request, timeout=timeout)


def fetch_bytes(urls: Sequence[str], proxy: Optional[str] = None, timeout: int = TIMEOUT) -> bytes:
    """按顺序尝试多个候选 URL，返回第一个成功响应的内容。"""
    errors: List[str] = []
    for url in urls:
        try:
            with open_url(url, proxy=proxy, timeout=timeout) as response:
                return response.read()
        except Exception as exc:  # noqa: BLE001 - 逐个回退，最后统一报错
            errors.append("%s -> %s" % (url, exc))
    raise DownloadError("所有地址都不可用：\n  " + "\n  ".join(errors))


def fetch_json(urls: Sequence[str], proxy: Optional[str] = None, timeout: int = TIMEOUT) -> dict:
    raw = fetch_bytes(urls, proxy=proxy, timeout=timeout)
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        raise DownloadError("返回内容不是合法 JSON：%s" % exc)


def file_sha1(path: str) -> str:
    digest = hashlib.sha1()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def human_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(num) < 1024 or unit == "GB":
            return "%.1f %s" % (num, unit)
        num /= 1024
    return "%.1f GB" % num


# ---------------------------------------------------------------- 进度显示


class Reporter:
    """单行刷新的进度输出；stdout 不是终端时退化为逐条输出。"""

    def __init__(self, enabled: bool = True, stream=None):
        self.enabled = enabled and not os.environ.get("MCD_NO_PROGRESS")
        self.stream = stream or sys.stdout
        self._lock = threading.Lock()
        self._last = 0.0
        self._tty = bool(getattr(self.stream, "isatty", lambda: False)())
        self.total_files = 0
        self.done_files = 0
        self.total_bytes = 0
        self.skipped_files = 0

    def start(self, total_files: int) -> None:
        self.total_files += total_files

    def progress(self, label: str, got: int, total: int) -> None:
        if not self.enabled or not self._tty:
            return
        now = time.time()
        if now - self._last < 0.2:
            return
        self._last = now
        percent = ("%3d%%" % int(got * 100 / total)) if total else " ??%"
        line = "  %s %8s / %-8s %s" % (percent, human_size(got), human_size(total), label[-52:])
        with self._lock:
            self.stream.write("\r" + line.ljust(96)[:96])
            self.stream.flush()

    def done(self, label: str, size: int) -> None:
        with self._lock:
            self.done_files += 1
            if self.done_files > self.total_files:
                self.total_files = self.done_files
            self.total_bytes += size
            if self._tty and self.enabled:
                self.stream.write("\r" + " " * 96 + "\r")
            if self.enabled and not self._tty:
                self.stream.write("  [%d/%d] %s (%s)\n" % (self.done_files, self.total_files, label, human_size(size)))
            self.stream.flush()

    def skipped(self, size: int) -> None:
        with self._lock:
            self.skipped_files += 1
            self.done_files += 1

    def flush(self) -> None:
        if self.enabled and self._tty:
            with self._lock:
                self.stream.write("\n")
                self.stream.flush()


# ---------------------------------------------------------------- 下载实现


def download(
    dest: str,
    urls: Sequence[str],
    sha1: Optional[str] = None,
    size: Optional[int] = None,
    proxy: Optional[str] = None,
    retries: int = 3,
    reporter: Optional[Reporter] = None,
    label: Optional[str] = None,
    counted: bool = False,
) -> int:
    """把 urls 中最先可用的资源下载到 dest，返回字节数；已存在且校验通过则返回 0。"""
    dest = os.path.abspath(dest)
    label = label or os.path.basename(dest)
    raise_if_cancelled()
    existed_before = os.path.exists(dest)
    if reporter and not counted:
        reporter.start(1)
        if size and hasattr(reporter, "expect"):
            reporter.expect(int(size))
    if os.path.exists(dest):
        if sha1:
            if file_sha1(dest) == sha1:
                if reporter:
                    reporter.skipped(os.path.getsize(dest))
                return 0
            os.remove(dest)
        else:
            return 0

    directory = os.path.dirname(dest)
    if directory:
        os.makedirs(directory, exist_ok=True)

    errors: List[str] = []
    for attempt in range(1, retries + 1):
        for url in urls:
            part = dest + ".part"
            try:
                with open_url(url, proxy=proxy) as response, open(part, "wb") as handle:
                    total = int(response.headers.get("Content-Length") or size or 0)
                    got = 0
                    while True:
                        if _CANCEL.is_set():
                            raise DownloadCancelled("已取消")
                        chunk = response.read(CHUNK)
                        if not chunk:
                            break
                        handle.write(chunk)
                        got += len(chunk)
                        if reporter:
                            reporter.progress(label, got, total)
                if sha1 and file_sha1(part) != sha1:
                    raise DownloadError("sha1 校验失败")
                os.replace(part, dest)
                if not existed_before:
                    _remember_created(dest)
                if reporter:
                    reporter.done(label, got)
                return got
            except DownloadCancelled:
                try:
                    os.remove(part)
                except OSError:
                    pass
                raise
            except Exception as exc:  # noqa: BLE001 - 换下一个候选/重试
                errors.append("%s -> %s" % (url, exc))
                try:
                    os.remove(part)
                except OSError:
                    pass
        if attempt < retries:
            time.sleep(min(2 ** (attempt - 1), 4))

    raise DownloadError("下载失败：%s\n  %s" % (dest, "\n  ".join(errors[-4:])))


def download_many(
    items: Iterable[Dict],
    proxy: Optional[str] = None,
    threads: int = 8,
    reporter: Optional[Reporter] = None,
) -> List[str]:
    """并发下载一批任务；每项形如 {dest, urls, sha1?, size?, label?}。返回失败清单。"""
    tasks = list(items)
    if reporter:
        reporter.start(len(tasks))
    failures: List[str] = []

    def worker(task: Dict) -> Optional[str]:
        raise_if_cancelled()
        try:
            download(
                task["dest"],
                task["urls"],
                sha1=task.get("sha1"),
                size=task.get("size"),
                proxy=proxy,
                reporter=reporter,
                label=task.get("label"),
                counted=True,
            )
            return None
        except DownloadCancelled:
            raise
        except Exception as exc:  # noqa: BLE001 - 汇总后统一报告
            return "%s: %s" % (task.get("label") or task["dest"], exc)

    if threads <= 1:
        for task in tasks:
            error = worker(task)
            if error:
                failures.append(error)
    else:
        with ThreadPoolExecutor(max_workers=max(1, threads)) as pool:
            for error in pool.map(worker, tasks):
                if error:
                    failures.append(error)
    if reporter:
        reporter.flush()
    return failures
