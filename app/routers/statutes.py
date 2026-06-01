"""기능 1(법령) + 기능 4 — 법령 검색 / 조문 조회 / 변경 추적"""
from fastapi import APIRouter, HTTPException, Query
from app.db import db

router = APIRouter(prefix="/statutes", tags=["법령"])


@router.get("/search")
def search_statutes(
    q: str = Query("", description="법령명 또는 조문 내용 검색"),
    kind: str = Query("", description="종류: 예규|훈령|고시|지침"),
    sido: str = Query("", description="시도 (부분일치)"),
    trust_grade: str = Query("", description="신뢰등급: A|B|C"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    conn = db()
    offset = (page - 1) * size
    params: list = []

    if q:
        sql = """
            SELECT DISTINCT s.id, s.law_id, s.name, s.kind,
                   s.region_sido, s.region_sigungu, s.effective_from,
                   s.trust_grade, s.source_url
            FROM articles_fts f
            JOIN articles a ON a.id = f.rowid
            JOIN statutes s ON s.id = a.statute_id
            WHERE articles_fts MATCH ?
        """
        params.append(q)
        alias = "s"
    else:
        sql = """
            SELECT id, law_id, name, kind,
                   region_sido, region_sigungu, effective_from,
                   trust_grade, source_url
            FROM statutes WHERE 1=1
        """
        alias = ""

    def col(c):
        return f"{alias}.{c}" if alias else c

    if kind:
        sql += f" AND {col('kind')} = ?"
        params.append(kind)
    if sido:
        sql += f" AND {col('region_sido')} LIKE ?"
        params.append(f"%{sido}%")
    if trust_grade:
        sql += f" AND {col('trust_grade')} = ?"
        params.append(trust_grade)

    total = conn.execute(f"SELECT COUNT(*) FROM ({sql})", params).fetchone()[0]
    sql += f" LIMIT {size} OFFSET {offset}"
    rows = conn.execute(sql, params).fetchall()

    return {
        "total": total,
        "page": page,
        "size": size,
        "items": [dict(r) for r in rows],
    }


@router.get("/{statute_id}/articles")
def get_articles(statute_id: int):
    """기능 4 — 법령 조문 전체 조회"""
    statute = db().execute("SELECT * FROM statutes WHERE id = ?", (statute_id,)).fetchone()
    if not statute:
        raise HTTPException(404, "법령을 찾을 수 없습니다")
    articles = db().execute(
        "SELECT id,article_no,article_title,content FROM articles WHERE statute_id = ? ORDER BY id",
        (statute_id,),
    ).fetchall()
    return {"statute": dict(statute), "articles": [dict(a) for a in articles]}


@router.get("/{statute_id}/history")
def get_history(statute_id: int):
    """기능 9 — 법령 조문 변경 이력 뷰어"""
    statute = db().execute("SELECT * FROM statutes WHERE id = ?", (statute_id,)).fetchone()
    if not statute:
        raise HTTPException(404, "법령을 찾을 수 없습니다")
    s = dict(statute)
    return {
        "law_id": s["law_id"],
        "name": s["name"],
        "current_version": {
            "promulgated_on": s["promulgated_on"],
            "effective_from": s["effective_from"],
            "estrev_label": s["estrev_label"],
            "version_count": s["version_count"],
        },
        "note": "상세 이력은 source_url에서 확인 가능",
        "source_url": s["source_url"],
    }
