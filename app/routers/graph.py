"""기능 6 — 판례 → 법령 인용 그래프"""
from fastapi import APIRouter, Query
from app.db import db

router = APIRouter(prefix="/graph", tags=["인용그래프"])


@router.get("/top-cited-statutes")
def top_cited_statutes(limit: int = Query(20, le=100)):
    """가장 많이 인용된 법령 순위"""
    rows = db().execute(
        """SELECT s.id, s.name, s.kind, s.region_sido, COUNT(*) cnt
           FROM case_statute_refs r
           JOIN statutes s ON s.id = r.statute_id
           GROUP BY r.statute_id
           ORDER BY cnt DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/statute/{statute_id}/citing-cases")
def citing_cases(
    statute_id: int,
    page: int = Query(1, ge=1),
    size: int = Query(20, le=100),
):
    """특정 법령을 인용한 판례 목록"""
    conn = db()
    offset = (page - 1) * size
    total = conn.execute(
        "SELECT COUNT(*) FROM case_statute_refs WHERE statute_id = ?", (statute_id,)
    ).fetchone()[0]
    rows = conn.execute(
        """SELECT c.id, c.case_no, c.case_name, c.court, c.case_type, c.date
           FROM case_statute_refs r
           JOIN cases c ON c.id = r.case_id
           WHERE r.statute_id = ?
           ORDER BY c.date DESC
           LIMIT ? OFFSET ?""",
        (statute_id, size, offset),
    ).fetchall()
    return {"total": total, "page": page, "size": size, "items": [dict(r) for r in rows]}


@router.get("/case/{case_id}/cited-statutes")
def cited_statutes(case_id: int):
    """특정 판례가 인용한 법령 목록"""
    rows = db().execute(
        """SELECT s.id, s.name, s.kind, s.region_sido, s.effective_from
           FROM case_statute_refs r
           JOIN statutes s ON s.id = r.statute_id
           WHERE r.case_id = ?""",
        (case_id,),
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/top-cited-cases")
def top_cited_cases(limit: int = Query(20, le=100)):
    """가장 많이 인용된 판례 순위 (참조판례 기반)"""
    rows = db().execute(
        """SELECT c.id, c.case_no, c.case_name, c.court, c.case_type, c.date,
                  COUNT(*) cnt
           FROM case_case_refs r
           JOIN cases c ON c.id = r.cited_id
           WHERE r.cited_id IS NOT NULL
           GROUP BY r.cited_id
           ORDER BY cnt DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/case/{case_id}/cites")
def case_cites(case_id: int):
    """이 판례가 인용한 판례 목록 (참조판례). 우리 DB에 없는 건 cited_id=null"""
    rows = db().execute(
        """SELECT r.cited_case_no, r.cited_id,
                  c.case_name, c.court, c.case_type, c.date
           FROM case_case_refs r
           LEFT JOIN cases c ON c.id = r.cited_id
           WHERE r.citing_id = ?
           ORDER BY r.cited_id IS NULL, c.date DESC""",
        (case_id,),
    ).fetchall()
    return {"case_id": case_id, "total": len(rows), "items": [dict(r) for r in rows]}


@router.get("/case/{case_id}/cited-by")
def case_cited_by(
    case_id: int,
    page: int = Query(1, ge=1),
    size: int = Query(20, le=100),
):
    """이 판례를 인용한 판례 목록"""
    conn = db()
    offset = (page - 1) * size
    total = conn.execute(
        "SELECT COUNT(*) FROM case_case_refs WHERE cited_id = ?", (case_id,)
    ).fetchone()[0]
    rows = conn.execute(
        """SELECT c.id, c.case_no, c.case_name, c.court, c.case_type, c.date
           FROM case_case_refs r
           JOIN cases c ON c.id = r.citing_id
           WHERE r.cited_id = ?
           ORDER BY c.date DESC
           LIMIT ? OFFSET ?""",
        (case_id, size, offset),
    ).fetchall()
    return {"total": total, "page": page, "size": size, "items": [dict(r) for r in rows]}


@router.get("/network")
def citation_network(
    sido: str = Query("", description="시도 필터"),
    limit: int = Query(30, le=100),
):
    """인용 네트워크 노드/엣지 데이터 (시각화용)"""
    conn = db()
    sql = """
        SELECT s.id statute_id, s.name statute_name,
               c.id case_id, c.case_name, c.case_type, COUNT(*) w
        FROM case_statute_refs r
        JOIN statutes s ON s.id = r.statute_id
        JOIN cases c ON c.id = r.case_id
    """
    params = []
    if sido:
        sql += " WHERE s.region_sido LIKE ?"
        params.append(f"%{sido}%")
    sql += " GROUP BY r.statute_id, r.case_id ORDER BY w DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()

    nodes: dict = {}
    edges = []
    for r in rows:
        sid = f"s_{r['statute_id']}"
        cid = f"c_{r['case_id']}"
        nodes[sid] = {"id": sid, "label": r["statute_name"], "type": "statute"}
        nodes[cid] = {"id": cid, "label": r["case_name"], "type": "case", "case_type": r["case_type"]}
        edges.append({"source": cid, "target": sid, "weight": r["w"]})

    return {"nodes": list(nodes.values()), "edges": edges}
