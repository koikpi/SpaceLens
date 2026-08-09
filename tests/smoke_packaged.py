import argparse
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    args = parser.parse_args()
    executable = args.executable.resolve()
    if not executable.is_file():
        raise SystemExit(f"Executable not found: {executable}")

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    environment = os.environ.copy()
    environment["SPACELENS_PORT"] = str(port)
    environment["SPACELENS_NO_BROWSER"] = "1"
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        [str(executable)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
        env=environment,
    )
    try:
        for _ in range(40):
            if process.poll() is not None:
                raise RuntimeError(f"Packaged program exited with code {process.returncode}")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/drives", timeout=2) as response:
                    if response.status == 200:
                        print("Packaged HTTP smoke test: OK")
                        return
            except OSError:
                time.sleep(0.5)
        raise RuntimeError("Packaged server did not become ready")
    finally:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    main()
