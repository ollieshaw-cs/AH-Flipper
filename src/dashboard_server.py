import threading
import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
import asyncio
import queue
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader
import time

from state import latest_flips, add_subscriber, remove_subscriber

app = FastAPI()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

static_path = os.path.join(BASE_DIR, "static")
os.makedirs(static_path, exist_ok=True)  # ensure it exists
app.mount("/static", StaticFiles(directory=static_path), name="static")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # folder of this file
template_path = os.path.join(BASE_DIR, "templates")

env = Environment(loader=FileSystemLoader(template_path))


@app.on_event("startup")
async def _on_startup():
    print("[Dashboard] FastAPI startup event — server running")

@app.get("/flips")
async def api_flips():
    return JSONResponse(content=list(latest_flips))


@app.get("/events")
async def sse_events():
    # Each connected client gets a private queue. We call add_subscriber and
    # remove_subscriber to maintain subscription list in `state`.
    q = queue.Queue()
    add_subscriber(q)

    async def event_generator():
        loop = asyncio.get_event_loop()
        try:
            while True:
                data = await loop.run_in_executor(None, q.get)
                # SSE event format
                yield f"data: {data}\n\n"
        finally:
            remove_subscriber(q)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    template = env.get_template("dashboard.html")
    html = template.render(
        flips=list(latest_flips)[::-1],
        time=time
    )
    return HTMLResponse(content=html)


if __name__ == "__main__":
    import uvicorn
    print("[Dashboard] Starting uvicorn on 127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000)
