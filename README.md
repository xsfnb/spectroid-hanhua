# Spectroid 汉化 + 液态玻璃 UI 补丁

> Spectroid（音频频谱分析仪）的中文汉化与界面美化工具 / 补丁。
> 纯 Python 实现，零第三方依赖，完全离线可用。

![status](https://img.shields.io/badge/版本-1.1.2-33D9FF) ![lang](https://img.shields.io/badge/语言-中文-FFC94D) ![py](https://img.shields.io/badge/Python-3.x-9D8CFF)

---

## ⚠️ 重要声明（请务必阅读）

**本仓库不包含任何 APK 文件，也不是 Spectroid 的官方版本。**

- Spectroid 是 **intoorbit（Carl Reinke）开发的闭源商业应用**，版权归原作者所有，官方版本发布于 [Google Play](https://play.google.com/store/apps/details?id=org.intoorbit.spectrum)。
- 本仓库提供的是**汉化补丁与构建工具**：你自行从合法渠道（Google Play / apkmirror）获取原版 APK，然后用本工具生成汉化美化版。
- 生成的 APK 仅限**个人学习与研究使用**，请勿用于商业分发；请在合理使用范围内遵守原作者的权利（来源：[GitHub: intoorbit/spectrum](https://github.com/intoorbit/spectrum)）。
- 若原开发者要求，本仓库将立即删除。

---

## ✨ 功能

- **全量汉化**：83 处界面文案中文化（设置、音频来源、窗函数、频谱、测试信号等），法语等其他语言不受影响
- **液态玻璃 UI**：
  - 深蓝黑窗口底色（#FF0E141E），替代原版纯黑
  - 霓虹频谱：电光青 `#33D9FF` + 紫色峰值保持 `#9D8CFF` + 琥珀标记 `#FFC94D`
  - 设置界面玻璃染色、SeekBar 行半透明
  - 全新启动图标（深蓝玻璃底 + 青色频谱柱，5 个密度）
- **零资源新增**：只"改值"（颜色/字符串/图标内容），不新增任何资源条目，最大兼容性（在澎湃 OS 3 / Android 16 实测稳定）
- **工程上干净**：未改动的文件在 APK 中逐字节保留，重新打包结构对齐 aapt2 规范

## 📦 快速开始

### 1. 获取原版

从以下任一渠道下载 Spectroid 1.1.2 的 APK（`org.intoorbit.spectrum`）：
- [Google Play](https://play.google.com/store/apps/details?id=org.intoorbit.spectrum)
- [APKMirror](https://www.apkmirror.com/apk/intoorbit/spectroid/)

### 2. 生成汉化版

```bash
# 需要 Python 3，无需安装任何第三方库
python build.py 原版.apk 输出.apk
```

### 3. 签名并安装

生成的 APK 使用了与官方不同的签名，无法直接覆盖安装：

1. 手机安装 **MT 管理器** → 打开生成的 APK → 选择「签名」（自签名）→ 保存
2. **先卸载手机上已安装的 Spectroid**（签名不同会冲突）
3. 点击签名后的 APK 安装

> 为什么不自带可安装签名？应用本体非开源，仓库内不内置签名密钥；自签名也符合"工具 + 补丁"的定位。

## 📁 项目结构

```
.
├── build.py             # 一键构建脚本（汉化 + 美化 + 重打包 + 签名）
├── translations.json    # 汉化对照表（资源名 → 中文）
├── tools/
│   ├── arsc_parser.py   # resources.arsc 解析器（纯 Python）
│   ├── arsc_edit.py     # resources.arsc 序列化/编辑器（对齐 aapt2 规范）
│   ├── binxml.py        # 二进制 XML 解码/编码器（4 字节块对齐）
│   ├── signing.py       # APK v1/v2 签名 + 外科手术式 zip 重建（纯 Python）
│   └── gen_icons.py     # 启动图标生成（RGBA PNG）
└── README.md
```

## 🛠 技术原理

| 模块 | 说明 |
|---|---|
| **汉化** | 解析 `resources.arsc` 的字符串池，把 83 条中文追加进池子，将 string 类型(default 配置)对应条目重定向到中文索引；法语等其它配置不受影响 |
| **美化** | 主题袋(style bag)内联颜色值改写（windowBackground → 深蓝黑）；主布局给 `SpectrumView` 注入 11 个自定义颜色属性；启动图标用纯 Python 手写 PNG 生成器重绘 |
| **重打包** | 外科手术式：未改动的文件（含压缩流）从原 APK 逐字节复制，只替换改动的条目；所有块 4 字节对齐（aapt2 规范），`resources.arsc` 对齐存储 |
| **签名** | 纯 Python 实现 v1(JAR, SHA1withRSA) + v2(APK Signature Scheme v2, SHA-256) 双签名，RSA-2048 自签名证书 |

全程零外部依赖：不依赖 Java / apktool / aapt / apksigner / 网络。

## ❓ 常见问题

**Q: 安装提示"解析失败 / 无法解析安装包"？**
- 先卸载旧版 Spectroid（签名冲突）
- 确认用了 MT 管理器签名后再安装
- 不要直接在微信/QQ 里点开，先用 MT 管理器处理

**Q: 打开后秒闪退？**
- 本工具生成的版本已在澎湃 OS 3（Android 16）上实测稳定；若闪退，请确认 APK 结构完整性（`python -m zipfile -t 输出.apk`），或提供闪退详情

**Q: 能否在其它 Android 版本运行？**
- 原版最低支持 Android 4.0（API 14）；本补丁只改资源，兼容范围与原版一致

## 📄 许可

- 本仓库的**工具代码**（`build.py`、`tools/`）采用 [MIT License](LICENSE)
- **汉化文本**与生成产物仅限个人学习使用，Spectroid 版权归原作者所有

## 🙏 致谢

- [intoorbit/spectrum](https://github.com/intoorbit/spectrum) — Spectroid 原作者
- APKMirror — 原版 APK 分发渠道
