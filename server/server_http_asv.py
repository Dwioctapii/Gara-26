"""HTTP state, detection, and camera snapshot API."""
import json, os, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from state import PHOTO_DIR, store

MAX_BODY = 12 * 1024 * 1024
class Handler(BaseHTTPRequestHandler):
    def respond(self, status, kind, size=0):
        self.send_response(status)
        for k,v in (("Content-Type",kind),("Content-Length",str(size)),("Access-Control-Allow-Origin","*"),("Access-Control-Allow-Headers","Content-Type"),("Access-Control-Allow-Methods","GET, POST, OPTIONS"),("Cache-Control","no-store")): self.send_header(k,v)
        self.end_headers()
    def send_json(self, value, status=200):
        body=json.dumps(value,separators=(",",":")).encode(); self.respond(status,"application/json",len(body)); self.wfile.write(body)
    def body(self):
        size=int(self.headers.get("Content-Length",0))
        if not 0 <= size <= MAX_BODY: raise ValueError("body terlalu besar")
        return self.rfile.read(size)
    def do_OPTIONS(self): self.respond(204,"text/plain")
    def do_GET(self):
        path=urlparse(self.path).path
        if path=="/health": self.send_json({"ok":True,"service":"asv-server"})
        elif path=="/state": self.send_json(store.snapshot())
        elif path=="/status": self.send_json({k:(PHOTO_DIR/f"{k}.jpg").is_file() for k in ("atas","bawah")})
        elif path in ("/atas.jpg","/bawah.jpg"):
            photo=PHOTO_DIR/path[1:]
            if not photo.is_file(): return self.send_json({"error":"photo unavailable"},404)
            body=photo.read_bytes(); self.respond(200,"image/jpeg",len(body)); self.wfile.write(body)
        else: self.send_json({"error":"not found"},404)
    def do_POST(self):
        path=urlparse(self.path).path
        try:
            if path in ("/api/photo/atas","/api/photo/bawah"):
                target=PHOTO_DIR/(path.rsplit("/",1)[1]+".jpg"); tmp=target.with_suffix(".tmp"); tmp.write_bytes(self.body()); tmp.replace(target); return self.send_json({"ok":True})
            data=json.loads(self.body() or b"{}")
            if not isinstance(data,dict): raise ValueError("JSON harus object")
            if path=="/api/state": store.update(data)
            elif path=="/api/detections": store.update({"detection":{**data,"updated_at":time.time()}})
            else: return self.send_json({"error":"not found"},404)
            self.send_json({"ok":True})
        except (ValueError,json.JSONDecodeError) as exc: self.send_json({"error":str(exc)},400)
    def log_message(self, fmt, *args): print("[HTTP] "+fmt%args)

def serve(host=None,port=None):
    host=host or os.getenv("ASV_HTTP_HOST","0.0.0.0"); port=port or int(os.getenv("ASV_HTTP_PORT","8766"))
    print(f"[HTTP] http://{host}:{port}"); ThreadingHTTPServer((host,port),Handler).serve_forever()
if __name__=="__main__": serve()
