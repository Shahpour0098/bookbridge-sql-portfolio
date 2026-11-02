"""Start/stop only the server process registered for this project copy."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

from runtime import HIDDEN, ROOT, RUNTIME, load_owner, write_json

STATE = RUNTIME / "server.json"
SCRIPT = ROOT / "run.py"


@contextmanager
def windows_process(pid: int, *, terminate: bool = False):
    """Hold one process handle so PID reuse cannot target another process."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
    kernel32.TerminateProcess.restype = wintypes.BOOL
    access = 0x1000 | 0x00100000 | (0x0001 if terminate else 0)
    handle = kernel32.OpenProcess(access, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:  # ERROR_INVALID_PARAMETER: process no longer exists.
            yield None
            return
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield (kernel32, handle)
    finally:
        kernel32.CloseHandle(handle)


def windows_process_details(process) -> dict | None:
    import ctypes
    from ctypes import wintypes

    if process is None:
        return None
    kernel32, handle = process
    if kernel32.WaitForSingleObject(handle, 0) == 0:
        return None
    size = wintypes.DWORD(32768)
    executable = ctypes.create_unicode_buffer(size.value)
    if not kernel32.QueryFullProcessImageNameW(handle, 0, executable, ctypes.byref(size)):
        raise ctypes.WinError(ctypes.get_last_error())
    created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
    if not kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                    ctypes.byref(kernel), ctypes.byref(user)):
        raise ctypes.WinError(ctypes.get_last_error())
    ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime
    return {"ExecutablePath": executable.value, "CreationDate": str(ticks)}


def process_details(pid: int) -> dict | None:
    if os.name == "nt":
        with windows_process(pid) as process:
            return windows_process_details(process)
    proc = Path(f"/proc/{pid}")
    try:
        # The final ')' ends comm, which can itself contain whitespace.
        fields = (proc / "stat").read_text().rsplit(")", 1)[1].split()
        return {"ExecutablePath": str((proc / "exe").resolve()),
                "CommandLine": (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode(),
                "CreationDate": fields[19]}
    except FileNotFoundError:
        return None


def matches_own_process(state: dict, info: dict | None) -> bool:
    if info is None:
        return False
    expected_exe = str(Path(state["python_executable"]).resolve()).casefold()
    observed_exe = str(Path(info.get("ExecutablePath") or "").resolve()).casefold()
    # State is written only from our Popen handle into the private runtime folder.
    # Executable + native creation time identify that exact child on Windows,
    # without relying on CIM/WMI availability or administrative permissions.
    script_matches = state.get("script_path") == str(SCRIPT)
    if "CommandLine" in info:
        command = info["CommandLine"].replace("/", "\\").casefold()
        script_matches = script_matches and str(SCRIPT).replace("/", "\\").casefold() in command
    return (state.get("project_root") == str(ROOT) and observed_exe == expected_exe
            and script_matches and info["CreationDate"] == state.get("creation_time"))


def is_own_process(state: dict) -> bool:
    return matches_own_process(state, process_details(int(state["pid"])))


def terminate_own_process(state: dict) -> bool:
    if os.name == "nt":
        import ctypes
        with windows_process(int(state["pid"]), terminate=True) as process:
            if not matches_own_process(state, windows_process_details(process)):
                return False
            kernel32, handle = process
            if not kernel32.TerminateProcess(handle, 0):
                raise ctypes.WinError(ctypes.get_last_error())
            if kernel32.WaitForSingleObject(handle, 10000) != 0:
                raise RuntimeError("Eigener Server wurde nicht innerhalb von 10 Sekunden beendet.")
            return True
    if not is_own_process(state):
        return False
    os.kill(int(state["pid"]), signal.SIGTERM)
    return True


def healthy() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8767/api/health", timeout=2) as response:
            body = json.load(response)
            return body.get("status") == "ok" and body.get("project") == "bookbridge-phase3"
    except (OSError, ValueError, urllib.error.HTTPError):
        return False


def start() -> None:
    load_owner()
    if not (RUNTIME / "config.json").is_file() or not SCRIPT.is_file():
        raise RuntimeError("Anwendung noch nicht eingerichtet; scripts/setup.ps1 ausfuehren.")
    if STATE.exists():
        state = json.loads(STATE.read_text(encoding="utf-8-sig"))
        if is_own_process(state):
            if healthy():
                print("BookBridge laeuft bereits: http://127.0.0.1:8767")
                return
            raise RuntimeError("Eigener Serverprozess laeuft, antwortet aber nicht. Protokoll pruefen und scripts/stop.ps1 ausfuehren.")
    # A port collision must never result in another project being stopped.
    import socket
    with socket.socket() as listener:
        try:
            listener.bind(("127.0.0.1", 8767))
        except OSError as error:
            raise RuntimeError("Port 8767 ist bereits belegt; kein fremder Prozess wird beendet.") from error
    with (RUNTIME / "server.out.log").open("ab") as output, (RUNTIME / "server.err.log").open("ab") as errors:
        process = subprocess.Popen([sys.executable, str(SCRIPT)], cwd=ROOT,
                                   stdin=subprocess.DEVNULL, stdout=output, stderr=errors,
                                   creationflags=HIDDEN, start_new_session=os.name != "nt")
    try:
        info = process_details(process.pid)
        if info is None:
            raise RuntimeError("Server wurde sofort beendet; .runtime/server.err.log pruefen.")
        write_json(STATE, {"pid": process.pid, "python_executable": sys.executable,
                          "project_root": str(ROOT), "script_path": str(SCRIPT),
                          "creation_time": info["CreationDate"],
                          "started_at": datetime.now(timezone.utc).isoformat()})
        for _ in range(60):
            if process.poll() is not None:
                raise RuntimeError("Server wurde beim Start beendet; .runtime/server.err.log pruefen.")
            if healthy():
                print("BookBridge bereit: http://127.0.0.1:8767")
                return
            time.sleep(0.5)
        raise RuntimeError("Server meldet nach 30 Sekunden keine Bereitschaft; .runtime/server.err.log pruefen.")
    except BaseException:
        # Popen retains the exact child handle; a failed start must not leave
        # an untracked server occupying the port or affect an unrelated PID.
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        STATE.unlink(missing_ok=True)
        raise


def stop() -> None:
    if not STATE.exists():
        print("Kein durch dieses Projekt gestarteter Server registriert.")
        return
    state = json.loads(STATE.read_text(encoding="utf-8-sig"))
    if not is_own_process(state):
        print("Registrierter Server ist bereits beendet; kein fremder Prozess wurde angefasst.")
        STATE.unlink()
        return
    terminate_own_process(state)
    for _ in range(40):
        if not is_own_process(state):
            STATE.unlink(missing_ok=True)
            print("Eigener BookBridge-Server beendet. Daten bleiben erhalten.")
            return
        time.sleep(0.25)
    raise RuntimeError("Eigener Server wurde nicht innerhalb von 10 Sekunden beendet.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop"))
    args = parser.parse_args()
    try:
        start() if args.action == "start" else stop()
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error))
