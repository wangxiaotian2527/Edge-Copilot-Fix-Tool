#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Edge Copilot 本地配置诊断/修复，Python 3.8+。

单文件版，已内置 VariationsSeedV2 处理逻辑，无需其他本地 Python 文件。
无参数运行进入中文菜单；携带参数时按命令行模式执行，不弹出菜单。
--apply --close-edge 先正常关闭窗口；确认无页面时清理无窗口启动的后台实例。
--restart-edge 在修复成功后打开 Edge 窗口；命令行默认不重开。
本地字段属于未公开的实现细节，不能保证服务端资格或地区可用性。
研究依据及用法见 README.md。
"""

import argparse
import copy
import ctypes
import ctypes.util
from functools import lru_cache
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time

try:
    import psutil
except ImportError:
    psutil = None

MISSING = "<未设置>"
COPILOT_EXTENSION = "ofefcgjbeghpigppfmkologfjadafddi"
POLICY_NAMES = (
    "HubsSidebarEnabled", "Microsoft365CopilotChatIconEnabled",
    "EdgeCopilotEnabled", "CopilotPageContext", "EdgeEntraCopilotPageContext",
    "ProxyMode", "ProxyPacUrl", "ProxySettings",
)


# 内置种子编解码：仅修改国家元数据，保留实验内容、签名及未知字段。
MAX_BYTES = 50 * 1024 * 1024
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
COUNTRY_FIELDS = {6: "session_country", 7: "permanent_country"}


class SeedFormatError(ValueError):
    """The file cannot safely be interpreted as the expected seed format."""


class SeedCodecError(RuntimeError):
    """No supported Zstandard implementation is available."""


def _check_frame_input(raw):
    if not isinstance(raw, bytes):
        raise TypeError("Seed input must be bytes")
    if not raw or len(raw) > MAX_BYTES:
        raise SeedFormatError("Compressed seed exceeds the 50 MiB limit or is empty")
    if not raw.startswith(ZSTD_MAGIC):
        raise SeedFormatError("Expected a standard Zstandard frame")


def _check_content_size(size):
    if size < 0 or size > MAX_BYTES:
        raise SeedFormatError("Unknown or excessive decompressed seed size")


class _PythonZstd:
    def __init__(self, module):
        self.module = module

    def decompress(self, raw):
        try:
            size = self.module.frame_content_size(raw)
            _check_content_size(size)
            # One-shot decompression uses the declared, bounded content size;
            # allow_extra_data=False rejects concatenated frames and trailers.
            result = self.module.ZstdDecompressor().decompress(
                raw, max_output_size=MAX_BYTES, allow_extra_data=False
            )
        except SeedFormatError:
            raise
        except TypeError as exc:
            raise SeedCodecError(
                "Installed zstandard lacks strict frame support"
            ) from exc
        except Exception as exc:
            raise SeedFormatError("Invalid Zstandard seed: {}".format(exc)) from exc
        if len(result) != size:
            raise SeedFormatError("Zstandard content size mismatch")
        return result

    def compress(self, data):
        try:
            result = self.module.ZstdCompressor(
                level=3, write_content_size=True
            ).compress(data)
        except Exception as exc:
            raise SeedFormatError("Cannot compress seed: {}".format(exc)) from exc
        if len(result) > MAX_BYTES:
            raise SeedFormatError("Compressed seed exceeds the 50 MiB limit")
        return result


class _CtypesZstd:
    def __init__(self, library):
        self.library = library
        signatures = {
            "ZSTD_getFrameContentSize": (ctypes.c_ulonglong, [ctypes.c_void_p, ctypes.c_size_t]),
            "ZSTD_findFrameCompressedSize": (ctypes.c_size_t, [ctypes.c_void_p, ctypes.c_size_t]),
            "ZSTD_decompress": (ctypes.c_size_t, [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t]),
            "ZSTD_compressBound": (ctypes.c_size_t, [ctypes.c_size_t]),
            "ZSTD_compress": (ctypes.c_size_t, [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]),
            "ZSTD_isError": (ctypes.c_uint, [ctypes.c_size_t]),
            "ZSTD_getErrorName": (ctypes.c_char_p, [ctypes.c_size_t]),
        }
        for name, (return_type, argument_types) in signatures.items():
            function = getattr(library, name)
            function.restype = return_type
            function.argtypes = argument_types

    def _result(self, result):
        if self.library.ZSTD_isError(result):
            message = self.library.ZSTD_getErrorName(result).decode("ascii", "replace")
            raise SeedFormatError("Zstandard error: {}".format(message))
        return result

    def decompress(self, raw):
        source = ctypes.create_string_buffer(raw)
        frame_size = self._result(
            self.library.ZSTD_findFrameCompressedSize(source, len(raw))
        )
        if frame_size != len(raw):
            raise SeedFormatError("Concatenated frames or trailing bytes are unsupported")
        size = self.library.ZSTD_getFrameContentSize(source, len(raw))
        _check_content_size(size)
        destination = ctypes.create_string_buffer(max(1, size))
        actual = self._result(
            self.library.ZSTD_decompress(destination, size, source, len(raw))
        )
        if actual != size:
            raise SeedFormatError("Zstandard content size mismatch")
        return destination.raw[:actual]

    def compress(self, data):
        source = ctypes.create_string_buffer(data)
        capacity = min(self.library.ZSTD_compressBound(len(data)), MAX_BYTES)
        destination = ctypes.create_string_buffer(max(1, capacity))
        actual = self._result(
            self.library.ZSTD_compress(destination, capacity, source, len(data), 3)
        )
        return destination.raw[:actual]


@lru_cache(maxsize=1)
def _codec():
    try:
        import zstandard
    except ImportError:
        pass
    else:
        return _PythonZstd(zstandard)

    candidates = [
        Path(sys.prefix) / "Library" / "bin" / "libzstd.dll",
        Path(sys.prefix) / "Library" / "bin" / "zstd.dll",
    ]
    for candidate in candidates:
        if candidate.is_file():
            try:
                return _CtypesZstd(ctypes.CDLL(str(candidate)))
            except (OSError, AttributeError):
                continue
    if os.name != "nt":
        library_name = ctypes.util.find_library("zstd")
        if library_name:
            try:
                return _CtypesZstd(ctypes.CDLL(library_name))
            except (OSError, AttributeError):
                pass
    raise SeedCodecError(
        "Zstandard support unavailable: install the optional zstandard package "
        "or use Python with Library/bin/libzstd.dll (or zstd.dll)"
    )


def _decompress(raw):
    _check_frame_input(raw)
    return _codec().decompress(raw)


def _compress(data):
    if not isinstance(data, bytes):
        raise TypeError("Protobuf input must be bytes")
    if len(data) > MAX_BYTES:
        raise SeedFormatError("Decompressed seed exceeds the 50 MiB limit")
    return _codec().compress(data)


def _varint(data, offset):
    value = 0
    for index in range(10):
        if offset >= len(data):
            raise SeedFormatError("Truncated protobuf varint")
        byte = data[offset]
        offset += 1
        if index == 9 and byte > 1:
            raise SeedFormatError("Protobuf varint exceeds 64 bits")
        value |= (byte & 0x7F) << (7 * index)
        if not byte & 0x80:
            return value, offset
    raise SeedFormatError("Protobuf varint exceeds ten bytes")


def _fields(data):
    offset = 0
    while offset < len(data):
        tag, offset = _varint(data, offset)
        number, wire = tag >> 3, tag & 7
        if not 1 <= number <= 0x1FFFFFFF:
            raise SeedFormatError("Invalid protobuf field number")
        payload_start = offset
        if wire == 0:
            unused, offset = _varint(data, offset)
        elif wire == 1:
            offset += 8
        elif wire == 2:
            size, offset = _varint(data, offset)
            payload_start = offset
            offset += size
        elif wire == 5:
            offset += 4
        else:
            raise SeedFormatError("Unsupported protobuf wire type {}".format(wire))
        if offset > len(data):
            raise SeedFormatError("Truncated protobuf field")
        yield number, wire, payload_start, offset


def _country(value):
    if len(value) == 2 and all(65 <= char <= 90 or 97 <= char <= 122 for char in value):
        return value.decode("ascii")
    return None


def _inspect(data):
    metadata = {
        "session_country": None,
        "permanent_country": None,
        "version": None,
        "data_present": False,
        "signature_present": False,
    }
    targets = {}
    for number, wire, start, end in _fields(data):
        if number in COUNTRY_FIELDS:
            if number in targets:
                raise SeedFormatError("Duplicate country field {}".format(number))
            if wire != 2:
                raise SeedFormatError("Country field {} is not a string".format(number))
            targets[number] = (start, end)
            metadata[COUNTRY_FIELDS[number]] = _country(data[start:end])
        elif number == 8 and wire == 2:
            metadata["version"] = data[start:end].decode("utf-8", "replace")
        elif number == 1 and wire == 2:
            metadata["data_present"] = True
        elif number == 2 and wire == 2:
            metadata["signature_present"] = True
    return metadata, targets


def read_seed_metadata(raw):
    """Validate the complete frame/protobuf and return non-secret metadata."""
    metadata, unused = _inspect(_decompress(raw))
    return metadata


def plan_seed(raw, country="US"):
    """Return (new_bytes, [(field_name, old, new), ...]) without file I/O.

    Absent or invalid country values are left untouched. Duplicate country
    fields and malformed protobufs are rejected. If no change is required,
    return the exact original compressed bytes.
    """
    if not isinstance(country, str) or len(country) != 2 or not country.isascii() or not country.isalpha():
        raise ValueError("country must contain exactly two ASCII letters")
    country = country.upper()
    data = _decompress(raw)
    metadata, targets = _inspect(data)
    replacements = []
    changes = []
    for number, (start, end) in targets.items():
        name = COUNTRY_FIELDS[number]
        previous = metadata[name]
        if previous is not None and previous != country:
            replacements.append((start, end))
            changes.append((name, previous, country))
    if not replacements:
        return raw, changes
    # Both old and replacement payloads are exactly two bytes: retain even
    # noncanonical tag/length encodings by replacing payload bytes alone.
    updated = bytearray(data)
    for start, end in replacements:
        updated[start:end] = country.encode("ascii")
    return _compress(bytes(updated)), changes


def default_paths():
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
        names = {"stable": "Edge", "beta": "Edge Beta", "dev": "Edge Dev", "canary": "Edge SxS"}
        return {k: base / "Microsoft" / v / "User Data" for k, v in names.items()}
    if sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
        names = {"stable": "Microsoft Edge", "beta": "Microsoft Edge Beta",
                 "dev": "Microsoft Edge Dev", "canary": "Microsoft Edge Canary"}
        return {k: base / v for k, v in names.items()}
    if sys.platform.startswith("linux"):
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        return {k: base / ("microsoft-edge" + suffix) for k, suffix in
                (("stable", ""), ("beta", "-beta"), ("dev", "-dev"), ("canary", "-canary"))}
    raise RuntimeError("不支持的操作系统：" + sys.platform)


def get_version_and_user_data_path():
    return {k: str(v) for k, v in default_paths().items() if v.is_dir()}


def get_last_version(user_data_path):
    path = Path(user_data_path) / "Last Version"
    return path.read_text(encoding="utf-8-sig").strip() if path.is_file() else None


def decode_json(raw, path):
    data = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("JSON 顶层必须是对象：{}".format(path))
    return data


def load_json(path):
    path = Path(path)
    return decode_json(path.read_bytes(), path)


def validate_country(value):
    value = value.upper()
    if not re.fullmatch(r"[A-Z]{2}", value):
        raise ValueError("地区代码必须是两个英文字母，例如 US。")
    return value


def set_value(data, key, value, changes, prefix=""):
    old = data.get(key, MISSING)
    if type(old) is not type(value) or old != value:
        data[key] = value
        changes.append((prefix + key, old, value))


def plan_local_state(data, country="US", version=None):
    """只同步已有的 consistency 缓存；不编造版本，不修改 safe seed。"""
    if not isinstance(data, dict):
        raise ValueError("Local State 必须是对象")
    country = validate_country(country)
    updated, changes = copy.deepcopy(data), []
    set_value(updated, "variations_country", country, changes)
    key = "variations_permanent_consistency_country"
    cached = updated.get(key)
    if (isinstance(cached, list) and len(cached) == 2
            and all(isinstance(v, str) for v in cached)
            and re.fullmatch(r"\d+(?:\.\d+){3}", cached[0])
            and re.fullmatch(r"[A-Za-z]{2}", cached[1])):
        set_value(updated, key, [cached[0], country], changes)
    return updated, changes


def plan_preferences(data):
    if not isinstance(data, dict):
        raise ValueError("Preferences 必须是对象")
    updated, changes = copy.deepcopy(data), []
    browser = updated.setdefault("browser", {})
    if not isinstance(browser, dict):
        raise ValueError("Preferences.browser 不是对象，拒绝覆盖异常结构")
    set_value(browser, "chat_ip_eligibility_status", True, changes, "browser.")
    set_value(browser, "show_discover_toolbar_button", True, changes, "browser.")
    return updated, changes


def profile_paths(root):
    root = Path(root)
    return sorted((p for p in root.iterdir()
                   if (p.name == "Default" or p.name.startswith("Profile "))
                   and p.is_dir() and not p.is_symlink() and (p / "Preferences").is_file()),
                  key=lambda p: p.name)


def atomic_write_bytes(path, encoded, expected_bytes):
    """原字节备份 + 同目录原子替换 + 并发变化检查 + 读回校验。"""
    path = Path(path)
    if path.is_symlink():
        raise ValueError("拒绝修改符号链接：{}".format(path))
    if path.read_bytes() != expected_bytes:
        raise RuntimeError("文件在读取后发生变化，请退出 Edge 后重试：{}".format(path))
    mode = stat.S_IMODE(path.stat().st_mode)
    if not mode & stat.S_IWUSR:
        raise PermissionError("文件是只读的：{}".format(path))
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(path.name + ".copilot-backup-{}-{}.bak".format(stamp, time.time_ns()))
    with backup.open("xb") as stream:
        stream.write(expected_bytes)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(str(backup), mode)
    if backup.read_bytes() != expected_bytes:
        raise OSError("备份校验失败：{}".format(backup))
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", prefix=path.name + ".copilot-",
                                         suffix=".tmp", dir=str(path.parent), delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(str(temporary), mode)
        if path.read_bytes() != expected_bytes:
            raise RuntimeError("写入前检测到并发修改，已保留原文件：{}".format(path))
        os.replace(str(temporary), str(path))
        temporary = None
        if path.read_bytes() != encoded:
            raise OSError("写入后校验失败；原文件备份位于 {}".format(backup))
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return backup


def atomic_write_json(path, data, expected_bytes):
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    decode_json(encoded, path)
    backup = atomic_write_bytes(path, encoded, expected_bytes)
    if load_json(path) != data:
        raise OSError("JSON 写入后校验失败；原文件备份位于 {}".format(backup))
    return backup


def is_edge_process_name(name):
    name = name.casefold()
    if sys.platform == "win32":
        return name == "msedge.exe"
    if sys.platform == "darwin":
        return name in ("microsoft edge", "microsoft edge beta", "microsoft edge dev",
                        "microsoft edge canary") or name.startswith("microsoft edge helper")
    return name in ("msedge", "microsoft-edge", "microsoft-edge-stable",
                    "microsoft-edge-beta", "microsoft-edge-dev", "microsoft-edge-canary")


def process_is_alive(process):
    """Windows 上查询退出状态，不能仅凭 PID/缓存名称判断存活。"""
    try:
        if not process.is_running():
            return False
        if sys.platform == "win32":
            try:
                process.wait(timeout=0)
                return False
            except psutil.TimeoutExpired:
                return True
        return process.status() not in (psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD)
    except psutil.NoSuchProcess:
        return False


def edge_processes():
    if psutil is None:
        raise RuntimeError("写入前需要 psutil 确认 Edge 已退出：python -m pip install psutil")
    owner = psutil.Process().username().casefold()
    found = []
    # 不复用 process_iter 的 Process 缓存，兼容本机 psutil 5.8。
    for pid in psutil.pids():
        try:
            process = psutil.Process(pid)
            try:
                name = process.name()
            except psutil.AccessDenied:
                # 无法辨认进程名时不能假定它一定不是 Edge。
                raise RuntimeError("无法读取 PID {} 的进程名，不能确认 Edge 是否退出。".format(pid))
            if not is_edge_process_name(name):
                continue
            if process_is_alive(process) and process.username().casefold() == owner:
                found.append(process)
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied as exc:
            raise RuntimeError("无法确认 Edge PID {} 的进程归属/退出状态，请使用启动 Edge 的同一用户运行。".format(pid)) from exc
    return found


def describe_edge_processes(processes):
    lines = []
    for process in processes:
        try:
            args = process.cmdline()
            role = next((a.split("=", 1)[1] for a in args if a.startswith("--type=")), "browser")
            background = " --no-startup-window" if "--no-startup-window" in args else ""
            lines.append("  PID={} PPID={} {} type={}{}".format(
                process.pid, process.ppid(), process.name(), role, background))
        except psutil.NoSuchProcess:
            lines.append("  PID={}（检查期间已退出）".format(process.pid))
        except psutil.AccessDenied:
            lines.append("  PID={}（无权读取详情）".format(process.pid))
    return "\n".join(lines)


def windows_edge_windows(processes, close=False):
    """返回可见 Edge 窗口的 PID；可选发送 WM_CLOSE，不读取窗口标题。"""
    from ctypes import wintypes
    pids = {p.pid for p in processes}
    visible = set()
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    failures = []

    @callback_type
    def visit_window(hwnd, _):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids:
            if user32.IsWindowVisible(hwnd):
                visible.add(pid.value)
            if close and not user32.PostMessageW(hwnd, 0x0010, 0, 0):
                error = ctypes.get_last_error()
                if error != 1400:  # 窗口可能已在枚举过程中销毁。
                    failures.append((pid.value, error))
        return True

    if not user32.EnumWindows(visit_window, 0):
        raise OSError("无法枚举 Edge 窗口，请手动退出 Edge。")
    if failures:
        raise OSError("发送关闭窗口消息失败：{}".format(failures))
    return visible


def wait_for_edge_exit(timeout):
    """轮询全新进程列表，覆盖延迟退出和关闭时新生的进程。"""
    deadline = time.monotonic() + timeout
    while True:
        remaining = edge_processes()
        if not remaining:
            # 避免恰好在后台重启的间隙宣布退出。
            time.sleep(0.25)
            remaining = edge_processes()
            if not remaining:
                return []
        if time.monotonic() >= deadline:
            return remaining
        time.sleep(min(0.25, max(0, deadline - time.monotonic())))


def is_startup_background_only(processes):
    """仅允许清理无窗口、无页面、明确以后台方式启动的 Edge 实例。"""
    if sys.platform != "win32" or not processes or windows_edge_windows(processes):
        return False
    has_browser = False
    try:
        for process in processes:
            args = process.cmdline()
            role = next((a.split("=", 1)[1] for a in args if a.startswith("--type=")), None)
            if role is None:
                has_browser = True
                if "--no-startup-window" not in args or any(
                        a.startswith(("--headless", "--remote-debugging", "--app")) for a in args):
                    return False
            elif role not in ("utility", "gpu-process", "crashpad-handler"):
                # renderer（含后台页面/扩展）、未知类型均不自动终止。
                return False
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False
    return has_browser


def shutdown_edge(force=False, timeout=10):
    processes = edge_processes()
    executables = set()
    for process in processes:
        try:
            if not any(arg.startswith("--type=") for arg in process.cmdline()):
                executables.add(process.exe())
        except psutil.NoSuchProcess:
            continue
    if not processes:
        return []
    print("正在请求关闭当前用户的全部 Edge 窗口，等待进程退出……")
    if sys.platform == "win32":
        windows_edge_windows(processes, close=True)
    else:
        for process in processes:
            try:
                if process.exe() in executables and not any(
                        arg.startswith("--type=") for arg in process.cmdline()):
                    process.send_signal(signal.SIGTERM)
            except psutil.NoSuchProcess:
                pass
    remaining = wait_for_edge_exit(timeout)
    if remaining and not force and is_startup_background_only(remaining):
        # 再核对一次，避免把正在创建窗口的后台实例当作空闲残留。
        time.sleep(0.5)
        refreshed = edge_processes()
        if {p.pid for p in refreshed} == {p.pid for p in remaining} and is_startup_background_only(refreshed):
            print("确认无可见窗口、无页面渲染进程；正在结束无窗口启动的 Edge 后台实例：")
            print(describe_edge_processes(refreshed))
            for process in refreshed:
                try:
                    process.terminate()
                except psutil.NoSuchProcess:
                    pass
            remaining = wait_for_edge_exit(timeout)
        else:
            remaining = wait_for_edge_exit(1)
    if remaining and force:
        print("已指定 --force-close：强制结束剩余 Edge 进程。")
        for process in remaining:
            try:
                process.kill()
            except psutil.NoSuchProcess:
                pass
        remaining = wait_for_edge_exit(timeout)
    if remaining:
        raise RuntimeError("Edge 仍有以下活动进程，未写入任何配置：\n{}\n"
                           "请在任务管理器的“详细信息”页按 PID 核对；保存网页工作后可使用 "
                           "--apply --patch-seed --close-edge --force-close。".format(
                               describe_edge_processes(remaining)))
    print("已确认 Edge 进程退出，将重新读取磁盘上的配置。")
    return sorted(executables)


def read_windows_diagnostics():
    """只读指定策略和代理是否启用，不输出账号、URL 或代理凭证。"""
    if sys.platform != "win32":
        return [], {}
    import winreg
    policies, proxy = [], {}
    base = r"SOFTWARE\Policies\Microsoft\Edge"
    for label, hive in (("HKCU", winreg.HKEY_CURRENT_USER), ("HKLM", winreg.HKEY_LOCAL_MACHINE)):
        for suffix in ("", r"\Recommended"):
            try:
                with winreg.OpenKey(hive, base + suffix, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                    for name in POLICY_NAMES:
                        try:
                            value = winreg.QueryValueEx(key, name)[0]
                            if name in ("ProxyPacUrl", "ProxySettings"):
                                value = "<已配置>"
                            policies.append((label + suffix, name, value))
                        except FileNotFoundError:
                            pass
            except FileNotFoundError:
                pass
            except OSError as exc:
                print("提示：无法读取 {} 策略（{}）；请以 edge://policy 为准。".format(label, exc))
        for name in ("ExtensionInstallBlocklist", "ExtensionInstallAllowlist"):
            try:
                with winreg.OpenKey(hive, base + "\\" + name, 0,
                                    winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                    values = [winreg.EnumValue(key, i)[1] for i in range(winreg.QueryInfoKey(key)[1])]
                    relevant = [v for v in values if v in ("*", COPILOT_EXTENSION)]
                    if relevant:
                        policies.append((label, name, relevant))
            except FileNotFoundError:
                pass
            except OSError as exc:
                print("提示：无法读取扩展策略（{}）。".format(exc))
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as key:
            for name in ("ProxyEnable", "AutoConfigURL"):
                try:
                    proxy[name] = bool(winreg.QueryValueEx(key, name)[0])
                except FileNotFoundError:
                    proxy[name] = False
    except OSError:
        proxy["unavailable"] = True
    return policies, proxy


def show_system_diagnostics():
    policies, proxy = read_windows_diagnostics()
    if sys.platform == "win32":
        print("\n[Windows 策略/网络提示]")
        for scope, name, value in policies:
            print("  {} {} = {}".format(scope, name, value))
        if not policies:
            print("  未在已检查的注册表位置发现相关策略；完整有效策略请查看 edge://policy。")
        print("  系统手动代理启用：{}；显式 PAC 地址已配置：{}".format(
            proxy.get("ProxyEnable", MISSING), proxy.get("AutoConfigURL", MISSING)))
        if proxy.get("AutoConfigURL") or any(name == "ProxyPacUrl" for _, name, _ in policies):
            print("  Edge 153 更改了 PAC 的本机 IP 选择逻辑；若更新后失效，请检查 PAC/VPN 路由。")
    print("  Microsoft365CopilotChatIconEnabled 仅适用于 Entra 工作/学校配置。")
    print("  EdgeCopilotEnabled 仅适用于移动端，写入桌面注册表不能修复此问题。")


def collect_plans(root, country, selected_profiles=None, patch_seed=False):
    version = get_last_version(root)
    print("\n[Edge {}] {}".format(version or "版本未知（仍检查配置）", root))
    plans, errors = [], []
    state_path = root / "Local State"
    profiles = profile_paths(root)
    if selected_profiles:
        requested = set(selected_profiles)
        for name in requested:
            if name in (".", "..") or Path(name).name != name or "/" in name or "\\" in name:
                raise ValueError("--profile 必须是配置目录名，例如 Default 或 Profile 1")
            candidate = root / name
            if not candidate.is_dir() or not (candidate / "Preferences").is_file():
                errors.append("找不到配置文件：{}".format(candidate / "Preferences"))
        profiles = [root / name for name in sorted(requested)
                    if (root / name / "Preferences").is_file()]
    if not profiles:
        errors.append("未找到有效 Preferences；--user-data-dir 应指向包含 Local State 的 User Data 目录。")
    seed_path = root / "VariationsSeedV2"
    if seed_path.is_file():
        try:
            if seed_path.is_symlink():
                raise ValueError("拒绝修改符号链接：{}".format(seed_path))
            raw_seed = seed_path.read_bytes()
            metadata = read_seed_metadata(raw_seed)
            print("  VariationsSeedV2: session_country={!r}, permanent_country={!r}, version={!r}".format(
                metadata["session_country"], metadata["permanent_country"], metadata["version"]))
            if any(metadata[k] is None for k in ("session_country", "permanent_country")):
                print("  提示：种子中部分国家字段缺失或格式未知，这些字段保留原样。")
            mismatch = any(metadata[k] not in (None, country) for k in ("session_country", "permanent_country"))
            if mismatch:
                print("  独立实验种子的地区与目标不一致；新版浏览器可能优先使用此文件。")
            if patch_seed:
                updated_seed, seed_changes = plan_seed(raw_seed, country)
                # 先修复原有 JSON，再同步 regular seed；SafeSeed 始终不动。
                plans.append((seed_path, raw_seed, updated_seed, seed_changes))
                for key, old, new in seed_changes:
                    print("    待修改 VariationsSeedV2.{}: {!r} -> {!r}".format(key, old, new))
            elif mismatch:
                print("  使用 --apply --patch-seed 可备份后同步国家元数据；种子内容及签名保持原样。")
        except (ImportError, OSError, ValueError, RuntimeError) as exc:
            message = "无法检查独立实验种子：{}".format(exc)
            if patch_seed:
                errors.append(message)
            else:
                print("  提示：" + message)
    elif patch_seed:
        print("  未发现 VariationsSeedV2，跳过独立种子修复，仅检查已有 JSON。")
    for path in [state_path] + [p / "Preferences" for p in profiles]:
        try:
            if path.is_symlink() or path.parent.is_symlink():
                raise ValueError("拒绝修改符号链接配置：{}".format(path))
            raw = path.read_bytes()
            data = decode_json(raw, path)
            if path == state_path:
                updated, changes = plan_local_state(data, country, version)
                print("  variations_country = {!r}".format(data.get("variations_country", MISSING)))
                cached = data.get("variations_permanent_consistency_country", MISSING)
                print("  permanent_consistency_country = {!r}".format(cached))
                if cached != MISSING and not (isinstance(cached, list) and len(cached) == 2
                        and all(isinstance(v, str) for v in cached)
                        and re.fullmatch(r"\d+(?:\.\d+){3}", cached[0])
                        and re.fullmatch(r"[A-Za-z]{2}", cached[1])):
                    print("  提示：permanent 缓存结构未知，将保留原样。")
                print("  safe_seed 国家是历史种子元数据，保留原样。")
            else:
                updated, changes = plan_preferences(data)
                browser = data.get("browser", {})
                print("  [{}] chat_ip_eligibility_status={!r}, show_discover_toolbar_button={!r}".format(
                    path.parent.name, browser.get("chat_ip_eligibility_status", MISSING),
                    browser.get("show_discover_toolbar_button", MISSING)))
                copilot = data.get("edge_copilot", {})
                eligible = copilot.get("msa_eligibility_info", {}) if isinstance(copilot, dict) else {}
                if isinstance(eligible, dict) and "isCopilotEligible" in eligible:
                    print("    本地 MSA 资格缓存 = {!r}（只读，不能证明服务端可用）".format(
                        eligible["isCopilotEligible"]))
                if not changes:
                    print("    这两个配置开关已满足；还需结合地区种子、策略和服务端资格判断。")
            for key, old, new in changes:
                print("    待修改 {}: {!r} -> {!r}".format(key, old, new))
            plans.append((path, raw, updated, changes))
        except (OSError, ValueError) as exc:
            errors.append("{}：{}".format(path, exc))
    plans.sort(key=lambda p: p[0].name == "VariationsSeedV2")
    return plans, errors


def troubleshooting():
    print("\n[功能验证]")
    print("  1. Edge 147+ 查看 edge://settings/ai；旧入口为")
    print("     edge://settings/appearance/copilotAndSidebar，检查显示 Copilot 按钮。")
    print("  2. 查看 edge://policy 的 Copilot/侧边栏/扩展限制。脚本不会覆盖组织策略。")
    print("  3. 在同一个 Edge 配置中访问 https://copilot.microsoft.com/，确认账号与网络可用。")
    print("  4. 重启后再运行 --diagnose，检查配置是否被 Edge 改回。")
    print("  本地写入验证不等于 Copilot 恢复；服务端地区、账号资格和网络不能靠 JSON 保证。")


def find_edge_executable(channel):
    """定位对应通道的浏览器，不用 shell 拼接启动命令。"""
    candidates = []
    if sys.platform == "win32":
        folder = {"stable": "Edge", "beta": "Edge Beta", "dev": "Edge Dev", "canary": "Edge SxS"}[channel]
        for variable in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
            base = os.environ.get(variable)
            if base:
                candidates.append(Path(base) / "Microsoft" / folder / "Application/msedge.exe")
    elif sys.platform == "darwin":
        name = {"stable": "Microsoft Edge", "beta": "Microsoft Edge Beta",
                "dev": "Microsoft Edge Dev", "canary": "Microsoft Edge Canary"}[channel]
        for base in (Path("/Applications"), Path.home() / "Applications"):
            candidates.append(base / (name + ".app") / "Contents/MacOS" / name)
    else:
        names = ["microsoft-edge", "microsoft-edge-stable"] if channel == "stable" else ["microsoft-edge-" + channel]
        candidates.extend(Path(value) for value in (shutil.which(name) for name in names) if value)
    for path in candidates:
        if path.is_file():
            return path.resolve()
    raise FileNotFoundError("找不到 {} 通道的 Edge 程序。可用 --edge-exe 指定 msedge.exe 的完整路径。".format(channel))


def build_restart_commands(args, roots):
    commands = []
    # 只比较路径文本，不为自定义配置访问其他通道的用户数据目录。
    known_paths = {os.path.normcase(os.path.abspath(str(p))): channel for channel, p in default_paths().items()}
    for root in roots:
        fallback = args.channel if args.channel != "all" else "stable"
        channel = known_paths.get(os.path.normcase(os.path.abspath(str(root))), fallback)
        executable = args.edge_exe.expanduser().resolve() if args.edge_exe else find_edge_executable(channel)
        if not executable.is_file():
            raise FileNotFoundError("Edge 程序不存在：{}".format(executable))
        for profile in dict.fromkeys(args.profile or [None]):
            command = [str(executable), "--user-data-dir=" + str(root.resolve()), "--new-window"]
            if profile:
                command.append("--profile-directory=" + profile)
            commands.append(command)
    return commands


def restart_edge(commands):
    for command in commands:
        try:
            subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, close_fds=True,
                             start_new_session=(os.name != "nt"))
        except OSError as exc:
            raise RuntimeError("配置处理已完成，但重新打开 Edge 失败：{}".format(exc)) from exc
    print("已发送 Edge 打开窗口请求（{} 个）。".format(len(commands)))


def menu_choice(prompt, choices, default=None):
    while True:
        value = input(prompt).strip().lower()
        if not value and default is not None:
            value = default
        if value in choices:
            return value
        print("输入无效，请选择：{}".format(" / ".join(choices)))


def interactive_menu():
    target = ["--channel", "stable", "--profile", "Default"]
    description = "正式版 / Default"
    try:
        while True:
            print("\n========== Edge Copilot 修复工具 ==========\n当前配置：{}".format(description))
            print("1. 修复 Copilot（自动关闭 Edge）")
            print("2. 预览修复内容")
            print("3. 只读诊断")
            print("4. 查看 Edge 进程")
            print("5. 更换浏览器通道 / 配置目录")
            print("0. 退出")
            choice = menu_choice("请选择操作 [0-5]：", ("0", "1", "2", "3", "4", "5"))
            if choice == "0":
                return 0
            if choice == "5":
                print("1. 正式版  2. Beta  3. Dev  4. Canary  5. 自定义 User Data 目录")
                channel_choice = menu_choice("选择通道 [默认 1]：", ("1", "2", "3", "4", "5"), "1")
                if channel_choice == "5":
                    path = input("输入 User Data 目录（不是 Default 目录）：").strip().strip('"')
                    if not path:
                        print("目录未填写，保留原配置。")
                        continue
                    target = ["--user-data-dir", path]
                    description = path
                else:
                    channel, description = {"1": ("stable", "正式版"), "2": ("beta", "Beta"),
                                            "3": ("dev", "Dev"), "4": ("canary", "Canary")}[channel_choice]
                    target = ["--channel", channel]
                profile = input("配置目录名 [默认 Default；输入 * 处理全部配置]：").strip() or "Default"
                if profile != "*":
                    target.extend(["--profile", profile])
                description += " / " + ("全部配置" if profile == "*" else profile)
                continue
            if choice == "1":
                print("修复会关闭 Edge，请先保存网页中的工作。")
                reopen = menu_choice("修复成功后重新打开 Edge 窗口？[Y/n]：", ("y", "n"), "y")
                arguments = ["--apply", "--patch-seed", "--close-edge"] + target
                arguments.append("--restart-edge" if reopen == "y" else "--no-restart-edge")
            elif choice == "2":
                arguments = ["--dry-run", "--patch-seed"] + target
            elif choice == "3":
                arguments = ["--diagnose"] + target
            else:
                arguments = ["--list-processes"]
            status = main(arguments)
            print("\n操作完成。" if status == 0 else "\n操作未完成，请查看上方错误信息。")
            input("按回车返回菜单……")
    except EOFError:
        print("\n输入已结束，退出菜单。自动化执行请使用命令行参数。")
        return 0
    except KeyboardInterrupt:
        print("\n已取消操作。")
        return 130


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--diagnose", action="store_true", help="只读诊断（仅提供路径等参数时默认采用）")
    action.add_argument("--dry-run", action="store_true", help="预览修改，不关闭 Edge、不写文件")
    action.add_argument("--apply", action="store_true", help="备份后应用本地配置补丁")
    action.add_argument("--list-processes", action="store_true", help="只读列出本用户活动 Edge 进程的 PID/类型")
    parser.add_argument("--channel", choices=("stable", "beta", "dev", "canary", "all"), default="stable")
    parser.add_argument("--user-data-dir", type=Path, help="自定义 User Data 目录；覆盖 --channel")
    parser.add_argument("--profile", action="append", help="只处理指定配置，可重复；默认所有常规配置")
    parser.add_argument("--country", default="US", help="本地地区缓存目标，默认 US")
    parser.add_argument("--patch-seed", action="store_true", help="同时同步新版 VariationsSeedV2 的国家元数据")
    parser.add_argument("--close-edge", action="store_true", help="关闭当前用户所有 Edge 窗口，必要时结束无页面的无窗口后台实例")
    parser.add_argument("--force-close", action="store_true", help="正常关闭超时后强杀，可能丢失未保存网页内容")
    reopen = parser.add_mutually_exclusive_group()
    reopen.add_argument("--restart-edge", action="store_true", help="修复成功后打开目标配置的 Edge 窗口")
    reopen.add_argument("--no-restart-edge", dest="restart_edge", action="store_false", help="结束后不打开 Edge（命令行默认）")
    parser.set_defaults(restart_edge=False)
    parser.add_argument("--edge-exe", type=Path, help="重新打开时使用的 Edge 可执行文件路径（默认自动查找）")
    args = parser.parse_args(argv)
    if (args.close_edge or args.force_close) and not args.apply:
        parser.error("关闭浏览器选项只能与 --apply 一起使用")
    if args.force_close and not args.close_edge:
        parser.error("--force-close 必须与 --close-edge 一起使用")
    if args.restart_edge and not args.apply:
        parser.error("--restart-edge 只能与 --apply 一起使用")
    if args.edge_exe and args.channel == "all" and not args.user_data_dir:
        parser.error("指定 --edge-exe 时请选择单一通道或自定义 User Data 目录")
    try:
        args.country = validate_country(args.country)
    except ValueError as exc:
        parser.error(str(exc))
    return args


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        return interactive_menu()
    args = parse_args(arguments)
    try:
        if args.list_processes:
            processes = edge_processes()
            print(describe_edge_processes(processes) if processes else "当前用户没有活动的 Edge 浏览器进程。")
            if processes and sys.platform == "win32":
                print("有可见窗口的 PID：{}".format(sorted(windows_edge_windows(processes))))
                print("可自动清理的无页面后台实例：{}".format(is_startup_background_only(processes)))
            return 0
        if args.user_data_dir:
            roots = [args.user_data_dir.expanduser().resolve()]
        else:
            available = default_paths()
            roots = list(available.values()) if args.channel == "all" else [available[args.channel]]
            roots = [p for p in roots if p.is_dir()]
        if not roots or any(not p.is_dir() for p in roots):
            raise FileNotFoundError("未找到 Edge 用户数据目录。可用 --user-data-dir 指定 edge://version 显示的配置路径的上一级。")
        print("模式：{}；目标地区缓存：{}".format("应用补丁" if args.apply else "只读预览/诊断", args.country))
        show_system_diagnostics()
        plans, errors = [], []
        for root in roots:
            batch, problems = collect_plans(root, args.country, args.profile, args.patch_seed)
            plans.extend(batch)
            errors.extend(problems)
        if errors:
            for error in errors:
                print("错误：" + error, file=sys.stderr)
            print("存在配置读取错误，未写入任何配置。")
            return 1
        changed = [p for p in plans if p[3]]
        # 关闭浏览器或修改文件前先确认重开所需的可执行文件存在。
        restart_commands = build_restart_commands(args, roots) if args.restart_edge else []
        print("\n共检查 {} 个文件，{} 个文件需要修改。".format(len(plans), len(changed)))
        if not args.apply:
            flags = "--apply --patch-seed" if args.patch_seed else "--apply"
            print("未写入配置。保存网页工作并退出 Edge 后，使用 {} 应用补丁（保留原路径/配置选择参数）。".format(flags))
            troubleshooting()
            return 0
        if not changed:
            print("本地配置已满足，无需写入，也不会关闭 Edge。")
            troubleshooting()
            if restart_commands:
                restart_edge(restart_commands)
            return 0
        if edge_processes():
            if not args.close_edge:
                raise RuntimeError("Edge 正在运行，未写入配置。请退出所有 Edge 窗口和后台进程，"
                                   "或保存网页工作后使用 --apply --close-edge。")
            shutdown_edge(force=args.force_close)
            # 正常退出可能把新设置写回，必须重新读取，不能使用关闭前的快照。
            plans, errors = [], []
            for root in roots:
                batch, problems = collect_plans(root, args.country, args.profile, args.patch_seed)
                plans.extend(batch)
                errors.extend(problems)
            if errors:
                raise RuntimeError("退出后重新读取失败：" + "; ".join(errors))
            changed = [p for p in plans if p[3]]
        written = 0
        for path, raw, updated, changes in changed:
            if edge_processes():
                raise RuntimeError("Edge 在补丁期间重新启动，已停止后续写入。已完成 {} 个文件；备份路径见上文。".format(written))
            if isinstance(updated, bytes):
                expected_metadata = read_seed_metadata(updated)
                backup = atomic_write_bytes(path, updated, raw)
                if read_seed_metadata(path.read_bytes()) != expected_metadata:
                    raise OSError("种子写入校验失败；备份：{}".format(backup))
            else:
                backup = atomic_write_json(path, updated, raw)
            written += 1
            print("已写入并读回校验：{}\n  原始备份：{}".format(path, backup))
        print("完成 {} 个文件的本地配置修改。".format(written))
        troubleshooting()
        if restart_commands:
            restart_edge(restart_commands)
        else:
            print("本次不自动打开 Edge；可稍后手动打开验证 Copilot。")
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print("错误：{}".format(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        if psutil is not None and isinstance(exc, psutil.Error):
            print("进程检查失败，已停止写入：{}".format(exc), file=sys.stderr)
            return 1
        raise


if __name__ == "__main__":
    sys.exit(main())
