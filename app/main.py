import os
import shutil
from fastapi import FastAPI, File, Header, HTTPException, UploadFile
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


@app.get("/admin/diag", include_in_schema=False)
def diag():
    data_dir = os.path.dirname(DB_PATH) or "."
    return {
        "db_path": DB_PATH,
        "data_dir": data_dir,
        "data_dir_exists": os.path.exists(data_dir),
        "data_dir_writable": os.access(data_dir, os.W_OK),
        "db_exists": os.path.exists(DB_PATH),
        "db_size_mb": round(os.path.getsize(DB_PATH) / 1024 / 1024, 1) if os.path.exists(DB_PATH) else 0,
        "data_dir_files": os.listdir(data_dir) if os.path.exists(data_dir) else [],
    }


@app.get("/", include_in_schema=False)
def index():
    return FileResponse("app/static/index.html")


# ── 청크 업로드 엔드포인트 (Railway Volume에 DB 적재용 — 업로드 후 제거 예정) ──
# UPLOAD_TOKEN 환경변수가 설정돼 있어야 동작. 미설정 시 전부 403.
def _check_token(token: str):
    secret = os.environ.get("UPLOAD_TOKEN", "")
    if not secret or token != secret:
        raise HTTPException(403, "forbidden")


@app.post("/admin/upload-chunk/{index}", include_in_schema=False)
async def upload_chunk(
    index: int,
    file: UploadFile = File(...),
    x_upload_token: str = Header(...),
):
    _check_token(x_upload_token)
    chunk_path = f"{DB_PATH}.chunk.{index:04d}"
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with open(chunk_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"status": "ok", "chunk": index, "bytes": os.path.getsize(chunk_path)}


@app.post("/admin/finalize-db", include_in_schema=False)
def finalize_db(x_upload_token: str = Header(...)):
    _check_token(x_upload_token)
    data_dir = os.path.dirname(DB_PATH) or "."
    prefix = os.path.basename(DB_PATH) + ".chunk."   # 실제 DB 파일명 기준 (medilaw.db.chunk.)
    chunks = sorted(f for f in os.listdir(data_dir) if f.startswith(prefix))
    if not chunks:
        raise HTTPException(400, "청크 파일이 없습니다")
    tmp = DB_PATH + ".tmp"
    with open(tmp, "wb") as out:
        for chunk_name in chunks:
            chunk_path = os.path.join(data_dir, chunk_name)
            with open(chunk_path, "rb") as f:
                shutil.copyfileobj(f, out)
            os.remove(chunk_path)
    os.replace(tmp, DB_PATH)
    return {"status": "ok", "chunks": len(chunks), "size_mb": round(os.path.getsize(DB_PATH) / 1024 / 1024, 1)}
