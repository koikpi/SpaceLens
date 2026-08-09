import argparse
import os
import socket
import subprocess
import tempfile
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
    with tempfile.TemporaryFile() as program_log:
        process = subprocess.Popen(
            [str(executable)],
            stdout=program_log,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            env=environment,
        )

        def captured_output():
            program_log.flush()
            program_log.seek(0)
            return program_log.read().decode("utf-8", errors="replace")[-8000:]

        try:
            for _ in range(40):
                if process.poll() is not None:
                    raise RuntimeError(
                        f"Packaged program exited with code {process.returncode}\n{captured_output()}"
                    )
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/drives", timeout=2) as response:
                        if response.status == 200:
                            print("Packaged HTTP smoke test: OK")
                            return
                except OSError:
                    time.sleep(0.5)
            raise RuntimeError(f"Packaged server did not become ready\n{captured_output()}")
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
