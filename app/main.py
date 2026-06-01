import os
import shutil
import threading
import urllib.request
from fastapi import FastAPI, Header, HTTPException
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
    return {
        "status": "ok",
        "db_exists": os.path.exists(db_path),
        "db_size_mb": round(os.path.getsize(db_path) / 1024 / 1024, 1) if os.path.exists(db_path) else 0,
    }


@app.get("/", include_in_schema=False)
def index():
    return FileResponse("app/static/index.html")


_fetch_status: dict = {"state": "idle", "progress": "", "error": ""}


def _check_token(token: str):
    secret = os.environ.get("UPLOAD_TOKEN", "")
    if not secret or token != secret:
        raise HTTPException(403, "forbidden")


@app.post("/admin/fetch-db", include_in_schema=False)
def fetch_db(body: dict, x_upload_token: str = Header(...)):
    _check_token(x_upload_token)
    url = body.get("url", "")
    if not url:
        raise HTTPException(400, "url 필드가 필요합니다")
    if _fetch_status["state"] == "running":
        return {"status": "already_running", "progress": _fetch_status["progress"]}

    def _download():
        _fetch_status["state"] = "running"
        _fetch_status["error"] = ""
        db_path = os.environ.get("DB_PATH", "data/law.db")
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        tmp = db_path + ".tmp"
        if os.path.exists(tmp):
            os.remove(tmp)
        try:
            def _report(count, block, total):
                pct = count * block * 100 // total if total > 0 else 0
                _fetch_status["progress"] = f"{min(pct,100)}% ({count*block//1024//1024}MB/{total//1024//1024}MB)"
            urllib.request.urlretrieve(url, tmp, reporthook=_report)
            os.replace(tmp, db_path)
            size_mb = os.path.getsize(db_path) / 1024 / 1024
            _fetch_status["state"] = "done"
            _fetch_status["progress"] = f"완료 {size_mb:.1f}MB"
        except Exception as e:
            _fetch_status["state"] = "error"
            _fetch_status["error"] = str(e)
            if os.path.exists(tmp):
                os.remove(tmp)

    threading.Thread(target=_download, daemon=True).start()
    return {"status": "started", "message": "/admin/fetch-status 로 진행률 확인"}


@app.get("/admin/fetch-status", include_in_schema=False)
def fetch_status():
    db_path = os.environ.get("DB_PATH", "data/law.db")
    size_mb = os.path.getsize(db_path) / 1024 / 1024 if os.path.exists(db_path) else 0
    return {**_fetch_status, "db_size_mb": round(size_mb, 1)}
