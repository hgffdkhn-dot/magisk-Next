# magisk-Next

基于 [topjohnwu/Magisk](https://github.com/topjohnwu/Magisk) 官方 `master`（`33bfff7ce7`，v31.1 之后）的第三方分支。目标不是换个名字，而是**在上游最新代码基线上补齐工程化能力，并直接增强 native 核心**（Zygisk、隐藏、线程与稳定性），同时把 v31.1 移除掉的部分可配置能力以模块化方式带回。

基线源码保持未改动，所有分支改动都叠加在后续提交里，`git log` 可以直接看出边界。

## 这个分支做了什么

| 类别 | 内容 | 主要文件 |
| --- | --- | --- |
| 分支标识 | `NEXT_BRAND` / `NEXT_CHANNEL` 编译进 C 头文件、Rust 常量、Gradle `flags.prop` | `build.py`、`config.prop.sample` |
| 构建配置闭环 | 4 个 `next.*` 配置贯通 `flags.prop` → `Plugin.kt` → `BuildConfig.NEXT_*` → App 开关默认值 | `build.py`、`app/build-logic/.../Plugin.kt`、`app/core/build.gradle.kts` |
| App 功能 | 3 个开关（均有实际作用）+ 8 项设备体检 + JSON 导出 + 分享入口 | `app/core/.../next/NextFeatures.kt`、`app/apk/.../settings/NextSection.kt` |
| **Native 核心增强** | **12 组修复**：Zygisk companion / 模块加载健壮性、accept 错误分类不再掉 root、线程池 FIFO 队列与上限、su 授权回包与子进程 reap、DenyList `end()` 守卫、`revert_unmount()` 隐藏清理增强、namespace 忙等上限 | `native/src/core/*` |
| **Native 静态守卫** | 12 条规则 / 60 项断言，防止 rebase 或合并上游时悄悄回滚修复，含逐条扰动自测 | `next/native_audit.py` |
| 模块快照 | capture / list / diff / verify / restore（dry-run 默认）/ prune，含篡改拒绝 | `next/snapshot.py` |
| 通道校验 | 清单格式、产物 SHA256、openssl RSA 签名与验签 | `next/channel.py` |
| 主机工具 | 环境自检、模块静态校验、产物 SHA256 清单、体检报告渲染、Kotlin API 守卫、10 项仓库一致性校验 | `next/*.py` |
| 工程脚本 | submodule 引导、一键构建、一键校验（含 Rust 语法解析与 CLI 冒烟） | `scripts/*.sh` |
| CI | push/PR 秒级校验；手动或 `v*` tag 触发完整构建并发布 Release（**上一轮已实跑 success**） | `.github/workflows/next-ci.yml`、`build-next.yml` |

功能清单、缺陷记录与后续可增加的新功能见 [ROADMAP.md](docs/ROADMAP.md)；**native 遗留缺陷的完整根因、症状对应与边界**见 [NATIVE-AUDIT.md](docs/NATIVE-AUDIT.md)。

新增的 App 设置分区是**自包含**的：直接读写 `Config`，不改 `SettingsUiState` / `SettingsViewModel`，在 `SettingsContent` 里只插入一行调用。上游合版时整体保留或整体删掉都很干净。

## 快速开始

```bash
# 1. 校验仓库（不需要 Android SDK）
bash scripts/verify-next.sh

# 2. 检查构建环境
python3 next/preflight.py

# 3. 引导 8 个 native 子模块
./scripts/bootstrap-submodules.sh

# 4. 完整构建（需要 JDK 25 + Android SDK + ONDK）
./scripts/next-build.sh --release
```

工具也可以单独用：

```bash
python3 next/module_lint.py /path/to/module      # 模块发布前静态校验
python3 next/integrity.py verify --dir out       # 校验下载产物
python3 next/health_report.py --demo             # 渲染体检报告
python3 next/native_audit.py                    # 校验 12 组 native 修复未被回滚
```

## 当前校验状态

在本仓库实测：

- 仓库一致性校验 **10/10 通过**（新增 `native guards` 第 10 项）
- 单元测试 **25/25 通过**，9 个工具 `--self-test` 全部通过（含 openssl RSA 签名/验签、快照回滚、native 守卫扰动自测）
- `next/native_audit.py`：**12/12 规则、60 项断言**通过
- `rustfmt --edition 2024` 语法解析：5 个改动的 Rust 文件全部可解析
- `bash scripts/verify-next.sh` → `ALL CHECKS PASSED`，含快照 `capture→diff→verify→restore` 与通道清单的真实 CLI 冒烟
- GitHub Actions 完整构建：上一轮 **success**（39.6 MB 产物）；**本轮 native 改动完整构建 success**（run `42370477749`，37.74 MB + 2.71 MB 符号表）。日志确认 `Compiling magisk v0.0.0 (.../native/src/core)` 与 `[arm64-v8a] Compile++ : magisk <= utils.cpp / entry.cpp / module.cpp` 全部编译通过，`BUILD SUCCESSFUL`

## 已知限制

- **本沙箱仍无 Android SDK / ONDK / JDK 25**，无法本地出包；完整编译依赖 [GitHub Actions](https://github.com/hgffdkhn-dot/magisk-Next/actions)。CI 证明「能编译」，尚未做真机 / AVD 冒烟（APK 安装与 Magisk 激活）。
- **native 改动只经过静态守卫、rustfmt 语法解析与 CI 编译验证，尚未真机验证**。本轮不改 MagiskSU 权限模型、不动 daemon 签名信任链、不含针对具体应用检测的绕过代码或特征串；隐藏增强只扩大 Magisk **自身挂载**的清理范围。
- 基线源码来自 GitHub release 归档快照，原始 zip **不含 8 个 submodule 内容，且丢失了可执行位、符号链接与 gitlink 记录**。`next` 分支已按官方 git tree（`33bfff7ce7`）补齐；`main` 保持未改动的原始快照。`scripts/bootstrap-submodules.sh` 对两种来源都做了处理，CI 里不要用 `--shallow`。
- Kotlin 改动通过 `api_audit.py`（27 个上游符号引用）、资源一致性与 CI 完整编译验证，但**尚未做真机验证**。
- **模块快照与通道验签目前是主机侧工具**（`next/snapshot.py`、`next/channel.py`），面向模块开发者与分发方；**设备上的自动快照 / 自动验签未实现**，App 里两个开关当前影响体检状态与构建期默认值。这是 [路线图](docs/ROADMAP.md) 的 P0/P1 首要缺口，不掩饰。

## 文档

- [功能清单、缺陷记录与后续可增加的新功能（路线图）](docs/ROADMAP.md)
- [Native 核心审查与增强报告：掉 root / 泄露 / 线程 / 隐藏](docs/NATIVE-AUDIT.md)
- [调研分析：官方架构、Kitsune 基线定位与差异数据](docs/ANALYSIS.md)
- [设计：优化点、新功能与路线图](docs/DESIGN.md)
- [构建与环境说明](docs/BUILDING-NEXT.md)
- [分支变更日志](docs/CHANGELOG-NEXT.md)

## 许可

继承上游 **GPL-3.0-or-later**。上游版权归 John Wu 及 Magisk 贡献者所有。本分支新增代码同样以 GPL-3.0-or-later 发布。

> 本项目与 Magisk 官方无关，也不是 Google 官方产品。
