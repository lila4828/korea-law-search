import os
import shutil
from fastapi import FastAPI, File, Header, HTTPException, UploadFile
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


# 임시 DB 업로드 엔드포인트 — 업로드 완료 후 삭제 예정
@app.post("/admin/upload-db", include_in_schema=False)
async def upload_db(
    file: UploadFile = File(...),
    x_upload_token: str = Header(...),
):
    secret = os.environ.get("UPLOAD_TOKEN", "")
    if not secret or x_upload_token != secret:
        raise HTTPException(403, "forbidden")
    db_path = os.environ.get("DB_PATH", "data/law.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    tmp = db_path + ".tmp"
    with open(tmp, "wb") as f:
        shutil.copyfileobj(file.file, f)
    os.replace(tmp, db_path)
    size_mb = os.path.getsize(db_path) / 1024 / 1024
    return {"status": "ok", "size_mb": round(size_mb, 1)}
