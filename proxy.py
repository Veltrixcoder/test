from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
import httpx
import sys

app = FastAPI()

if len(sys.argv) < 3:
    print("Usage: python proxy.py <port> <target_url>")
    sys.exit(1)

port = int(sys.argv[1])
target_url = sys.argv[2].rstrip("/")

client = httpx.AsyncClient(
    timeout=60.0,
    follow_redirects=True,
    limits=httpx.Limits(max_connections=100, max_keepalive_connections=20)
)

@app.get("/healthz")
async def health():
    return {"status": "ok", "port": port, "target": target_url}

@app.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"]
)
async def reverse_proxy(request: Request, path: str):
    url = f"{target_url}/{path}"
    if request.url.query:
        url = f"{url}?{request.url.query}"

    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in ("host", "connection", "transfer-encoding", "content-length")
    }
    # Set proper Host header for the target
    from urllib.parse import urlparse
    headers["host"] = urlparse(target_url).netloc

    body = await request.body()

    try:
        req = client.build_request(
            method=request.method,
            url=url,
            headers=headers,
            content=body if body else None
        )
        response = await client.send(req, stream=True)

        async def streamer():
            async for chunk in response.aiter_bytes():
                yield chunk

        res_headers = {
            k: v for k, v in response.headers.items()
            if k.lower() not in (
                "content-encoding", "content-length",
                "transfer-encoding", "connection"
            )
        }

        return StreamingResponse(
            streamer(),
            status_code=response.status_code,
            headers=res_headers,
            background=response.aclose
        )
    except httpx.RequestError as e:
        print(f"[proxy:{port}] Request error: {e}")
        return StreamingResponse(
            iter([f"Upstream error: {e}".encode()]),
            status_code=502
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
