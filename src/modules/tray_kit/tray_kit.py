# -*- coding: utf-8 -*-
# TEMPLATE-FROM: my-diy-tool-template/modules/tray_kit/tray_kit.py | TEMPLATE-VER: 1.0.1
# TEMPLATE-LOCAL-OVERRIDE: 互斥体名由调用方显式传入（reme 用 APP_ID + "-tray"，全局命名
#   空间，无 Local/ 前缀——历史行为，保持不变）；warn_duplicate_instance 留 main.py
#   （提示文案走 t() 翻译 + 6 秒自动关窗，UI 细节与业务耦合）。
"""T7｜托盘机制件（reme-helper 形态）：单实例互斥体的抢/探。"""
import ctypes
import os
from ctypes import wintypes

ERROR_ALREADY_EXISTS = 183
_MUTEX_HANDLE = None    # 必须留在模块级：句柄被回收就等于放锁


def acquire_single_instance(mutex_name: str, log=print) -> bool:
    """抢一个命名互斥体：多开时只有第一个实例能继续，其余直接退出（False）。

    必须在托盘与服务逻辑之前判定。诊断类参数（--smoke / --ui-check 等）不走这里。
    守卫自身失败时放行（continuing without the guard）。
    """
    global _MUTEX_HANDLE
    if os.name != "nt":
        return True
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
    # 名字不带版本号：旧版本与新版也必须互斥，否则升级期间会出现两个托盘在抢同一份配置
    handle = kernel32.CreateMutexW(None, False, mutex_name)
    if not handle:
        log("single-instance: CreateMutexW failed; continuing without the guard")
        return True
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False
    _MUTEX_HANDLE = handle
    return True


def single_instance_free(mutex_name: str) -> bool:
    """探一下互斥体现在是否空着，**不持有**它（诊断参数用；自检不能顺手占锁）。"""
    if os.name != "nt":
        return True
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
    handle = kernel32.CreateMutexW(None, False, mutex_name)
    if not handle:
        return True
    already = ctypes.get_last_error() == ERROR_ALREADY_EXISTS
    kernel32.CloseHandle(handle)
    return not already
