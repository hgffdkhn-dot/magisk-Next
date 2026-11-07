# magisk-Next

基于 [topjohnwu/Magisk](https://github.com/topjohnwu/Magisk) 官方 `master`（`33bfff7ce7`，v31.1 之后）的第三方分支。目标不是换个名字，而是**在上游最新代码基线上补齐工程化能力**，并把 v31.1 移除掉的部分可配置能力以模块化方式带回。

基线源码保持未改动，所有分支改动都叠加在后续提交里，`git log` 可以直接看出边界。

## 这个分支做了什么

| 类别 | 内容 | 主要文件 |
| --- | --- | --- |
| 分支标识 | `NEXT_BRAND` / `NEXT_CHANNEL` 编译进 C 头文件、Rust 常量、Gradle `flags.prop` | `build.py`、`config.prop.sample` |
| 构建配置 | 4 个 `next.*` 可选配置，带 HTTPS 校验与默认值 | `build.py`、`config.prop.sample` |
| App 功能 | 3 个独立开关（模块快照 / 通道校验 / 运行体检）+ 设备体检 JSON 导出 | `app/core/.../next/NextFeatures.kt`、`app/apk/.../settings/NextSection.kt` |
| 主机工具 | 环境自检、模块静态校验、产物 SHA256 清单、体检报告渲染、仓库一致性校验 | `next/*.py` |
| 工程脚本 | submodule 引导、一键构建、一键校验 | `scripts/*.sh` |
| CI | push/PR 秒级校验；手动或 `v*` tag 触发完整构建并发布 Release | `.github/workflows/next-ci.yml`、`build-next.yml` |

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
```

## 当前校验状态

在本仓库实测：

- 仓库一致性校验 **6/6 通过**（Python 语法、52 个资源 XML、7 个 Kotlin 资源引用、`next.*` 配置一致性、3 个 shell 脚本、8 个 submodule 登记）
- 单元测试 **11/11 通过**
- 4 个工具 `--self-test` 全部通过
- `python3 -m py_compile build.py`、`python3 build.py -h` 通过；`dump_flags_app` / `dump_flags_native` 实际执行并生成了含 `NEXT_*` 的 `flags.prop` / `flags.h` / `flags.rs`

## 已知限制

- **未产出可刷入的 APK / boot 镜像**。当前沙箱没有 Android SDK、ONDK 和 JDK 25，`preflight` 会如实报出这三项缺失。完整构建需在 [构建文档](docs/BUILDING-NEXT.md) 描述的环境中执行。
- 基线源码来自 GitHub release 归档快照，原始 zip **不含 8 个 submodule 内容，且丢失了可执行位、符号链接与 gitlink 记录**。`next` 分支已按官方 git tree（`33bfff7ce7`）补齐：10 个脚本恢复 `100755`、`native/src/base/include/rust/cxx.h` 恢复为符号链接、8 个 gitlink 锁定到官方 commit；`main` 保持未改动的原始快照。`scripts/bootstrap-submodules.sh` 对两种来源都做了处理，CI 里不要用 `--shallow`（取不到 gitlink 指向的历史 commit）。
- Kotlin 改动通过了静态引用与资源一致性检查，但**未经 Android Gradle 编译**。首次合版请在 Android Studio 里跑一次 `:apk:assembleDebug`。
- `next.*` 中的 `next.moduleSnapshot` / `next.channelVerify` 目前是构建期标识 + App 侧开关，**模块快照与通道签名校验的执行逻辑属于路线图 P1**，尚未实现。详见 [设计文档](docs/DESIGN.md)。

## 文档

- [调研分析：官方架构、Kitsune 基线定位与差异数据](docs/ANALYSIS.md)
- [设计：优化点、新功能与路线图](docs/DESIGN.md)
- [构建与环境说明](docs/BUILDING-NEXT.md)
- [分支变更日志](docs/CHANGELOG-NEXT.md)

## 许可

继承上游 **GPL-3.0-or-later**。上游版权归 John Wu 及 Magisk 贡献者所有。本分支新增代码同样以 GPL-3.0-or-later 发布。

> 本项目与 Magisk 官方无关，也不是 Google 官方产品。
