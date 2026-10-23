"""下载源：官方、BMCLAPI，以及用户导入的自定义源。

BMCLAPI（Bang Bang 93 提供的公益镜像）覆盖：
    * 版本清单   /mc/game/version_manifest_v2.json
    * 版本 JSON  /version/<id>/json
    * 客户端 JAR /version/<id>/client
    * 资源对象   /assets/<前两位>/<hash>
    * maven 库   /maven/<group>/<artifact>/...

自定义源由用户提供 JSON（见 sources.py），格式为地址模板 + 重写规则；
任何一条 404 都会回退到官方地址，所以写错规则不会导致完全不可用。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

BMCLAPI_BASE = "https://bmclapi2.bangbang93.com"
OFFICIAL_BASE = "https://piston-meta.mojang.com"

OFFICIAL = "official"
BMCLAPI = "bmclapi"
CUSTOM = "custom"
NAMES = (OFFICIAL, BMCLAPI, CUSTOM)

# 官方主机 -> BMCLAPI 前缀；仅用于确实被镜像的路径
_REWRITE_RULES: Tuple[Tuple[str, str], ...] = (
    ("https://resources.download.minecraft.net/", BMCLAPI_BASE + "/assets/"),
    ("https://libraries.minecraft.net/", BMCLAPI_BASE + "/maven/"),
    ("https://maven.minecraftforge.net/", BMCLAPI_BASE + "/maven/"),
    ("https://maven.neoforged.net/releases/", BMCLAPI_BASE + "/maven/"),
    ("https://maven.fabricmc.net/", BMCLAPI_BASE + "/maven/"),
    ("https://maven.quiltmc.org/repository/release/", BMCLAPI_BASE + "/maven/"),
)


class Mirror:
    """按名称选择下载源，并把官方 URL 映射为镜像 URL（附带回退候选）。

    自定义源示例：
        Mirror("custom", base="https://mirror.example.com",
               templates={"manifest": "{base}/mc/game/version_manifest_v2.json",
                          "version_json": "{base}/version/{id}/json",
                          "client": "{base}/version/{id}/client"},
               rules=[("https://resources.download.minecraft.net/", "{base}/assets/")])
    """

    def __init__(
        self,
        name: str = OFFICIAL,
        base: Optional[str] = None,
        templates: Optional[Dict[str, str]] = None,
        rules: Optional[List[Tuple[str, str]]] = None,
        label: Optional[str] = None,
    ):
        name = (name or OFFICIAL).lower()
        if name not in NAMES:
            raise ValueError("未知下载源 %r，可选：%s" % (name, " / ".join(NAMES)))
        self.name = name
        self._base = (base or "").rstrip("/")
        self._templates = templates or {}
        self._rules = list(rules or [])
        self._label = label

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return "Mirror(%s)" % self.label

    @property
    def is_mirror(self) -> bool:
        return self.name in (BMCLAPI, CUSTOM)

    @property
    def base(self) -> str:
        if self.name == BMCLAPI:
            return BMCLAPI_BASE
        return self._base

    @property
    def label(self) -> str:
        if self._label:
            return self._label
        return {"official": "官方源", "bmclapi": "BMCLAPI 镜像", "custom": "自定义源"}[self.name]

    # ---- 版本清单 / 版本 JSON / 客户端 ----------------------------------

    def manifest_urls(self) -> List[str]:
        official = OFFICIAL_BASE + "/mc/game/version_manifest_v2.json"
        if self.name == BMCLAPI:
            return [BMCLAPI_BASE + "/mc/game/version_manifest_v2.json", official]
        if self.name == CUSTOM:
            template = self._templates.get("manifest")
            mirror_url = template.format(base=self._base) if template else ""
            return [url for url in (mirror_url, official) if url]
        return [official]

    def version_json_urls(self, version_id: str, official_url: str) -> List[str]:
        if self.name == BMCLAPI:
            return ["%s/version/%s/json" % (BMCLAPI_BASE, version_id), official_url]
        if self.name == CUSTOM:
            template = self._templates.get("version_json")
            mirror_url = template.format(base=self._base, id=version_id) if template else ""
            return [url for url in (mirror_url, official_url) if url]
        return [official_url]

    def client_urls(self, version_id: str, official_url: str) -> List[str]:
        if self.name == BMCLAPI:
            return ["%s/version/%s/client" % (BMCLAPI_BASE, version_id), official_url]
        if self.name == CUSTOM:
            template = self._templates.get("client")
            mirror_url = template.format(base=self._base, id=version_id) if template else ""
            return [url for url in (mirror_url, official_url) if url]
        return [official_url]

    # ---- 通用重写 -------------------------------------------------------

    def _rules_for_name(self) -> List[Tuple[str, str]]:
        if self.name == BMCLAPI:
            return list(_REWRITE_RULES)
        if self.name == CUSTOM:
            return [(prefix, replacement.format(base=self._base)) for prefix, replacement in self._rules]
        return []

    def rewrite(self, url: str) -> str:
        if not self.is_mirror or not url:
            return url
        for prefix, replacement in self._rules_for_name():
            if url.startswith(prefix):
                return replacement + url[len(prefix):]
        return url

    def urls(self, official_url: str) -> List[str]:
        """镜像优先、官方兜底；官方源则原样返回。"""
        rewritten = self.rewrite(official_url)
        if rewritten == official_url:
            return [official_url]
        return [rewritten, official_url]
