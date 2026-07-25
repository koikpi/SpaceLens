from __future__ import annotations

import ctypes
import gzip
import json
import mimetypes
import os
import subprocess
import sys
import threading
import time
import webbrowser
import uuid
from collections import defaultdict
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "local"
SAVED = ROOT / "saved_scans"
scan_state = {"running": False, "files": 0, "folders": 0, "bytes": 0, "path": "", "error": None, "result": None}
lock = threading.Lock()
cancel_event = threading.Event()


def snapshot_path(snapshot_id: str):
    if not snapshot_id or any(c not in "0123456789abcdef" for c in snapshot_id):
        raise ValueError("Invalid snapshot id")
    return SAVED / f"{snapshot_id}.json.gz"


def list_snapshots():
    SAVED.mkdir(exist_ok=True)
    items = []
    for file in SAVED.glob("*.json.gz"):
        try:
            with gzip.open(file, "rt", encoding="utf-8") as stream:
                payload = json.load(stream)
            meta = payload.get("meta", {})
            meta["id"] = file.name.removesuffix(".json.gz")
            items.append(meta)
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(items, key=lambda item: item.get("created", 0), reverse=True)


def save_snapshot(name: str, automatic=False):
    with lock:
        result = scan_state.get("result")
        meta = {
            "name": (name or "").strip()[:80] or scan_state.get("path") or "未命名扫描",
            "path": scan_state.get("path", ""),
            "created": int(time.time()),
            "files": scan_state.get("files", 0),
            "folders": scan_state.get("folders", 0),
            "bytes": result["root"]["size"] if result else 0,
            "automatic": automatic,
        }
    if not result:
        raise ValueError("没有可保存的扫描结果")
    SAVED.mkdir(exist_ok=True)
    snapshot_id = uuid.uuid4().hex
    with gzip.open(snapshot_path(snapshot_id), "wt", encoding="utf-8", compresslevel=6) as stream:
        json.dump({"meta": meta, "result": result}, stream, ensure_ascii=False, separators=(",", ":"))
    meta["id"] = snapshot_id
    return meta


def load_snapshot(snapshot_id: str):
    with gzip.open(snapshot_path(snapshot_id), "rt", encoding="utf-8") as stream:
        return json.load(stream)


def fmt_node(path: str, size: int, children=None, kind="folder", ext=""):
    return {"name": os.path.basename(path.rstrip("\\/")) or path, "path": path, "size": size,
            "children": children or [], "kind": kind, "ext": ext}


def scan_folder(path: str):
    type_sizes = defaultdict(int)
    largest = []

    def walk(current: str):
        if cancel_event.is_set():
            return 0, []
        total = 0
        children = []
        files_here = []
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if cancel_event.is_set():
                        break
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
                            ext = Path(entry.name).suffix.lower() or "(无扩展名)"
                            type_sizes[ext] += size
                            largest.append((size, entry.name, entry.path, ext))
                            files_here.append(fmt_node(entry.path, size, kind="file", ext=ext))
                            with lock:
                                scan_state["files"] += 1
                                scan_state["bytes"] += size
                    except (PermissionError, FileNotFoundError, OSError):
                        continue
        except (PermissionError, FileNotFoundError, OSError):
            return 0, []
        children.extend(files_here)
        children.sort(key=lambda n: n["size"], reverse=True)
        total += sum(n["size"] for n in children)
        # 保留完整大小，但只下发最大的 80 个子目录，防止浏览器内存失控。
        return total, children[:120]

    total, children = walk(path)
    largest.sort(reverse=True)
    types = sorted(({"ext": k, "size": v} for k, v in type_sizes.items()), key=lambda x: x["size"], reverse=True)[:20]
    return {"root": fmt_node(path, total, children), "types": types, "largest": [
        {"name": n, "path": p, "size": s, "ext": e} for s, n, p, e in largest[:100]
    ]}


def run_scan(path: str):
    cancel_event.clear()
    completed = False
    with lock:
        scan_state.update({"running": True, "cancelled": False, "files": 0, "folders": 0, "bytes": 0, "path": path, "error": None, "result": None})
    try:
        result = scan_folder(path)
        with lock:
            if cancel_event.is_set():
                scan_state["cancelled"] = True
            else:
                scan_state["result"] = result
                completed = True
        if completed:
            try:
                save_snapshot(f"自动快照 · {path}", automatic=True)
            except OSError:
                pass
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
            letter = f"{chr(65+i)}:"
            path = f"{letter}\\"
            try:
                free = ctypes.c_ulonglong(0)
                total = ctypes.c_ulonglong(0)
                ctypes.windll.kernel32.GetDiskFreeSpaceExW(path, None, ctypes.pointer(total), ctypes.pointer(free))
                remote_buffer = ctypes.create_unicode_buffer(2048)
                remote_length = ctypes.c_ulong(len(remote_buffer))
                remote_result = ctypes.windll.mpr.WNetGetConnectionW(
                    letter, remote_buffer, ctypes.byref(remote_length)
                )
                remote = remote_buffer.value if remote_result == 0 else None
                result.append({
                    "path": path, "total": total.value, "free": free.value,
                    "used": total.value - free.value, "remote": remote,
                    "is_network": bool(remote),
                })
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
        if parsed.path == "/api/snapshots":
            return self.send_json(list_snapshots())
        if parsed.path == "/api/snapshot":
            try:
                snapshot_id = parse_qs(parsed.query).get("id", [""])[0]
                return self.send_json(load_snapshot(snapshot_id))
            except (ValueError, OSError, json.JSONDecodeError) as exc:
                return self.send_json({"error": str(exc)}, 404)
        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/cancel":
            cancel_event.set()
            return self.send_json({"ok": True})
        if parsed.path == "/api/save":
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(length) or b"{}")
            try:
                return self.send_json(save_snapshot(data.get("name", "")), 201)
            except ValueError as exc:
                return self.send_json({"error": str(exc)}, 400)
        if parsed.path == "/api/delete-snapshot":
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(length) or b"{}")
            try:
                file = snapshot_path(data.get("id", ""))
                file.unlink()
                return self.send_json({"ok": True})
            except (ValueError, OSError) as exc:
                return self.send_json({"error": str(exc)}, 400)
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
