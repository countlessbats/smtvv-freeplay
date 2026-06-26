// SPDX-License-Identifier: MIT
#pragma once

#include <Windows.h>
#include <Xinput.h>

namespace smtvv_flight {

void Initialize(HMODULE module);
void Shutdown();
void OnXInputState(DWORD user_index, const XINPUT_STATE& state);
void OnXInputPoll(DWORD user_index, DWORD result);

}  // namespace smtvv_flight
