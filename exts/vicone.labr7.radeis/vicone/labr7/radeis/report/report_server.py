"""Tiny localhost HTTP server for browsing red-team reports inside/alongside
Isaac Sim. Stdlib only (runs in Kit Python). Serves a run-history index plus
each run's self-contained report.html, so the "Open Report" button can launch
the system browser (or an in-Kit webview if available) at a stable URL.
"""
from __future__ import annotations

import http.server
import os
import socketserver
import threading
from typing import Optional


class _Handler(http.server.SimpleHTTPRequestHandler):
    root_dir = "."

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=type(self).root_dir, **kw)

    def do_GET(self):  # noqa: N802
        if self.path in ("/", "/index.html"):
            self._send_index()
            return
        return super().do_GET()

    def _send_index(self):
        runs = []
        try:
            for name in sorted(os.listdir(self.root_dir), reverse=True):
                rp = os.path.join(self.root_dir, name, "report.html")
                if os.path.isfile(rp):
                    runs.append(name)
        except OSError:
            pass
        rows = "".join(
            f'<li><a href="/{r}/report.html">{r}</a></li>' for r in runs
        ) or "<li><i>no runs yet</i></li>"
        html = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<title>Radeis Red-Team — Runs</title>"
            "<style>body{background:#14161c;color:#e9ecf4;font-family:system-ui;"
            "padding:28px}a{color:rgb(232,28,109)}h1{font-weight:700}"
            "li{margin:6px 0;font-family:monospace}</style></head><body>"
            "<h1>LAB <span style='color:rgb(232,28,109)'>R7</span> · Red-Team Runs</h1>"
            f"<ul>{rows}</ul></body></html>"
        )
        data = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):  # silence
        pass


class ReportServer:
    def __init__(self, root_dir: str, port: int = 8770):
        self.root_dir = root_dir
        self.port = port
        self._httpd: Optional[socketserver.TCPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> str:
        os.makedirs(self.root_dir, exist_ok=True)
        handler = type("H", (_Handler,), {"root_dir": self.root_dir})
        for port in range(self.port, self.port + 12):
            try:
                socketserver.TCPServer.allow_reuse_address = True
                self._httpd = socketserver.TCPServer(("127.0.0.1", port), handler)
                self.port = port
                break
            except OSError:
                continue
        if self._httpd is None:
            raise RuntimeError("no free port for report server")
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self.url()

    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    def stop(self):
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd = None
