from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import subprocess
import threading
import re
import time
import sys
import os
import socket

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


HF_URLS = [
    "https://inv-veltrix-2.zeabur.app",
    "https://inv-veltrix-3.zeabur.app"
]

LOCAL_START_PORT = 19000

proxy_processes = []
cloudflared_processes = []
tunnels_info: dict = {}

PROXY_PY = os.path.join(os.path.dirname(__file__), "proxy.py")


def wait_for_port(port: int, timeout: float = 20.0) -> bool:
    """Wait until a TCP port is accepting connections, up to timeout seconds."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.3)
    return False


def run_proxy(port: int, target_url: str):
    proc = subprocess.Popen(
        [sys.executable, PROXY_PY, str(port), target_url],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    proxy_processes.append(proc)
    return proc


def run_cloudflared(port: int, hf_url: str, index: int):
    proc = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", f"http://localhost:{port}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        universal_newlines=True,
    )
    cloudflared_processes.append(proc)

    url_pattern = re.compile(r'https://[a-zA-Z0-9\-]+\.trycloudflare\.com')

    def read_output(stream):
        for line in stream:
            match = url_pattern.search(line)
            if match:
                tunnel_url = match.group(0)
                tunnels_info[hf_url] = tunnel_url
                print(f"[{index}] Tunnel ready → {hf_url}: {tunnel_url}", flush=True)

    threading.Thread(target=read_output, args=(proc.stderr,), daemon=True).start()
    threading.Thread(target=read_output, args=(proc.stdout,), daemon=True).start()
    return proc


def start_all_services():
    """Start proxy servers, wait for them to be ready, then start cloudflared."""
    for i, hf_url in enumerate(HF_URLS):
        port = LOCAL_START_PORT + i
        run_proxy(port, hf_url)

    # Wait for all proxies to be ready before starting tunnels
    for i, hf_url in enumerate(HF_URLS):
        port = LOCAL_START_PORT + i
        ready = wait_for_port(port, timeout=20.0)
        if ready:
            print(f"[{i}] Proxy ready on port {port}, starting tunnel for {hf_url}", flush=True)
        else:
            print(f"[{i}] WARNING: Proxy on port {port} did not become ready!", flush=True)
        run_cloudflared(port, hf_url, i)
        time.sleep(0.3)


def kill_cloudflared():
    while cloudflared_processes:
        p = cloudflared_processes.pop()
        try:
            p.terminate()
            p.wait(timeout=3)
        except subprocess.TimeoutExpired:
            p.kill()
        except Exception:
            pass


@app.on_event("startup")
async def startup_event():
    threading.Thread(target=start_all_services, daemon=True).start()


@app.on_event("shutdown")
async def shutdown_event():
    kill_cloudflared()
    for p in proxy_processes:
        try:
            p.terminate()
            p.wait(timeout=2)
        except Exception:
            p.kill()


@app.get("/api/instances")
async def get_instances():
    return [
        tunnels_info[hf_url]
        for hf_url in HF_URLS
        if tunnels_info.get(hf_url)
    ]


@app.get("/api/new")
@app.post("/api/new")
async def new_tunnels():
    kill_cloudflared()
    for hf_url in HF_URLS:
        tunnels_info[hf_url] = None

    def restart():
        # Give old processes a moment to fully die
        time.sleep(1)
        for i, hf_url in enumerate(HF_URLS):
            port = LOCAL_START_PORT + i
            # Wait for each proxy port to be up (they should already be running)
            wait_for_port(port, timeout=5.0)
            run_cloudflared(port, hf_url, i)
            time.sleep(0.3)

    threading.Thread(target=restart, daemon=True).start()
    return {
        "status": "restarting",
        "message": "New tunnels are being created. Check /api/instances in ~15 seconds."
    }
