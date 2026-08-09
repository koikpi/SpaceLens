import json
import os
import subprocess
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import local_server


class ScannerTests(unittest.TestCase):
    def setUp(self):
        local_server.cancel_event.clear()
        with local_server.lock:
            local_server.scan_state.update({"files": 0, "folders": 0, "bytes": 0})

    def test_scan_builds_tree_and_search_index(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "中文 目录"
            data.mkdir()
            (root / "small.txt").write_bytes(b"abc")
            (data / "video.mov").write_bytes(b"x" * 2048)
            saved = root / "indexes"

            with patch.object(local_server, "SAVED", saved):
                result, index_path = local_server.scan_folder(str(root))

            try:
                self.assertEqual(result["root"]["size"], 2051)
                self.assertEqual(result["largest"][0]["name"], "video.mov")
                self.assertTrue(index_path.exists())
            finally:
                index_path.unlink(missing_ok=True)

    def test_macos_smb_mount_is_detected(self):
        completed = SimpleNamespace(
            stdout="//user@nas/share on /Volumes/Share (smbfs, nodev, nosuid)\n"
        )
        with patch.object(local_server.subprocess, "run", return_value=completed):
            source, is_network = local_server.macos_mount_details("/Volumes/Share")
        self.assertEqual(source, "//user@nas/share")
        self.assertTrue(is_network)

    def test_macos_reveals_existing_file_in_finder(self):
        calls = []

        def fake_run(*args, **kwargs):
            calls.append((args, kwargs))
            return subprocess.CompletedProcess(args[0], 0)

        with (
            patch.object(local_server.sys, "platform", "darwin"),
            patch.object(local_server.os.path, "normpath", side_effect=lambda value: value),
            patch.object(local_server.os.path, "isfile", return_value=True),
            patch.object(local_server.subprocess, "run", side_effect=fake_run),
        ):
            response = local_server.open_containing_folder("/Volumes/Share/video.mov")

        self.assertTrue(response["ok"])
        self.assertEqual(calls[0][0][0], ["open", "-R", "/Volumes/Share/video.mov"])


class HttpSmokeTests(unittest.TestCase):
    def test_static_page_and_drives_api(self):
        expected = [{"path": "/", "total": 10, "free": 4, "used": 6, "remote": None, "is_network": False}]
        with patch.object(local_server, "drives", return_value=expected):
            server = local_server.ThreadingHTTPServer(("127.0.0.1", 0), local_server.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                with urllib.request.urlopen(base + "/", timeout=5) as response:
                    html = response.read().decode("utf-8")
                with urllib.request.urlopen(base + "/api/drives", timeout=5) as response:
                    drives = json.load(response)
                self.assertIn("SpaceLens", html)
                self.assertEqual(drives, expected)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
