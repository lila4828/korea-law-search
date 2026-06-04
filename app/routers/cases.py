"""기능 1 — 판례 검색 / 조회 / 유사 판례"""
import collections
import re
from fastapi import APIRouter, HTTPException, Query
from app.db import db

router = APIRouter(prefix="/cases", tags=["판례"])

_TOKEN_RE = re.compile(r"[가-힣]{2,}")


@router.get("/search")
def search_cases(
    q: str = Query("", description="검색어 (FTS)"),
    case_type: str = Query("", description="사건종류: 민사|형사|가사|세무|일반행정|특허|기타"),
    court: str = Query("", description="법원명 (부분일치)"),
    date_from: str = Query("", description="선고일 시작 YYYY-MM-DD"),
    date_to: str = Query("", description="선고일 종료 YYYY-MM-DD"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    conn = db()
    offset = (page - 1) * size
    params: list = []

    if q:
        sql = """
            SELECT c.id,c.case_no,c.case_name,c.court,c.court_level,
                   c.case_type,c.date,c.summary,c.source_url,
                   snippet(cases_fts,-1,'<mark>','</mark>','…',15) AS snippet
            FROM cases_fts
            JOIN cases c ON c.id = cases_fts.rowid
            WHERE cases_fts MATCH ?
        """
        params.append(q)
    else:
        sql = """
            SELECT id,case_no,case_name,court,court_level,
                   case_type,date,summary,source_url
            FROM cases WHERE 1=1
        """

    if case_type:
        sql += " AND c.case_type = ?" if q else " AND case_type = ?"
        params.append(case_type)
    if court:
        sql += " AND c.court LIKE ?" if q else " AND court LIKE ?"
        params.append(f"%{court}%")
    if date_from:
        sql += " AND c.date >= ?" if q else " AND date >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND c.date <= ?" if q else " AND date <= ?"
        params.append(date_to)

    count_sql = f"SELECT COUNT(*) FROM ({sql})"
    total = conn.execute(count_sql, params).fetchone()[0]

    sql += f" LIMIT {size} OFFSET {offset}"
    rows = conn.execute(sql, params).fetchall()

    return {
        "total": total,
        "page": page,
        "size": size,
        "items": [dict(r) for r in rows],
    }


@router.get("/{case_id}/similar")
def similar_cases(case_id: int, limit: int = Query(10, ge=1, le=30)):
    """판시사항·판결요지·사건명 키워드 기반 유사 판례 추천 (FTS)"""
    conn = db()
    row = conn.execute(
        "SELECT case_name, issues, summary FROM cases WHERE id = ?", (case_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "판례를 찾을 수 없습니다")

    text = " ".join(filter(None, [row["case_name"], row["issues"], row["summary"]]))
    freq = collections.Counter(_TOKEN_RE.findall(text))
    # 긴 단어(고유 개념) 우선, 동률이면 빈도순 — 상위 8개를 OR 매칭
    terms = [t for t, _ in sorted(freq.items(), key=lambda x: (-len(x[0]), -x[1]))[:8]]
    if not terms:
        return {"case_id": case_id, "terms": [], "items": []}

    match = " OR ".join(f'"{t}"' for t in terms)
    rows = conn.execute(
        """SELECT c.id, c.case_no, c.case_name, c.court, c.case_type, c.date,
                  snippet(cases_fts,-1,'<mark>','</mark>','…',12) AS snippet
           FROM cases_fts JOIN cases c ON c.id = cases_fts.rowid
           WHERE cases_fts MATCH ? AND c.id != ?
           ORDER BY bm25(cases_fts)
           LIMIT ?""",
        (match, case_id, limit),
    ).fetchall()
    return {"case_id": case_id, "terms": terms, "items": [dict(r) for r in rows]}


@router.get("/{case_id}")
def get_case(case_id: int):
    row = db().execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    if not row:
        raise HTTPException(404, "판례를 찾을 수 없습니다")
    return dict(row)
