"""
HTTP server for the pizza price dashboard.
  GET  /*             → static files (dashboard.html, data/, ...)
  POST /run-scrape    → run multi_scraper.py, stream stdout as text/plain
Run: python server.py
Then open: http://localhost:8765/dashboard.html
"""

import http.server
import socketserver
import subprocess
import sys
import os
import threading

PORT = 8765
DIR  = os.path.dirname(os.path.abspath(__file__))


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIR, **kwargs)

    def log_message(self, fmt, *args):
        pass  # suppress access logs

    def do_POST(self):
        if self.path != "/run-scrape":
            self.send_error(404)
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        scraper = os.path.join(DIR, "multi_scraper.py")
        try:
            proc = subprocess.Popen(
                [sys.executable, scraper],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=DIR,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            for line in proc.stdout:
                try:
                    self.wfile.write(line.encode("utf-8"))
                    self.wfile.flush()
                except BrokenPipeError:
                    proc.kill()
                    break
            proc.wait()
            status = "OK" if proc.returncode == 0 else f"ERROR (exit {proc.returncode})"
            self.wfile.write(f"\n__DONE__{status}__\n".encode("utf-8"))
        except Exception as e:
            try:
                self.wfile.write(f"\n__DONE__ERROR: {e}__\n".encode("utf-8"))
            except Exception:
                pass

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.end_headers()


class ThreadedServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    os.chdir(DIR)
    with ThreadedServer(("", PORT), Handler) as httpd:
        url = f"http://localhost:{PORT}/dashboard.html"
        print(f"Dashboard: {url}")
        print("Ctrl+C to stop")
        httpd.serve_forever()
