#include <sys/mount.h>
#include <android/dlext.h>
#include <dlfcn.h>
#include <poll.h>
#include <cerrno>

#include <base.hpp>
#include <core.hpp>

#include "zygisk.hpp"

using namespace std;

using comp_entry = void(*)(int);
extern "C" void exec_companion_entry(int, comp_entry);

static void zygiskd(int socket) {
    if (getuid() != 0 || fcntl(socket, F_GETFD) < 0)
        exit(-1);

#if defined(__LP64__)
    set_nice_name("zygiskd64");
    LOGI("* Launching zygiskd64\n");
#else
    set_nice_name("zygiskd32");
    LOGI("* Launching zygiskd32\n");
#endif

    // Load modules
    vector<comp_entry> modules;
    {
        auto module_fds = recv_fds(socket);
        for (int fd : module_fds) {
            comp_entry entry = nullptr;
            struct stat s{};
            if (fstat(fd, &s) == 0 && S_ISREG(s.st_mode)) {
                android_dlextinfo info {
                    .flags = ANDROID_DLEXT_USE_LIBRARY_FD,
                    .library_fd = fd,
                };
                if (void *h = android_dlopen_ext("/jit-cache", RTLD_LAZY, &info)) {
                    *(void **) &entry = dlsym(h, "zygisk_companion_entry");
                    if (entry == nullptr) {
                        // magisk-Next: a module without a companion entry still
                        // holds a dlopen handle. Release it instead of leaking one
                        // handle per module for the whole life of zygiskd.
                        dlclose(h);
                    }
                } else {
                    LOGW("Failed to dlopen zygisk module: %s\n", dlerror());
                }
            }
            modules.push_back(entry);
            close(fd);
        }
    }

    // ack
    write_int(socket, 0);

    // Start accepting requests
    for (;;) {
        // magisk-Next: upstream ignored poll()'s return value and never reset
        // revents. On EINTR (a signal) poll returns -1 with revents untouched,
        // so a stale POLLIN from a previous iteration could make zygiskd call
        // recv_fd() on a socket with nothing pending, or miss a real hangup.
        // Rebuild the pollfd every iteration and handle the return code.
        pollfd pfd = { socket, POLLIN, 0 };
        int rc;
        do {
            rc = poll(&pfd, 1, -1);
        } while (rc < 0 && errno == EINTR);
        if (rc < 0) {
            // Something bad happened in magiskd, terminate zygiskd
            exit(0);
        }
        if (pfd.revents & (POLLERR | POLLHUP | POLLNVAL)) {
            // magiskd went away, terminate zygiskd
            exit(0);
        }
        if (!(pfd.revents & POLLIN)) {
            continue;
        }
        int client = recv_fd(socket);
        if (client < 0) {
            // Something bad happened in magiskd, terminate zygiskd
            exit(0);
        }
        int module_id = read_int(client);
        if (module_id >= 0 && static_cast<size_t>(module_id) < modules.size() &&
            modules[module_id]) {
            exec_companion_entry(client, modules[module_id]);
        } else {
            // magisk-Next: always close the accepted fd on the invalid path.
            // The companion handler owns it on the valid path (see mod.rs).
            close(client);
        }
    }
}

// Entrypoint where we need to re-exec ourselves
// This should only ever be called internally
int zygisk_main(int argc, char *argv[]) {
    android_logging();
    if (argc == 3 && argv[1] == "companion"sv) {
        zygiskd(parse_int(argv[2]));
    }
    return 0;
}

// Entrypoint of code injection
extern "C" [[maybe_unused]] NativeBridgeCallbacks NativeBridgeItf {
    .version = 2,
    .padding = {},
    .isCompatibleWith = [](auto) {
        zygisk_logging();
        hook_entry();
        ZLOGD("load success\n");
        return false;
    },
};
