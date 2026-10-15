"""Small read-only leaderboard dashboard for Racer Check Bot."""
from __future__ import annotations

import html
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


class DashboardHandler(BaseHTTPRequestHandler):
    db_path: Path
    dashboard_token: str = ""

    def log_message(self, *_args: object) -> None:
        return

    def authorized(self) -> bool:
        if not self.dashboard_token:
            return True
        query_token = parse_qs(urlparse(self.path).query).get("token", [""])[0]
        return query_token == self.dashboard_token or self.headers.get("X-Dashboard-Token") == self.dashboard_token

    def send_text(self, status: int, content: str, content_type: str = "text/html; charset=utf-8") -> None:
        body = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            self.send_text(200, "ok", "text/plain; charset=utf-8")
            return
        if path != "/" or not self.authorized():
            self.send_text(403, "forbidden", "text/plain; charset=utf-8")
            return
        try:
            with sqlite3.connect(self.db_path, timeout=5) as connection:
                rows = connection.execute(
                    "SELECT username, score, passed, checks FROM users ORDER BY score DESC, id"
                ).fetchall()
        except sqlite3.Error:
            self.send_text(503, "database unavailable", "text/plain; charset=utf-8")
            return
        table_rows = "".join(
            "<tr><td>{}</td><td>@{}</td><td>{}</td><td>{}/{}</td></tr>".format(
                index,
                html.escape(str(username or "ไม่มี username")),
                score,
                passed,
                checks,
            )
            for index, (username, score, passed, checks) in enumerate(rows, 1)
        )
        if not table_rows:
            table_rows = '<tr><td colspan="5">ยังไม่มีผู้ร่วมงาน</td></tr>'
        page = f"""<!doctype html>
<html lang="th"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="10"><title>Racer Board</title>
<style>body{{font-family:system-ui,sans-serif;background:#111;color:#fff;margin:0;padding:24px}}main{{max-width:850px;margin:auto}}h1{{color:#ffd700}}table{{width:100%;border-collapse:collapse;background:#1a1a1a}}th,td{{padding:12px;text-align:left;border-bottom:1px solid #333}}th{{color:#ffd700}}tr:nth-child(even){{background:#222}}small{{color:#aaa}}</style></head>
<body><main><h1>🏆 Racer Leaderboard</h1><small>อัปเดตอัตโนมัติทุก 10 วินาที</small><table><thead><tr><th>#</th><th>User</th><th>คะแนน</th><th>ผ่าน/ส่งงาน</th></tr></thead><tbody>{table_rows}</tbody></table></main></body></html>"""
        self.send_text(200, page)


def serve_dashboard(db_path: Path, port: int) -> None:
    handler = type("ConfiguredDashboardHandler", (DashboardHandler,), {})
    handler.db_path = Path(db_path)
    handler.dashboard_token = os.getenv("DASHBOARD_TOKEN", "")
    server = ThreadingHTTPServer(("0.0.0.0", port), handler)
    print(f"Dashboard listening on 0.0.0.0:{port}")
    server.serve_forever()


if __name__ == "__main__":
    serve_dashboard(Path(os.getenv("DB_PATH", "score.db")), int(os.getenv("PORT", "8080")))
