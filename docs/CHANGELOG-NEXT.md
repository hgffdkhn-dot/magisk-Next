# magisk-Next 变更日志

## 31.1-next.3 — Native 核心增强：Zygisk / 隐藏 / 线程 / 遗留缺陷

> 方向调整：上一轮的主机侧工具与文档被明确评价为「加了跟没加似的」。本轮**直接修改
> `native/src` 核心**，并用推送后的 CI 完整构建做真实编译验证。完整审查见
> [NATIVE-AUDIT.md](NATIVE-AUDIT.md)。

### Native 改动（10 个文件，+173 −44）

| 分类 | 文件 | 改动 |
| --- | --- | --- |
| Zygisk | `core/zygisk/entry.cpp` | companion `dlsym` 失败时 `dlclose`；`poll` 每次重建 `pollfd`、处理 EINTR / `POLLERR\|POLLHUP\|POLLNVAL`；非法 `module_id` 显式 `close(client)` |
| Zygisk | `core/zygisk/daemon.rs` | `poll()` 返回 `-1`（EINTR）不再误判 socket 死亡、不再无谓重 fork zygiskd |
| Zygisk | `core/zygisk/module.cpp` | 模块缺 `zygisk_module_entry` 时 `dlclose` 并置 `fds[i] = -1` |
| 隐藏 | `core/mount.rs` | `revert_unmount()` 额外清理私有 tmpfs `<tmp>/.magisk/` 下的 target/source，使用完整路径前缀避免误卸载 |
| 线程 | `core/thread.rs` | 单 `Option<task>` 槽改 `VecDeque` FIFO 队列、提交者不再等待、双 Condvar 合一、新增 `MAX_POOL_SIZE = 16` |
| 线程 | `core/utils.cpp` | `pthread_create()` 返回值不再写进 `errno`，补 `pthread_attr_destroy()` |
| 掉 root | `core/daemon.rs` | accept 错误按 `EMFILE/ENFILE/EINTR/ECONNABORTED/EAGAIN/EBADF/EINVAL` 分类，不再一律 `exit(1)`；`connect_daemon()` 加 5 秒 deadline |
| 掉 root | `core/deny/utils.cpp` | 守卫 `pkg_to_procs.find(pkg)->second` 的 `end()` 解引用 |
| 授权 / 泄露 | `core/su/daemon.rs` | fork 失败显式回 `SuPolicy::Deny`；`waitpid()` 处理 EINTR 避免僵尸进程 |
| 高占用 | `core/deny/logcat.cpp` | namespace 等待加 `MAX_NS_POLLS = 300`（约 3 秒）上限，消除无限 10ms 忙等与 helper 残留 |

### 新增静态守卫与校验

- `next/native_audit.py`：把 12 组修复固化成 **12 条规则 / 60 项断言**，含逐条扰动自测
  （删除必需片段 / 注入反模式，验证守卫确实能抓到回滚），防止 rebase 或合并上游时静静丢失修复。
- `next/verify_repo.py`：9 项 → **10 项**（新增 `native guards`）。
- `scripts/verify-next.sh`：工具自测 8 → 9 个；新增 **Rust edition 2024 语法解析段**
  （先探测 rustfmt 支持度，不支持则 SKIP，不阻断 CI）。
- `tests/test_next_tools.py`：21 → **25 个单测**（新增 `TestNativeAudit` 4 项）。
- 版本号统一推进到 `31.1-next.3`，修复此前 `next_common.py` / `__init__.py` / `NextFeatures.kt`
  停留在 `next.1`、文档写 `next.2` 的漂移。

### 验证记录（本地实测）

| 检查 | 结果 |
| --- | --- |
| `rustfmt --edition 2024 --emit stdout`（5 个改动 `.rs`） | 全部可解析 |
| `python3 next/native_audit.py` / `--self-test` | 12/12 规则、60 项断言、扰动自测通过 |
| `python3 next/verify_repo.py` | **10/10 通过** |
| `python3 -m unittest discover -s tests -v` | **25/25 通过** |
| `bash scripts/verify-next.sh` | **ALL CHECKS PASSED** |
| GitHub Actions `build-next.yml` 完整构建 | **success**（run `42370477749`，debug，约 7 分钟，见下方） |

### 推送与 CI 结果（2026-11-07）

- **推送方式**：本轮 `github.com` 直连不可达（`api.github.com` 可达），改用 GitHub Git Data
  API 重建 commit 并更新 `refs/heads/next`。两个 commit 的 **tree SHA 与 commit SHA 均与
  本地完全一致**，远端 `next` = `72a4d9a13`，本地与远端无分叉。
- **自动静态校验**（`magisk-Next CI`，run `42370394500`）：**success**。日志确认
  `native guards 12/12`、仓库校验 `10/10`、25 个单测、`rustfmt` 5 个文件可解析、
  `ALL CHECKS PASSED`。
- **完整构建**（`magisk-Next Build`，run `42370477749`）：**success**。日志确认
  `Compiling magisk v0.0.0 (.../native/src/core)` —— `thread.rs` / `daemon.rs` /
  `mount.rs` / `su/daemon.rs` / `zygisk/daemon.rs` 真实编译通过；
  `[arm64-v8a] Compile++ : magisk <= utils.cpp` / `entry.cpp` / `module.cpp` 等
  C++ 改动同样编译通过；`BUILD SUCCESSFUL`；`integrity.py verify` 全部通过。
- **产物**：37.74 MB 主 artifact（`app-debug.apk` / `test.apk`）+ 2.71 MB 符号表。

### 诚实标注

- **不动 MagiskSU 权限模型与 daemon 签名信任链**；不含针对具体应用检测的绕过代码、
  特征串或黑名单。隐藏增强只扩大 Magisk **自身挂载** 的清理范围。
- 本地无 Android SDK / ONDK / submodule 内容，native 真编译必须依赖 CI；
  rustfmt 解析与静态守卫**不等于运行时正确**，真机 / AVD 冒烟仍未实现（P0）。
- 本轮修复是对既有路径的健壮性与资源生命周期修复，不引入新的 root 能力或对外接口。

## 31.1-next.2 — 功能增强与缺陷修复

> 事实基线：上一轮的完整构建工作流已在 GitHub Actions 实跑 **success**
> （run #2，产物 39.6 MB + 符号表 2.8 MB），归档快照的权限/gitlink 修复确认有效。
> 本轮在已验证的基线上继续增强。详见 [ROADMAP.md](ROADMAP.md)。

### 修掉的缺陷

| 编号 | 问题 | 修复 |
| --- | --- | --- |
| D1 | `next.*` 注入 `flags.prop` 后 Gradle / App 从未消费，配置写了不生效 | `Plugin.kt` 加 4 个 getter（含特殊字符转义）、`core/build.gradle.kts` 加 4 个 `buildConfigField`、`Config.kt` 开关默认值改读 `BuildConfig.NEXT_*` |
| D2 | `Config.nextHealthCheck` 存了值但无人读取 | 控制导出入口显隐，导出 JSON 增加 `health_enabled`，报告渲染显示开关状态 |
| D3 | `health_report.py --output` 父目录不存在时抛未捕获异常 | 自动建父目录 + 捕获 `OSError` |
| D4 | demo 报告检查项与 App 实际导出的 8 项不一致 | demo 与 `collectChecks()` 逐项对齐，自测断言 8 项 |
| D5 | `module_lint` 路径穿越重复报警，漏检可执行位与符号链接逃逸 | 去重；新增 `ID_DIR_MISMATCH`、`BAD_NAME`、`NOT_EXECUTABLE`、`SYMLINK_ESCAPE` |
| D7 | `integrity.collect()` 会跟随符号链接 | 跳过链接，verify 报 `SYMLINK_SKIPPED` WARN |
| D8 | 文档仍写「未产出 APK」「Gradle 未读取 flags.prop」 | README / DESIGN / CHANGELOG 同步为事实 |
| D9 | 静态校验只查资源名，不查上游 Kotlin 符号 | 新增 `api_audit.py`，接入 `verify_repo.py` |
| D10 | `snapshot.py` 两个连续 `nargs="?"` 位置参数，`verify --root X <sid>` 报 `unrecognized arguments` | 改用 `parse_intermixed_args()`，并加入 `verify-next.sh` 的 CLI 冒烟防回归 |

### 新增能力

- `next/snapshot.py`：模块快照与回滚 —— `capture` / `list` / `show` / `diff` / `verify` /
  `restore`（默认 dry-run，`--force` 执行且自动先备份当前状态）/ `prune`。含路径穿越防护、
  符号链接记录、负载篡改检测与拒绝回滚。
- `next/channel.py`：更新通道清单 —— 格式定义、HTTPS 强制、产物 SHA256 校验、
  `openssl` RSA 签名/验签（`canonical_bytes` 规范化签名对象）；篡改即验签失败。
  未提供公钥时明确报 `UNVERIFIED` WARN，不假装验签成功。
- `next/api_audit.py`：从官方 `Info.kt` / `Config.kt` / `build.gradle.kts` / `strings.xml` /
  Compose 组件动态提取定义，核对 Next Kotlin 的 27 个上游引用，防止上游重命名导致编译失败。
- `NextFeatures.kt`：`BRAND` / `CHANNEL` 改读 `BuildConfig.NEXT_*`，`Health` 增加
  `channel` 与 `health_enabled` 字段并写入导出 JSON。
- `NextSection.kt`：新增「导出体检报告」入口（写 `cacheDir/next-health.json` + `ACTION_SEND`
  纯文本分享，带失败 Toast），受 `nextHealthCheck` 开关控制；新增中英文各 2 条文案。
- `verify_repo.py`：由 6 项扩到 **9 项**（新增 Kotlin API 守卫、`next.*` 配置闭环、
  工具自测完整性）。
- `scripts/verify-next.sh`：8 个工具自测 + 快照/通道 **CLI 真实冒烟**。
- `tests/test_next_tools.py`：单测由 11 个扩到 **21 个**，覆盖快照回滚、验签清单、
  API 守卫、符号链接防护、输出目录创建。
- `docs/ROADMAP.md`：能力矩阵、缺陷清单、12 项后续可增加的新功能与优先级。

### 验证记录（本轮实测）

| 检查 | 结果 |
| --- | --- |
| `python3 next/verify_repo.py` | **9/9 通过** |
| `python3 next/api_audit.py` | 27 个上游引用全部有定义 |
| 8 个工具 `--self-test` | 全部通过（含 openssl RSA 签名/验签/篡改实测） |
| `python3 -m unittest discover -s tests -v` | **21/21 通过** |
| `bash scripts/verify-next.sh` | ALL CHECKS PASSED（含快照 capture→diff→verify→restore 冒烟） |
| `python3 next/health_report.py --output <多级目录>/report.md` | 自动建目录成功 |

### 仍未实现（诚实标注）

- 设备侧自动模块快照与设备侧通道验签：**主机侧工具已完整可用，App 侧自动执行逻辑未写**（P0/P1）。
- Kotlin 改动仍**未经 Android Gradle 编译**；`api_audit.py` 是静态守卫，不能替代编译。
- 完整构建由 GitHub Actions 完成，本沙箱仍无 Android SDK / ONDK / JDK 25。

## 31.1-next.1

基线：`topjohnwu/Magisk` `master @ 33bfff7ce7`（v31.1 之后）。基线 commit 保持未改动，以下均为叠加改动。

### 新增

- `next/` 主机工具箱：`preflight.py`（9 项环境自检）、`module_lint.py`（模块静态校验）、`integrity.py`（SHA256 产物清单）、`health_report.py`（体检报告渲染）、`verify_repo.py`（6 项仓库一致性校验）、`next_common.py`（公共定义）。
- `tests/test_next_tools.py`：11 个单元测试。
- `scripts/bootstrap-submodules.sh`：兼容 gitlink 与归档快照两种来源，支持镜像回退。
- `scripts/next-build.sh`：自检 → `build.py` → 产物清单。
- `scripts/verify-next.sh`：静态校验 + 单测 + 工具自测统一入口。
- `.github/workflows/next-ci.yml`：push/PR 秒级静态校验。
- `.github/workflows/build-next.yml`：手动 / `v*` tag 触发的完整构建工作流，复用上游 `setup` composite action，含子模块引导、环境自检、产物校验、上传与自动发 Release。
- `.github/next-ci.prop`：CI 构建配置，带 `next.*` 标识、不含签名占位值。
- `app/core/src/main/java/com/topjohnwu/magisk/core/next/NextFeatures.kt`：分支常量、8 项体检检查、JSON 导出。
- `app/apk/src/main/java/com/topjohnwu/magisk/ui/settings/NextSection.kt`：独立设置分区。
- `README-NEXT.md`、`docs/ANALYSIS.md`、`docs/DESIGN.md`、`docs/BUILDING-NEXT.md`、`docs/CHANGELOG-NEXT.md`。

### 修改

- `build.py`：`dump_flags_native()` 注入 `NEXT_BRAND` / `NEXT_CHANNEL`（C 与 Rust 两处）；`dump_flags_app()` 注入 4 个 `next*` 属性；`load_config()` 增加 `next.*` 显式映射、默认值与 `next.channel` 的 HTTPS 校验。
- `config.prop.sample`：新增 4 个 `next.*` 可选配置及说明。
- `app/core/.../Config.kt`：`Key` 新增 3 个 preference 键，新增 3 个委托属性（默认开启）。
- `app/apk/.../settings/SettingsScreen.kt`：`SettingsContent` 第二列插入 1 行 `NextSection()` 调用。
- `app/core/src/main/res/values/strings.xml`、`values-zh-rCN/strings.xml`：各新增 7 条 Next 文案。
- `scripts/next-build.sh`：**修正参数拼接缺陷**。`build.py` 的 `-r/-v/-c` 是全局参数、必须排在 action 之前；此前 `--release` 被当作 action 透传，既不补默认的 `all`，也会让 `./build.py --release` 只打印帮助并以 1 退出（原 `next-ci.yml` 的完整构建 job 因此跑不通）。现在单独收集全局参数并自动补 `all`。

### 修复（归档快照损伤）

release 归档 zip 不保留 Unix 文件属性，导致 `./build.py` 在 CI 里 `Permission denied`（exit 126）。按官方 git tree `33bfff7ce7` 逐项对齐 `next` 分支：

- 恢复 **10 个** `100755` 可执行位（`build.py`、`app/gradlew`、`scripts/env.py`、`scripts/release.sh` 等）；新增的 `next/*.py` 工具也补上可执行位。
- `native/src/base/include/rust/cxx.h` 由「内容为路径文本的普通文件」恢复为 **120000 符号链接**（blob sha 与官方一致）。
- 补齐 **8 个 160000 gitlink**，SHA 与官方锁定的 submodule commit 一致；`bootstrap-submodules.sh` 因此能走 `git submodule update` 锁定版本。
- `.github/workflows/build-next.yml`：子模块引导去掉 `--shallow`，避免 shallow clone 取不到 gitlink 指向的历史 commit。
- `main` 分支保持未改动的原始基线，以上修复只叠加在 `next`。

### 未改动

- 官方 `README.MD`、LICENSE、`.gitmodules`、`docs/` 下的上游文档、`native/` 源码、Gradle 构建脚本、签名与 SU 信任链逻辑。

### 验证记录

| 检查 | 结果 |
| --- | --- |
| `python3 -m py_compile build.py` | 通过 |
| `python3 build.py -h` | 通过 |
| `dump_flags_app` / `dump_flags_native` 实跑 | 生成含 `NEXT_*` 的 `flags.prop` / `flags.h` / `flags.rs` |
| `python3 next/verify_repo.py` | 6/6 通过 |
| `python3 -m unittest discover -s tests -v` | 11/11 通过 |
| 4 个工具 `--self-test` | 全部通过 |
| `bash scripts/verify-next.sh` | ALL CHECKS PASSED |
| `python3 next/preflight.py`（本沙箱） | 6 通过 / 3 失败（SDK、ONDK、submodule 缺失，符合预期） |

### 已知未完成

- Kotlin 改动未经 Android Gradle 编译验证。
- 基线缺 submodule commit 锁定。
- 模块快照、通道签名校验、体检报告导出 UI 入口属于路线图 P1，仅有开关与数据层，未实现执行逻辑。

详见 [DESIGN.md](DESIGN.md) 与 [BUILDING-NEXT.md](BUILDING-NEXT.md)。
