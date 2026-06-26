// SPDX-License-Identifier: MIT
#include "flight_backend.h"

#include <Windows.h>
#include <Xinput.h>

namespace {

HMODULE g_real_xinput = nullptr;
HMODULE g_self = nullptr;
INIT_ONCE g_init_once = INIT_ONCE_STATIC_INIT;
HANDLE g_bootstrap_thread = nullptr;

using XInputGetStateFn = DWORD(WINAPI*)(DWORD, XINPUT_STATE*) WIN_NOEXCEPT;
using XInputSetStateFn = DWORD(WINAPI*)(DWORD, XINPUT_VIBRATION*) WIN_NOEXCEPT;
using XInputGetCapabilitiesFn = DWORD(WINAPI*)(DWORD, DWORD, XINPUT_CAPABILITIES*) WIN_NOEXCEPT;
using XInputEnableFn = void(WINAPI*)(BOOL) WIN_NOEXCEPT;
using XInputGetDSoundAudioDeviceGuidsFn = DWORD(WINAPI*)(DWORD, GUID*, GUID*);
using XInputGetBatteryInformationFn = DWORD(WINAPI*)(DWORD, BYTE, XINPUT_BATTERY_INFORMATION*) WIN_NOEXCEPT;
using XInputGetKeystrokeFn = DWORD(WINAPI*)(DWORD, DWORD, PXINPUT_KEYSTROKE) WIN_NOEXCEPT;

XInputGetStateFn RealXInputGetState = nullptr;
XInputSetStateFn RealXInputSetState = nullptr;
XInputGetCapabilitiesFn RealXInputGetCapabilities = nullptr;
XInputEnableFn RealXInputEnable = nullptr;
XInputGetDSoundAudioDeviceGuidsFn RealXInputGetDSoundAudioDeviceGuids = nullptr;
XInputGetBatteryInformationFn RealXInputGetBatteryInformation = nullptr;
XInputGetKeystrokeFn RealXInputGetKeystroke = nullptr;

template <typename T>
void Resolve(T& out, const char* name) {
    out = reinterpret_cast<T>(GetProcAddress(g_real_xinput, name));
}

bool LoadRealXInput() {
    if (g_real_xinput) {
        return true;
    }

    wchar_t system_dir[MAX_PATH] = {};
    if (!GetSystemDirectoryW(system_dir, MAX_PATH)) {
        return false;
    }

    wchar_t path[MAX_PATH] = {};
    lstrcpynW(path, system_dir, MAX_PATH);
    lstrcatW(path, L"\\xinput1_3.dll");

    g_real_xinput = LoadLibraryW(path);
    if (!g_real_xinput) {
        return false;
    }

    Resolve(RealXInputGetState, "XInputGetState");
    Resolve(RealXInputSetState, "XInputSetState");
    Resolve(RealXInputGetCapabilities, "XInputGetCapabilities");
    Resolve(RealXInputEnable, "XInputEnable");
    Resolve(RealXInputGetDSoundAudioDeviceGuids, "XInputGetDSoundAudioDeviceGuids");
    Resolve(RealXInputGetBatteryInformation, "XInputGetBatteryInformation");
    Resolve(RealXInputGetKeystroke, "XInputGetKeystroke");
    return true;
}

BOOL CALLBACK InitializeOnce(PINIT_ONCE, PVOID, PVOID*) {
    LoadRealXInput();
    smtvv_flight::Initialize(g_self);
    return TRUE;
}

void EnsureInitialized() {
    InitOnceExecuteOnce(&g_init_once, InitializeOnce, nullptr, nullptr);
}

DWORD WINAPI BootstrapThread(LPVOID) {
    Sleep(1000);
    EnsureInitialized();
    return 0;
}

}  // namespace

extern "C" DWORD WINAPI XInputGetState(DWORD dwUserIndex, XINPUT_STATE* pState) WIN_NOEXCEPT {
    EnsureInitialized();
    if (!LoadRealXInput() || !RealXInputGetState) {
        return ERROR_DEVICE_NOT_CONNECTED;
    }

    const DWORD result = RealXInputGetState(dwUserIndex, pState);
    smtvv_flight::OnXInputPoll(dwUserIndex, result);
    if (result == ERROR_SUCCESS && pState) {
        smtvv_flight::OnXInputState(dwUserIndex, *pState);
    }
    return result;
}

extern "C" BOOL WINAPI XInputDllMain(HINSTANCE instance, DWORD reason, LPVOID reserved) {
    (void)instance;
    (void)reason;
    (void)reserved;
    return TRUE;
}

extern "C" DWORD WINAPI XInputSetState(DWORD dwUserIndex, XINPUT_VIBRATION* pVibration) WIN_NOEXCEPT {
    EnsureInitialized();
    if (!LoadRealXInput() || !RealXInputSetState) {
        return ERROR_DEVICE_NOT_CONNECTED;
    }
    return RealXInputSetState(dwUserIndex, pVibration);
}

extern "C" DWORD WINAPI XInputGetCapabilities(
    DWORD dwUserIndex,
    DWORD dwFlags,
    XINPUT_CAPABILITIES* pCapabilities) WIN_NOEXCEPT {
    EnsureInitialized();
    if (!LoadRealXInput() || !RealXInputGetCapabilities) {
        return ERROR_DEVICE_NOT_CONNECTED;
    }
    return RealXInputGetCapabilities(dwUserIndex, dwFlags, pCapabilities);
}

extern "C" void WINAPI XInputEnable(BOOL enable) WIN_NOEXCEPT {
    EnsureInitialized();
    if (LoadRealXInput() && RealXInputEnable) {
        RealXInputEnable(enable);
    }
}

extern "C" DWORD WINAPI XInputGetDSoundAudioDeviceGuids(
    DWORD dwUserIndex,
    GUID* pDSoundRenderGuid,
    GUID* pDSoundCaptureGuid) {
    EnsureInitialized();
    if (!LoadRealXInput() || !RealXInputGetDSoundAudioDeviceGuids) {
        return ERROR_DEVICE_NOT_CONNECTED;
    }
    return RealXInputGetDSoundAudioDeviceGuids(
        dwUserIndex, pDSoundRenderGuid, pDSoundCaptureGuid);
}

extern "C" DWORD WINAPI XInputGetBatteryInformation(
    DWORD dwUserIndex,
    BYTE devType,
    XINPUT_BATTERY_INFORMATION* pBatteryInformation) WIN_NOEXCEPT {
    EnsureInitialized();
    if (!LoadRealXInput() || !RealXInputGetBatteryInformation) {
        return ERROR_DEVICE_NOT_CONNECTED;
    }
    return RealXInputGetBatteryInformation(dwUserIndex, devType, pBatteryInformation);
}

extern "C" DWORD WINAPI XInputGetKeystroke(
    DWORD dwUserIndex,
    DWORD dwReserved,
    PXINPUT_KEYSTROKE pKeystroke) WIN_NOEXCEPT {
    EnsureInitialized();
    if (!LoadRealXInput() || !RealXInputGetKeystroke) {
        return ERROR_EMPTY;
    }
    return RealXInputGetKeystroke(dwUserIndex, dwReserved, pKeystroke);
}

BOOL APIENTRY DllMain(HMODULE module, DWORD reason, LPVOID reserved) {
    (void)reserved;

    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(module);
        g_self = module;
        g_bootstrap_thread = CreateThread(nullptr, 0, BootstrapThread, nullptr, 0, nullptr);
        if (g_bootstrap_thread) {
            CloseHandle(g_bootstrap_thread);
            g_bootstrap_thread = nullptr;
        }
    } else if (reason == DLL_PROCESS_DETACH) {
        smtvv_flight::Shutdown();
        if (g_real_xinput) {
            FreeLibrary(g_real_xinput);
            g_real_xinput = nullptr;
        }
    }

    return TRUE;
}
