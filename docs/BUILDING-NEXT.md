# 构建与环境说明

## 1. 前置条件

沿用上游 `docs/build.md` 的要求，没有额外门槛：

| 项 | 要求 |
| --- | --- |
| 系统 | Linux x64 / macOS x64 / macOS arm64 / Windows x64（Windows 需开发者模式以支持符号链接） |
| Python | 3.8+ |
| Git | 需要符号链接支持 |
| JDK | 25；推荐设置 `ANDROID_STUDIO` 让 `build.py` 自动定位自带 JDK |
| Android SDK | 设置 `ANDROID_HOME` 或 `ANDROID_SDK_ROOT` |
| ONDK | `./build.py ndk` 自动安装（`scripts/env.py` 中 `ondk_version = "r30.1"`） |
| 磁盘 | 建议 ≥ 10 GiB |
| 可选 | `sccache` / `ccache` 加速 C++ 与 Rust 编译 |

先跑一次自检，缺什么会直接列出来：

```bash
python3 next/preflight.py
```

## 2. 获取完整基线

**推荐方式**（能锁定 submodule commit）：

```bash
git clone --recurse-submodules https://github.com/topjohnwu/Magisk.git magisk-Next
cd magisk-Next
git remote add next <你的 magisk-Next 仓库地址>
# 再把本分支的提交 cherry-pick / merge 过来
```

本仓库当前基线是从 GitHub release 归档快照导入的，**不含 8 个 submodule 的内容，也没有 gitlink 记录**。`scripts/bootstrap-submodules.sh` 针对这种情况会按 `.gitmodules` 逐个克隆，并明确提示无法锁定上游 commit：

```bash
./scripts/bootstrap-submodules.sh
# 网络受限时：
MAGISK_NEXT_MIRROR=https://ghfast.top/https://github.com/ ./scripts/bootstrap-submodules.sh
# 只想快速拉一份、不关心 commit：
./scripts/bootstrap-submodules.sh --shallow
```

8 个子模块：`selinux`、`lz4`、`libcxx`、`cxx-rs`、`lsplt`、`system_properties`、`crt0`、`xz-embedded`。

## 3. 构建

```bash
cp config.prop.sample config.prop     # 按需修改
./scripts/next-build.sh --release
```

等价的上游命令是 `./build.py -c config.prop all`。`next-build.sh` 只多做三件事：环境自检、把参数透传、给产物目录生成 `SHA256SUMS`。

也可以只用上游命令：

```bash
./build.py ndk
./build.py all
./build.py -h          # 全部子命令
scripts/env.py ./gradlew :apk:assembleDebug   # 单独跑 Gradle 时的环境包装
```

### `next.*` 配置

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `next.brand` | `magisk-Next` | 编入 `flags.h` / `flags.rs` / `flags.prop` 的分支标签 |
| `next.channel` | 空 | 更新通道清单 URL，**必须以 `https://` 开头**，留空则沿用上游通道 |
| `next.moduleSnapshot` | `1` | 模块快照开关的构建期默认值 |
| `next.channelVerify` | `1` | 通道清单校验开关的构建期默认值 |

注意：后两个目前只是构建期标识 + App 侧偏好，**执行逻辑尚未实现**，见 [DESIGN.md](DESIGN.md) 路线图 P1。

### 签名与分发

上游 release 构建会用签名 APK 的证书作为 root daemon 的信任依据，拒装并卸载签名不匹配的 Magisk App。要分发自己的构建，必须在 `config.prop` 里**完整配置** `keyStore` / `keyStorePass` / `keyAlias` / `keyPass` 四项（要么全填、要么全不填），`preflight.py` 会检查这一点。开发调试请切到官方 debug 构建以关闭签名校验。

## 4. 校验与工具

```bash
bash scripts/verify-next.sh                 # 静态校验 + 单测 + 工具自测（不需要 Android SDK）
python3 next/verify_repo.py --json          # 机器可读的一致性报告
python3 next/preflight.py --strict          # 有 WARN 也返回非零
python3 next/module_lint.py <模块目录>       # 模块发布前检查
python3 next/integrity.py generate --dir out
python3 next/integrity.py verify --dir out
python3 next/health_report.py --input next-health.json --output report.md
python3 next/health_report.py --demo
python3 -m unittest discover -s tests -v
```

## 4.1 GitHub Actions 工作流

仓库里有两条分工明确的工作流：

| 工作流 | 触发 | 做什么 | 需要 SDK |
| --- | --- | --- | --- |
| `next-ci.yml` | push / PR / 手动 | `scripts/verify-next.sh` 静态校验 + 单测 + 工具自测，外加 `next-build.sh --help` 参数入口冒烟 | 否 |
| `build-next.yml` | 手动 `workflow_dispatch` / 推送 `v*` tag | 完整构建、产物校验、上传 artifact；tag 触发时额外自动创建 Release | 是 |

`build-next.yml` 的几个关键点：

- **子模块引导**：基线来自归档快照，index 里没有 gitlink，`actions/checkout` 的 `submodules: recursive` 对本仓库无效，因此用 `./scripts/bootstrap-submodules.sh --shallow` 按 `.gitmodules` 逐个克隆（直连失败自动回退镜像）。这是本分支与上游 `build.yml` 最大的差异。
- **环境**：直接复用上游 composite action `./.github/actions/setup`（`is-asset-build: true`），由它安装 JDK 25、Python、sccache、Gradle 缓存并执行 `build.py ndk` 装 ONDK，与官方 master 保持一致。
- **配置**：`cp .github/next-ci.prop config.prop`。该文件带 `next.*` 构建标识、只构建 `arm64-v8a` 加速 CI，且**刻意不含签名占位值**——`config.prop.sample` 里的 `keyStore=string` 若被照搬会被当成真实 keystore 导致失败。手动触发时可用 `abi_list` / `build_type` 两个输入覆盖。
- **产物**：`scripts/next-build.sh` 自动把 `--release` 归到全局参数并补 `all`；构建完成后 `next/integrity.py` 生成并校验 `SHA256SUMS`，`upload-artifact` 上传 `out/` 与符号表。

> GitHub Actions 的 `workflow_dispatch` 只在**默认分支**上注册，所以本仓库把默认分支设为 `next`；`main` 是未改动的官方基线，不含这两条工作流。

## 5. 当前沙箱为什么没有产出 APK

本次任务运行环境实测：

| 有 | 没有 |
| --- | --- |
| git 2.43、OpenJDK 20、Gradle 9.3、Rust 1.93、Python 3.11 | `ANDROID_HOME` / `ANDROID_SDK_ROOT` |
| 254 GiB 可用磁盘 | Magisk ONDK（`ndk/magisk`，需要 r30.1 的定制 Rust 工具链 + NDK） |
| `api.github.com`、CDN、release 归档可达 | 8 个 submodule 的内容 |
| 完整源码快照与 git 仓库 | JDK 25（上游要求） |

`preflight.py` 在这个环境里如实报出 3 项 FAIL（SDK、ONDK、submodule），因此**没有生成 APK 或 boot 镜像**。仓库里可执行、已验证的部分是：Python 工具箱、构建脚本语法与流程、`build.py` 的配置注入（实际执行 `dump_flags_app` / `dump_flags_native` 生成了 `flags.prop` / `flags.h` / `flags.rs`）、资源与引用的静态一致性。

要拿到可刷入产物，请在满足第 1 节条件的机器上执行第 3 节命令。

### 关于手动 APK 构建工具的适用性

任务里挂载的 `android-apk-builder` / `android-handmade-apk-toolkit` 这类工具，解决的是「没有 Android SDK/NDK 时，用 JDK + d8 手写二进制 Manifest，或把单文件 HTML 包成一个轻量可安装 APK」。它们**不适用于 Magisk 主产物**，原因很具体：

- Magisk App 依赖 AndroidX Compose、Room/protobuf、多模块 Gradle 构建与 `build-logic` 的代码生成任务；
- 真正的 root 能力在 native 侧：`magiskinit` / `magiskboot` / `magiskpolicy` 等由 ONDK 的 Rust + C++ 工具链交叉编译，产物要打进 boot 镜像，不是 APK 能承载的；
- release 包的签名证书与 root daemon 信任链绑定，随手签出来的 APK 会被 daemon 判定为不匹配并强制卸载。

所以本分支坚持走上游 `build.py` 链路，没有用手搓 APK 的方式伪造一个「能装但不能用」的产物。这两套工具适合做**配套的独立小工具**（例如纯展示用的模块仓库查看器），本分支没有引入，以免偏离主线。

## 6. 目录速查

```
next/                     主机侧工具箱（Python，无三方依赖）
tests/                    工具箱单元测试
scripts/bootstrap-submodules.sh   submodule 引导
scripts/next-build.sh     自检 → 构建 → 产物清单
scripts/verify-next.sh    一键校验
app/core/.../next/        App 侧分支标识与体检数据
app/apk/.../settings/NextSection.kt   独立设置分区
docs/                     调研、设计、构建、变更日志
```
