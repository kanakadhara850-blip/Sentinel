"""Static server for the frontend that mimics vercel.json rewrites:
   /  -> index.html ; /login /dashboard /queue /audit /system ... -> app.html ; real files served as-is."""
import http.server, os, sys, functools
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend", "public")

class H(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/") or "/"
        if path == "/":
            self.path = "/index.html" + ("?" + self.path.split("?", 1)[1] if "?" in self.path else "")
        elif not os.path.isfile(os.path.join(ROOT, path.lstrip("/"))):
            self.path = "/app.html" + ("?" + self.path.split("?", 1)[1] if "?" in self.path else "")
        return super().do_GET()
    def log_message(self, *a): pass

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
    http.server.ThreadingHTTPServer(("127.0.0.1", port),
        functools.partial(H, directory=ROOT)).serve_forever()
