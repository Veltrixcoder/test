import http.server
import socketserver
import uuid
import json
import http.client
import urllib.request

PORT = 7860

# -------- Detect server region ONCE --------
def get_country():
    try:
        return urllib.request.urlopen(
            "https://ipinfo.io/country",
            timeout=5
        ).read().decode().strip()
    except Exception:
        return "UNKNOWN"

SERVER_COUNTRY = get_country()

HTML = f"""
<!DOCTYPE html>
<html>
<head>
  <title>ImgBB Upload</title>
</head>
<body>
  <h3>ImgBB Anonymous Upload (Python)</h3>
  <p><b>Server Region:</b> {SERVER_COUNTRY}</p>
  <hr>
  <input type="file" id="f">
  <button onclick="up()">Upload</button>
  <pre id="o"></pre>
  <script>
    async function up() {{
      const f = document.getElementById('f').files[0];
      if (!f) return alert('Pick file');
      const fd = new FormData();
      fd.append('image', f);
      const r = await fetch('/upload', {{ method: 'POST', body: fd }});
      const j = await r.json();
      document.getElementById('o').textContent =
        JSON.stringify(j, null, 2);
    }}
  </script>
</body>
</html>
"""

class Handler(http.server.BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(HTML.encode())

    def do_POST(self):
        if self.path != "/upload":
            self.send_error(404)
            return

        content_type = self.headers.get("Content-Type", "")
        if "boundary=" not in content_type:
            self.send_error(400)
            return

        boundary = content_type.split("boundary=")[1].encode()
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        image_bytes = None
        parts = body.split(b"--" + boundary)

        for part in parts:
            if b"filename=" in part:
                image_bytes = part.split(b"\r\n\r\n", 1)[1].rsplit(b"\r\n", 1)[0]
                break

        if not image_bytes:
            self.send_error(400)
            return

        self.forward_to_imgbb(image_bytes)

    def forward_to_imgbb(self, image_bytes):
        boundary = "----WebKitFormBoundary" + uuid.uuid4().hex

        body_start = (
            f"--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"type\"\r\n\r\n"
            f"file\r\n"
            f"--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"action\"\r\n\r\n"
            f"upload\r\n"
            f"--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"source\"; filename=\"x.jpg\"\r\n"
            f"Content-Type: image/jpeg\r\n\r\n"
        ).encode()

        body_end = f"\r\n--{boundary}--\r\n".encode()

        conn = http.client.HTTPSConnection("imgbb.com")
        conn.request(
            "POST",
            "/json",
            body=body_start + image_bytes + body_end,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(body_start) + len(image_bytes) + len(body_end)),
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0"
            }
        )

        resp = conn.getresponse()
        raw = resp.read()

        try:
            imgbb = json.loads(raw.decode())
        except:
            self.send_error(500)
            return

        if imgbb.get("status_code") == 200:
            image = imgbb.get("image", {})
            output = {
                "success": True,
                "url": image.get("display_url") or image.get("url"),
                "delete_url": image.get("delete_url"),
                "width": image.get("display_width"),
                "height": image.get("display_height"),
                "size": image.get("size"),
                "server_country": SERVER_COUNTRY
            }
        else:
            output = {
                "success": False,
                "error": imgbb.get("status_txt", "Upload failed"),
                "server_country": SERVER_COUNTRY
            }

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(output).encode())

with socketserver.TCPServer(("", PORT), Handler) as server:
    print(f"🌍 Server region: {SERVER_COUNTRY}")
    print(f"Running → http://localhost:{PORT}")
    server.serve_forever()
