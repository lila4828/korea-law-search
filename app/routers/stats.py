"""기능 3 — 데이터 분석 통계 / 기능 10 — 통계 데이터 추출"""
import csv
import io
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from app.db import db

router = APIRouter(prefix="/stats", tags=["통계"])


@router.get("/summary")
def summary():
    """전체 현황 요약"""
    conn = db()
    cases_total = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
    statutes_total = conn.execute("SELECT COUNT(*) FROM statutes").fetchone()[0]
    articles_total = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    refs_total = conn.execute("SELECT COUNT(*) FROM case_statute_refs").fetchone()[0]
    return {
        "cases": cases_total,
        "statutes": statutes_total,
        "articles": articles_total,
        "citation_refs": refs_total,
    }


@router.get("/cases/by-year")
def cases_by_year():
    rows = db().execute(
        "SELECT SUBSTR(date,1,4) yr, COUNT(*) cnt FROM cases WHERE date != '' GROUP BY yr ORDER BY yr"
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/cases/by-type")
def cases_by_type():
    rows = db().execute(
        "SELECT case_type, COUNT(*) cnt FROM cases GROUP BY case_type ORDER BY cnt DESC"
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/cases/by-court")
def cases_by_court():
    rows = db().execute(
        "SELECT court, COUNT(*) cnt FROM cases GROUP BY court ORDER BY cnt DESC LIMIT 30"
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/cases/by-court-level")
def cases_by_court_level():
    """심급별 판례 수"""
    rows = db().execute(
        "SELECT court_level, COUNT(*) cnt FROM cases GROUP BY court_level ORDER BY cnt DESC"
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/cases/content-coverage")
def cases_content_coverage():
    """판례 본문/판시사항/참조조문 보유율 + 평균 본문 길이"""
    conn = db()
    total = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]

    def cov(col):
        n = conn.execute(
            f"SELECT COUNT(*) FROM cases WHERE {col} IS NOT NULL AND {col}!=''"
        ).fetchone()[0]
        return {"count": n, "ratio": round(n / total, 3)}

    avg_body = conn.execute(
        "SELECT AVG(LENGTH(body)) FROM cases WHERE body IS NOT NULL AND body!=''"
    ).fetchone()[0]
    return {
        "total": total,
        "body": cov("body"),
        "issues": cov("issues"),
        "ref_text": cov("ref_text"),
        "summary": cov("summary"),
        "avg_body_length": round(avg_body or 0),
    }


@router.get("/statutes/by-region")
def statutes_by_region():
    rows = db().execute(
        "SELECT region_sido, COUNT(*) cnt FROM statutes GROUP BY region_sido ORDER BY cnt DESC"
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/statutes/by-kind")
def statutes_by_kind():
    rows = db().execute(
        "SELECT kind, COUNT(*) cnt FROM statutes GROUP BY kind ORDER BY cnt DESC"
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/statutes/recent")
def recent_statutes(limit: int = Query(20, le=100)):
    rows = db().execute(
        "SELECT id,name,kind,region_sido,effective_from,trust_grade FROM statutes ORDER BY effective_from DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/export/cases")
def export_cases(
    case_type: str = Query("", description="사건종류 필터"),
    fmt: str = Query("json", description="json|csv"),
    include_body: bool = Query(False, description="판시사항·참조조문·본문 포함"),
):
    """기능 10 — 판례 데이터 CSV/JSON 추출"""
    conn = db()
    cols = "id,case_no,case_name,court,court_level,case_type,date,source_url"
    if include_body:
        cols += ",summary,issues,ref_text,body"
    sql = f"SELECT {cols} FROM cases"
    params = []
    if case_type:
        sql += " WHERE case_type = ?"
        params.append(case_type)
    sql += " LIMIT 5000"
    rows = conn.execute(sql, params).fetchall()
    data = [dict(r) for r in rows]

    if fmt == "csv":
        output = io.StringIO()
        if data:
            writer = csv.DictWriter(output, fieldnames=data[0].keys())
            writer.writeheader()
            writer.writerows(data)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=cases.csv"},
        )
    return {"count": len(data), "data": data}


@router.get("/export/statutes")
def export_statutes(
    sido: str = Query("", description="시도 필터"),
    fmt: str = Query("json", description="json|csv"),
):
    """기능 10 — 법령 데이터 CSV/JSON 추출"""
    conn = db()
    sql = "SELECT id,law_id,name,kind,region_sido,region_sigungu,effective_from,trust_grade FROM statutes"
    params = []
    if sido:
        sql += " WHERE region_sido LIKE ?"
        params.append(f"%{sido}%")
    sql += " LIMIT 5000"
    rows = conn.execute(sql, params).fetchall()
    data = [dict(r) for r in rows]

    if fmt == "csv":
        output = io.StringIO()
        if data:
            writer = csv.DictWriter(output, fieldnames=data[0].keys())
            writer.writeheader()
            writer.writerows(data)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=statutes.csv"},
        )
    return {"count": len(data), "data": data}
