# 功能清单与后续路线图

> 本文回答两个问题：**magisk-Next 现在到底有哪些能力**、**还能加什么**。
> 所有「已实现」项都能用 `bash scripts/verify-next.sh` 复验；所有「未实现」项明确标注，
> 不把「开关已落地」当作「功能已完成」。
> native 核心的完整审查（12 组缺陷的根因与边界）见 [NATIVE-AUDIT.md](NATIVE-AUDIT.md)。

## 1. 能力矩阵（31.1-next.3）

| 能力 | 所在层 | 状态 | 复验方式 |
| --- | --- | --- | --- |
| 分支标识 `NEXT_BRAND` / `NEXT_CHANNEL` | 构建期 C / Rust / Gradle | 已实现 | `build.py` 的 `dump_flags_*` 实跑 |
| `next.*` 配置 → `flags.prop` → `BuildConfig` → App | 全链路 | 已实现 | `verify_repo.py` 第 6 项 |
| 3 个设置开关 + 独立 Compose 分区 | App UI | 已实现 | `api_audit.py`（27 个上游引用） |
| 8 项设备体检 + JSON 导出 + 分享入口 | App / UI | 已实现 | `health_report.py --demo` |
| 模块快照：capture / list / show / diff / verify / restore / prune | 主机工具 | 已实现 | `snapshot.py --self-test` |
| 更新通道清单：格式校验 / 产物 SHA256 / RSA 签名与验签 | 主机工具 | 已实现 | `channel.py --self-test`（实测 openssl） |
| 模块静态校验（含符号链接逃逸、可执行位） | 主机工具 | 已实现 | `module_lint.py --self-test` |
| 产物 SHA256 清单（不跟随符号链接） | 主机工具 | 已实现 | `integrity.py --self-test` |
| Kotlin 上游 API 引用守卫 | 静态校验 | 已实现 | `api_audit.py` |
| **Zygisk / 隐藏 / 线程 / 掉 root / 泄露修复（12 组）** | **`native/src/core`** | **本轮新增** | `native_audit.py` + CI 完整构建 |
| **native 修复防回滚守卫（12 规则 / 60 断言）** | 静态校验 | **本轮新增** | `native_audit.py --self-test` |
| 仓库一致性 10 项校验 | 静态校验 | 由 6 项扩到 10 项 | `verify_repo.py` |
| 完整构建 + 产物上传 + tag 自动发 Release | CI | 已实现并实跑 success | Actions run #2（39.6 MB 产物） |

**层级边界要说清楚**：模块快照与通道验签目前是**主机侧工具**（面向模块开发者与分发方），
设备上的自动快照 / 自动验签**尚未实现**——App 里的两个开关当前只影响体检报告的状态项
与构建期默认值。这是下面 P0/P1 的首要缺口，不掩饰。

**native 改动的边界同样要说清楚**：本轮修改了 magiskd / MagiskSU / Zygisk / DenyList 的
健壮性与资源生命周期，但**没有改变 MagiskSU 权限模型、没有加入针对具体应用检测的绕过代码、
没有引入新的 root 能力或对外接口**。完整构建只证明「能编译」，尚未做真机 / AVD 冒烟。

## 2. 上一轮修掉的缺陷（D1–D10）

> 本轮（next.3）的 12 组 native 缺陷、症状与根因见
> [NATIVE-AUDIT.md](NATIVE-AUDIT.md) 第 2–6 节。

| 编号 | 缺陷 | 后果 | 修复 |
| --- | --- | --- | --- |
| D1 | `next.*` 注入 `flags.prop` 后 Gradle / App 从未消费 | 配置写了不生效 | `Plugin.kt` 加 4 个 getter，`core/build.gradle.kts` 加 4 个 `buildConfigField`，`Config.kt` 默认值改读 `BuildConfig.NEXT_*` |
| D2 | `Config.nextHealthCheck` 存了值但无人读 | 开关形同虚设 | 控制「导出报告」入口显隐；导出 JSON 增加 `health_enabled`，报告渲染显示 |
| D3 | `health_report.py --output` 父目录不存在时抛未捕获异常 | CLI 崩溃 | 自动建父目录 + 捕获 `OSError` |
| D4 | demo 报告检查项与 App 实际 8 项不一致 | 文档误导 | demo 数据按 `collectChecks()` 逐项对齐，自测断言 8 项 |
| D5 | `module_lint` 路径穿越重复报警、漏检可执行位与符号链接逃逸 | 坏模块漏网 | 去重 + 新增 4 类检查 |
| D7 | `integrity.collect()` 会跟随符号链接 | 清单可能覆盖宿主文件 | 跳过符号链接并在 verify 报 WARN |
| D8 | 文档仍写「未产出 APK」「Gradle 未读取 flags.prop」 | 与事实不符 | README / DESIGN / CHANGELOG 同步 |
| D9 | 静态校验只查资源名，不查 `Info` / `Config` / `BuildConfig` 符号 | 上游重命名导致编译失败才发现 | 新增 `api_audit.py`，接入 `verify_repo.py` |

## 3. 后续可增加的新功能（按优先级）

### Native 方向（本轮新增，详见 [NATIVE-AUDIT.md](NATIVE-AUDIT.md) 第 9 节）

| 优先级 | 功能 | 说明 |
| --- | --- | --- |
| P0 | 真机 / AVD 冒烟脚本 | 用 `su -c` + DenyList + Zygisk 模块组合验证「掉 root」是否还会复现 |
| P0 | daemon 健康指标 | 统计 accept 错误分类次数、线程池队列长度、峰值线程数，暴露给体检报告 |
| P1 | Zygisk 模块 watchdog | companion 超时 / 崩溃后按 backoff 重启，避免单个坏模块拖死 zygiskd |
| P1 | fd 泄露计数器 | 在 zygiskd / su 路径上记录 fd 分配与释放，超阈值告警 |
| P1 | su 请求超时 | 给授权等待（用户点按）加可配置上限，避免 UI 卡死时请求永久占用 |
| P1 | DenyList 规则热更新 | 不走全量 `scan_deny_apps()` 重建，收敛两侧不同步窗口（D-A3 的进一步收敛） |
| P2 | zygiskd crash backoff | 连续崩溃时指数退避，避免 fork 风暴 |
| P2 | 模块兼容性矩阵 | 主机侧声明模块要求的 Zygisk API 版本，装前拦截 |
| P2 | boot A/B 槽位回滚辅助 | 与主机侧 `snapshot.py` 联动 |

### P0 — 上线前必须补

1. **真机 / 模拟器冒烟**。CI 目前只证明「能编译出包」，没证明 APK 能安装、Magisk 能激活、
   `BuildConfig.NEXT_*` 在运行时正常。上游已有 `scripts/avd.sh test` 与 15 个 API 的 AVD 矩阵
   （见 `.github/workflows/build.yml`），可在 `build-next.yml` 里加一个可选 `avd-test` job。
   风险：耗时、需要 KVM、AVD 镜像下载。
2. **设备侧自动模块快照**。把 `snapshot.py` 的语义移植到 App：模块安装前用官方 root `Shell`
   API 对 `/data/adb/modules` 做状态记录，刷入失败时一键回滚。落点 `app/core/.../tasks/`，
   与主机工具共用清单格式。风险：需要 root、事务边界、`/data/adb` 权限、失败检测条件、
   回滚本身可能失败（必须先备份当前状态，主机工具已实现 `restore` 的 backup 语义）。
   **这是当前最大的「开关有、设备侧无」缺口。**

### P1 — 主机侧可先落地，价值明确

3. **设备侧更新通道验签**。`channel.py` 已定义清单格式与 RSA 验签，但 App 的更新流程
   （`NetworkService` / `JobService` / `HomeViewModel`）还没接。需要内置公钥资源、公钥轮换策略、
   离线降级行为。风险：与官方更新通道强耦合，上游改动易冲突。
4. **模块兼容性矩阵**。`module_lint.py` 已校验 `minMagisk` 格式，可扩为
   「`minMagisk` ↔ 运行时版本 ↔ ABI ↔ Zygisk」矩阵，发布前给出兼容结论。落点
   `next/module_lint.py` + 一份可维护的 `compat.json`。风险：版本数据需持续维护。
5. **模块仓库索引与签名**。把 `channel.py` 的清单格式扩到多模块仓库（多版本、依赖、
   每模块签名）。落点新增 `next/repo_index.py`。风险：需兼容现有模块生态。
6. **设置项导入 / 导出**。把 `Config` 的偏好（含 3 个 Next 开关）导出为可校验的 JSON，
   刷机后一键恢复。落点 `NextSection.kt` + `next/settings_io.py`。风险：更新通道 URL、
   下载目录等字段需脱敏。
7. **体检报告一键附到 issue**。把导出 JSON 渲染为 GitHub issue 预填正文，减少来回追问。
   落点 `next/health_report.py --github-body` + `.github/ISSUE_TEMPLATE/`。风险：隐私字段审查。

### P2 — 架构级 / 发布工程

8. **可复现构建与 SBOM**。固定 ONDK r30.1 / Gradle / Rust 版本，输出 SPDX SBOM，
   与 `integrity.py` 的 SHA256 清单联动。风险：上游工具链版本漂移。
9. **多 ABI / 多 OS 构建矩阵**。当前 CI 只构建 `arm64-v8a`（加速），正式发布应覆盖 4 个 ABI
   及 Linux / macOS / Windows 测试构建（可参考上游 `build.yml` 的矩阵）。风险：CI 时长。
10. **Zygisk 模块冲突检测**。扫描已装模块的 `zygisk/` 与 DenyList 配置，提示潜在冲突，
    新增体检检查项。风险：需要 root 读取 `/data/adb`。
11. **App Cloak 可选插件**。以独立模块形式带回 v31.1 移除的隐藏 / 重打包能力，主仓库只保留
    接口。设计已定（见 [DESIGN.md](DESIGN.md)），未实现。风险：与 Compose 单 Activity 架构冲突。
12. **boot 镜像 A/B 槽位回滚**。基于 `Info.isAB` / `Info.slot` 做修补前备份与一键还原，
    落点 `app/core/.../tasks/MagiskInstaller.kt`。风险：误操作可能变砖，需强确认与二次校验。

## 4. 明确不做

- 不针对任何具体应用的检测逻辑做绕过（不含特征串、黑名单、规避代码）。
- 不提供预编译二进制、签名密钥或现成刷机包。
- 不改变 MagiskSU 的权限模型与 daemon 签名信任链。
- 不把未经真机 / AVD 验证的改动宣称「运行时正确」。

## 5. 验证入口

```bash
bash scripts/verify-next.sh          # 10 项静态校验 + 25 单测 + 9 个工具自测
                                     # + Rust edition 2024 语法解析 + CLI 冒烟
python3 next/native_audit.py         # 12 条 native 修复守卫规则
python3 next/api_audit.py            # Kotlin 上游 API 引用守卫
python3 next/snapshot.py --self-test # 快照/回滚/篡改拒绝
python3 next/channel.py --self-test  # 结构与 RSA 验签（依赖 openssl）
```
