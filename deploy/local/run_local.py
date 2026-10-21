"""Runs the full local-mode test (pieces #2-#4, plus #1 if the Gateway is
already provisioned) with one command: starts the local MCP tool server,
waits for it to be reachable, runs the agent, then stops the server.

Usage:
    python deploy/local/run_local.py
    python deploy/local/run_local.py "What's 12 * (3 + 4)?"
"""

import socket
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MCP_SERVER = REPO_ROOT / "app" / "mcp_tool" / "server.py"
AGENT = REPO_ROOT / "app" / "agent" / "agent.py"
MCP_HOST, MCP_PORT = "127.0.0.1", 8000


def wait_for_port(host: str, port: int, proc: subprocess.Popen, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"Local MCP server exited early (code {proc.returncode})")
        try:
            with socket.create_connection((host, port), timeout=1):
                return
        except OSError:
            time.sleep(0.3)
    raise TimeoutError(f"{host}:{port} did not become reachable within {timeout}s")


def main() -> None:
    prompt_args = sys.argv[1:]

    print("[run_local] Starting local MCP tool server...")
    server_proc = subprocess.Popen([sys.executable, str(MCP_SERVER)], cwd=REPO_ROOT)
    try:
        wait_for_port(MCP_HOST, MCP_PORT, server_proc)
        print(f"[run_local] Local MCP server is up on {MCP_HOST}:{MCP_PORT}.")

        print("[run_local] Running agent...\n")
        subprocess.run([sys.executable, str(AGENT), *prompt_args], cwd=REPO_ROOT, check=True)
    finally:
        print("\n[run_local] Stopping local MCP server.")
        server_proc.terminate()
        try:
            server_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server_proc.kill()


if __name__ == "__main__":
    main()
