from __future__ import annotations

import ctypes
import json
import mimetypes
import os
import subprocess
import sys
import threading
import time
import webbrowser
from collections import defaultdict
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "local"
scan_state = {"running": False, "files": 0, "folders": 0, "bytes": 0, "path": "", "error": None, "result": None}
lock = threading.Lock()


def fmt_node(path: str, size: int, children=None):
    return {"name": os.path.basename(path.rstrip("\\/")) or path, "path": path, "size": size, "children": children or []}


def scan_folder(path: str):
    type_sizes = defaultdict(int)
    largest = []

    def walk(current: str):
        total = 0
        children = []
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            size, nested = walk(entry.path)
                            children.append(fmt_node(entry.path, size, nested))
                            with lock:
                                scan_state["folders"] += 1
                        else:
                            size = entry.stat(follow_symlinks=False).st_size
                            total += size
                            ext = Path(entry.name).suffix.lower() or "(无扩展名)"
                            type_sizes[ext] += size
                            largest.append((size, entry.name, entry.path, ext))
                            with lock:
                                scan_state["files"] += 1
                                scan_state["bytes"] += size
                    except (PermissionError, FileNotFoundError, OSError):
                        continue
        except (PermissionError, FileNotFoundError, OSError):
            return 0, []
        children.sort(key=lambda n: n["size"], reverse=True)
        total += sum(n["size"] for n in children)
        # 保留完整大小，但只下发最大的 80 个子目录，防止浏览器内存失控。
        return total, children[:80]

    total, children = walk(path)
    largest.sort(reverse=True)
    types = sorted(({"ext": k, "size": v} for k, v in type_sizes.items()), key=lambda x: x["size"], reverse=True)[:20]
    return {"root": fmt_node(path, total, children), "types": types, "largest": [
        {"name": n, "path": p, "size": s, "ext": e} for s, n, p, e in largest[:100]
    ]}


def run_scan(path: str):
    with lock:
        scan_state.update({"running": True, "files": 0, "folders": 0, "bytes": 0, "path": path, "error": None, "result": None})
    try:
        result = scan_folder(path)
        with lock:
            scan_state["result"] = result
    except Exception as exc:
        with lock:
            scan_state["error"] = str(exc)
    finally:
        with lock:
            scan_state["running"] = False


def drives():
    result = []
    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    for i in range(26):
        if bitmask & (1 << i):
            path = f"{chr(65+i)}:\\"
            try:
                free = ctypes.c_ulonglong(0)
                total = ctypes.c_ulonglong(0)
                ctypes.windll.kernel32.GetDiskFreeSpaceExW(path, None, ctypes.pointer(total), ctypes.pointer(free))
                result.append({"path": path, "total": total.value, "free": free.value, "used": total.value - free.value})
            except OSError:
                pass
    return result


def pick_folder():
    code = (
        "import tkinter as tk\n"
        "from tkinter import filedialog\n"
        "root=tk.Tk(); root.withdraw(); root.attributes('-topmost', True)\n"
        "path=filedialog.askdirectory(title='选择要扫描的文件夹', mustexist=True)\n"
        "print(path)\n"
        "root.destroy()\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        timeout=300,
    )
    return completed.stdout.strip()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def log_message(self, format, *args):
        pass

    def send_json(self, data, code=200):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/drives":
            return self.send_json(drives())
        if parsed.path == "/api/status":
            with lock:
                return self.send_json(dict(scan_state))
        if parsed.path == "/api/pick-folder":
            try:
                return self.send_json({"path": pick_folder()})
            except (subprocess.SubprocessError, OSError) as exc:
                return self.send_json({"error": str(exc)}, 500)
        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/scan":
            return self.send_json({"error": "Not found"}, 404)
        length = int(self.headers.get("Content-Length", "0"))
        data = json.loads(self.rfile.read(length) or b"{}")
        path = os.path.abspath(data.get("path", ""))
        if not os.path.exists(path):
            return self.send_json({"error": "路径不存在"}, 400)
        with lock:
            if scan_state["running"]:
                return self.send_json({"error": "已有扫描任务正在运行"}, 409)
        threading.Thread(target=run_scan, args=(path,), daemon=True).start()
        self.send_json({"ok": True, "path": path}, 202)


if __name__ == "__main__":
    print("SpaceLens 本地版已启动：http://127.0.0.1:8765")
    print("关闭此窗口即可停止。所有扫描数据仅保留在内存中。")
    server = ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
    threading.Timer(0.8, lambda: webbrowser.open("http://127.0.0.1:8765")).start()
    server.serve_forever()
