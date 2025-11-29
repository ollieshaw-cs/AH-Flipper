import threading
import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader
import time

from state import latest_flips

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
