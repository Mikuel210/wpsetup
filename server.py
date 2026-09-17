#!/usr/bin/env python3
"""wpsetup local mirror — static HTTPS server (Web Bluetooth needs a secure context).

node on this VM core-dumps on every invocation (that is what killed the
previous attempt, leaving core.* files behind), so this is python3 stdlib.

Serves /home/soup/wpsetup
  https on 0.0.0.0:8444   (the real setup site)
  http  on 0.0.0.0:8081   (301 redirect to https, same host)
"""
import os
import ssl
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
HTTPS_PORT = 8444
HTTP_PORT = 8081

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".ico": "image/x-icon",
    ".json": "application/json",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".map": "application/json",
    ".txt": "text/plain; charset=utf-8",
}

# never iterate on the bot against a stale cached rts.js/main.html
NEVER_CACHE = {".js", ".html", ".json", ".txt"}


class Handler(BaseHTTPRequestHandler):
    server_version = "wpsetup-mirror/1.0"

    def log(self, code, path):
        sys.stderr.write(f"{self.address_string()} {code} {path}\n")
        sys.stderr.flush()

    def do_GET(self):
        path = self.path.split("?")[0]
        path = path.split("#")[0]
        if "%2F" in path or "%25" in path:
            from urllib.parse import unquote

            path = unquote(path)
        if path.endswith("/"):
            path += "index.html"

        # resolve safely, do not escape ROOT
        file = os.path.normpath(os.path.join(ROOT, path.lstrip("/")))
        if os.path.commonpath([ROOT, file]) != ROOT:
            self.send_error(403, "forbidden")
            self.log(403, path)
            return

        if not os.path.isfile(file):
            self.send_error(404, f"not found: {path}")
            self.log(404, path)
            return

        ext = os.path.splitext(file)[1].lower()
        ctype = MIME.get(ext, "application/octet-stream")
        size = os.path.getsize(file)

        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        if ext in NEVER_CACHE:
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        else:
            self.send_header("Cache-Control", "public, max-age=3600")
        # rts.js does cross-endpoint XHR/fetch in dev; keep it permissive
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        with open(file, "rb") as fh:
            while chunk := fh.read(65536):
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
        self.log(200, path)

    def do_HEAD(self):
        path = self.path.split("?")[0]
        if path.endswith("/"):
            path += "index.html"
        file = os.path.normpath(os.path.join(ROOT, path.lstrip("/")))
        if os.path.commonpath([ROOT, file]) != ROOT or not os.path.isfile(file):
            self.send_error(404, "not found")
            return
        ext = os.path.splitext(file)[1].lower()
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(os.path.getsize(file)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()

    def do_POST(self):
        # vector-web-setup's /firmware endpoint, for completeness. The deployed
        # mirror (static) uses a fixed otaEndpoints in js/env/endpoints.js, so
        # this just answers an empty list.
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)) if int(
            self.headers.get("Content-Length") or 0
        ) else b""
        payload = '{"message":[]}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload.encode())
        self.log(200, self.path)

    def log_message(self, fmt, *args):
        pass  # handled by self.log()


def main():
    # ---- http redirector (8081 -> https) -----------------------------------
    class Redirect(BaseHTTPRequestHandler):
        def do_GET(self):
            host = (self.headers.get("Host") or "localhost").split(":")[0]
            self.send_response(301)
            self.send_header(
                "Location", f"https://{host}:{HTTPS_PORT}{self.path.split('?')[0]}"
            )
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *a):
            pass

        def do_HEAD(self):
            self.do_GET()

        def do_POST(self):
            self.do_GET()

    try:
        httpd = ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), Redirect)
        print(f"http redirect on 0.0.0.0:{HTTP_PORT} -> https:{HTTPS_PORT}", flush=True)
    except OSError as e:
        print(f"WARNING: http port {HTTP_PORT} unusable: {e}", flush=True)
        httpd = None

    # ---- https (8444) -------------------------------------------------------
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(
        os.path.join(ROOT, "cert", "wpsetup.crt"),
        os.path.join(ROOT, "cert", "wpsetup.key"),
    )
    httpsd = ThreadingHTTPServer(("0.0.0.0", HTTPS_PORT), Handler)
    httpsd.socket = ctx.wrap_socket(httpsd.socket, server_side=True)
    import socket

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        lan_ip = s.getsockname()[0]
        s.close()
    except Exception:
        lan_ip = "<this-host>"
    print(f"https on 0.0.0.0:{HTTPS_PORT}  (root: {ROOT})", flush=True)
    print(f"open: https://{lan_ip}:{HTTPS_PORT}/html/main.html", flush=True)

    import threading

    if httpd is not None:
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        httpsd.serve_forever()
    except KeyboardInterrupt:
        print("shutting down", flush=True)
    finally:
        httpsd.server_close()
        if httpd is not None:
            httpd.server_close()


if __name__ == "__main__":
    main()
