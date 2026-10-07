// SPDX-License-Identifier: LGPL-2.1-or-later
// Host-local source installation wrapper; the dependency prefix remains external.
#define _DARWIN_C_SOURCE 1
#include <errno.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <pwd.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#ifndef APP_DEPENDENCY_PREFIX
#error APP_DEPENDENCY_PREFIX must identify the preserved dependency environment
#endif
#ifndef APP_BINARY_NAME
#define APP_BINARY_NAME "FreeCAD"
#endif

static int fail(const char *what, const char *path) {
    fprintf(stderr, "FreeCAD Local: %s: %s (%s)\n", what, path, strerror(errno));
    return 1;
}

static char *join(const char *left, const char *right) {
    size_t size = strlen(left) + strlen(right) + 2;
    char *value = malloc(size);
    if (value != NULL) snprintf(value, size, "%s/%s", left, right);
    return value;
}

static int directory_exists(const char *path) {
    struct stat st;
    return stat(path, &st) == 0 && S_ISDIR(st.st_mode);
}

static int mkdir_parents(const char *path) {
    char *copy = strdup(path);
    if (copy == NULL) return -1;
    for (char *p = copy + 1; ; ++p) {
        if (*p != '/' && *p != '\0') continue;
        char saved = *p;
        *p = '\0';
        if (mkdir(copy, 0700) != 0 && errno != EEXIST) {
            free(copy);
            return -1;
        }
        if (!directory_exists(copy)) {
            free(copy);
            errno = ENOTDIR;
            return -1;
        }
        *p = saved;
        if (saved == '\0') break;
    }
    free(copy);
    return 0;
}

static int set_joined(const char *name, const char *prefix, const char *suffix) {
    char *value = join(prefix, suffix);
    if (value == NULL) return -1;
    int rc = setenv(name, value, 1);
    free(value);
    return rc;
}

static int prepend_paths(const char *name, const char *first, const char *second) {
    const char *old = getenv(name);
    size_t size = strlen(first) + strlen(second) + (old ? strlen(old) : 0) + 3;
    char *value = malloc(size);
    if (value == NULL) return -1;
    snprintf(value, size, "%s:%s%s%s", first, second, old && *old ? ":" : "", old ? old : "");
    int rc = setenv(name, value, 1);
    free(value);
    return rc;
}

static int set_plugin_paths(const char *overlay, const char *baseline) {
    size_t size = strlen(overlay) + strlen(baseline) + 2;
    char *value = malloc(size);
    if (value == NULL) return -1;
    snprintf(value, size, "%s:%s", overlay, baseline);
    int rc = setenv("QT_PLUGIN_PATH", value, 1);
    free(value);
    return rc;
}

static int set_default_directory(const char *name, const char *base, const char *suffix) {
    const char *existing = getenv(name);
    if (existing != NULL && *existing != '\0') return mkdir_parents(existing);
    char *path = join(base, suffix);
    if (path == NULL) return -1;
    int rc = mkdir_parents(path);
    if (rc == 0) rc = setenv(name, path, 1);
    free(path);
    return rc;
}

int main(int argc, char **argv) {
    uint32_t length = 0;
    (void)_NSGetExecutablePath(NULL, &length);
    char *raw_path = malloc(length);
    if (raw_path == NULL) return fail("cannot allocate executable path", "launcher");
    if (_NSGetExecutablePath(raw_path, &length) != 0) {
        free(raw_path);
        return fail("cannot resolve executable path", "launcher");
    }
    char *executable_path = realpath(raw_path, NULL);
    free(raw_path);
    if (executable_path == NULL) return fail("cannot resolve executable path", "launcher");
    char *slash = strrchr(executable_path, '/');
    if (slash == NULL) {
        free(executable_path);
        errno = EINVAL;
        return fail("invalid executable path", "launcher");
    }
    *slash = '\0';
    char *resources_relative = join(executable_path, "../Resources");
    free(executable_path);
    if (resources_relative == NULL) return fail("cannot allocate resources path", "launcher");
    char *resources = realpath(resources_relative, NULL);
    free(resources_relative);
    if (resources == NULL) return fail("cannot resolve application resources", "Resources");

    const char *dependency = APP_DEPENDENCY_PREFIX;
    if (!directory_exists(dependency)) {
        errno = ENOENT;
        return fail("required dependency environment is unavailable", dependency);
    }
    char *app_lib = join(resources, "lib");
    char *dependency_lib = join(dependency, "lib");
    char *app_bin = join(resources, "bin");
    char *dependency_bin = join(dependency, "bin");
    if (!app_lib || !dependency_lib || !app_bin || !dependency_bin) {
        return fail("cannot allocate runtime paths", resources);
    }
    char *overlay = join(resources, "qt-cocoa");
    char *baseline_plugins = join(dependency, "lib/qt6/plugins");
    char *platform_plugins = overlay ? join(overlay, "platforms") : NULL;
    char *cocoa_plugin = platform_plugins ? join(platform_plugins, "libqcocoa.dylib") : NULL;
    struct stat plugin_stat;
    if (!overlay || !baseline_plugins || !platform_plugins || !cocoa_plugin) {
        return fail("cannot allocate plugin paths", resources);
    }
    if (!directory_exists(platform_plugins) || lstat(cocoa_plugin, &plugin_stat) != 0 ||
        !S_ISREG(plugin_stat.st_mode) || access(cocoa_plugin, R_OK) != 0) {
        errno = ENOENT;
        return fail("required app-local Cocoa overlay is unavailable", cocoa_plugin);
    }
    if (prepend_paths("DYLD_LIBRARY_PATH", app_lib, dependency_lib) != 0 ||
        prepend_paths("PATH", app_bin, dependency_bin) != 0 ||
        setenv("PYTHONHOME", dependency, 1) != 0 ||
        set_plugin_paths(overlay, baseline_plugins) != 0 ||
        setenv("QT_QPA_PLATFORM_PLUGIN_PATH", platform_plugins, 1) != 0 ||
        set_joined("QML_IMPORT_PATH", dependency, "lib/qt6/qml") != 0 ||
        set_joined("QML2_IMPORT_PATH", dependency, "lib/qt6/qml") != 0 ||
        set_joined("SSL_CERT_FILE", dependency, "ssl/cacert.pem") != 0 ||
        set_joined("GIT_SSL_CAINFO", dependency, "ssl/cacert.pem") != 0) {
        return fail("cannot configure runtime environment", resources);
    }
    unsetenv("PYTHONPATH");
    unsetenv("VIRTUAL_ENV");

    const char *home = getenv("HOME");
    if (home == NULL || *home == '\0') {
        struct passwd *account = getpwuid(getuid());
        home = account ? account->pw_dir : NULL;
    }
    if (home == NULL || *home == '\0') {
        errno = ENOENT;
        return fail("cannot identify user home", "HOME");
    }
    char *profile = join(home, "Library/Application Support/FreeCAD Local");
    if (profile == NULL) return fail("cannot allocate user profile path", home);
    if (set_default_directory("FREECAD_USER_HOME", profile, "config") != 0 ||
        set_default_directory("FREECAD_USER_DATA", profile, "data") != 0 ||
        set_default_directory("FREECAD_USER_TEMP", profile, "temp") != 0) {
        return fail("cannot configure local user profile", profile);
    }

    char *target = join(app_bin, APP_BINARY_NAME);
    if (target == NULL) return fail("cannot allocate FreeCAD executable path", app_bin);
    if (access(target, X_OK) != 0) return fail("installed executable is unavailable", target);
    char **child_argv = calloc((size_t)argc + 1, sizeof(*child_argv));
    if (child_argv == NULL) return fail("cannot allocate process arguments", target);
    child_argv[0] = target;
    for (int index = 1; index < argc; ++index) child_argv[index] = argv[index];
    execv(target, child_argv);
    return fail("cannot start installed FreeCAD", target);
}
