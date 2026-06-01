from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.routers import cases, statutes, stats, compare, validity, graph

app = FastAPI(title="한국 법률 데이터 검색 API", version="1.0.0")

app.include_router(cases.router)
app.include_router(statutes.router)
app.include_router(stats.router)
app.include_router(compare.router)
app.include_router(validity.router)
app.include_router(graph.router)

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def index():
    return FileResponse("app/static/index.html")
