"""phingr-cli: LLM-driven mobile UI automation."""

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn

from .api import router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("phingr-cli")

app = FastAPI(docs_url=None, redoc_url=None)
app.include_router(router)

STATIC_DIR = Path(__file__).parent / "static"

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8800)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()
    uvicorn.run("app.server:app", host=args.host, port=args.port)
