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
    db_path = os.environ.get("DB_PATH", "data/law.db")
    data_dir = os.path.dirname(db_path) or "."
    return {
        "status": "ok",
        "db_path": db_path,
        "db_exists": os.path.exists(db_path),
        "db_size_mb": round(os.path.getsize(db_path) / 1024 / 1024, 1) if os.path.exists(db_path) else 0,
        "data_dir_exists": os.path.exists(data_dir),
        "data_dir_writable": os.access(data_dir, os.W_OK),
    }


@app.get("/admin/diag", include_in_schema=False)
def diag():
    db_path = os.environ.get("DB_PATH", "data/law.db")
    data_dir = os.path.dirname(db_path) or "."
    try:
        test_file = os.path.join(data_dir, ".write_test")
        with open(test_file, "w") as f:
            f.write("ok")
        os.remove(test_file)
        writable = True
    except Exception as e:
        writable = str(e)
    return {
        "db_path": db_path,
        "data_dir": data_dir,
        "data_dir_exists": os.path.exists(data_dir),
        "data_dir_writable": writable,
        "db_exists": os.path.exists(db_path),
        "db_size_mb": round(os.path.getsize(db_path) / 1024 / 1024, 1) if os.path.exists(db_path) else 0,
        "cwd": os.getcwd(),
        "ls_app": os.listdir("/app") if os.path.exists("/app") else [],
    }


@app.get("/", include_in_schema=False)
def index():
    return FileResponse("app/static/index.html")


# 청크 업로드 엔드포인트 — 업로드 완료 후 삭제 예정
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
    db_path = os.environ.get("DB_PATH", "data/law.db")
    chunk_path = f"{db_path}.chunk.{index:04d}"
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    with open(chunk_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    size = os.path.getsize(chunk_path)
    return {"status": "ok", "chunk": index, "bytes": size}


@app.post("/admin/finalize-db", include_in_schema=False)
def finalize_db(x_upload_token: str = Header(...)):
    _check_token(x_upload_token)
    db_path = os.environ.get("DB_PATH", "data/law.db")
    data_dir = os.path.dirname(db_path) or "."
    chunks = sorted(f for f in os.listdir(data_dir) if f.startswith("law.db.chunk."))
    if not chunks:
        raise HTTPException(400, "청크 파일이 없습니다")
    tmp = db_path + ".tmp"
    total = 0
    with open(tmp, "wb") as out:
        for chunk_name in chunks:
            chunk_path = os.path.join(data_dir, chunk_name)
            with open(chunk_path, "rb") as f:
                shutil.copyfileobj(f, out)
            total += os.path.getsize(chunk_path)
            os.remove(chunk_path)
    os.replace(tmp, db_path)
    size_mb = os.path.getsize(db_path) / 1024 / 1024
    return {"status": "ok", "chunks": len(chunks), "size_mb": round(size_mb, 1)}


@app.post("/admin/fetch-db", include_in_schema=False)
def fetch_db(body: dict, x_upload_token: str = Header(...)):
    """외부 URL에서 DB 파일을 직접 다운로드"""
    import urllib.request
    _check_token(x_upload_token)
    url = body.get("url", "")
    if not url:
        raise HTTPException(400, "url 필드가 필요합니다")
    db_path = os.environ.get("DB_PATH", "data/law.db")
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    tmp = db_path + ".tmp"
    urllib.request.urlretrieve(url, tmp)
    os.replace(tmp, db_path)
    size_mb = os.path.getsize(db_path) / 1024 / 1024
    return {"status": "ok", "size_mb": round(size_mb, 1)}
