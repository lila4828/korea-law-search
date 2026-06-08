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
    """청크를 DB_PATH에 직접 이어붙임 (index 0=새로 쓰기, 이후=append).
    별도 tmp/합치기 단계가 없어 추가 디스크 공간이 필요 없음."""
    _check_token(x_upload_token)
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    if index == 0:
        # 새 업로드 시작 — 옛 방식 잔여물 정리
        for leftover in (DB_PATH + ".tmp",):
            if os.path.exists(leftover):
                os.remove(leftover)
    mode = "wb" if index == 0 else "ab"
    with open(DB_PATH, mode) as f:
        shutil.copyfileobj(file.file, f)
    return {"status": "ok", "chunk": index, "size_mb": round(os.path.getsize(DB_PATH) / 1024 / 1024, 1)}


@app.post("/admin/finalize-db", include_in_schema=False)
def finalize_db(x_upload_token: str = Header(...)):
    """append 방식이라 합칠 게 없음 — 크기만 확인해 반환."""
    _check_token(x_upload_token)
    if not os.path.exists(DB_PATH) or os.path.getsize(DB_PATH) == 0:
        raise HTTPException(400, "업로드된 DB가 비어 있습니다")
    return {"status": "ok", "size_mb": round(os.path.getsize(DB_PATH) / 1024 / 1024, 1)}
