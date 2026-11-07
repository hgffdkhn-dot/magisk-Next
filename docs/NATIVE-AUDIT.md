# magisk-Next · Native 核心审查与增强报告

> 版本 `31.1-next.3` ｜ 基线 `topjohnwu/Magisk @ 33bfff7ce7`（v31.1+）
> 本轮目标：不再只做主机侧工具与文档，而是**直接修改 `native/src` 核心** ——
> 强化 Zygisk、增强隐藏、优化线程逻辑避免高占用，并排查「有概率掉 root」
> 「部分授权时内存泄露」这类遗留缺陷。

---

## 1. 审查范围

| 子系统 | 重点文件 | 关注点 |
| --- | --- | --- |
| magiskd 主循环 | `core/daemon.rs`、`core/utils.cpp`、`core/thread.rs` | accept 错误、连接重试、线程池、pthread 生命周期 |
| MagiskSU 授权 | `core/su/daemon.rs`、`su/su.cpp`、`su/pts.rs` | fork / waitpid / 回包、pty pump、fd 生命周期 |
| Zygisk | `core/zygisk/entry.cpp`、`daemon.rs`、`module.cpp`、`mod.rs`、`hook.cpp`、`module.hpp` | companion dlopen、poll 判定、模块加载、fd 归属 |
| DenyList / 隐藏 | `core/deny/utils.cpp`、`deny/logcat.cpp`、`core/mount.rs` | `end()` 解引用、namespace 等待、`revert_unmount()` 覆盖面 |
| 基础库 | `base/logging.rs`、`base/result.rs`、`base/mount.rs`、`include/consts.*` | 日志宏签名、`log_err!` 返回类型、`MountInfo` 字段 |

共读取并分析 20 个文件，落地 **12 组修复 / 10 个文件、+173 −44 行**。

---

## 2. 结论速览

| 编号 | 分类 | 用户可感知症状 | 根因 | 修复文件 |
| --- | --- | --- | --- | --- |
| D-A1 | 掉 root | root 突然失效，重启才恢复 | accept 任意错误即 `exit(1)` 杀掉 magiskd | `core/daemon.rs` |
| D-A2 | 掉 root | `su` 永久卡住无响应 | `connect_daemon()` 无限 100ms 重试 | `core/daemon.rs` |
| D-A3 | 掉 root | zygote 特化时随机崩溃 | `find()->second` 解引用 `end()` | `core/deny/utils.cpp` |
| D-B1 | 资源泄露 | 长时间运行后线程栈累积 | `pthread_attr_t` 未 `destroy`，且把返回值写进 `errno` | `core/utils.cpp` |
| D-B2 | 资源泄露 | zygiskd / system_server 常驻 handle 增长 | `dlopen` 成功但 `dlsym` 失败时未 `dlclose` | `zygisk/entry.cpp`、`zygisk/module.cpp` |
| D-B3 | 资源泄露 | 高频授权后僵尸进程堆积 | `waitpid()` 被信号打断（EINTR）直接放弃 reap | `core/su/daemon.rs` |
| D-B4 | 资源泄露 | 冻结/慢应用启动后 helper 常驻 | logcat namespace 等待无上限，10ms 忙等 | `core/deny/logcat.cpp` |
| D-B5 | 授权路径 | 「部分授权」：请求挂起或被误判为已授权 | fork 失败直接 return，不回包 | `core/su/daemon.rs` |
| D-B6 | 资源泄露 | 无效模块请求残留 fd | 非法 `module_id` 分支未 `close(client)` | `zygisk/entry.cpp` |
| D-C1 | 高占用 | 请求串行、慢任务卡住全部 su/zygisk 请求 | 线程池单 `Option<task>` 槽，提交者需等待旧任务被消费 | `core/thread.rs` |
| D-C2 | 高占用 | 突发请求下线程无上限增长，调度抖动 | 池无 `MAX_POOL_SIZE` 上限 | `core/thread.rs` |
| D-E1 | Zygisk | zygiskd 偶发误退出 / 空转 | 忽略 `poll()` 返回值、不重置 `revents`、不处理 EINTR | `zygisk/entry.cpp` |
| D-E2 | Zygisk | 每次杂散信号都杀掉并重 fork zygiskd | `poll() == -1`（EINTR）被当成 socket 死亡 | `zygisk/daemon.rs` |
| D-D1 | 隐藏 | DenyList 清理后仍有可见挂载痕迹 | `revert_unmount()` 只匹配 `source=="magisk"` 与 `/adb/modules` | `core/mount.rs` |

---

## 3. 「有概率掉 root」的三条真实链路

### D-A1 accept 错误杀掉整个 daemon（最典型）

上游写法：

```rust
for client in sock.incoming() {
    if let Ok(client) = client.log() {
        daemon.handle_requests(client);
    } else {
        exit(1);          // ← 任何 accept 错误都终止 magiskd
    }
}
```

`accept()` 在 **fd 表满（EMFILE/ENFILE）**、**信号打断（EINTR）**、**客户端连接中途放弃
（ECONNABORTED）** 时都会返回错误，这些全是瞬时、可恢复状态。但上游一律 `exit(1)`，
daemon 从此消失；之后所有 `su` 与模块请求都连不上 socket，直到重启 —— 这正是社区里
「用着用着 root 就没了，重启又好了」的典型表现，且因为触发依赖瞬时资源压力，
表现为「有概率」。

修复：按 `raw_os_error()` 分类 —— `EMFILE/ENFILE` 退避 50ms（避免在 fd 满时 100% CPU
空转）、`EINTR/ECONNABORTED/EAGAIN` 直接重试、只有 `EBADF/EINVAL`（监听 socket 本身坏了）
才 `exit(1)`，其它未知错误告警并短暂退避后继续。

### D-A2 `su` 永久挂起

`connect_daemon()` fork 出 daemon 后，客户端用无限 `loop { connect; sleep(100ms) }` 等待。
一旦 daemon 因 init 竞态、fork 失败等原因没起来，`su` 会永远卡在这里，既不报错也不退出。
修复：加 **5 秒 deadline**，超时返回 `log_err!("Cannot connect to daemon: startup timed out")`，
让调用方能明确失败而不是挂死。

### D-A3 DenyList `end()` 解引用

```cpp
if (pkg_to_procs.find(pkg)->second.count(process))   // ← end() 被解引用
```

`app_id_to_pkgs` 里的 `string_view` 键指向 `pkg_to_procs`；一旦两侧因
`scan_deny_apps()` 重建而不同步，`find()` 返回 `end()`，解引用即 UB / magiskd 崩溃。
它发生在 **每次 zygote specialization**，所以表现为随机、难以复现的 root 丢失。
修复：`auto hit = ...; if (hit != end() && hit->second.count(process))`。

---

## 4. 「部分授权 / 内存泄露」类

- **D-B5（授权回包）**：`fork()` 在资源紧张时返回 `-1`，上游只 `error!` 后 `return`。
  客户端 `su_client_main()` 会在 `read_int(fd)` 上阻塞，或从关闭的 socket 读到 `0` 而
  **把请求误判为已授权**。这就是「部分授权」最危险的形态：既可能挂起，也可能给出错误结论。
  修复：失败时显式 `client.write_pod(&SuPolicy::Deny.repr)`，与文件内既有的拒绝路径保持一致。
- **D-B3（僵尸进程）**：`waitpid()` 被信号打断返回 `-1/EINTR` 时，上游直接 `break -1`，
  root 子进程永远不被 reap，形成进程表泄露。修复：循环重试直到非 EINTR。
- **D-B2（dlopen handle）**：zygisk companion 与 Zygisk 模块都出现过「`dlopen` 成功、
  `dlsym` 找不到入口符号」时把 handle 留在全局表里。修复：`dlclose(h)`；模块侧同时
  `fds[i] = -1`，让 system_server 正常创建 unloaded marker，而不是静默忽略坏模块。
- **D-B1（pthread attr）**：`pthread_create()` **返回错误码而不是设置 `errno`**，上游却
  `errno = pthread_create(...)`，既污染了真实 errno，又漏掉 `pthread_attr_destroy()`。
  修复：用局部 `int rc` 接返回值、配对 init/destroy、仅在失败时设置 errno 供 `PLOGE` 使用。
- **D-B4 / D-B6（进程与 fd 残留）**：logcat fallback 的 namespace 等待是无限 10ms 轮询，
  遇到冻结应用会永久留下一个 helper 进程并持续占 CPU；zygiskd 收到非法 `module_id` 时
  没有 `close(client)`。修复：轮询上限 `MAX_NS_POLLS = 300`（约 3 秒）后 `_exit(0)`；
  无效路径显式 close（有效路径的 fd 仍由 companion handler 负责，避免重复关闭）。

---

## 5. 线程逻辑与高占用

上游 `ThreadPool` 用一个 `Option<task>` 槽 + 两个 Condvar（`task_is_some` / `task_is_none`），
**提交者必须等旧任务被消费才能入队**。而 `handle_requests()` 在 accept 循环里调用
`exec_task()`，于是一个慢任务会把**所有请求准入**都卡住；同时池无上限扩线程，突发请求下
每个 detached 线程都要预留完整栈，带来内存压力与调度抖动。

修复（`core/thread.rs`）：

- 单槽改 `VecDeque<Box<dyn FnOnce() + Send>>` FIFO 队列，提交者 `push_back` 后立即返回；
- 两个 Condvar 合并为单个 `task_ready`；
- 新增 `MAX_POOL_SIZE = 16`，超过上限的任务排队而不是继续开线程；
- 保留 3 个 core 线程与 60 秒 idle timeout，worker 在超时且队列为空时才退出。

`deny/logcat.cpp` 的 3 秒上限、accept 的 EMFILE 退避、`zygisk/entry.cpp` 的 `poll` 处理
也一并消除了几处「忙等吃满一个核」的路径。

---

## 6. 隐藏能力增强

`revert_unmount()` 原先只收集 `source == "magisk"` 或 `root` 在 `/adb/modules` 下的挂载。
模块从 worker / preinit tmpfs 等其它 root 绑定挂载到系统路径时，DenyList 清理后会留下
可见的 mount 痕迹。

修复（`core/mount.rs`）：额外收集 **target 或 source 位于私有 tmpfs 子树
`<tmp>/.magisk/`** 的挂载。用完整路径前缀（含 `/` 边界）+ `target == private_dir` 判断，
而不是裸的 `.magisk` 子串匹配，避免误卸载无关系统挂载。这是本轮唯一直接扩大隐藏覆盖面
的改动，且严格限定在 Magisk 私有目录范围内。

**Zygisk 侧的健壮性**（D-E1 / D-E2）保证隐藏链路本身不会因为 `poll()` 的 EINTR 或
stale `revents` 而误退出 zygiskd，属于「让已存在的 Zygisk/DenyList 能力稳定生效」。

---

## 7. 明确没做的事（边界）

- **没有改 MagiskSU 的权限模型**：授权策略、多用户模式、UID 判定、签名信任链全部保持上游语义；
  本轮只修复「失败时没有正确回包 / 没有正确 reap」这类生命周期缺陷。
- **没有加入针对具体应用检测逻辑的绕过代码**：不含任何特征串、黑名单、指纹对抗逻辑。
  隐藏增强仅扩大 Magisk **自身挂载** 的清理范围。
- **没有引入新的 root 能力或新的对外接口**：所有改动都是对既有路径的健壮性 / 资源修复。
- **没有真机 / AVD 运行验证**：本地无 Android SDK / ONDK，完整编译由 GitHub Actions 证明；
  静态守卫 + rustfmt 语法解析只证明「代码结构正确、能被解析」，不等于运行时正确。

---

## 8. 验证方式

| 层次 | 手段 | 结论 |
| --- | --- | --- |
| 语法 | `rustfmt --edition 2024 --emit stdout` 解析 5 个改动的 `.rs` | 全部可解析 |
| 修复防回滚 | `next/native_audit.py`：12 条规则 / 60 项断言，逐条扰动自测 | 12/12 通过 |
| 仓库一致性 | `next/verify_repo.py`：10 项（新增 native guards） | 10/10 通过 |
| 单元测试 | `python3 -m unittest discover -s tests -v` | 25/25 通过 |
| 一键套件 | `bash scripts/verify-next.sh` | ALL CHECKS PASSED |
| 真实编译 | GitHub Actions `build-next.yml` 完整构建 | 推送后验证（见 CHANGELOG） |

`verify-next.sh` 里新增的 Rust 语法解析段会先探测 rustfmt 是否支持 edition 2024，
不支持时自动 SKIP（完整编译仍由 `build-next.yml` 兜底），不会让 CI 因工具链版本误失败。

---

## 9. 还能加什么（native 方向）

| 优先级 | 功能 | 说明 |
| --- | --- | --- |
| P0 | 真机 / AVD 冒烟脚本 | 用 CTS 风格的 `su -c` + DenyList + Zygisk 模块组合验证掉 root 是否复现 |
| P0 | daemon 健康指标 | 统计 accept 错误分类次数、线程池队列长度、峰值线程数，暴露给体检报告 |
| P1 | Zygisk 模块 watchdog | companion 超时 / 崩溃后按 backoff 重启，避免单个坏模块拖死 zygiskd |
| P1 | fd 泄露计数器 | 在 zygiskd / su 路径上记录 fd 分配与释放，超阈值告警 |
| P1 | su 请求超时 | 给授权等待（用户点按）加可配置上限，避免 UI 卡死时请求永久占用 |
| P1 | DenyList 规则热更新 | 不走全量 `scan_deny_apps()` 重建，减少两侧不同步窗口（D-A3 的进一步收敛） |
| P2 | zygiskd crash backoff | 连续崩溃时指数退避，避免 fork 风暴 |
| P2 | 模块兼容性矩阵 | 在主机侧声明模块要求的 Zygisk API 版本，装前拦截 |
| P2 | boot A/B 槽位回滚辅助 | 与主机侧 snapshot 工具联动 |

主机侧 / 设备侧的功能路线图仍见 [ROADMAP.md](ROADMAP.md)。
