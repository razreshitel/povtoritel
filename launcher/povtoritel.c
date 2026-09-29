#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>
#include <wchar.h>

#include "pyconf.h"

typedef int (*py_main_fn)(int, wchar_t **);

/* load dll from home */
static HMODULE load_from(const wchar_t *home)
{
    wchar_t path[MAX_PATH * 2];
    size_t n = wcslen(home);
    if (!n || n > MAX_PATH)
        return NULL;
    swprintf(path, MAX_PATH * 2, L"%s%s%s", home,
             home[n - 1] == L'\\' ? L"" : L"\\", PY_DLL);
    return LoadLibraryExW(path, NULL, LOAD_WITH_ALTERED_SEARCH_PATH);
}

static HMODULE load_python(void)
{
    HKEY roots[2] = {HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE};
    wchar_t home[MAX_PATH + 1];
    HMODULE h;
    for (int i = 0; i < 2; i++) {
        DWORD size = sizeof(home);
        if (RegGetValueW(roots[i],
                         L"Software\\Python\\PythonCore\\" PY_VER L"\\InstallPath",
                         NULL, RRF_RT_REG_SZ, NULL, home, &size) == ERROR_SUCCESS
            && (h = load_from(home)) != NULL)
            return h;
    }
    if ((h = load_from(PY_HOME)) != NULL)
        return h;
    return LoadLibraryW(PY_DLL);
}

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE prev, PWSTR cmd, int show)
{
    wchar_t exe[MAX_PATH], script[MAX_PATH];
    int argc = 0;
    wchar_t **argv, **args;
    HMODULE py;
    py_main_fn py_main;
    wchar_t *slash;

    (void)inst; (void)prev; (void)cmd; (void)show;
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOOPENFILEERRORBOX);
    if (!GetModuleFileNameW(NULL, exe, MAX_PATH))
        return 1;
    wcscpy_s(script, MAX_PATH, exe);
    slash = wcsrchr(script, L'\\');
    if (!slash)
        return 1;
    wcscpy_s(slash + 1, MAX_PATH - (slash + 1 - script), L"povtoritel.pyw");

    py = load_python();
    py_main = py ? (py_main_fn)GetProcAddress(py, "Py_Main") : NULL;
    if (!py_main) {
        MessageBoxW(NULL,
                    L"Python " PY_VER L" was not found.\n\n"
                    L"Install it, or rebuild the launcher with launcher\\build.ps1.",
                    L"Povtoritel", MB_ICONERROR);
        return 1;
    }

    argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    args = (wchar_t **)HeapAlloc(GetProcessHeap(), 0,
                                 sizeof(wchar_t *) * (size_t)(argc + 2));
    if (!argv || !args)
        return 1;
    args[0] = exe;
    args[1] = script;
    for (int i = 1; i < argc; i++)
        args[i + 1] = argv[i];
    args[argc + 1] = NULL;
    return py_main(argc + 1, args);
}
