"""기능 7 — 지역 법령 전국 비교 / 기능 4 — 법령 비교"""
import difflib
from fastapi import APIRouter, HTTPException, Query
from app.db import db

router = APIRouter(prefix="/compare", tags=["비교"])


@router.get("/regions")
def compare_regions(
    keyword: str = Query(..., description="비교할 법령명 키워드 (예: 직소민원)"),
):
    """같은 주제 법령을 지역별로 나란히 비교"""
    conn = db()
    rows = conn.execute(
        """SELECT s.id, s.name, s.kind, s.region_sido, s.region_sigungu, s.effective_from
           FROM statutes s
           WHERE s.name LIKE ?
           ORDER BY s.region_sido, s.region_sigungu
           LIMIT 50""",
        (f"%{keyword}%",),
    ).fetchall()

    if not rows:
        return {"message": "해당 키워드로 검색된 법령이 없습니다", "items": []}

    result = {}
    for r in rows:
        sido = r["region_sido"] or "기타"
        result.setdefault(sido, []).append(dict(r))

    return {"keyword": keyword, "regions": result, "total": len(rows)}


@router.get("/statutes")
def diff_statutes(
    id1: int = Query(..., description="법령 ID 1"),
    id2: int = Query(..., description="법령 ID 2"),
):
    """두 법령의 조문을 텍스트 diff로 비교"""
    conn = db()

    def get_full_text(sid: int) -> tuple[str, str]:
        st = conn.execute("SELECT name FROM statutes WHERE id = ?", (sid,)).fetchone()
        if not st:
            raise HTTPException(404, f"법령 {sid}을 찾을 수 없습니다")
        arts = conn.execute(
            "SELECT article_no, article_title, content FROM articles WHERE statute_id = ? ORDER BY id",
            (sid,),
        ).fetchall()
        text = "\n\n".join(
            f"[{a['article_no']} {a['article_title']}]\n{a['content']}" for a in arts
        )
        return st["name"], text

    name1, text1 = get_full_text(id1)
    name2, text2 = get_full_text(id2)

    diff = list(
        difflib.unified_diff(
            text1.splitlines(),
            text2.splitlines(),
            fromfile=name1,
            tofile=name2,
            lineterm="",
            n=2,
        )
    )

    return {
        "statute1": {"id": id1, "name": name1},
        "statute2": {"id": id2, "name": name2},
        "diff_lines": len(diff),
        "diff": "\n".join(diff[:500]),
    }
