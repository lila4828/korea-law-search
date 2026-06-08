import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.routers import cases, statutes, stats, compare, validity, graph

app = FastAPI(title="MediLaw — 의료법 판례·법령 검색 API", version="2.0.0")

app.include_router(cases.router)
app.include_router(statutes.router)
app.include_router(stats.router)
app.include_router(compare.router)
app.include_router(validity.router)
app.include_router(graph.router)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

DB_PATH = os.environ.get("DB_PATH", "data/medilaw.db")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "db_path": DB_PATH,
        "db_exists": os.path.exists(DB_PATH),
        "db_size_mb": round(os.path.getsize(DB_PATH) / 1024 / 1024, 1) if os.path.exists(DB_PATH) else 0,
    }


@app.get("/", include_in_schema=False)
def index():
    return FileResponse("app/static/index.html")
