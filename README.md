# MineCraftDownloader

独立的 Minecraft **下载器**：只负责把文件下载齐、按规范落盘，不含启动、登录、正版验证、皮肤、模组管理等任何其他功能。

起因是 PCL 在最近一次更新里禁用了“下载 Minecraft 本体”。这个项目参照 PCL 的下载源策略与目录规范，用纯 Python 标准库重新实现了一遍下载链路——不依赖 PCL、不依赖任何第三方包。

## 下载

**Windows 图形界面版（推荐）**：[Releases › v0.1.0](https://github.com/luanxing10086/MineCraftDownloader/releases/latest) → `MCD-GUI-win64.zip`（解压即用）

| 文件 | 说明 |
|---|---|
| `MCD-GUI-win64.zip` | **最稳**：onedir 结构，运行时不解压任何东西 |
| `MCD-GUI-portable.exe` | 单文件，但解压目录是**自己所在的文件夹**，不碰 `%TEMP%` |
| `MCD-GUI.exe` | 单文件，解压到 `%TEMP%`；部分机器上会被安全策略拦截（见下方 FAQ） |

> 命令行版不再提供 exe；需要 CLI 时从源码运行 `python -m mcd`。

解压后双击 `MCD-GUI.exe` 即开窗口：左边选版本、右边选加载器，底部设目录/下载源，点“开始下载”。

### FAQ：双击报 `could not create temporary directory`

`MCD-GUI.exe` 是单文件版，启动时要把自身解压到 `%TEMP%`。如果系统不允许“未受信任签名的程序写系统盘”，
解压就会失败并弹出这个提示（杀软日志里可能什么都看不到）。

按顺序尝试：改用 `MCD-GUI-win64.zip`（完全不解压）→ 或 `MCD-GUI-portable.exe`（解压到自身目录）→
或把 `TEMP`/`TMP` 指到非系统盘再运行。

## 图形界面

![界面](docs/gui.png)

- **版本列表**：从 Mojang / BMCLAPI 拉取，支持“正式版 / 快照 / 全部”过滤和关键字搜索（`1.20.1` 里的小数点可以直接输入），双击某行直接开始
- **加载器**：无 / Fabric / Quilt / Forge / NeoForge；能区分正式/测试版的来源给出“最新正式版（自动）”“最新测试版（自动）”，分不出的只给“最新（自动）”，只有一个可选版本时直接标 `- 唯一`
- **版本名称**：可自定义安装后的版本名（留空则自动命名，如 `1.20.1`、`fabric-loader-…`）；装完会把版本目录、版本 JSON 与 jar 一起改名，启动器里看到的就是你起的名字
- **Fabric API**：选 Fabric 时可勾选一并安装，并可选具体版本（数据来自 Modrinth）
- **整合包**：另一个标签页，填 Modrinth slug、页面链接或选本地 `.mrpack`；页面内写明了暂不支持 CurseForge 的原因
- **自定义下载**：第三个标签页，粘贴任意 http/https 链接存到指定位置；下载到 `.mrpack` 会额外询问是否直接安装
- **版本隔离**：开启后内容写到 `versions/<版本>/`，与 PCL / HMCL 的隔离目录结构一致；切换安装目录时会按特征自动判定并切换
- **安装目录**：未选择时显示“未选择”，**点一下输入框等同于点“浏览…”（取消后可直接粘贴/输入路径）**；地址栏支持直接输入或粘贴，会自动去掉资源管理器“复制文件地址”带的双引号、中文引号和末尾多余斜杠，也支持 `%APPDATA%` 这类环境变量；选到非 `.minecraft` 的目录且其一级子目录里也没有时会提示“未找到 .minecraft 文件夹”，由你确认是否仍下载到该处；确认前不会创建任何文件夹；目录不可写会说明具体原因，并可一键改用 `%APPDATA%\MCD\minecraft`
- **下载源**：BMCLAPI / Mojang 官方 / 导入的自定义源（JSON 模板）
- **首次启动**：提示仅面向正版用户，两个按钮（获取正版 / 我是正版用户），确认后不再弹出
- **日志与进度**：两条进度条——上面是当前文件，下面是总进度；下载中“开始下载”左边出现“取消”，取消后只删除**本次新建**的文件，此前下载的内容不受影响；下载失败时会询问是否清理本次新建文件（默认保留，重试可直接跳过已完成文件）；**任何设置项改动都会把进度条重置**
- **下载中锁定**：版本、加载器、目录、下载源、并发等设置全部禁用，只保留“取消”；此时点窗口关闭会先问是否继续下载，选择停止后再问是否删除已下载文件
- **Fabric API**：与“加载器版本”同一行，勾选后可立即选版本

界面用 tkinter（Python 标准库），不引入任何第三方依赖。

## 版本隔离

开启后，整合包内容与 Fabric API 会落到 `versions/<版本>/`（`mods/`、`config/` 等），与 PCL、HMCL 的“版本隔离”目录结构一致。

自动判定规则（切换安装目录时触发）：

* `versions/<某版本>/mods|config|saves` 或 `versions/<版本>/.minecraft` 存在 → 视为**开启**
* 根目录有 `mods/`、版本目录里没有隔离结构 → 视为**关闭**
* 都没有对应特征 → 不自动切换，保持当前设置

> 隔离只影响**下载内容写到哪里**；游戏启动时的存档与配置重定向由启动器负责。
> 请确保启动器里的版本隔离设置与这里一致，否则可能加载不到模组。

## 自定义下载源

“下载源 → 导入…” 选择一个 JSON：

```json
{
  "name": "我的镜像",
  "base": "https://mirror.example.com",
  "templates": {
    "manifest": "{base}/mc/game/version_manifest_v2.json",
    "version_json": "{base}/version/{id}/json",
    "client": "{base}/version/{id}/client"
  },
  "rules": [
    ["https://libraries.minecraft.net/", "{base}/maven/"],
    ["https://resources.download.minecraft.net/", "{base}/assets/"]
  ]
}
```

`templates` 与 `rules` 都可省略；缺失或命中 404 时自动回退官方地址，所以规则写错不会导致完全不可用。

## 从源码运行 GUI

```bash
python -m mcd.gui
```

## 微软商店（MSIX）

仓库提供 MSIX 打包脚本与上架说明：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build-msix.ps1 -InputDir <onedir 目录>
```

产物 `dist/MCD_<版本>_x64.msix` 已通过 `makeappx validate`。提交商店需要 Partner Center 账号、
实名验证，并把清单里的 Publisher 换成商店分配的身份——详见 [docs/store.md](docs/store.md)。

## 能下什么

| 类型 | 说明 |
|---|---|
| 原版 | 任意正式版 / 快照，含 client jar、libraries、assets、log4j 配置、老版本 natives |
| 带加载器 | Fabric、Quilt（直装，无需 Java）、Forge、NeoForge（调官方 installer） |
| 整合包 | Modrinth `.mrpack`：本地文件、直链、项目 slug、`slug@版本` |
| 附加 | Fabric API（可选，来自 Modrinth）；任意 URL 的自定义下载 |

## 环境要求

* Python 3.8+（Windows 上建议 3.9 及以上）
* 仅 Forge / NeoForge 安装需要 Java（17 或 21，脚本会自动挑一个合适的）
* 不需要 `pip install` 任何东西

## 快速开始

```bash
# 查看帮助
python -m mcd --help

# 环境自检：网络 + Java
python -m mcd doctor

# 列出可下载版本
python -m mcd list --limit 10

# 下载原版 1.20.1 到 ./minecraft
python -m mcd install 1.20.1

# 国内网络：加 --mirror bmclapi（走 BMCLAPI 镜像）
python -m mcd install 1.20.1 --mirror bmclapi

# 原版 + Fabric
python -m mcd install 1.20.1 --loader fabric

# 原版 + Forge（需要 Java）
python -m mcd install 1.20.1 --loader forge

# 原版 + NeoForge
python -m mcd install 1.21.1 --loader neoforge --mirror bmclapi

# 整合包（Modrinth）
python -m mcd modpack fabulously-optimized --dir ./fo --mirror bmclapi
python -m mcd modpack fabulously-optimized --dry-run     # 只看计划，不下载

# 本地 .mrpack
python -m mcd modpack D:\packs\MyPack.mrpack --dir ./instance
```

Windows 下也可以直接用启动器：双击或 `MCD.cmd install 1.20.1`。

## 安装为命令

```bash
pip install -e .
mcd install 1.20.1 --loader fabric
```

## 常用参数

| 参数 | 说明 |
|---|---|
| `--dir` | 游戏目录，默认 `./minecraft` |
| `--mirror official\|bmclapi` | 下载源，默认官方；国内建议 `bmclapi` |
| `--loader fabric\|quilt\|forge\|neoforge` | 同时安装加载器 |
| `--loader-version` | 指定加载器版本，默认最新 / Forge 推荐版 |
| `--no-assets` | 跳过 assets（体积最大，约 300–700 MB） |
| `--threads` | 并发下载数，默认 8 |
| `--proxy` | HTTP(S) 代理，如 `http://127.0.0.1:7890`；也会读 `HTTPS_PROXY` |
| `--java` | 指定 java.exe（Forge/NeoForge 用） |
| `--json` | 机器可读输出 |
| `--refresh` | 忽略 1 小时的版本清单缓存 |

## 从源码打包 exe

默认只出图形界面版；命令行版直接 `python -m mcd` 运行即可。

```powershell
# Windows：一条命令出 GUI 版（内含 PyInstaller 依赖的获取与签名）
powershell -ExecutionPolicy Bypass -File scripts\build-exe.ps1
```

手动打包：

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --icon packaging/icon.ico --name MCD-GUI --paths . tools/gui_entry.py
```

产物在 `dist/MCD-GUI.exe`（Windows）。需要 CLI 的 exe 时，加 `-Cli`：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build-exe.ps1 -Cli
```

## 落盘结构

完全遵循官方 launcher 规范，可以被任何启动器（PCL、HMCL、Prism、官方启动器）直接识别：

```
minecraft/
├─ versions/
│  ├─ 1.20.1/1.20.1.json
│  ├─ 1.20.1/1.20.1.jar
│  └─ fabric-loader-0.15.11-1.20.1/…
├─ libraries/…
├─ assets/
│  ├─ indexes/5.json
│  ├─ objects/ab/abcdef…
│  └─ log_configs/client-1.12.xml
├─ resources/…            （极老版本的 map_to_resources）
└─ .mcd/                 （清单缓存、installer、整合包缓存）
```

## 镜像说明

`--mirror bmclapi` 时按以下规则改写（与 PCL 一致），任何一条 404 都会自动回退官方地址：

| 内容 | BMCLAPI 路径 | 是否镜像 |
|---|---|---|
| 版本清单 | `/mc/game/version_manifest_v2.json` | ✅ |
| 版本 JSON | `/version/<id>/json` | ✅ |
| 客户端 JAR | `/version/<id>/client` | ✅ |
| 资源对象 | `/assets/<xx>/<hash>` | ✅ |
| 依赖库 / 加载器 maven | `/maven/<group>/…` | ✅ |
| 资源索引 JSON | — | ❌ 回退官方 |
| log4j 配置 | — | ❌ 回退官方 |

## 已知限制

* **NeoForge 需要能访问 `maven.neoforged.net`**：installer 下载本身可以走镜像，但 installer 运行时会直连该 maven；本工具会先用 `--mirror` 预取 `install_profile.json` 里的依赖，不过 BMCLAPI 对 `net.neoforged.*` 只代理了一部分（其余返回 403）。受限网络请配 `--proxy` 或使用全局代理。
* Forge / NeoForge 的 installer 由官方提供，其内部下载不走 `--mirror`；`--mirror` 模式会先预取依赖，让 installer 尽量只做本地处理。
* Forge installer 在“Injecting profile”阶段偶尔会失败并把 `launcher_profiles.json` 截断；此时版本 JSON 与补丁后的 jar 其实已经写好，本工具会容错继续，并修复该文件。
* NeoForge 版本号会自动匹配：`1.21.1 → 21.1.x`（旧体系）、`26.3 → 26.3.x.y`（新体系）。
* 不下载 Java 运行时（只探测本机已有的）。
* 不支持 CurseForge 整合包（其 API 需要 Key）；检测到会给出明确提示。
* 不做启动，因此不生成启动参数、不合并 `inheritsFrom`——那是启动器的职责。

## 测试

```bash
python -m unittest discover -s tests -v
```

28 个用例，覆盖规则求值、镜像改写、maven 坐标、下载/校验/进度、`.mrpack` 解析与 zip-slip 防护。

真实网络冒烟测试（本机实测，`--mirror bmclapi --no-assets`）：

| 场景 | 结果 |
|---|---|
| `install 1.0` | ✅ 11 个文件 / 4.6 MB，natives 正常解压 |
| `install 1.20.1 --loader fabric` | ✅ `fabric-loader-0.20.1-1.20.1`，65 个库 |
| `install 1.20.1 --loader quilt` | ✅ `quilt-loader-0.20.0-beta.9-1.20.1`，14 个库 |
| `install 1.20.1 --loader forge` | ✅ `1.20.1-forge-47.4.10`，Java 17 跑完 installer 并产出补丁 client jar |
| `modpack fabulously-optimized` | ✅ MC 26.2 + Fabric 0.19.5，51 个文件 + 57 个 overrides |
| NeoForge 版本解析 | ✅ 1.21.1→`21.1.264`，26.3→`26.3.0.94`（新旧两套版本号都支持） |
| NeoForge 完整安装 | ✅ `neoforge-21.1.264`，installer 跑完 processors（需把 UA 换成不含网址的写法，否则 BMCLAPI 返回 403；限流时自动退避） |

CLI 版不单独出 exe，实测用源码运行同样正常：`python -m mcd --version`、`list`、`install 1.0`（11 文件 / 4.6 MB）。

## 目录

```
mcd/
├─ cli.py       命令行
├─ vanilla.py   原版安装
├─ loaders.py   Fabric / Quilt / Forge / NeoForge
├─ modpack.py   .mrpack
├─ net.py       下载与进度
├─ mirror.py    镜像重写
├─ rules.py     libraries 规则
└─ java.py      Java 探测
tests/          28 个单元测试
```

## 致谢与声明

* 下载源策略、镜像路径与目录布局参考了 [PCL](https://github.com/Meloong-Git/PCL) 的实现，代码为独立编写。
* 仅下载用户有权使用的文件；请遵守 Mojang 的 EULA 与各加载器/整合包的分发许可。
* Forge 的版本 JSON 里带有“请勿自动化下载”的提示。本项目只是调用官方 installer 与官方 maven，如你认同该提示，请通过 <https://www.patreon.com/LexManos/> 支持 Forge，或手动安装。
* 发布的 exe 使用自签名证书（`CN=Cantabile`），未导入该证书的机器首次运行可能提示“未知发布者 / Windows 已保护你的电脑”：
  这是缺少商业证书的正常现象，不是文件有问题。可核对 release 里的 SHA256，或从源码运行（`python -m mcd` / `python -m mcd.gui`）。
  想在本机消除提示，可自行生成自签名证书签名（见仓库外的 `scripts/sign-exe.ps1` 思路），
  或申请真证书 / 开源项目免费签名（SignPath）。
* 单文件 exe 启动时会把自身解压到 `%TEMP%`。若临时目录不可写，或安全软件拦截“未签名程序在临时目录
  释放 DLL”，会弹出标题为 “Error” 的对话框并提示 `Could not create temporary directory`。
  **解决办法：改用 `MCD-GUI-win64.zip`（onedir 版，运行时不解压）**，或改用源码方式（`python -m mcd.gui`）。
* MIT License。

## 后记

本项目制作原因是 PCL 等一众第三方启动器 MC 本体的下载功能被一刀切了，我知道改个文件就能修好，但我许愿许快了（

这个下载器支持下载 MC 本体 / 带加载器的版本 / 整合包；启动器的 mod 下载功能暂且没起爆那我就不许愿这个了，说实话我不觉得 mod 下载功能会爆。

这是我有史以来做的第一个代码超过 1000 行的项目（实则大概也不算是我做的），全项目只有提示词、空仓库、逐版测试以及这段文字是我弄的，其他全是白饭喂出来的。大肥鱼 1017 香啊造啊，我现在也算是个 wishcoding 糕手了（乐

由衷希望三方启动器的下载功能能尽快恢复，我这个当个纪念也挺好的。
