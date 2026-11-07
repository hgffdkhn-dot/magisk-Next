# 调研分析：上游现状与参考分支基线定位

本文记录 `magisk-Next` 立项时的实际调研过程与数据。所有数字来自对两个仓库源码快照的逐文件 SHA-256 比对和 GitHub API，不是估计值。

数据采集时间：2026-11-07（GMT+8）。

## 1. 调研方法

沙箱里 `github.com` 的 **git 协议不通**（`git ls-remote` 走直连、钉 IP、镜像全部超时，SSH 门可达但无密钥），但 `api.github.com`、CDN 与 release 归档端点可用。因此改用：

| 用途 | 通道 |
| --- | --- |
| 仓库元信息、分支、提交历史 | `api.github.com` |
| 源码快照 | `https://github.com/<repo>/archive/refs/heads/master.zip`（经 `ghfast.top` 转发，约 2MB / 5 秒） |
| 历史 tag 快照 | 同上，`refs/tags/<tag>.zip`，一次性并发拉取 15 个 tag |
| 文本与差异分析 | 本地逐文件 SHA-256 + `difflib` |

拿到的是归档快照，不是完整 git 历史，这一点直接影响后面 submodule 与 commit 对齐的处理。

## 2. 上游 topjohnwu/Magisk 现状

| 项 | 值 |
| --- | --- |
| `master` HEAD | `33bfff7ce7` |
| 最新 tag | `v31.1`（`0972f67d97`，2026-10-24） |
| 其他分支 | `cxxmodules` |
| `master` 快照 | **440 个文件 / 5.3MB** |
| 最低 Android | 7.0（v31.1 起，v31.0 及以前为 6.0） |
| 技术栈 | Jetpack Compose + Material 3（App）、Rust + C/C++（native）、Gradle Kotlin DSL |
| App 模块 | `:apk`、`:core`、`:test`，`build-logic` 复合构建 |
| native 产物 | `magisk`、`magiskinit`、`magiskboot`、`magiskpolicy`、`resetprop` |
| 子模块 | 8 个，见 `.gitmodules` |
| 工具链 | Python 3.8+、JDK 25、Android SDK + ONDK（`ondk_version = "r30.1"`） |

### v31.1 的关键变化（摘自 `docs/changes.md`）

> - [General] Remove the app hiding (repackaging) feature and the stub app
> - [App] Remove reactive superuser request prompts
> - [App] Unify the image patching pipeline across local files and remote URLs
> - [MagiskBoot] Support signing ChromeOS boot images natively
> - [Core] Fix potential crashes when handling `NULL` database strings

v31.0 则完成了「Compose + Material 3 全量重写，移除 legacy View/Fragment」并新增内置终端。这两次重构把仓库从 641 个文件（v30.7）精简到 440 个文件（v31.1）——`app/stub`、`app/stub-res`、`app/shared`、`app/apk-ng` 等模块被删掉或合并。

**这条「移除 app hiding / stub」的变更，正是第三方隐藏类分支最核心的分歧点。**

## 3. 参考仓库 QOS3/Magisk（用户标注为 Kitsune Mask）

| 项 | 值 |
| --- | --- |
| 默认分支 | `master`（`be7a4b4dcc`） |
| fork 关系 | `parent` / `source` 均为 `topjohnwu/Magisk` |
| 创建 / 最近推送 | 2026-03-10 / 2026-04-26 |
| 仓库大小 | 62,846 KB，语言 Kotlin，GPL-3.0，58 stars（采集时） |
| 其他分支 | `aviraxp-patch-1`、`lz4flex`、`miuix` |
| `master` 快照 | **707 个文件 / 6.6MB** |

### 3.1 先看整体差异

对两个 `master` 快照做逐文件比对：

| 结果 | 数量 |
| --- | --- |
| Kitsune 有、官方没有 | **343** |
| 官方有、Kitsune 没有 | **76** |
| 内容不同 | **227** |
| 完全相同 | **137** |

新增文件按目录聚合：`app/apk` 175、`app/apk-ng` 56、`app/stub-res` 52、`app/core` 18、`app/stub` 18。

但这个数字**不能直接读成「Kitsune 自研了 343 个文件」**。两边的 master 根本不在同一代代码基线上：官方已经完成 v31.1 重构，Kitsune 还停在重构前的结构。

### 3.2 定位 fork 基线

把 Kitsune 快照逐一与官方 15 个历史 tag 做文件指纹比对（`jaccard_same` = 完全相同文件数 / 两边文件并集）：

| tag | tag 文件数 | 交集 | 完全相同 | jaccard_same |
| --- | --- | --- | --- | --- |
| **v30.7** | 641 | 583 | **517** | **0.676** |
| v30.6 | 647 | 581 | 457 | 0.591 |
| v30.5 | 647 | 581 | 456 | 0.590 |
| v30.4 | 642 | 573 | 436 | 0.562 |
| v30.3 | 642 | 573 | 432 | 0.557 |
| v30.2 | 644 | 560 | 389 | 0.492 |
| v30.1 | 681 | 560 | 381 | 0.460 |
| v30.0 | 681 | 560 | 376 | 0.454 |
| v29.0 | 678 | 549 | 361 | 0.432 |
| v31.0 | 715 | 476 | 333 | 0.352 |
| v28.1 | 658 | 499 | 301 | 0.348 |
| v28.0 | 656 | 498 | 297 | 0.343 |
| v31.1 | 440 | 364 | 138 | 0.176 |
| v27.0 | 659 | 138 | 39 | 0.032 |
| v26.4 | 663 | 124 | 37 | 0.030 |

**v30.7 明显最接近**，且 v30.7 → v31.0 之间正是官方「合并下一代 App 实现」的开发窗口。所以 Kitsune 的 fork 点应落在 v30.7 之后、v31.0 之前。

以 v30.7 为基线重算：新增 124、删除 58、内容变更 66、未变 517。

### 3.3 这 66 个变更到底是什么

抽看 `Config.kt`、`Const.kt`、`strings.xml`、`SettingsItems.kt`、`MagiskInstaller.kt`、`build.py`、`Cargo.toml` 的逐行 diff，新增内容主要是：

- `COLOR_MODE` / `color_mode` 数组与 6 档主题（Material 3 Monet）
- `DownloadDialog`、`download_patch_file` 等远程 OTA 下载修补能力
- `buildSrc` → `build-logic`、`stub` → `stub-res`、新增 `apk-ng` Compose 模块
- `PreferenceConfig` 的属性委托重写、`DataSourceChannel` 用户态拷贝
- Rust 依赖升级（`libc 0.2.182→0.2.184`、`nix 0.30.1→0.31.2`、`zopfli` 启用 std 等）

这些全部对应官方 v31 开发期的正常提交，**不是隐藏增强类改动**。native 层的源码文件在这一层对比里几乎没有变化，只有 `Cargo.toml` / `Cargo.lock` / `boot/Cargo.toml` 三个依赖文件不同。

### 3.4 提交历史给出的结论

拉取 `QOS3/Magisk` master 最近 100 条提交，前几条是：

```
be7a4b4dc  2026-04-14  Update Serbian translations (Cyrillic & Latin)
63b20ceca  2026-04-14  Update Samsung download mode documentation
7976897ac  2026-04-14  Switch over to use Wire
483901f3c  2025-09-30  app: use userspace copy
b9d21071f  2025-09-29  app: support download image and patch 2/2
debf1800d  2026-03-16  Merge next generation app impl into master
62c6ab8c0  2026-03-16  Move apk module to apk-ng
e2a437ebf  2026-03-18  Switch to Google Material 3 library
```

往下的 100 条里也全部是官方 Magisk 的开发提交（Compose 重写、状态卡重设计、翻译更新、CI 调整、依赖升级……），**没有一条 Kitsune 自研提交**；在整个 Kitsune 快照里检索 `Kitsune` / `HuskyDG` / `KitsuneMask` 也是 0 命中。

> **结论**：用户提供的 `QOS3/Magisk` master 分支，实际上是一份官方 v31 开发期的源码快照，并未包含 Kitsune Mask 的隐藏增强实现。Kitsune 的改动可能在它另外三个分支（`aviraxp-patch-1` / `lz4flex` / `miuix`），或者该仓库只承担同步镜像的角色。本文只对 `master` 负责，不对其余分支下结论。

另外，Kitsune 快照 `strings.xml` 里确实有 `<!--MagiskHide-->` 区块、`settings_hide_app_*`、`settings_random_name_*`，但这些在官方 v30.7 里同样存在（未出现在新增 diff 中），属于上游自带功能，不能算作 Kitsune 的改动。

## 4. 由此确定的分支方向

真正值得参考的不是「Kitsune 具体改了哪些文件」，而是**取舍分歧**：

| 能力 | 官方 v30.7 | 官方 v31.1 | 隐藏类第三方分支 |
| --- | --- | --- | --- |
| 隐藏 / 重打包 App（stub） | 有 | **移除** | 通常保留并增强 |
| 随机包名、随机输出文件名 | 有 | 保留 | 强化 |
| 反应式 SU 请求弹窗 | 有 | **移除** | 通常保留 |
| Compose / Material 3 UI | 开发中 | 完成 | 无 |
| DenyList / Zygisk | 有 | 有（新增 Android 17 支持） | 有 |

所以 `magisk-Next` 的选择是：**站在官方 v31.1 的最新基线上**（拿到 Compose UI、统一修补管线、MagiskBoot 原生签名、Android 17 Zygisk），**不回退架构**，把工程化能力和可配置能力补齐；隐藏类能力作为可选插件列入路线图，而不是把旧版 stub 代码硬搬回来。

## 5. 上游可优化点（本次已落地的部分）

| 编号 | 观察 | 处理方式 |
| --- | --- | --- |
| O1 | `build.py` 版本与分支标识写死在 `flags.h` / `flags.rs` / `flags.prop` 三处，第三方分支改起来容易漏 | 抽出 `next.*` 配置，三处统一注入，`verify_repo.py` 校验配置一致性 |
| O2 | 构建失败常见于环境缺件（SDK / ONDK / submodule），但报错分散 | `preflight.py` 一次性列出 9 项检查与修复建议 |
| O3 | 模块 `module.prop` 没有安装前的静态校验 | `module_lint.py` 校验必填字段、id 合法性、路径穿越、versionCode、minMagisk |
| O4 | 分发产物没有完整性清单 | `integrity.py` 生成 / 校验 `SHA256SUMS`（兼容 `sha256sum -c`） |
| O5 | issue 里缺统一的设备状态汇总 | `NextFeatures.exportHealthJson()` + `health_report.py` 渲染 Markdown |
| O6 | 分支相对上游的改动容易被合版冲掉 | 自包含 `NextSection` + 独立 `next/` 工具目录 + 基线 commit 边界 |

未落地的优化项与风险见 [设计文档](DESIGN.md)。
