"""기능 5 — 법령 유효성 검증기"""
from datetime import date
from fastapi import APIRouter, Query
from app.db import db

router = APIRouter(prefix="/validity", tags=["유효성"])

TODAY = date.today().isoformat()


@router.get("/check")
def check_validity(
    statute_id: int = Query(None, description="법령 ID"),
    name: str = Query("", description="법령명 검색"),
):
    conn = db()
    if statute_id:
        rows = conn.execute("SELECT * FROM statutes WHERE id = ?", (statute_id,)).fetchall()
    elif name:
        rows = conn.execute(
            "SELECT * FROM statutes WHERE name LIKE ? LIMIT 20", (f"%{name}%",)
        ).fetchall()
    else:
        return {"error": "statute_id 또는 name을 입력하세요"}

    result = []
    for r in rows:
        s = dict(r)
        eff = s.get("effective_from", "") or ""
        is_effective = eff <= TODAY if eff else None
        result.append(
            {
                "id": s["id"],
                "name": s["name"],
                "kind": s["kind"],
                "region_sido": s["region_sido"],
                "effective_from": eff,
                "trust_grade": s["trust_grade"],
                "is_effective": is_effective,
                "status": "현행" if is_effective else ("미시행" if is_effective is False else "확인불가"),
            }
        )
    return {"checked_at": TODAY, "items": result}


@router.get("/expired")
def list_expired(
    sido: str = Query("", description="시도 필터"),
    limit: int = Query(50, le=200),
):
    """시행일 기준 최근 개정된 법령 목록 (유효성 모니터링용)"""
    conn = db()
    sql = """
        SELECT id, name, kind, region_sido, effective_from, trust_grade
        FROM statutes
        WHERE effective_from != ''
    """
    params = []
    if sido:
        sql += " AND region_sido LIKE ?"
        params.append(f"%{sido}%")
    sql += " ORDER BY effective_from DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]
