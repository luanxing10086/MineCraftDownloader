"""镜像支持：官方源与 BMCLAPI。

BMCLAPI（Bang Bang 93 提供的公益镜像）在本项目里覆盖：
    * 版本清单   /mc/game/version_manifest_v2.json
    * 版本 JSON  /version/<id>/json
    * 客户端 JAR /version/<id>/client
    * 资源对象   /assets/<前两位>/<hash>
    * maven 库   /maven/<group>/<artifact>/...
资源索引 JSON 与 log4j 配置没有被镜像，会自动回退到官方地址。
"""

from __future__ import annotations

from typing import List

BMCLAPI_BASE = "https://bmclapi2.bangbang93.com"
OFFICIAL_BASE = "https://piston-meta.mojang.com"

OFFICIAL = "official"
BMCLAPI = "bmclapi"
NAMES = (OFFICIAL, BMCLAPI)

# 官方主机 -> BMCLAPI 前缀；仅用于确实被镜像的路径
_REWRITE_RULES = (
    ("https://resources.download.minecraft.net/", "/assets/"),
    ("https://libraries.minecraft.net/", "/maven/"),
    ("https://maven.minecraftforge.net/", "/maven/"),
    ("https://maven.neoforged.net/releases/", "/maven/"),
    ("https://maven.fabricmc.net/", "/maven/"),
    ("https://maven.quiltmc.org/repository/release/", "/maven/"),
)


class Mirror:
    """按名称选择下载源，并把官方 URL 映射为镜像 URL（附带回退候选）。"""

    def __init__(self, name: str = OFFICIAL):
        name = (name or OFFICIAL).lower()
        if name not in NAMES:
            raise ValueError("未知下载源 %r，可选：%s" % (name, " / ".join(NAMES)))
        self.name = name

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return "Mirror(%s)" % self.name

    @property
    def is_mirror(self) -> bool:
        return self.name == BMCLAPI

    @property
    def base(self) -> str:
        return BMCLAPI_BASE if self.is_mirror else ""

    @property
    def label(self) -> str:
        return "BMCLAPI 镜像" if self.is_mirror else "官方源"

    # ---- 版本清单 / 版本 JSON / 客户端 ----------------------------------

    def manifest_urls(self) -> List[str]:
        official = OFFICIAL_BASE + "/mc/game/version_manifest_v2.json"
        if self.is_mirror:
            return [BMCLAPI_BASE + "/mc/game/version_manifest_v2.json", official]
        return [official]

    def version_json_urls(self, version_id: str, official_url: str) -> List[str]:
        if self.is_mirror:
            return ["%s/version/%s/json" % (BMCLAPI_BASE, version_id), official_url]
        return [official_url]

    def client_urls(self, version_id: str, official_url: str) -> List[str]:
        if self.is_mirror:
            return ["%s/version/%s/client" % (BMCLAPI_BASE, version_id), official_url]
        return [official_url]

    # ---- 通用重写 -------------------------------------------------------

    def rewrite(self, url: str) -> str:
        if not self.is_mirror or not url:
            return url
        for prefix, replacement in _REWRITE_RULES:
            if url.startswith(prefix):
                return BMCLAPI_BASE + replacement + url[len(prefix):]
        return url

    def urls(self, official_url: str) -> List[str]:
        """镜像优先、官方兜底；官方源则原样返回。"""
        rewritten = self.rewrite(official_url)
        if rewritten == official_url:
            return [official_url]
        return [rewritten, official_url]
