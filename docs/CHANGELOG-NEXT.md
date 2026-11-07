# magisk-Next 变更日志

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
