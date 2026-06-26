// SPDX-License-Identifier: MIT
#include "flight_backend.h"

#include <Windows.h>
#include <Xinput.h>
#include <share.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cmath>
#include <mutex>
#include <thread>

// =============================================================================
// SMTVV Flight backend
//
// Capture: inline-detour the four pre-decrypted "#2" PlayerMovementComponent
// exec thunks (verified vs SMT5V-Win64-Shipping.exe). At entry rcx = the live
// component. (The old registration-array overwrite was a dead end -- UE reads
// that array only once at startup. See RESEARCH_NOTES.md / verify_addresses.py.)
//
// Input: we poll the real XInput device ourselves from the worker thread, so
// controller B works even when the game doesn't route input through our proxy.
// SPACE works as a keyboard equivalent.
//
// Flight: velocityJump boosted at jump-init; gravityJump reversed while airborne
// + held to ascend (normalized to a negative baseline otherwise); a table of
// horizontal/turn fields latched (boosted) for the airborne window and restored
// on landing. Field offsets were extracted from the reflection table by
// extract_movement_fields.py.
// =============================================================================

namespace smtvv_flight {
namespace {

// ---- runtime state ----------------------------------------------------------
std::atomic<bool> g_running{false};
std::atomic<bool> g_flight_enabled{true};
std::atomic<bool> g_self_pad_b{false};   // our own controller poll
std::atomic<bool> g_game_pad_b{false};   // from the game's XInput calls (if any)
std::atomic<bool> g_jump_held{false};    // combined: pad B or SPACE
std::atomic<bool> g_is_jumping{false};
std::atomic<unsigned long> g_xinput_polls{0};
std::atomic<unsigned long> g_xinput_success{0};
std::atomic<void*> g_player_movement{nullptr};
std::atomic<unsigned long long> g_last_capture_ms{0};
std::thread g_worker;

std::mutex g_log_mutex;
FILE* g_log = nullptr;
char g_log_path[MAX_PATH] = "SMTVVFlight.log";

// ---- image / reflection layout ----------------------------------------------
constexpr uintptr_t kPreferredImageBase = 0x140000000ull;

constexpr uintptr_t kVaCanJump2 = 0x140d104c0ull;
constexpr uintptr_t kVaIsJumping2 = 0x140cb4860ull;
constexpr uintptr_t kVaJump2 = 0x140d10710ull;
constexpr uintptr_t kVaJumpTakeOff2 = 0x140d10740ull;

constexpr ptrdiff_t kOffVelocityMaxFallen = 0x160;  // used by the sanity filter
constexpr ptrdiff_t kOffVelX = 0x1a0;  // live horizontal velocity X (F9 diff: 0 -> -795.8 running)
constexpr ptrdiff_t kOffVelY = 0x1a4;  // live horizontal velocity Y (F9 diff: 0 -> -318.3 running)
constexpr ptrdiff_t kOffGravityJump = 0x244;
constexpr ptrdiff_t kOffVelocityJump = 0x248;

// ---- flight tunables --------------------------------------------------------
constexpr float kTakeoffBoostMul = 1.5f;  // velocityJump * this at jump init
constexpr float kAscendMul = 0.5f;        // ascent strength = |gravity| * this
                                          // (0.5 = gentle hover/glide)
constexpr float kHorizSpeedMul = 18.0f;   // VelocityMax / DashVelocityMax (fast travel)
constexpr float kTurnMul = 6.0f;          // RotationSpeed / InputInterpSpeed
constexpr float kFwdRatioMul = 9.0f;      // ForwardMovementRatio (air-control gate)
constexpr float kAccelMul = 18.0f;        // DashAcceleration (reach speed quickly)

// Direct horizontal-velocity flight control.
constexpr float kFlightSpeed = 3000.0f;   // target horizontal flight speed
constexpr float kFlightAccel = 1.15f;     // per-tick ramp toward kFlightSpeed
constexpr float kFlightMinSpeed = 50.0f;  // don't amplify near-zero (standing jump)

constexpr unsigned long long kCaptureFreshMs = 300;

// Fields boosted (latched) for the whole airborne window, restored on landing.
struct LatchField {
    ptrdiff_t off;
    float mul;
    const char* name;
};
constexpr LatchField kLatchFields[] = {
    {0x154, kHorizSpeedMul, "VelocityMax"},
    {0x158, kHorizSpeedMul, "DashVelocityMax"},
    {0x164, kTurnMul,       "RotationSpeed"},
    {0x168, kTurnMul,       "RotationSpeed_OnSpot"},
    {0x174, kAccelMul,      "DashAcceleration"},
    {0x1a8, kFwdRatioMul,   "ForwardMovementRatio"},
    {0x1bc, kTurnMul,       "InputInterpSpeed"},
};
constexpr size_t kNumLatch = sizeof(kLatchFields) / sizeof(kLatchFields[0]);

// Saved baselines, keyed to the component they were read from.
std::mutex g_flight_mutex;
void* g_saved_for = nullptr;
float g_orig_gravity = 0.0f;
float g_orig_velocity = 0.0f;
float g_orig_latch[kNumLatch] = {};
bool g_last_flight_on = false;

// ---- direct controller polling ----------------------------------------------
using XInputGetStateFn = DWORD(WINAPI*)(DWORD, XINPUT_STATE*);
XInputGetStateFn g_xinput_getstate = nullptr;

// =============================================================================
// Logging
// =============================================================================
void Log(const char* message) {
    std::lock_guard<std::mutex> lock(g_log_mutex);
    if (!g_log) {
        g_log = _fsopen(g_log_path, "a", _SH_DENYNO);
    }
    if (g_log) {
        std::fprintf(g_log, "%s\n", message);
        std::fflush(g_log);
    }
}

// =============================================================================
// SEH-guarded raw memory access (POD-only so __try is legal here).
// =============================================================================
__declspec(noinline) bool SafeRead(const void* src, void* dst, size_t n) {
    __try {
        std::memcpy(dst, src, n);
        return true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
}

__declspec(noinline) bool SafeWrite(void* dst, const void* src, size_t n) {
    __try {
        std::memcpy(dst, src, n);
        return true;
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        return false;
    }
}

float ReadFloat(const void* base, ptrdiff_t offset) {
    float value = 0.0f;
    SafeRead(static_cast<const unsigned char*>(base) + offset, &value, sizeof(value));
    return value;
}

bool WriteFloat(void* base, ptrdiff_t offset, float value) {
    return SafeWrite(static_cast<unsigned char*>(base) + offset, &value, sizeof(value));
}

unsigned long long NowMs() {
    return GetTickCount64();
}

uintptr_t RuntimeAddress(uintptr_t preferred_va) {
    const auto base = reinterpret_cast<uintptr_t>(GetModuleHandleW(nullptr));
    return base + (preferred_va - kPreferredImageBase);
}

// =============================================================================
// Component identification & baseline capture
// =============================================================================
bool LooksLikePlayerMovement(void* context) {
    if (!context) {
        return false;
    }
    const float velocity_jump = ReadFloat(context, kOffVelocityJump);
    const float gravity_jump = ReadFloat(context, kOffGravityJump);
    const float velocity_max_fallen = ReadFloat(context, kOffVelocityMaxFallen);
    return std::isfinite(velocity_jump) &&
           std::isfinite(gravity_jump) &&
           std::isfinite(velocity_max_fallen) &&
           velocity_jump > 100.0f && velocity_jump < 100000.0f &&
           std::fabs(gravity_jump) > 1.0f && std::fabs(gravity_jump) < 100000.0f &&
           velocity_max_fallen > 1.0f && velocity_max_fallen < 100000.0f;
}

// Caller must hold g_flight_mutex.
void EnsureSavedLocked(void* component) {
    if (g_saved_for == component) {
        return;
    }
    g_orig_gravity = ReadFloat(component, kOffGravityJump);
    g_orig_velocity = ReadFloat(component, kOffVelocityJump);
    for (size_t i = 0; i < kNumLatch; ++i) {
        g_orig_latch[i] = ReadFloat(component, kLatchFields[i].off);
    }
    g_saved_for = component;

    char line[256] = {};
    std::snprintf(line, sizeof(line),
        "SMTVVFlight: baseline component=%p gravity=%0.3f velocity=%0.3f "
        "VelocityMax=%0.3f RotationSpeed=%0.3f ForwardMovementRatio=%0.3f InputInterp=%0.3f",
        component, g_orig_gravity, g_orig_velocity,
        g_orig_latch[0], g_orig_latch[2], g_orig_latch[5], g_orig_latch[6]);
    Log(line);
}

void OnCapture(const char* event_name, void* context) {
    if (!LooksLikePlayerMovement(context)) {
        return;
    }
    void* previous = g_player_movement.exchange(context, std::memory_order_release);
    g_last_capture_ms.store(NowMs(), std::memory_order_relaxed);

    {
        std::lock_guard<std::mutex> lk(g_flight_mutex);
        EnsureSavedLocked(context);
    }

    // Log only when a new component instance is captured (not every frame).
    if (previous == context) {
        return;
    }
    char line[200] = {};
    std::snprintf(line, sizeof(line),
        "SMTVVFlight: %s component=%p gravity=%0.3f velocity=%0.3f",
        event_name, context,
        ReadFloat(context, kOffGravityJump), ReadFloat(context, kOffVelocityJump));
    Log(line);
}

void SetJumping(bool jumping) {
    bool prev = g_is_jumping.exchange(jumping, std::memory_order_relaxed);
    if (prev != jumping) {
        Log(jumping ? "SMTVVFlight: airborne (IsJumping=true)"
                    : "SMTVVFlight: grounded (IsJumping=false)");
    }
}

// Apply the take-off velocity boost so THIS jump (about to run) goes higher.
void MaybeBoostTakeoff(void* component) {
    if (!g_flight_enabled.load(std::memory_order_relaxed)) {
        return;
    }
    if (!g_jump_held.load(std::memory_order_relaxed)) {
        return;
    }
    if (!LooksLikePlayerMovement(component)) {
        return;
    }
    std::lock_guard<std::mutex> lk(g_flight_mutex);
    EnsureSavedLocked(component);
    if (g_saved_for != component) {
        return;
    }
    WriteFloat(component, kOffVelocityJump, g_orig_velocity * kTakeoffBoostMul);
}

// =============================================================================
// Inline detours
// =============================================================================
using NativeFn = void (*)(void* context, void* stack, void* result);

NativeFn g_tramp_can_jump = nullptr;
NativeFn g_tramp_is_jumping = nullptr;
NativeFn g_tramp_jump = nullptr;
NativeFn g_tramp_jump_takeoff = nullptr;

void Detour_CanJump(void* ctx, void* stack, void* result) {
    OnCapture("CanJump#2", ctx);
    if (g_tramp_can_jump) {
        g_tramp_can_jump(ctx, stack, result);
    }
}

void Detour_IsJumping(void* ctx, void* stack, void* result) {
    OnCapture("IsJumping#2", ctx);
    if (g_tramp_is_jumping) {
        g_tramp_is_jumping(ctx, stack, result);
    }
    if (result) {
        unsigned char v = 0;
        if (SafeRead(result, &v, sizeof(v))) {
            SetJumping(v != 0);
        }
    }
}

void Detour_Jump(void* ctx, void* stack, void* result) {
    OnCapture("Jump#2", ctx);
    MaybeBoostTakeoff(ctx);  // before the original reads velocityJump
    if (g_tramp_jump) {
        g_tramp_jump(ctx, stack, result);
    }
}

void Detour_JumpTakeOff(void* ctx, void* stack, void* result) {
    OnCapture("JumpTakeOff#2", ctx);
    MaybeBoostTakeoff(ctx);
    if (g_tramp_jump_takeoff) {
        g_tramp_jump_takeoff(ctx, stack, result);
    }
}

// ---- inline hook engine -----------------------------------------------------
constexpr size_t kAbsJmpLen = 14;  // FF 25 00000000 <abs64>

unsigned char* g_tramp_pool = nullptr;
size_t g_tramp_used = 0;
constexpr size_t kTrampPoolSize = 0x1000;

struct HookSpec {
    const char* name;
    uintptr_t va;
    void* detour;
    NativeFn* tramp_out;
    const unsigned char* expected;
    size_t expected_len;
    size_t steal_len;
};

const unsigned char kSigCommon2[16] = {
    0x40, 0x53, 0x48, 0x83, 0xec, 0x20, 0x48, 0x8b,
    0x42, 0x20, 0x45, 0x33, 0xc9, 0x48, 0x85, 0xc0};
const unsigned char kSigJumpTakeOff2[14] = {
    0x48, 0x8b, 0x42, 0x20, 0x45, 0x33, 0xc0, 0x48,
    0x85, 0xc0, 0x41, 0x0f, 0x95, 0xc0};

void WriteAbsJmp(unsigned char* dst, uintptr_t target) {
    dst[0] = 0xFF;
    dst[1] = 0x25;
    dst[2] = 0x00;
    dst[3] = 0x00;
    dst[4] = 0x00;
    dst[5] = 0x00;
    std::memcpy(dst + 6, &target, sizeof(target));
}

bool InstallInlineHook(const HookSpec& spec) {
    auto* target = reinterpret_cast<unsigned char*>(RuntimeAddress(spec.va));

    unsigned char actual[16] = {};
    if (!SafeRead(target, actual, spec.expected_len)) {
        char line[160] = {};
        std::snprintf(line, sizeof(line), "SMTVVFlight: hook %s entry unreadable", spec.name);
        Log(line);
        return false;
    }
    if (std::memcmp(actual, spec.expected, spec.expected_len) != 0) {
        char line[200] = {};
        std::snprintf(line, sizeof(line),
            "SMTVVFlight: hook %s SIGNATURE MISMATCH (game updated?) -- skipped", spec.name);
        Log(line);
        return false;
    }

    if (g_tramp_used + spec.steal_len + kAbsJmpLen > kTrampPoolSize) {
        Log("SMTVVFlight: trampoline pool exhausted");
        return false;
    }

    unsigned char* tramp = g_tramp_pool + g_tramp_used;
    std::memcpy(tramp, target, spec.steal_len);
    WriteAbsJmp(tramp + spec.steal_len,
                reinterpret_cast<uintptr_t>(target) + spec.steal_len);
    g_tramp_used += spec.steal_len + kAbsJmpLen;
    g_tramp_used = (g_tramp_used + 15) & ~static_cast<size_t>(15);
    *spec.tramp_out = reinterpret_cast<NativeFn>(tramp);

    unsigned char patch[16];
    WriteAbsJmp(patch, reinterpret_cast<uintptr_t>(spec.detour));
    for (size_t i = kAbsJmpLen; i < spec.steal_len; ++i) {
        patch[i] = 0x90;
    }

    DWORD old_protect = 0;
    if (!VirtualProtect(target, spec.steal_len, PAGE_EXECUTE_READWRITE, &old_protect)) {
        char line[160] = {};
        std::snprintf(line, sizeof(line), "SMTVVFlight: hook %s VirtualProtect failed", spec.name);
        Log(line);
        return false;
    }
    const bool wrote = SafeWrite(target, patch, spec.steal_len);
    DWORD ignored = 0;
    VirtualProtect(target, spec.steal_len, old_protect, &ignored);
    FlushInstructionCache(GetCurrentProcess(), target, spec.steal_len);

    char line[200] = {};
    std::snprintf(line, sizeof(line),
        "SMTVVFlight: hook %s installed at %p tramp=%p %s",
        spec.name, target, tramp, wrote ? "ok" : "(write failed)");
    Log(line);
    return wrote;
}

void InstallHooks() {
    g_tramp_pool = reinterpret_cast<unsigned char*>(
        VirtualAlloc(nullptr, kTrampPoolSize, MEM_COMMIT | MEM_RESERVE,
                     PAGE_EXECUTE_READWRITE));
    if (!g_tramp_pool) {
        Log("SMTVVFlight: trampoline VirtualAlloc failed -- no hooks installed");
        return;
    }

    const HookSpec specs[] = {
        {"CanJump#2", kVaCanJump2, reinterpret_cast<void*>(&Detour_CanJump),
         &g_tramp_can_jump, kSigCommon2, sizeof(kSigCommon2), 16},
        {"IsJumping#2", kVaIsJumping2, reinterpret_cast<void*>(&Detour_IsJumping),
         &g_tramp_is_jumping, kSigCommon2, sizeof(kSigCommon2), 16},
        {"Jump#2", kVaJump2, reinterpret_cast<void*>(&Detour_Jump),
         &g_tramp_jump, kSigCommon2, sizeof(kSigCommon2), 16},
        {"JumpTakeOff#2", kVaJumpTakeOff2, reinterpret_cast<void*>(&Detour_JumpTakeOff),
         &g_tramp_jump_takeoff, kSigJumpTakeOff2, sizeof(kSigJumpTakeOff2), 14},
    };
    for (const auto& spec : specs) {
        InstallInlineHook(spec);
    }
}

// =============================================================================
// Flight application (worker thread, ~125 Hz)
// =============================================================================
void ApplyFlight() {
    if (!g_flight_enabled.load(std::memory_order_relaxed)) {
        return;
    }
    void* component = g_player_movement.load(std::memory_order_acquire);
    if (!component) {
        return;
    }
    if (NowMs() - g_last_capture_ms.load(std::memory_order_relaxed) > kCaptureFreshMs) {
        return;
    }

    std::lock_guard<std::mutex> lk(g_flight_mutex);
    if (g_saved_for != component) {
        return;
    }

    const bool held = g_jump_held.load(std::memory_order_relaxed);
    const bool airborne = g_is_jumping.load(std::memory_order_relaxed);
    const bool flight_on = held && airborne;

    const float baseline_gravity = -std::fabs(g_orig_gravity);
    const float ascend_gravity = std::fabs(g_orig_gravity) * kAscendMul;
    WriteFloat(component, kOffGravityJump, flight_on ? ascend_gravity : baseline_gravity);

    // Speed / turn fields are ground-locomotion params (airborne motion is
    // ballistic), so boost them whenever B is HELD -- this speeds up the run and
    // the fast takeoff momentum carries into the leap. Restored when released.
    for (size_t i = 0; i < kNumLatch; ++i) {
        const float value = held ? g_orig_latch[i] * kLatchFields[i].mul
                                 : g_orig_latch[i];
        WriteFloat(component, kLatchFields[i].off, value);
    }

    // Direct horizontal-velocity flight: ramp the live velocity vector up to a
    // target speed, preserving direction so stick-steering (which rotates the
    // vector) gives fast turns incl. 180s. VelocityMax is boosted above so this
    // isn't clamped. Skip near-zero to avoid flinging on a standing jump. The
    // throttled log is the proof: speed climbing to target = writes are sticking.
    if (flight_on) {
        // Boost the horizontal velocity axis (0x1a0), sign-preserved so turning
        // (incl. 180s) still works. 0x1a4 is vertical velocity -- left untouched.
        const float h = ReadFloat(component, kOffVelX);
        if (std::fabs(h) > kFlightMinSpeed) {
            const float ramped = std::fabs(h) * kFlightAccel;
            const float mag = ramped < kFlightSpeed ? ramped : kFlightSpeed;
            WriteFloat(component, kOffVelX, h < 0.0f ? -mag : mag);
        }
    }

    if (flight_on != g_last_flight_on) {
        // Read the fields back AFTER writing -- proves the write landed and
        // shows real magnitudes (VelocityMax orig vs boosted, etc.).
        char line[224] = {};
        std::snprintf(line, sizeof(line),
            "SMTVVFlight: flight %s gravity=%0.3f VelocityMax=%0.3f "
            "ForwardMovementRatio=%0.3f RotationSpeed=%0.3f",
            flight_on ? "ENGAGED" : "released",
            flight_on ? ascend_gravity : baseline_gravity,
            ReadFloat(component, 0x154), ReadFloat(component, 0x1a8),
            ReadFloat(component, 0x164));
        Log(line);
        g_last_flight_on = flight_on;
    }
}

void RestoreBaselines() {
    std::lock_guard<std::mutex> lk(g_flight_mutex);
    void* component = g_saved_for;
    if (!component) {
        return;
    }
    WriteFloat(component, kOffGravityJump, -std::fabs(g_orig_gravity));
    WriteFloat(component, kOffVelocityJump, g_orig_velocity);
    for (size_t i = 0; i < kNumLatch; ++i) {
        WriteFloat(component, kLatchFields[i].off, g_orig_latch[i]);
    }
}

// Dump the captured component's raw floats so the live velocity vector can be
// located by diffing a standing snapshot vs a running one (F9). Config
// UProperties end ~0x32c; live native physics state should be past that.
void DumpComponentFloats() {
    void* c = g_player_movement.load(std::memory_order_acquire);
    if (!c) {
        Log("SMTVVFlight: F9 dump - no component captured yet");
        return;
    }
    char line[1024];
    for (ptrdiff_t base = 0x140; base < 0x800; base += 0x40) {
        int n = std::snprintf(line, sizeof(line), "SMTVVFlight: +0x%03x:", (unsigned)base);
        for (ptrdiff_t o = base; o < base + 0x40; o += 4) {
            n += std::snprintf(line + n, sizeof(line) - (size_t)n, " %.1f", ReadFloat(c, o));
        }
        Log(line);
    }
}

// =============================================================================
// Controller polling (independent of the game's input path)
// =============================================================================
void LoadSystemXInput() {
    wchar_t dir[MAX_PATH] = {};
    if (!GetSystemDirectoryW(dir, MAX_PATH)) {
        return;
    }
    wchar_t path[MAX_PATH] = {};
    lstrcpynW(path, dir, MAX_PATH);
    lstrcatW(path, L"\\xinput1_3.dll");
    HMODULE mod = LoadLibraryW(path);
    if (mod) {
        g_xinput_getstate =
            reinterpret_cast<XInputGetStateFn>(GetProcAddress(mod, "XInputGetState"));
    }
    Log(g_xinput_getstate ? "SMTVVFlight: system XInput loaded for direct polling"
                          : "SMTVVFlight: system XInput unavailable");
}

// Returns true if B is down on any connected pad; reports diagnostics.
bool PollControllerB() {
    if (!g_xinput_getstate) {
        return false;
    }
    static int s_logged_connected = -1;
    static WORD s_last_buttons = 0xFFFF;
    bool b_down = false;

    for (DWORD i = 0; i < 4; ++i) {
        XINPUT_STATE state = {};
        if (g_xinput_getstate(i, &state) == ERROR_SUCCESS) {
            if (s_logged_connected != static_cast<int>(i)) {
                char line[96] = {};
                std::snprintf(line, sizeof(line), "SMTVVFlight: controller %lu connected", i);
                Log(line);
                s_logged_connected = static_cast<int>(i);
            }
            const WORD b_bit = state.Gamepad.wButtons & XINPUT_GAMEPAD_B;
            if (b_bit != (s_last_buttons & XINPUT_GAMEPAD_B)) {
                Log(b_bit ? "SMTVVFlight: pad B down" : "SMTVVFlight: pad B up");
            }
            s_last_buttons = state.Gamepad.wButtons;
            if (state.Gamepad.wButtons & XINPUT_GAMEPAD_B) {
                b_down = true;
            }
        }
    }
    return b_down;
}

void WorkerMain() {
    Log("SMTVVFlight: worker started");
    LoadSystemXInput();
    InstallHooks();

    bool last_jump = false;
    bool last_enabled = true;
    bool last_f8 = false;
    bool last_f9 = false;

    while (g_running.load(std::memory_order_acquire)) {
        const bool f8 = (GetAsyncKeyState(VK_F8) & 0x8000) != 0;
        if (f8 && !last_f8) {
            g_flight_enabled.store(!g_flight_enabled.load(std::memory_order_relaxed),
                                   std::memory_order_relaxed);
        }
        last_f8 = f8;

        const bool f9 = (GetAsyncKeyState(VK_F9) & 0x8000) != 0;
        if (f9 && !last_f9) {
            Log("SMTVVFlight: --- F9 component float dump ---");
            DumpComponentFloats();
        }
        last_f9 = f9;

        const bool enabled = g_flight_enabled.load(std::memory_order_relaxed);
        if (enabled != last_enabled) {
            Log(enabled ? "SMTVVFlight: feature ENABLED (F8)"
                        : "SMTVVFlight: feature DISABLED (F8)");
            if (!enabled) {
                RestoreBaselines();
            }
            last_enabled = enabled;
        }

        const bool self_b = PollControllerB();
        g_self_pad_b.store(self_b, std::memory_order_relaxed);
        const bool space = (GetAsyncKeyState(VK_SPACE) & 0x8000) != 0;
        const bool held = self_b || g_game_pad_b.load(std::memory_order_relaxed) || space;
        g_jump_held.store(held, std::memory_order_relaxed);

        if (held != last_jump) {
            Log(held ? "SMTVVFlight: jump held" : "SMTVVFlight: jump released");
            last_jump = held;
        }

        ApplyFlight();
        std::this_thread::sleep_for(std::chrono::milliseconds(8));
    }

    RestoreBaselines();
    Log("SMTVVFlight: worker stopped");
}

}  // namespace

// =============================================================================
// Public surface
// =============================================================================
void Initialize(HMODULE module) {
    if (module) {
        wchar_t dll_path[MAX_PATH] = {};
        if (GetModuleFileNameW(module, dll_path, MAX_PATH)) {
            wchar_t* slash = wcsrchr(dll_path, L'\\');
            if (slash) {
                slash[1] = L'\0';
                wchar_t wide_log[MAX_PATH] = {};
                lstrcpynW(wide_log, dll_path, MAX_PATH);
                lstrcatW(wide_log, L"SMTVVFlight.log");
                WideCharToMultiByte(
                    CP_UTF8, 0, wide_log, -1, g_log_path, MAX_PATH, nullptr, nullptr);
            }
        }
    }

    // Truncate the log each launch -- append-across-runs made it unreadable.
    { FILE* truncate = _fsopen(g_log_path, "w", _SH_DENYNO); if (truncate) std::fclose(truncate); }

    bool expected = false;
    if (!g_running.compare_exchange_strong(expected, true)) {
        return;
    }

    Log("SMTVVFlight: initialized (inline exec-thunk capture build)");
    g_worker = std::thread(WorkerMain);
}

void Shutdown() {
    bool expected = true;
    if (!g_running.compare_exchange_strong(expected, false)) {
        return;
    }

    if (g_worker.joinable()) {
        g_worker.join();
    }

    std::lock_guard<std::mutex> lock(g_log_mutex);
    if (g_log) {
        std::fprintf(g_log, "SMTVVFlight: shutdown\n");
        std::fclose(g_log);
        g_log = nullptr;
    }
}

void OnXInputState(DWORD user_index, const XINPUT_STATE& state) {
    (void)user_index;
    const bool jump = (state.Gamepad.wButtons & XINPUT_GAMEPAD_B) != 0;
    g_game_pad_b.store(jump, std::memory_order_relaxed);
}

void OnXInputPoll(DWORD user_index, DWORD result) {
    (void)user_index;
    g_xinput_polls.fetch_add(1, std::memory_order_relaxed);
    if (result == ERROR_SUCCESS) {
        g_xinput_success.fetch_add(1, std::memory_order_relaxed);
    }
}

}  // namespace smtvv_flight
