# 设计：定位、已实现能力与路线图

## 1. 定位

`magisk-Next` 是**基于官方最新基线的工程化分支**，不是旧版回退分支。

三条约束：

1. **不回退架构**。基线是官方 `master @ 33bfff7ce7`（v31.1+），Compose / Material 3、统一修补管线、Rust native 全部保留。
2. **改动可剥离**。新增能力集中在 `next/`、独立 Kotlin 文件和少量配置注入点，上游合版时容易分辨、容易取舍。
3. **诚实标注完成度**。构建期标识、开关、工具链是完整可跑的代码；模块快照、通道签名校验的执行逻辑列为路线图，不假装已经实现。

调研依据见 [ANALYSIS.md](ANALYSIS.md)。

## 2. 已实现（本仓库代码中存在且通过校验）

### 2.1 分支标识与构建期配置

`build.py` 三处注入点，全部实测执行过：

| 输出 | 内容 |
| --- | --- |
| `native/out/generated/flags.h` | `#define NEXT_BRAND` / `#define NEXT_CHANNEL` |
| `native/out/generated/flags.rs` | `pub const NEXT_BRAND` / `NEXT_CHANNEL` |
| `app/build/flags.prop` | `nextBrand` / `nextChannel` / `nextModuleSnapshot` / `nextChannelVerify` |

`config.prop` 用 4 个可选键配置，`load_config()` 做默认值填充和 `next.channel` 的 HTTPS 校验：

```properties
next.brand=magisk-Next
next.channel=
next.moduleSnapshot=1
next.channelVerify=1
```

用显式映射（`next_props`）而不是直接散落键名，是为了让 `next/verify_repo.py` 能自动核对 `build.py` 与 `config.prop.sample` 是否同步。

### 2.2 App 侧

| 文件 | 作用 |
| --- | --- |
| `app/core/.../next/NextFeatures.kt` | 分支常量、8 项设备体检 `Check`、UTC 时间戳、手写 JSON 转义导出 |
| `app/core/.../Config.kt` | 新增 3 个 preference 键与委托属性，默认值全部保守开启 |
| `app/apk/.../settings/NextSection.kt` | 独立 Compose 分区，3 个 `SettingsSwitch` + 版本信息 |
| `app/apk/.../settings/SettingsScreen.kt` | 仅插入 1 行 `NextSection()` 调用 |
| `values/strings.xml` / `values-zh-rCN/strings.xml` | 7 条文案，中英齐全 |

`NextFeatures` 只依赖 Kotlin 标准库、Android/Java 基础类和项目里已有的 `Config` / `Info` / `BuildConfig`，没有引入任何第三方依赖。JSON 用 `StringBuilder` 手工拼接并自己处理转义，避免在 core 模块里加序列化库。

**为什么不改 `SettingsUiState` / `SettingsViewModel`**：那会牵动数据类、初始状态、回调和两处双列布局，改动面大且容易在上游合版时冲突。自包含分区用 `remember { mutableStateOf(...) }` 直接读写 `Config`，功能等价但只多一行调用点。

### 2.3 主机侧工具箱（`next/`）

| 工具 | 作用 | 验证方式 |
| --- | --- | --- |
| `preflight.py` | 9 项构建前检查，输出修复建议，`--json` / `--strict` | 自测 + 沙箱实跑（正确报出 SDK / ONDK / submodule 缺失） |
| `module_lint.py` | `module.prop` 必填字段、id 正则、路径穿越、`versionCode`、`minMagisk`、脚本 shebang、空模块检查 | 自测 + 单测，构造合法/非法模块 |
| `integrity.py` | 生成 `SHA256SUMS`（兼容 `sha256sum -c`）+ `SHA256SUMS.json`，校验缺失/篡改/多余文件 | 自测 + 单测，含篡改与删除场景 |
| `health_report.py` | 把 App 导出的 JSON 渲染成 Markdown 体检表，`--demo` 可独立演示 | 自测 + 单测 |
| `verify_repo.py` | 6 项仓库一致性静态校验 | 直接实跑，6/6 通过 |

五个工具都不依赖第三方库，Python 3.8+ 可跑，全部支持 `--self-test`。

### 2.4 脚本与 CI

- `scripts/bootstrap-submodules.sh`：兼容「带 gitlink 的 `next` 分支」和「无 gitlink 的 `main` 基线」两种情况，前者用 `git submodule update` 锁定官方 commit，后者按 `.gitmodules` 逐个克隆并支持镜像回退；CI 中不加 `--shallow`。
- `scripts/next-build.sh`：自检 → `build.py` → 产物清单，参数可透传。
- `scripts/verify-next.sh`：静态校验 + 单测 + 自测，一处入口。
- `.github/workflows/next-ci.yml`：push/PR 跑秒级静态校验，不需要 SDK。
- `.github/workflows/build-next.yml`：`workflow_dispatch` / `v*` tag 跑完整构建。复用上游 `setup` composite action 装 JDK 25 与 ONDK，但**子模块改用 `bootstrap-submodules.sh` 引导**（归档快照无 gitlink，`submodules: recursive` 无效）；产物经 `integrity.py` 校验后上传，tag 触发时用 `gh release create` 自动发 Release。
- `.github/next-ci.prop`：CI 专用构建配置，带 `next.*` 标识、不含签名占位值。

## 3. 路线图（未实现，明确列出）

**完整路线图（12 项后续可增加的新功能、优先级、落点与风险）见 [ROADMAP.md](ROADMAP.md)。**
下表只保留状态摘要。

| 优先级 | 项目 | 当前状态 |
| --- | --- | --- |
| P0 | Android Gradle 编译验证 | **已由 CI 覆盖**：`build-next.yml` 实跑 success 并产出 39.6 MB 包；但真机/AVD 冒烟仍未做 |
| P0 | 对齐 submodule commit | **已完成**（`next` 分支按官方 tree 补齐 8 个 gitlink） |
| P0 | `next.*` 配置闭环 | **已完成**（`flags.prop` → `Plugin.kt` → `BuildConfig` → App，有 `verify_repo.py` 守卫） |
| P1 | 模块快照 | **主机侧已完成**（`next/snapshot.py` 含回滚与篡改拒绝）；**设备侧自动快照未写** |
| P1 | 更新通道签名校验 | **主机侧已完成**（`next/channel.py` 含 RSA 签名/验签）；**设备侧接入未写** |
| P1 | 体检报告导出入口 | **已完成**（`NextSection` 导出按钮 + 分享，受 `nextHealthCheck` 控制） |
| P2 | 可选 App Cloak 插件 | 设计阶段，见下 |
| P2 | 模块仓库签名与兼容性矩阵 | 未开始（`module_lint.py` 已具备 `minMagisk` 基础） |
| P2 | 可复现构建 / SBOM / 多 ABI 矩阵 | 未开始 |

### 关于 App Cloak（隐藏能力）

官方 v31.1 明确移除了 app hiding（repackaging）与 stub app。第三方分支通常把它加回来，但直接把 v30.7 的 `app/stub` 整套代码搬进 v31.1 会：

- 重新引入已被删除的 `build-logic` 桩生成的 transform 任务；
- 与 Compose 单 Activity 架构、新的更新通道逻辑冲突；
- 让上游合版变成长期负担。

因此本分支的设计是**独立可选插件**：主仓库只保留配置与接口，隐藏实现放在单独模块/仓库，用户按需安装。本次**没有实现**它，只在体检报告的 `app.cloak` 检查项里预留了 `na` 状态。

## 4. 非目标

- 不针对任何具体应用的检测逻辑做绕过（本分支不含特征字符串、黑名单或规避代码）。
- 不提供预编译二进制、签名密钥或现成刷机包。
- 不改变 MagiskSU 的权限模型与签名信任链。

## 5. 风险

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| `main` 基线来自归档快照 | 该分支缺可执行位、符号链接与 gitlink，直接在其上构建会失败 | 修复只叠加在 `next`（按官方 tree 对齐）；`bootstrap-submodules.sh` 兼容两种来源 |
| Kotlin 未在本沙箱编译 | 可能存在编译期类型/import 问题 | CI 完整构建已实跑 success；`api_audit.py` + `verify_repo.py` 做静态守卫；真机/AVD 冒烟仍待补 |
| `next.*` 配置链路较长 | 任一环缺失（`build.py` / `Plugin.kt` / `build.gradle.kts`）都会让配置静默失效 | `verify_repo.py` 第 6 项强制核对 4 个 flag 的全链路 |
| 签名信任链 | 自行签名的 release 包会被 Magisk daemon 视为不匹配并卸载 | 按上游 `docs/build.md` 配置 `config.prop` 签名，或使用 debug 构建 |
| 上游快速迭代 | v31.x 后续可能再次调整 `Config` / 设置页结构 | 改动集中在少数文件，且有 `verify_repo.py` 做回归校验 |
