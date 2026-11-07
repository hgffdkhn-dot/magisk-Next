use crate::new_daemon_thread;
use base::ResultExt;
use nix::sys::signal::SigSet;
use nix::unistd::{getpid, gettid};
use std::collections::VecDeque;
use std::sync::LazyLock;
use std::sync::nonpoison::{Condvar, Mutex};
use std::time::Duration;

static THREAD_POOL: LazyLock<ThreadPool> = LazyLock::new(ThreadPool::default);

const THREAD_IDLE_MAX_SEC: u64 = 60;
const CORE_POOL_SIZE: i32 = 3;
// magisk-Next: upstream grows the pool without any ceiling. A burst of su /
// zygisk requests (or a slow root child) can create detached threads without
// bound, each reserving a full stack -> memory pressure and scheduler churn.
// Cap the pool; excess tasks queue instead of spawning more threads.
const MAX_POOL_SIZE: i32 = 16;

#[derive(Default)]
pub struct ThreadPool {
    task_ready: Condvar,
    info: Mutex<PoolInfo>,
}

#[derive(Default)]
struct PoolInfo {
    idle_threads: i32,
    total_threads: i32,
    // magisk-Next: upstream kept a single `Option<task>` slot and made every
    // submitter wait until it was consumed. Because handle_requests() calls
    // exec_task() from the accept loop, one slow task stalled ALL request
    // admission. A FIFO queue lets submitters enqueue and return immediately.
    tasks: VecDeque<Box<dyn FnOnce() + Send>>,
}

impl ThreadPool {
    fn pool_loop(&self, is_core_pool: bool) {
        let mask = SigSet::all();

        loop {
            // Always restore the sigmask to block all signals
            mask.thread_set_mask().log_ok();

            let task: Option<Box<dyn FnOnce() + Send>>;
            {
                let mut info = self.info.lock();
                info.idle_threads += 1;
                loop {
                    if let Some(t) = info.tasks.pop_front() {
                        task = Some(t);
                        info.idle_threads -= 1;
                        break;
                    }
                    if is_core_pool {
                        // Core pool never closes, wait forever.
                        self.task_ready.wait(&mut info);
                    } else {
                        let dur = Duration::from_secs(THREAD_IDLE_MAX_SEC);
                        if self.task_ready.wait_timeout(&mut info, dur).timed_out()
                            && info.tasks.is_empty()
                        {
                            // Terminate thread after timeout
                            info.idle_threads -= 1;
                            info.total_threads -= 1;
                            return;
                        }
                    }
                }
            }
            if let Some(task) = task {
                task();
            }
            if getpid() == gettid() {
                // This meant the current thread forked and became the main thread, exit
                std::process::exit(0);
            }
        }
    }

    fn exec_task_impl(&self, f: impl FnOnce() + Send + 'static) {
        extern "C" fn pool_loop_raw(arg: usize) -> usize {
            let is_core_pool = arg != 0;
            THREAD_POOL.pool_loop(is_core_pool);
            0
        }

        let mut info = self.info.lock();
        info.tasks.push_back(Box::new(f));
        if info.idle_threads == 0 && info.total_threads < MAX_POOL_SIZE {
            info.total_threads += 1;
            let is_core_thread = if info.total_threads <= CORE_POOL_SIZE {
                1_usize
            } else {
                0_usize
            };
            unsafe {
                new_daemon_thread(pool_loop_raw, is_core_thread);
            }
        }
        // Wake an idle worker (if we just spawned one it will pick the task up
        // from the queue itself; the extra notify is harmless).
        self.task_ready.notify_one();
    }

    pub fn exec_task(f: impl FnOnce() + Send + 'static) {
        THREAD_POOL.exec_task_impl(f);
    }
}
