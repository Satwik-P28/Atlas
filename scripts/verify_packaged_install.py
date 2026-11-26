#!/usr/bin/env python
"""Certify a built wheel outside the source checkout.

The check that matters for a public distribution is not "the repository tests pass" but
"a user who installs the wheel gets a working Atlas". This harness creates a fresh virtual
environment, installs the wheel from ``dist/`` with the terminal extra, and then exercises
the packaged application from a working directory that contains no checkout:

    atlas init      create and migrate a database
    atlas doctor    verify schema and integrity
    atlas demo      run the offline demonstration on the bundled fixtures
    atlas serve     start the API and the bundled frontend, then read /api/health
    atlas mcp       complete an MCP handshake and call a tool

``PYTHONPATH`` is removed for every step, so the installed package is the only code path.
The report records each step's exit status and duration; a failure exits nonzero.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import venv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "atlas.release.packaged_install.v1"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def venv_paths(directory: Path) -> tuple[Path, Path]:
    if os.name == "nt":
        return directory / "Scripts" / "python.exe", directory / "Scripts" / "atlas.exe"
    return directory / "bin" / "python", directory / "bin" / "atlas"


def clean_env() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items()
           if key not in {"PYTHONPATH", "PYTHONHOME", "ATLAS_DB"}}
    env["PYTHONUNBUFFERED"] = "1"
    return env


def run(command: Sequence[str], *, cwd: Path, timeout: float = 300.0) -> dict[str, Any]:
    started = time.monotonic()
    completed = subprocess.run(list(command), cwd=cwd, capture_output=True, text=True,
                               env=clean_env(), timeout=timeout)
    return {
        "command": [str(part) for part in command],
        "exit": completed.returncode,
        "duration_s": round(time.monotonic() - started, 2),
        "stdout_tail": completed.stdout[-1500:],
        "stderr_tail": completed.stderr[-1500:],
        "ok": completed.returncode == 0,
    }


def _http(url: str, timeout: float = 5.0) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - loopback
            return response.status, response.read(200_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(5_000).decode("utf-8", "replace")


def wait_for_http(url: str, *, timeout: float = 90.0) -> tuple[bool, int, str]:
    deadline = time.monotonic() + timeout
    last: tuple[int, str] = (0, "")
    while time.monotonic() < deadline:
        try:
            status, body = _http(url)
        except (urllib.error.URLError, OSError):
            time.sleep(0.4)
            continue
        last = (status, body)
        if status == 200:
            return True, status, body
        time.sleep(0.4)
    return False, last[0], last[1]


def mcp_handshake(atlas: Path, db: Path, cwd: Path) -> dict[str, Any]:
    """Drive one real MCP session against the installed server.

    Requests are written one at a time and each answer is awaited by its id. Pipelining all
    three and then reading three lines made the check depend on both directions buffering at
    once, which is not how an MCP client behaves and produced a false failure on slower
    runners.
    """
    process = subprocess.Popen(
        [str(atlas), "--db", str(db), "mcp"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1, cwd=cwd, env=clean_env(),
    )
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    def drain(stream: Any, sink: list[str]) -> None:
        if stream is None:
            return
        for line in stream:
            sink.append(line)

    threading.Thread(target=drain, args=(process.stdout, stdout_lines), daemon=True).start()
    threading.Thread(target=drain, args=(process.stderr, stderr_lines), daemon=True).start()

    started = time.monotonic()
    payloads: dict[Any, dict[str, Any]] = {}
    consumed = 0

    def write(message: dict[str, Any]) -> bool:
        if process.stdin is None:
            return False
        try:
            process.stdin.write(json.dumps(message) + "\n")
            process.stdin.flush()
        except (BrokenPipeError, OSError):
            return False
        return True

    def exchange(message: dict[str, Any], *, timeout: float = 60.0) -> dict[str, Any] | None:
        nonlocal consumed
        if not write(message):
            return None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            while consumed < len(stdout_lines):
                line = stdout_lines[consumed]
                consumed += 1
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                payloads[payload.get("id")] = payload
                if payload.get("id") == message["id"]:
                    return payload
            if process.poll() is not None and consumed >= len(stdout_lines):
                return None
            time.sleep(0.05)
        return None

    try:
        exchange({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                  "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                             "clientInfo": {"name": "install-harness", "version": "1"}}})
        # Completes the lifecycle handshake; notifications have no response.
        write({"jsonrpc": "2.0", "method": "notifications/initialized"})
        exchange({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        exchange({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                  "params": {"name": "inspect_data_health", "arguments": {}}})
    finally:
        process.kill()
        process.wait(timeout=20)

    initialize = payloads.get(1) or {}
    tools = payloads.get(2) or {}
    health = payloads.get(3) or {}
    tool_names = [entry.get("name") for entry in (tools.get("result", {}).get("tools") or [])]
    health_result = health.get("result", {}) or {}
    stderr_tail = "".join(stderr_lines)[-1500:]
    result = {
        "duration_s": round(time.monotonic() - started, 2),
        "responses": len(payloads),
        "response_ids": sorted(payloads, key=str),
        "ok": bool(initialize.get("result", {}).get("serverInfo"))
        and len(tool_names) >= 12
        and health_result.get("isError") is False
        and bool(health_result.get("structuredContent")),
        "tool_count": len(tool_names),
        "server_name": initialize.get("result", {}).get("serverInfo", {}).get("name"),
        "protocol_version": initialize.get("result", {}).get("protocolVersion"),
        "health_keys": sorted(health_result.get("structuredContent") or {}),
        "stderr_tail": stderr_tail,
        "error": stderr_tail,
    }
    return result


def certify(wheel: Path, workdir: Path) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    environment = workdir / "venv"
    venv.EnvBuilder(with_pip=True, clear=True).create(environment)
    python, atlas = venv_paths(environment)

    install = run([str(python), "-m", "pip", "install", "--disable-pip-version-check",
                   f"{wheel}[terminal]"], cwd=workdir, timeout=600)
    install["step"] = "pip install wheel[terminal]"
    steps.append(install)
    if not install["ok"]:
        return _report(wheel, workdir, steps, failed="wheel installation failed")

    database = workdir / "atlas.db"
    demo_db = workdir / "demo.db"
    # --db and --json are global options: they must precede the subcommand.
    init = run([str(atlas), "--db", str(database), "init"], cwd=workdir)
    init["step"] = "atlas init"
    steps.append(init)

    doctor = run([str(atlas), "--db", str(database), "--json", "doctor"], cwd=workdir)
    doctor["step"] = "atlas doctor"
    steps.append(doctor)

    demo = run([str(atlas), "--db", str(demo_db), "demo", "--keep"], cwd=workdir, timeout=600)
    # `atlas demo` once ignored --db and populated a different file, which made the MCP step
    # below certify an empty database. Require the requested file to hold the demo data.
    demo["database_created"] = demo_db.is_file()
    demo["ok"] = demo["ok"] and demo["database_created"]
    demo["step"] = "atlas demo (packaged fixtures)"
    steps.append(demo)

    port = free_port()
    log = (workdir / "serve.log").open("w", encoding="utf-8")
    server = subprocess.Popen(
        [str(atlas), "--db", str(demo_db), "serve", "--port", str(port)],
        cwd=workdir, stdout=log, stderr=subprocess.STDOUT, env=clean_env(),
    )
    started = time.monotonic()
    try:
        ready, status, body = wait_for_http(f"http://127.0.0.1:{port}/api/health")
        health: dict[str, Any] = {"step": "atlas serve /api/health", "ok": ready, "exit": 0,
                                  "duration_s": round(time.monotonic() - started, 2),
                                  "status": status, "body_tail": body[:800]}
        if ready:
            try:
                payload = json.loads(body)
                health["release_version"] = payload.get("release_version")
                health["schema_version"] = payload.get("schema_version")
                health["status_value"] = payload.get("status")
                health["ok"] = payload.get("status") == "ok"
            except ValueError:
                health["ok"] = False
            frontend_status, frontend = _http(f"http://127.0.0.1:{port}/")
            health["frontend_status"] = frontend_status
            health["frontend_bundled"] = "<div id=\"root\"" in frontend or "<script" in frontend
            index_status, _ = _http(f"http://127.0.0.1:{port}/api/command/index")
            answers_status, _ = _http(f"http://127.0.0.1:{port}/api/answers/concepts")
            health["command_index_status"] = index_status
            health["answer_concepts_status"] = answers_status
        steps.append(health)
    finally:
        server.terminate()
        try:
            server.wait(timeout=20)
        except subprocess.TimeoutExpired:  # pragma: no cover - a stuck server
            server.kill()
        log.close()

    mcp = mcp_handshake(atlas, demo_db, workdir)
    steps.append({"step": "atlas mcp handshake", **mcp})

    failed = next((step["step"] for step in steps if not step.get("ok")), None)
    return _report(wheel, workdir, steps, failed=failed)


def _report(wheel: Path, workdir: Path, steps: list[dict[str, Any]],
            *, failed: str | None) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "wheel": {"path": wheel.name, "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
                  "bytes": wheel.stat().st_size},
        "workdir": str(workdir),
        "steps": steps,
        "failed_step": failed,
        "ok": failed is None,
        "policy": ("the wheel is installed into a fresh environment with PYTHONPATH removed, so "
                   "the source checkout cannot satisfy an import. Node.js is not required."),
        "exit_code": 0 if failed is None else 1,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=ROOT / "dist")
    parser.add_argument("--workdir", type=Path, default=None)
    parser.add_argument("--out", type=Path,
                        default=ROOT / "artifacts" / "release" / "packaged_install.json")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    # Absolute, because pip runs with cwd set to the temporary certification workdir: a
    # relative --dist would resolve against the wrong directory there.
    dist = Path(args.dist).resolve()
    wheels = sorted(dist.glob("*.whl")) or sorted(dist.rglob("*.whl"))
    if not wheels:
        print(f"no wheel found in {dist}; run scripts/build_release_artifacts.py first",
              file=sys.stderr)
        return 2
    workdir = args.workdir or Path(tempfile.mkdtemp(prefix="atlas-install-"))
    workdir.mkdir(parents=True, exist_ok=True)
    report = certify(wheels[0], workdir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"packaged install: {'ok' if report['ok'] else 'FAILED'}")
        for step in report["steps"]:
            print(f"  {'ok  ' if step.get('ok') else 'fail'} {step['step']} "
                  f"({step.get('duration_s', 0)}s)")
        if report["failed_step"]:
            print(f"  first failure: {report['failed_step']}")
    return int(report["exit_code"])


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
