@echo off
:: Starts the HTTP server and opens the Domino's price dashboard.
cd /d "%~dp0"
echo Starting dashboard server at http://localhost:8765/dominos_dashboard.html
echo Close this window to stop the server.
echo.
python -c "
import http.server, socketserver, webbrowser, os, threading, time
PORT = 8765
DIR = r'%~dp0'
class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw): super().__init__(*a, directory=DIR, **kw)
    def log_message(self, *a): pass
def open_later():
    time.sleep(0.8)
    webbrowser.open(f'http://localhost:{PORT}/dominos_dashboard.html')
threading.Thread(target=open_later, daemon=True).start()
with socketserver.TCPServer(('', PORT), H) as s:
    print(f'Server running. Press Ctrl+C to stop.')
    s.serve_forever()
"
pause
