"""Static server with SPA fallback (paths like /approve serve index.html). usage: spa.py DIR PORT"""
import http.server, os, sys
root, port = sys.argv[1], int(sys.argv[2])
class H(http.server.SimpleHTTPRequestHandler):
    def __init__(s, *a, **k): super().__init__(*a, directory=root, **k)
    def send_head(s):
        if not os.path.exists(os.path.join(root, s.path.split('?')[0].lstrip('/'))): s.path = '/index.html'
        return super().send_head()
    def log_message(s, *a): pass
http.server.ThreadingHTTPServer(('127.0.0.1', port), H).serve_forever()
