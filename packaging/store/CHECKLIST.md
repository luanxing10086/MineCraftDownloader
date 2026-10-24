# 提交微软商店：你需要做的清单

> 下面这些步骤涉及你的 Microsoft 账号、身份证明和付款，只能由你本人完成。
> 仓库里已经备好了包、截图、文案与隐私声明，按顺序走即可。

## 0. 先确认（1 分钟）

- [ ] 已确认应用名：`MCD` 或 `MineCraftDownloader`（预留后不可随意改）
- [ ] 已接受：应用描述里必须写明“非官方、与 Mojang / Microsoft 无关”
- [ ] 已接受：MCD 只下载官方公开文件，不提供账号、不破解

## 1. 注册 Partner Center（约 15–30 分钟 + 审核等待）

- [ ] 打开 <https://partner.microsoft.com/dashboard>，用 Microsoft 账号登录
- [ ] 选择 **Individual developer**（一次性约 $19）或 **Company**（约 $99/年）
- [ ] 填写真实姓名、地址、联系方式
- [ ] 上传身份证明（个人通常为护照/身份证 + 地址证明），提交验证
- [ ] 等待验证通过（一般 1–5 个工作日，可能需要补材料）

## 2. 预留应用名称并拿到两个标识

- [ ] Partner Center → **Apps and games** → **New product** → **MSIX or PWA app**
- [ ] 名称填 `MCD`（若被占用，用 `MineCraftDownloader`）
- [ ] 进入 **Product identity** 页面，抄下：
  - [ ] **Package/Identity/Name**（形如 `12345Publisher.MCD`）
  - [ ] **Package/Identity/Publisher**（形如 `CN=8A7B...`）
  - [ ] **Package/Properties/PublisherDisplayName**

  这三个值要填进下一次打包，否则商店会因 Identity 不匹配拒收。

## 3. 用你的标识重新打包（约 2 分钟）

```powershell
cd F:\DSH-WORK\MineCraftDownloader

# 1) 先构建 onedir（若还没有）
powershell -ExecutionPolicy Bypass -File scripts\build-exe.ps1 -Gui

# 2) 用商店标识打 MSIX
powershell -ExecutionPolicy Bypass -File scripts\build-msix.ps1 `
    -InputDir F:\DSH-WORK\.build\onedir2\MCD-GUI `
    -IdentityName "12345Publisher.MCD" `
    -Publisher "CN=8A7B..." `
    -PublisherDisplayName "你的发布者名称" `
    -Version 0.1.0.0
```

- [ ] 产物：`F:\DSH-WORK\dist\MCD_0.1.0.0_x64.msix`（约 12.8 MB）
- [ ] 不要给商店包签名（Store 会重签）；`-Sign` 只用于本地侧载测试

## 4. 填写商店页面（约 30–60 分钟）

- [ ] 上传 MSIX 包（Packages 页面）
- [ ] **Description**：直接粘贴 `packaging/store/description-zh.md` 与 `description-en.md` 的对应段落
- [ ] **Screenshots**：上传 `packaging/store/screenshot-version.png`、`screenshot-modpack.png`（1920×1080）
- [ ] **Store logo / 图标**：打包时已生成；若页面单独要求，上传 300×300 的 PNG（可用同款“MCD”字样图）
- [ ] **Category**：Utilities → File tools（就近选择）
- [ ] **Pricing**：Free
- [ ] **Age rating**：完成 IARC 问卷（无社交/无用户内容 → 通常 3+）
- [ ] **Privacy policy**：粘贴 `packaging/store/privacy.md` 的内容，或托管成网页后填链接
- [ ] **Support contact**：填你的邮箱或 GitHub Issues 地址
- [ ] **System requirements**：Windows 10 1809 及以上，x64

## 5. 提交与后续

- [ ] 点 **Submit for certification**
- [ ] 等待 1–3 个工作日；被拒会给出策略编号，按提示改后重提
- [ ] 通过后应用会以微软的身份签名，用户安装不再有“未知发布者”
- [ ] 以后每次更新：`Version` 递增（如 `0.1.0.1`）→ 重新打包 → 上传新包 → 提交

## 常见被拒原因（提前规避）

| 原因 | 处理 |
|---|---|
| 商标/关联暗示 | 描述里保留“非官方、与 Mojang / Microsoft 无关” |
| 功能不明确 | 截图与描述对应，说明“只下载、不启动” |
| 崩溃/无法启动 | 提交前用同一台机器侧载测试一次（见下） |
| 隐私声明缺失 | 填 `privacy.md` 内容 |

## 可选：本地侧载自测

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build-msix.ps1 -InputDir <onedir> -Sign
Add-AppxPackage -Path dist\MCD_0.1.0.0_x64.msix
# 运行后卸载：
Get-AppxPackage *MCD* | Remove-AppxPackage
```

> 侧载需要签名证书在“受信任的根证书颁发机构”或“受信任人”中；仓库的 `certs/mcd-signing.cer`
> 就是这张自签名证书（在 `F:\DSH-WORK\certs\`）。
