# 上架微软商店（MSIX）

本文记录 MCD 打包成 MSIX 并提交 Microsoft Store 的流程。仓库里已经准备好了打包脚本，
剩下**注册账号、实名验证、点击提交**这些必须由开发者本人完成。

## 一、已经准备好的

| 文件 | 作用 |
|---|---|
| `packaging/AppxManifest.template.xml` | 清单模板（Identity / 图标 / full-trust 应用） |
| `scripts/build-msix.ps1` | 渲染清单、生成图标、调用 `makeappx` 打包与校验 |
| `packaging/store/description-zh.md` / `description-en.md` | 商店文案（短描述、长描述、声明） |
| `packaging/store/privacy.md` | 隐私声明（中英） |
| `packaging/store/screenshot-version.png` / `screenshot-modpack.png` | 1920×1080 截图 |
| `packaging/store/CHECKLIST.md` | 你需要做的步骤清单 |

本地构建（使用 onedir 产物）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build-msix.ps1 `
    -InputDir F:\DSH-WORK\.build\onedir2\MCD-GUI
```

产物：`dist\MCD_0.1.0.0_x64.msix`。这条命令已实测通过（`makeappx pack` + `makeappx validate` 均成功）。

## 二、你必须自己做的（我无法代做）

1. **注册 Partner Center**
   - 地址：<https://partner.microsoft.com/dashboard>
   - 个人开发者：一次性约 **$19**；公司：约 **$99/年**
   - 需要 Microsoft 账号，并完成**身份验证**（政府证件；个人通常还要地址证明，审核 1–5 个工作日）
2. **预留应用名称**
   - 在 Partner Center 里新建应用，名称填 `MCD` 或 `MineCraftDownloader`
   - 预留后，页面会给你两个值：**Package/Identity/Name**（形如 `12345Publisher.MCD`）和
     **Package/Identity/Publisher**（形如 `CN=8A7B...`）——这是商店签名的身份，**必须**写进清单
3. **用你的身份重新打包**

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\build-msix.ps1 `
       -InputDir <onedir 目录> `
       -IdentityName "12345Publisher.MCD" `
       -Publisher "CN=8A7B..." `
       -Version 0.1.0.0
   ```

   > 现在的默认 Publisher 是本机自签名（`CN=mcdonloader self-signed`），只适用于侧载测试，
   > 商店会因为这个 Identity 与预留信息不匹配而拒收。

4. **上传包并填写商店信息**
   - 包：上传 `.msix`
   - 商品页：名称、简介、至少 1 张截图（可用 `docs/gui.png`）、分类（建议“实用工具”）
   - 年龄分级：完成 IARC 问卷（本应用无用户生成内容、无社交，通常为 3+）
   - 定价：免费
   - 隐私政策：本应用**不上传任何用户数据**，若表单要求可写“本程序不会向任何网络系统传输信息，
     除非用户明确请求”（下载行为本身访问 Mojang / Modrinth 公共接口）
5. **提交认证**：通常 1–3 个工作日；被拒会给出具体策略条目，改完可重提

## 三、风险提示（提交前请评估）

- **商标**：描述里必须写明“非官方工具，与 Mojang / Microsoft 无关”，不要使用 Minecraft 官方 logo
- **下载器类目**：商店对“下载第三方游戏文件”的应用审核偏严。建议在描述中明确：
  不提供账号、不破解、不绕过正版验证，仅从官方公开接口下载
- **首次启动的正版提示**：应用内已有“仅面向正版用户”的说明，对审核是加分项
- **更新**：上架后每次发版需要递增 `Version`（第四位也可递增，如 `0.1.0.1`）

## 四、本地侧载测试（可选）

```powershell
# 用本机自签名证书签名
powershell -ExecutionPolicy Bypass -File scripts\build-msix.ps1 -InputDir <onedir> -Sign

# 安装（需要证书在“受信任的根证书颁发机构”或“受信任人”里）
Add-AppxPackage -Path dist\MCD_0.1.0.0_x64.msix
# 卸载
Get-AppxPackage *MCD* | Remove-AppxPackage
```

## 五、另一种更省事的路径

如果只是想让用户“下载后不被 SmartScreen 拦”，**MSIX 也可以不经商店、直接分发**：
用户双击 `.msix` 安装（需要可信签名），或走 **App Installer** 的旁加载。
但要消除“未知发布者”，签名证书仍然是绕不开的前提。
