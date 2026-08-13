from __future__ import annotations

import argparse
import ctypes
import gzip
import hashlib
import json
import mimetypes
import os
import plistlib
import re
import shutil
import sqlite3
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

SOURCE_ROOT = Path(__file__).resolve().parent
BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", SOURCE_ROOT))


def application_data_root():
    if not getattr(sys, "frozen", False) and (SOURCE_ROOT / ".git").exists():
        return SOURCE_ROOT
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "SpaceLens"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "SpaceLens"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "SpaceLens"


ROOT = BUNDLE_ROOT
WEB = BUNDLE_ROOT / "local"
SAVED = application_data_root() / "saved_scans"
scan_state = {"running": False, "files": 0, "folders": 0, "bytes": 0, "path": "", "error": None, "result": None, "index_path": None}
lock = threading.Lock()
cancel_event = threading.Event()
duplicate_lock = threading.Lock()
duplicate_cancel = threading.Event()
duplicate_state = {
    "running": False, "phase": "", "path": "", "files": 0, "bytes": 0,
    "candidates": 0, "groups": 0, "reclaimable": 0, "methods": [],
    "result": None, "error": None, "cancelled": False,
}


def open_app_url(address: str) -> bool:
    """Open the local UI with the operating system's native URL handler."""
    try:
        if sys.platform == "darwin":
            completed = subprocess.run(
                ["/usr/bin/open", address],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=10,
            )
            if completed.returncode == 0:
                return True
        elif sys.platform == "win32":
            os.startfile(address)  # type: ignore[attr-defined]
            return True
    except (OSError, subprocess.SubprocessError):
        pass

    try:
        return bool(webbrowser.open(address, new=2))
    except webbrowser.Error:
        return False


def snapshot_path(snapshot_id: str):
    if not snapshot_id or any(c not in "0123456789abcdef" for c in snapshot_id):
        raise ValueError("Invalid snapshot id")
    return SAVED / f"{snapshot_id}.json.gz"


def snapshot_index_path(snapshot_id: str):
    snapshot_path(snapshot_id)
    return SAVED / f"{snapshot_id}.files.db"


def init_file_index(path: Path, complete: bool):
    path.parent.mkdir(exist_ok=True)
    if path.exists():
        path.unlink()
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=OFF")
    connection.execute("PRAGMA synchronous=OFF")
    connection.execute("PRAGMA temp_store=MEMORY")
    connection.execute("CREATE TABLE files (name TEXT NOT NULL, path TEXT PRIMARY KEY, size INTEGER NOT NULL, ext TEXT NOT NULL)")
    connection.execute("CREATE INDEX files_size_desc ON files(size DESC)")
    connection.execute("CREATE INDEX files_name_nocase ON files(name COLLATE NOCASE)")
    connection.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    connection.execute("INSERT INTO meta(key,value) VALUES('complete',?)", ("1" if complete else "0",))
    return connection


def build_legacy_index(snapshot_id: str):
    target = snapshot_index_path(snapshot_id)
    if target.exists():
        return target
    payload = load_snapshot(snapshot_id)
    connection = init_file_index(target, False)
    batch = []
    stack = [payload.get("result", {}).get("root", {})]
    while stack:
        node = stack.pop()
        if not node:
            continue
        if node.get("kind") == "file":
            batch.append((node.get("name", ""), node.get("path", ""), int(node.get("size", 0)), node.get("ext", "")))
            if len(batch) >= 5000:
                connection.executemany("INSERT OR IGNORE INTO files(name,path,size,ext) VALUES(?,?,?,?)", batch)
                batch.clear()
        else:
            stack.extend(node.get("children", []))
    if batch:
        connection.executemany("INSERT OR IGNORE INTO files(name,path,size,ext) VALUES(?,?,?,?)", batch)
    connection.commit()
    connection.close()
    return target


def resolve_file_index(snapshot_id: str = ""):
    if snapshot_id:
        target = snapshot_index_path(snapshot_id)
        return target if target.exists() else build_legacy_index(snapshot_id)
    with lock:
        current = scan_state.get("index_path")
    if current and Path(current).exists():
        return Path(current)
    raise ValueError("当前扫描没有可用的文件索引")


def query_files(snapshot_id: str, query: str, mode: str, limit=5000):
    index = resolve_file_index(snapshot_id)
    connection = sqlite3.connect(index)
    complete_row = connection.execute("SELECT value FROM meta WHERE key='complete'").fetchone()
    complete = bool(complete_row and complete_row[0] == "1")
    limit = max(1, min(int(limit), 5000))
    rows = []
    if mode == "regex":
        try:
            pattern = re.compile(query, re.IGNORECASE)
        except re.error as exc:
            connection.close()
            raise ValueError(f"正则表达式错误：{exc}") from exc
        cursor = connection.execute("SELECT name,path,size,ext FROM files ORDER BY size DESC")
        for row in cursor:
            if pattern.search(row[0]):
                rows.append(row)
                if len(rows) > limit:
                    break
    else:
        rows = connection.execute(
            "SELECT name,path,size,ext FROM files WHERE instr(lower(name),lower(?))>0 ORDER BY size DESC LIMIT ?",
            (query, limit + 1),
        ).fetchall()
    connection.close()
    has_more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [{"name": name, "path": path, "size": size, "ext": ext} for name, path, size, ext in rows],
        "has_more": has_more,
        "complete": complete,
    }


def largest_files(snapshot_id: str, limit=1000):
    index = resolve_file_index(snapshot_id)
    connection = sqlite3.connect(index)
    complete_row = connection.execute("SELECT value FROM meta WHERE key='complete'").fetchone()
    rows = connection.execute(
        "SELECT name,path,size,ext FROM files ORDER BY size DESC LIMIT ?",
        (max(1, min(int(limit), 5000)),),
    ).fetchall()
    connection.close()
    return {
        "items": [{"name": name, "path": path, "size": size, "ext": ext} for name, path, size, ext in rows],
        "complete": bool(complete_row and complete_row[0] == "1"),
    }


def resolve_mapped_path(file_path: str):
    normalized = os.path.normpath(file_path)
    if sys.platform != "win32":
        return normalized
    drive, tail = os.path.splitdrive(normalized)
    if len(drive) != 2 or drive[1] != ":":
        return normalized
    try:
        remote_buffer = ctypes.create_unicode_buffer(32768)
        remote_length = ctypes.c_ulong(len(remote_buffer))
        result = ctypes.windll.mpr.WNetGetConnectionW(
            drive, remote_buffer, ctypes.byref(remote_length)
        )
    except (AttributeError, OSError):
        return normalized
    if result != 0 or not remote_buffer.value:
        return normalized
    return remote_buffer.value.rstrip("\\/") + tail


def nearest_existing_folder(file_path: str):
    candidates = [os.path.normpath(file_path)]
    mapped = resolve_mapped_path(file_path)
    if mapped != candidates[0]:
        candidates.insert(0, mapped)
    for candidate in candidates:
        folder = candidate if os.path.isdir(candidate) else os.path.dirname(candidate)
        for _ in range(32):
            if folder and os.path.isdir(folder):
                return folder
            parent = os.path.dirname(folder.rstrip("\\/"))
            if not parent or parent == folder:
                break
            folder = parent
    raise ValueError("文件已经移动、删除，或当前无法连接群晖网络共享")


def open_containing_folder(file_path: str):
    if not file_path.strip():
        raise ValueError("缺少文件路径")
    normalized = os.path.normpath(file_path)
    mapped = resolve_mapped_path(normalized)
    candidates = list(dict.fromkeys((mapped, normalized)))
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            if sys.platform == "darwin":
                if os.path.isfile(candidate):
                    subprocess.run(["open", "-R", candidate], check=True)
                    return {"ok": True, "opened_path": candidate}
                folder = nearest_existing_folder(candidate)
                subprocess.run(["open", folder], check=True)
            elif sys.platform == "win32":
                folder = nearest_existing_folder(candidate)
                os.startfile(folder)
            else:
                folder = nearest_existing_folder(candidate)
                subprocess.run(["xdg-open", folder], check=True)
            return {"ok": True, "opened_path": folder}
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            last_error = exc
    raise ValueError(f"无法打开文件所在目录：{last_error or '磁盘或网络共享不可用'}")


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
        current_index = scan_state.get("index_path")
        meta = {
            "name": (name or "").strip()[:80] or scan_state.get("path") or "未命名扫描",
            "path": scan_state.get("path", ""),
            "created": int(time.time()),
            "files": scan_state.get("files", 0),
            "folders": scan_state.get("folders", 0),
            "bytes": result["root"]["size"] if result else 0,
            "automatic": automatic,
            "search_index": bool(current_index and Path(current_index).exists()),
        }
    if not result:
        raise ValueError("没有可保存的扫描结果")
    SAVED.mkdir(exist_ok=True)
    snapshot_id = uuid.uuid4().hex
    with gzip.open(snapshot_path(snapshot_id), "wt", encoding="utf-8", compresslevel=6) as stream:
        json.dump({"meta": meta, "result": result}, stream, ensure_ascii=False, separators=(",", ":"))
    if current_index and Path(current_index).exists():
        shutil.copy2(current_index, snapshot_index_path(snapshot_id))
    meta["id"] = snapshot_id
    return meta


def load_snapshot(snapshot_id: str):
    with gzip.open(snapshot_path(snapshot_id), "rt", encoding="utf-8") as stream:
        return json.load(stream)


def sample_hash(path: str, size: int):
    digest = hashlib.blake2b(digest_size=16)
    chunk = 64 * 1024
    with open(path, "rb") as stream:
        positions = [0, max(0, size // 2 - chunk // 2), max(0, size - chunk)]
        for position in positions:
            stream.seek(position)
            digest.update(stream.read(chunk))
    return digest.hexdigest()


def full_hash(path: str):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while not duplicate_cancel.is_set():
            block = stream.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def same_content(first: str, second: str):
    with open(first, "rb") as left, open(second, "rb") as right:
        while not duplicate_cancel.is_set():
            a = left.read(1024 * 1024)
            b = right.read(1024 * 1024)
            if a != b:
                return False
            if not a:
                return True
    return False


def regroup(groups, key_function):
    output = []
    for group in groups:
        buckets = defaultdict(list)
        for item in group:
            if duplicate_cancel.is_set():
                return []
            try:
                buckets[key_function(item)].append(item)
            except (PermissionError, FileNotFoundError, OSError):
                continue
        output.extend(bucket for bucket in buckets.values() if len(bucket) > 1)
    return output


def regroup_by_bytes(groups):
    output = []
    for group in groups:
        exact = []
        for item in group:
            if duplicate_cancel.is_set():
                return []
            placed = False
            for bucket in exact:
                try:
                    if same_content(bucket[0], item):
                        bucket.append(item)
                        placed = True
                        break
                except (PermissionError, FileNotFoundError, OSError):
                    placed = True
                    break
            if not placed:
                exact.append([item])
        output.extend(bucket for bucket in exact if len(bucket) > 1)
    return output


def run_duplicate_scan(path: str, methods, min_size: int):
    duplicate_cancel.clear()
    with duplicate_lock:
        duplicate_state.update({
            "running": True, "phase": "正在按大小分组", "path": path, "files": 0,
            "bytes": 0, "candidates": 0, "groups": 0, "reclaimable": 0,
            "methods": methods, "result": None, "error": None, "cancelled": False,
        })
    try:
        by_size = defaultdict(list)
        for folder, dirs, files in os.walk(path, followlinks=False):
            if duplicate_cancel.is_set():
                break
            dirs[:] = [name for name in dirs if not os.path.islink(os.path.join(folder, name))]
            for name in files:
                if duplicate_cancel.is_set():
                    break
                file_path = os.path.join(folder, name)
                try:
                    if os.path.islink(file_path):
                        continue
                    size = os.path.getsize(file_path)
                    if size >= min_size:
                        by_size[size].append(file_path)
                    with duplicate_lock:
                        duplicate_state["files"] += 1
                        duplicate_state["bytes"] += size
                except (PermissionError, FileNotFoundError, OSError):
                    continue
        groups = [items for items in by_size.values() if len(items) > 1]
        with duplicate_lock:
            duplicate_state["candidates"] = sum(len(items) for items in groups)
        if "quick" in methods and not duplicate_cancel.is_set():
            with duplicate_lock:
                duplicate_state["phase"] = "正在计算分段快速指纹"
            groups = regroup(groups, lambda item: sample_hash(item, os.path.getsize(item)))
        if "sha256" in methods and not duplicate_cancel.is_set():
            with duplicate_lock:
                duplicate_state["phase"] = "正在计算完整 SHA-256"
            groups = regroup(groups, full_hash)
        if "byte" in methods and not duplicate_cancel.is_set():
            with duplicate_lock:
                duplicate_state["phase"] = "正在逐字节确认"
            groups = regroup_by_bytes(groups)
        if duplicate_cancel.is_set():
            with duplicate_lock:
                duplicate_state["cancelled"] = True
            return
        results = []
        reclaimable = 0
        for items in groups:
            try:
                size = os.path.getsize(items[0])
            except OSError:
                continue
            reclaim = size * (len(items) - 1)
            reclaimable += reclaim
            results.append({"size": size, "reclaimable": reclaim, "paths": items})
        results.sort(key=lambda group: group["reclaimable"], reverse=True)
        with duplicate_lock:
            duplicate_state.update({
                "phase": "完成", "groups": len(results), "reclaimable": reclaimable,
                "result": results[:2000], "truncated": len(results) > 2000,
            })
    except Exception as exc:
        with duplicate_lock:
            duplicate_state["error"] = str(exc)
    finally:
        with duplicate_lock:
            duplicate_state["running"] = False


def fmt_node(path: str, size: int, children=None, kind="folder", ext=""):
    return {"name": os.path.basename(path.rstrip("\\/")) or path, "path": path, "size": size,
            "children": children or [], "kind": kind, "ext": ext}


def scan_folder(path: str):
    type_sizes = defaultdict(int)
    SAVED.mkdir(exist_ok=True)
    index_path = SAVED / f"_scan-{uuid.uuid4().hex}.files.db"
    index_connection = init_file_index(index_path, True)
    index_batch = []

    def flush_index():
        if index_batch:
            index_connection.executemany(
                "INSERT OR IGNORE INTO files(name,path,size,ext) VALUES(?,?,?,?)",
                index_batch,
            )
            index_batch.clear()

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
                            index_batch.append((entry.name, entry.path, size, ext))
                            if len(index_batch) >= 5000:
                                flush_index()
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

    try:
        total, children = walk(path)
        flush_index()
        index_connection.commit()
        largest = index_connection.execute(
            "SELECT name,path,size,ext FROM files ORDER BY size DESC LIMIT 100"
        ).fetchall()
        types = sorted(({"ext": k, "size": v} for k, v in type_sizes.items()), key=lambda x: x["size"], reverse=True)[:20]
        result = {"root": fmt_node(path, total, children), "types": types, "largest": [
            {"name": name, "path": file_path, "size": size, "ext": ext}
            for name, file_path, size, ext in largest
        ], "search_index_complete": True}
        return result, index_path
    except Exception:
        index_connection.close()
        if index_path.exists():
            index_path.unlink()
        raise
    finally:
        try:
            index_connection.close()
        except sqlite3.Error:
            pass


def run_scan(path: str):
    cancel_event.clear()
    completed = False
    with lock:
        scan_state.update({"running": True, "cancelled": False, "files": 0, "folders": 0, "bytes": 0, "path": path, "error": None, "result": None, "index_path": None})
    try:
        result, temporary_index = scan_folder(path)
        with lock:
            if cancel_event.is_set():
                scan_state["cancelled"] = True
                if temporary_index.exists():
                    temporary_index.unlink()
            else:
                current_index = SAVED / "_current.files.db"
                os.replace(temporary_index, current_index)
                scan_state["result"] = result
                scan_state["index_path"] = str(current_index)
                completed = True
        if completed:
            try:
                meta = save_snapshot(f"自动快照 · {path}", automatic=True)
                with lock:
                    scan_state["snapshot_id"] = meta["id"]
            except OSError:
                pass
    except Exception as exc:
        with lock:
            scan_state["error"] = str(exc)
    finally:
        with lock:
            scan_state["running"] = False


def windows_drives():
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


def macos_mount_details(path: str):
    """Return a best-effort source/type description for a macOS mount."""
    normalized = os.path.normpath(path)
    try:
        completed = subprocess.run(
            ["/sbin/mount"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        for line in completed.stdout.splitlines():
            match = re.match(r"^(.+?) on (.+?) \(([^,\s)]+)", line)
            if not match:
                continue
            source, mount_path, filesystem = match.groups()
            mount_path = mount_path.replace("\\040", " ")
            if os.path.normpath(mount_path) != normalized:
                continue
            filesystem = filesystem.lower()
            is_network = filesystem in {"smbfs", "afpfs", "nfs", "webdav"} or source.startswith("//")
            return source, is_network
    except (OSError, subprocess.SubprocessError):
        pass

    try:
        completed = subprocess.run(
            ["diskutil", "info", "-plist", path],
            capture_output=True,
            check=True,
            timeout=10,
        )
        info = plistlib.loads(completed.stdout)
        protocol = str(info.get("BusProtocol") or info.get("FilesystemType") or "")
        source = str(info.get("MountFrom") or info.get("DeviceNode") or "")
        is_network = bool(info.get("NetworkVolume")) or protocol.lower() in {
            "smbfs", "afpfs", "nfs", "webdav",
        }
        return source or None, is_network
    except (OSError, subprocess.SubprocessError, plistlib.InvalidFileException):
        return None, False


def unix_drive(path: str, remote=None, is_network=False):
    usage = shutil.disk_usage(path)
    return {
        "path": path,
        "total": usage.total,
        "free": usage.free,
        "used": usage.used,
        "remote": remote,
        "is_network": is_network,
    }


def macos_drives():
    paths = ["/"]
    volumes = Path("/Volumes")
    if volumes.is_dir():
        try:
            paths.extend(
                str(item)
                for item in sorted(volumes.iterdir(), key=lambda item: item.name.lower())
                if item.is_dir() and os.path.ismount(item)
            )
        except (PermissionError, OSError):
            pass

    result = []
    seen = set()
    for path in paths:
        try:
            identity = os.path.realpath(path)
            if identity in seen:
                continue
            seen.add(identity)
            remote, is_network = macos_mount_details(path)
            result.append(unix_drive(path, remote, is_network))
        except OSError:
            continue
    return result


def drives():
    if sys.platform == "win32":
        return windows_drives()
    if sys.platform == "darwin":
        return macos_drives()
    try:
        return [unix_drive("/")]
    except OSError:
        return []


def pick_folder():
    if sys.platform == "darwin":
        try:
            completed = subprocess.run(
                [
                    "osascript",
                    "-e",
                    'POSIX path of (choose folder with prompt "选择要扫描的文件夹")',
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=300,
            )
            return os.path.normpath(completed.stdout.strip())
        except subprocess.CalledProcessError as exc:
            # AppleScript returns a cancellation error when the user closes the picker.
            if exc.returncode == 1:
                return ""
            raise
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

    def send_gzip_json_file(self, file: Path):
        size = file.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "private, max-age=31536000, immutable")
        self.end_headers()
        with open(file, "rb") as stream:
            while True:
                block = stream.read(1024 * 1024)
                if not block:
                    break
                self.wfile.write(block)

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
                return self.send_gzip_json_file(snapshot_path(snapshot_id))
            except (ValueError, OSError) as exc:
                return self.send_json({"error": str(exc)}, 404)
        if parsed.path == "/api/files/largest":
            try:
                params = parse_qs(parsed.query)
                snapshot_id = params.get("snapshot_id", [""])[0]
                limit = int(params.get("limit", ["1000"])[0])
                return self.send_json(largest_files(snapshot_id, limit))
            except (ValueError, OSError, sqlite3.Error, json.JSONDecodeError) as exc:
                return self.send_json({"error": str(exc)}, 400)
        if parsed.path == "/api/duplicates/status":
            with duplicate_lock:
                return self.send_json(dict(duplicate_state))
        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/cancel":
            cancel_event.set()
            return self.send_json({"ok": True})
        if parsed.path == "/api/duplicates/cancel":
            duplicate_cancel.set()
            return self.send_json({"ok": True})
        if parsed.path == "/api/duplicates/start":
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(length) or b"{}")
            path = os.path.abspath(data.get("path", ""))
            methods = [method for method in data.get("methods", []) if method in {"quick", "sha256", "byte"}]
            min_size = max(1, int(data.get("min_size", 1024 * 1024)))
            if not os.path.exists(path):
                return self.send_json({"error": "路径不存在"}, 400)
            with duplicate_lock:
                if duplicate_state["running"]:
                    return self.send_json({"error": "重复文件检测正在运行"}, 409)
            with lock:
                if scan_state["running"]:
                    return self.send_json({"error": "请等待磁盘扫描完成"}, 409)
            threading.Thread(
                target=run_duplicate_scan, args=(path, methods, min_size), daemon=True
            ).start()
            return self.send_json({"ok": True}, 202)
        if parsed.path == "/api/files/search":
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(length) or b"{}")
            query = str(data.get("query", ""))
            if not query:
                return self.send_json({"error": "请输入文件名或正则表达式"}, 400)
            try:
                mode = "regex" if data.get("mode") == "regex" else "name"
                return self.send_json(query_files(
                    str(data.get("snapshot_id", "")),
                    query,
                    mode,
                    int(data.get("limit", 5000)),
                ))
            except (ValueError, OSError, sqlite3.Error, json.JSONDecodeError) as exc:
                return self.send_json({"error": str(exc)}, 400)
        if parsed.path == "/api/open-folder":
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(length) or b"{}")
            try:
                return self.send_json(open_containing_folder(str(data.get("path", ""))))
            except (ValueError, OSError) as exc:
                return self.send_json({"error": str(exc)}, 400)
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
                index_file = snapshot_index_path(data.get("id", ""))
                if index_file.exists():
                    index_file.unlink()
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


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="spacelens",
        description="Privacy-first local disk space analyzer for Windows and macOS.",
    )
    parser.add_argument("--port", type=int, default=int(os.environ.get("SPACELENS_PORT", "8765")), help="local HTTP port (default: 8765)")
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser automatically")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    port = args.port
    address = f"http://127.0.0.1:{port}"
    system_name = "macOS" if sys.platform == "darwin" else "Windows" if sys.platform == "win32" else sys.platform
    print(f"SpaceLens {system_name} 本地版已启动：{address}")
    print("关闭此窗口即可停止。所有扫描结果和文件索引仅保存在本机。")
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    if not args.no_browser and os.environ.get("SPACELENS_NO_BROWSER") != "1":
        browser_timer = threading.Timer(0.8, open_app_url, args=(address,))
        browser_timer.daemon = True
        browser_timer.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nSpaceLens stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
