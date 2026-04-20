import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

load_dotenv()

from database import init_db
from routers import photos, milestones, timeline, children

THUMBNAILS_DIR = os.getenv("THUMBNAILS_DIR", "./thumbnails")
# Must exist before StaticFiles mount below
Path(THUMBNAILS_DIR).mkdir(parents=True, exist_ok=True)

# ALLOWED_ORIGINS="*" (default dev) or comma-separated list for production
# e.g. ALLOWED_ORIGINS=https://myapp.com,http://192.168.1.42:3000
_raw_origins = os.getenv("ALLOWED_ORIGINS", "*")
ALLOWED_ORIGINS: list[str] = [o.strip() for o in _raw_origins.split(",")]
_wildcard = ALLOWED_ORIGINS == ["*"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="AI Baby Book",
    description="Scan your photo library and discover childhood milestones powered by Claude Vision.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    # Credentials (cookies) cannot be sent with wildcard origin per CORS spec
    allow_credentials=not _wildcard,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(photos.router)
app.include_router(milestones.router)
app.include_router(timeline.router)
app.include_router(children.router)

app.mount("/thumbnails", StaticFiles(directory=THUMBNAILS_DIR), name="thumbnails")


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}
