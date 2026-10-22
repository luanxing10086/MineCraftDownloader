"""mcd - 独立的 Minecraft 下载器（仅下载，不含启动/登录/其他功能）。

模块划分：
    net      HTTP 下载（重试、sha1 校验、并发、进度）
    mirror   官方源 / BMCLAPI 镜像重写
    rules    libraries 规则求值（os / arch / features）
    vanilla  原版：version json、client jar、libraries、assets、log4j 配置
    java     探测并选择合适的 JRE/JDK
    loaders  Fabric / Quilt / Forge / NeoForge
    modpack  Modrinth .mrpack 整合包
    cli      命令行入口
"""

__version__ = "0.1.0"
__all__ = ["__version__"]
