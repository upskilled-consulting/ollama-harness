#!/usr/bin/env python3
"""
start.py — Windows-compatible service launcher.

Usage:
    python start.py                      # start all services
    python start.py api mcp dashboard    # start subset
    python start.py --no-llama           # skip GPU binary

Differences from honcho:
  - taskkill /F /T kills entire process trees (vite child, CUDA threads, etc.)
  - One service exiting does NOT kill the others
  - Ports are freed before starting (kills stale holders)
"""

from __future__ import annotations
import argparse, os, socket, subprocess, sys, time
from threading import Thread

SERVICES: dict[str, str] = {
    "api":       "uvicorn harness.api.main:app --host 0.0.0.0 --port 7860",
    "mcp":       "python -m harness.mcp_server --http --host 0.0.0.0 --port 8766",
    "dashboard": "node dashboard/node_modules/vite/bin/vite.js dashboard --host 0.0.0.0",
    "ollama":    "ollama serve",
    "llama":     r"llama.cpp\build\bin\llama-server.exe"
                 r" --model models\Qwen3.6-35B-A3B-UD-IQ3_S.gguf"
                 r" --ctx-size 8192 --parallel 1 --port 8083 -ngl 99 --flash-attn",
}

PORT_MAP = {"api": 7860, "mcp": 8766, "dashboard": 5173, "ollama": 11434, "llama": 8083}

_procs: dict[str, subprocess.Popen] = {}


def _taskkill(pid: int) -> None:
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)


def _port_listening(port: int) -> bool:
    r = subprocess.run(["netstat", "-ano"], capture_output=True, text=True)
    return any(f":{port} " in l and "LISTENING" in l for l in r.stdout.splitlines())


def _kill_port(port: int) -> None:
    """Kill any process holding a TCP port, then wait until the socket is free."""
    r = subprocess.run(["netstat", "-ano"], capture_output=True, text=True)
    for line in r.stdout.splitlines():
        if f":{port} " in line and "LISTENING" in line:
            parts = line.split()
            pid = int(parts[-1])
            if pid > 4:  # skip System (PID 4)
                _taskkill(pid)
    # Poll until the OS releases the port (up to 8 s)
    for _ in range(16):
        if not _port_listening(port):
            return
        time.sleep(0.5)


def _wait_ready(port: int, timeout: int = 20) -> bool:
    """Return True once a TCP connection to localhost:port succeeds."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def _stream(name: str, proc: subprocess.Popen) -> None:
    for line in proc.stdout:
        sys.stdout.write(f"{name:12}| {line}")
        sys.stdout.flush()


def _start(name: str, cmd: str) -> None:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"]       = "1"
    proc = subprocess.Popen(
        cmd, shell=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, encoding="utf-8", env=env,
    )
    _procs[name] = proc
    Thread(target=_stream, args=(name, proc), daemon=True).start()
    print(f"[start] {name} started (pid={proc.pid})", flush=True)


def _shutdown() -> None:
    print("\n[start] shutting down all services...", flush=True)
    for name, proc in list(_procs.items()):
        print(f"[start] killing {name} (pid={proc.pid})", flush=True)
        _taskkill(proc.pid)
    _procs.clear()


def main() -> None:
    parser = argparse.ArgumentParser(description="Start harness services")
    parser.add_argument("services", nargs="*", default=list(SERVICES))
    parser.add_argument("--no-llama", action="store_true", help="skip llama-server")
    args = parser.parse_args()

    chosen = args.services
    if args.no_llama and "llama" in chosen:
        chosen = [s for s in chosen if s != "llama"]

    invalid = [s for s in chosen if s not in SERVICES]
    if invalid:
        print(f"[start] unknown service(s): {', '.join(invalid)}")
        print(f"[start] available: {', '.join(SERVICES)}")
        sys.exit(1)

    # Build dashboard dist so port 7860 always serves fresh UI
    import os
    dashboard_dir = os.path.join(os.path.dirname(__file__), "dashboard")
    if os.path.isdir(dashboard_dir):
        print("[start] building dashboard…", flush=True)
        result = subprocess.run(
            "npm run build",
            cwd=dashboard_dir,
            capture_output=True, text=True,
            shell=True,
        )
        if result.returncode == 0:
            print("[start] dashboard built ok", flush=True)
        else:
            print("[start] dashboard build FAILED — continuing anyway", flush=True)
            print(result.stderr[-2000:], flush=True)

    # Free stale port holders before starting (each _kill_port waits until free)
    for name in chosen:
        if name in PORT_MAP:
            _kill_port(PORT_MAP[name])

    for name in chosen:
        _start(name, SERVICES[name])
        # Wait for API to be ready before starting the dashboard so the Vite
        # proxy doesn't flood the console with ECONNREFUSED errors on startup.
        if name == "api" and "dashboard" in chosen:
            if _wait_ready(PORT_MAP["api"]):
                print("[start] api ready", flush=True)
            else:
                print("[start] api did not respond within 20s — starting dashboard anyway", flush=True)

    print("[start] all services started. Ctrl+C to stop.", flush=True)
    try:
        while True:
            time.sleep(2)
            for name, proc in list(_procs.items()):
                rc = proc.poll()
                if rc is not None:
                    print(f"[start] {name} exited (rc={rc})", flush=True)
    except KeyboardInterrupt:
        _shutdown()


if __name__ == "__main__":
    main()
