"""HTTP 层：只用标准库，支持重试、镜像回退、sha1 校验、并发下载与进度显示。"""

from __future__ import annotations

import hashlib
import http.client
import io
import json
import os
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Iterable, List, Optional, Sequence
from urllib.parse import urljoin, urlsplit

USER_AGENT = "MCD/0.1 (Minecraft downloader)"
CHUNK = 256 * 1024
TIMEOUT = 30


class DownloadError(RuntimeError):
    """下载失败（网络、校验或磁盘）。"""


class DownloadCancelled(DownloadError):
    """用户主动取消。"""


_CANCEL = threading.Event()
_CREATED: "set[str]" = set()
_CREATED_LOCK = threading.Lock()

# 自适应并发：遇 429/403 就把并发减半，连续成功后慢慢加回来
_ADAPT = {"base": 8, "cap": 8}
_ADAPT_LOCK = threading.Lock()


def _cap_for(base: int) -> int:
    with _ADAPT_LOCK:
        if _ADAPT["base"] != base:
            _ADAPT["base"] = base
            _ADAPT["cap"] = base
        return max(1, min(base, _ADAPT["cap"]))


def _note_throttled() -> None:
    with _ADAPT_LOCK:
        _ADAPT["cap"] = max(2, _ADAPT["cap"] // 2)


def _note_batch_ok() -> None:
    with _ADAPT_LOCK:
        if _ADAPT["cap"] < _ADAPT["base"]:
            _ADAPT["cap"] += 1


def current_concurrency(configured: int) -> int:
    """给 UI / 日志用：当前实际使用的并发数。"""
    return _cap_for(configured)


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


_TLS_CONTEXT = ssl.create_default_context()
_TLS_LOCAL = threading.local()
_SSL_LOCK = threading.Lock()


def _thread_pool() -> Dict[tuple, http.client.HTTPConnection]:
    pool = getattr(_TLS_LOCAL, "pool", None)
    if pool is None:
        pool = _TLS_LOCAL.pool = {}
    return pool


class _KeepAliveResponse:
    """把 http.client 的响应包成和 urllib 一样好用的上下文管理器，并在读完后归还连接。"""

    def __init__(self, conn, response, pool, key, url):
        self._conn = conn
        self._response = response
        self._pool = pool
        self._key = key
        self._url = url
        self._complete = False
        self._closed = False

    @property
    def headers(self):
        return self._response.headers

    def read(self, amount: int = -1) -> bytes:
        # 没有 Content-Length 时不能直接用 read(-1)：keep-alive 连接不会 EOF，会一直阻塞
        if amount is None or amount < 0:
            pieces = []
            while True:
                piece = self._response.read(CHUNK)
                if not piece:
                    break
                pieces.append(piece)
            self._complete = True
            return b"".join(pieces)
        data = self._response.read(amount)
        if not data:
            self._complete = True
        return data

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        # 只复用“长度已知且已读完”的响应；chunked / 未知长度一律关掉，避免连接状态错乱
        length_known = (getattr(self._response, "length", None) is not None
                        and not getattr(self._response, "chunked", False))
        reusable = self._complete and not self._response.will_close and length_known
        if reusable:
            self._pool[self._key] = (time.time(), self._conn)
        else:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


def _request_keepalive(url: str, proxy: Optional[str], timeout: int, redirects: int = 0):
    """用线程内的连接池发 GET；同 host 复用连接，省掉每次 240ms 的 TLS 握手。"""
    parts = urlsplit(url)
    scheme = (parts.scheme or "https").lower()
    host = parts.hostname
    if not host:
        raise ValueError("非法 URL: %s" % url)
    port = parts.port or (443 if scheme == "https" else 80)
    path = (parts.path or "/") + (("?" + parts.query) if parts.query else "")
    key = (scheme, host, port)
    pool = _thread_pool()

    for attempt in (0, 1):
        entry = pool.pop(key, None)
        conn = None
        if entry is not None:
            cached_at, cached = entry
            if time.time() - cached_at < 45:
                conn = cached
            else:
                try:
                    cached.close()
                except Exception:  # noqa: BLE001
                    pass
        if conn is None:
            if scheme == "https":
                with _SSL_LOCK:
                    conn = http.client.HTTPSConnection(host, port, timeout=timeout, context=_TLS_CONTEXT)
            else:
                conn = http.client.HTTPConnection(host, port, timeout=timeout)
        try:
            conn.request("GET", path, headers={
                "User-Agent": USER_AGENT,
                "Accept": "*/*",
                "Connection": "keep-alive",
            })
            response = conn.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                try:
                    while response.read(CHUNK):
                        pass
                except Exception:  # noqa: BLE001
                    pass
                if not location or redirects >= 5:
                    conn.close()
                    raise DownloadError("重定向次数过多：%s" % url)
                target = urljoin(url, location)
                if urlsplit(target).hostname == host and not response.will_close:
                    # 同主机跳转：连接还能用，放回池里省一次 TLS
                    pool[key] = (time.time(), conn)
                else:
                    conn.close()
                return _request_keepalive(target, proxy, timeout, redirects + 1)
            if response.status >= 400:
                body = response.read()
                conn.close()
                raise urllib.error.HTTPError(url, response.status, response.reason, response.headers,
                                             io.BytesIO(body))
            return _KeepAliveResponse(conn, response, pool, key, url)
        except urllib.error.HTTPError:
            raise
        except Exception:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
            if attempt == 1:
                raise
    raise DownloadError("请求失败：%s" % url)


def open_url(url: str, proxy: Optional[str] = None, timeout: int = TIMEOUT):
    scheme = urlsplit(url).scheme.lower()
    if proxy or scheme not in ("http", "https"):
        # 代理 / file: 等非 HTTP 场景交回 urllib
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        handlers = []
        if proxy:
            handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        opener = urllib.request.build_opener(*handlers)
        return opener.open(request, timeout=timeout)
    return _request_keepalive(url, proxy, timeout)


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
    rate_limited = False
    next_wait = 0
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
                status = getattr(exc, "code", None)
                if status in (403, 429):
                    retry_after = None
                    try:
                        retry_after = exc.headers.get("Retry-After")  # type: ignore[union-attr]
                    except Exception:  # noqa: BLE001
                        retry_after = None
                    rate_limited = True
                    _note_throttled()
                    if retry_after and str(retry_after).isdigit():
                        next_wait = max(next_wait, min(int(retry_after), 60))
                try:
                    os.remove(part)
                except OSError:
                    pass
        if attempt < retries:
            # 限流时退避得久一点：5s → 15s → 30s；普通错误 1/2/4s
            default_wait = [5, 15, 30][min(attempt - 1, 2)] if rate_limited else min(2 ** (attempt - 1), 4)
            time.sleep(max(default_wait, next_wait))
            next_wait = 0

    raise DownloadError(_describe_failure(dest, errors))


def _describe_failure(dest: str, errors: Sequence[str]) -> str:
    """把失败原因翻译成人能看懂的一句话提示。"""
    joined = " ".join(errors)
    text = "下载失败：%s\n  %s" % (dest, "\n  ".join(list(errors)[-4:]))
    if "429" in joined or "403" in joined:
        text += "\n提示：镜像限流（HTTP 429/403）。等几秒再试，或换下载源/换时段。"
    if "timed out" in joined.lower() or "URLError" in joined or "ConnectionReset" in joined:
        text += "\n提示：连接超时或被重置，可能需要代理（--proxy 或系统代理）。"
    if all("404" in item for item in list(errors)[-2:]):
        text += "\n提示：返回 404，这个版本可能没有对应的产物文件。"
    return text


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

    workers = _cap_for(threads)
    if workers <= 1:
        for task in tasks:
            error = worker(task)
            if error:
                failures.append(error)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for error in pool.map(worker, tasks):
                if error:
                    failures.append(error)
    if failures:
        if any(("429" in item) or ("403" in item) for item in failures):
            _note_throttled()
    else:
        _note_batch_ok()
    if reporter:
        reporter.flush()
    return failures
