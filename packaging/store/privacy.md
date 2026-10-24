# 隐私声明 / Privacy statement

## 中文

MCD 不收集、不上传任何个人数据，也没有遥测、账号系统或广告。

应用运行时会访问以下公开接口，仅用于获取版本与文件信息：

- Mojang：`piston-meta.mojang.com`、`launchermeta.mojang.com`、`resources.download.minecraft.net`、`libraries.minecraft.net`
- BMCLAPI（可选镜像）：`bmclapi2.bangbang93.com`
- Fabric / Quilt：`meta.fabricmc.net`、`meta.quiltmc.org`
- Forge / NeoForge：`files.minecraftforge.net`、`maven.minecraftforge.net`、`maven.neoforged.net`
- Modrinth：`api.modrinth.com`、`cdn.modrinth.com`

这些请求不携带任何用户标识；本机只保存少量设置（是否已确认正版提示、上次选择的目录、自定义下载源），
保存在 `%APPDATA%\MCD\config.json`（若该位置不可写则退回程序目录的 `data\`）。

## English

MCD collects and uploads no personal data. There is no telemetry, no account system and no advertising.

At runtime the app contacts the following public endpoints only to resolve versions and download files:
Mojang (`piston-meta.mojang.com`, `launchermeta.mojang.com`, `resources.download.minecraft.net`,
`libraries.minecraft.net`), BMCLAPI (`bmclapi2.bangbang93.com`) when the mirror is selected,
Fabric/Quilt (`meta.fabricmc.net`, `meta.quiltmc.org`), Forge/NeoForge (`files.minecraftforge.net`,
`maven.minecraftforge.net`, `maven.neoforged.net`) and Modrinth (`api.modrinth.com`, `cdn.modrinth.com`).

No user identifiers are sent. Local settings (licence-notice acknowledgement, last chosen directory,
imported mirrors) are stored in `%APPDATA%\MCD\config.json`, or in `data\` next to the program if that
location is not writable.
