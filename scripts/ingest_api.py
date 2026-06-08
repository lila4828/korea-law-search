"""
국가법령정보 Open API → medilaw.db 적재 (4대 법령 본문·조문)

extract_medical.py가 만든 medilaw.db의 비어있는 "법령 본문" 자리를 채운다.
대상: 의료법·개인정보보호법·생명윤리법·정보통신망법 (각 본법 + 시행령 + 시행규칙).
적재 후 cases.ref_text(참조조문) 매칭으로 법령↔판례 인용 그래프를 재구성한다.

인증: OC는 환경변수 LAW_OC, 기본 'H-Lab'. JSON만 사용. 한글 query는 URL 인코딩.
사용법: python scripts/ingest_api.py --db data/medilaw.db
"""
import argparse
import json
import os
import sqlite3
import time
import urllib.parse
import urllib.request

OC = os.environ.get("LAW_OC", "H-Lab")
BASE = "https://www.law.go.kr/DRF"


def as_list(x):
    """법제처 API는 항목이 1개면 list 대신 dict/단일값을 준다 → 항상 list로 정규화."""
    if x is None or x == "":
        return []
    return x if isinstance(x, list) else [x]

# 4대 법령(본법). 각각 시행령/시행규칙도 자동 탐색해서 함께 적재.
BASE_LAWS = [
    "의료법",
    "개인정보 보호법",
    "생명윤리 및 안전에 관한 법률",
    "정보통신망 이용촉진 및 정보보호 등에 관한 법률",
]
VARIANTS = ["", " 시행령", " 시행규칙"]


def call(path, **params):
    """DRF JSON 호출 (URL 인코딩 + 간단 재시도)."""
    params.setdefault("OC", OC)
    params.setdefault("type", "JSON")
    url = f"{BASE}/{path}?" + urllib.parse.urlencode(params)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                raw = r.read().decode("utf-8", "ignore")
            if raw.lstrip().startswith("<"):
                raise RuntimeError("HTML 응답(미신청/오류 가능)")
            return json.loads(raw) if raw.strip() else {}
        except Exception as e:
            if attempt == 2:
                raise
            time.sleep(1.5)


def find_current(name: str):
    """정확 법령명 + 현행 버전의 (MST, 상세링크) 반환. 없으면 None."""
    d = call("lawSearch.do", target="law", query=name, display=50)
    laws = d.get("LawSearch", {}).get("law", [])
    if isinstance(laws, dict):  # 결과 1건이면 list 아닌 dict로 옴
        laws = [laws]
    for L in laws:
        if L.get("법령명한글") == name and L.get("현행연혁코드") == "현행":
            # 사용자에게 보여줄 공개 URL (OC 키 노출 방지 — 법령상세링크엔 OC 포함됨)
            url = "https://www.law.go.kr/법령/" + urllib.parse.quote(name)
            return L["법령일련번호"], url
    return None


def assemble_content(unit: dict) -> str:
    """조문내용(제목줄) + 항내용들(+호) 합쳐 조문 전문 구성."""
    parts = [unit.get("조문내용", "").strip()]
    for h in as_list(unit.get("항")):
        if not isinstance(h, dict):
            continue
        txt = (h.get("항내용") or "").strip()
        if txt:
            parts.append(txt)
        for ho in as_list(h.get("호")):
            if isinstance(ho, dict):
                ho_txt = (ho.get("호내용") or "").strip()
                if ho_txt:
                    parts.append(ho_txt)
    return "\n".join(p for p in parts if p)


def fetch_law(mst: str):
    """본문조회 → (statute_meta dict, [(조문번호,조문제목,content), ...])."""
    d = call("lawService.do", target="law", MST=mst).get("법령", {})
    bi = d.get("기본정보", {})

    def field(v):
        return v.get("content") if isinstance(v, dict) else (v or "")

    meta = {
        "law_id": bi.get("법령ID", ""),
        "name": bi.get("법령명_한글", ""),
        "kind": field(bi.get("법종구분", "")),
        "region_sido": field(bi.get("소관부처", "")),
        "promulgated_on": str(bi.get("공포일자", "")),
        "effective_from": str(bi.get("시행일자", "")),
        "estrev_label": bi.get("제개정구분", ""),
    }
    units = as_list(d.get("조문", {}).get("조문단위", []))
    rows = []
    for u in units:
        if not isinstance(u, dict) or u.get("조문여부") != "조문":   # '전문'(편/장/절 헤더) 제외
            continue
        content = assemble_content(u)
        if content:
            rows.append((u.get("조문번호", ""), u.get("조문제목", ""), content))
    return meta, rows


def upsert_statute(conn, meta, source_url):
    conn.execute(
        """INSERT INTO statutes
           (law_id,name,kind,region_sido,promulgated_on,effective_from,source_url,trust_grade,estrev_label)
           VALUES (:law_id,:name,:kind,:sido,:prom,:eff,:url,'법령',:est)
           ON CONFLICT(law_id) DO UPDATE SET
             effective_from=excluded.effective_from,
             promulgated_on=excluded.promulgated_on,
             source_url=excluded.source_url,
             estrev_label=excluded.estrev_label""",
        {"law_id": meta["law_id"], "name": meta["name"], "kind": meta["kind"],
         "sido": meta["region_sido"], "prom": meta["promulgated_on"],
         "eff": meta["effective_from"], "url": source_url, "est": meta["estrev_label"]},
    )
    conn.commit()
    row = conn.execute("SELECT id FROM statutes WHERE law_id=?", (meta["law_id"],)).fetchone()
    return row[0] if row else None


def insert_articles(conn, statute_id, rows):
    # 재적재 시 중복 방지 — 해당 법령 조문 먼저 삭제
    conn.execute("DELETE FROM articles WHERE statute_id=?", (statute_id,))
    conn.executemany(
        "INSERT INTO articles (statute_id,article_no,article_title,content) VALUES (?,?,?,?)",
        [(statute_id, a, t, c) for a, t, c in rows],
    )
    conn.commit()


def rebuild_refs(conn):
    """적재된 법령명을 cases.ref_text(참조조문)에서 찾아 case_statute_refs 재구성."""
    statutes = {r[0]: r[1] for r in conn.execute("SELECT id,name FROM statutes WHERE trust_grade='법령'")}
    # 재실행 idempotent — 법령 관련 인용만 비우고 다시 채움
    conn.execute("DELETE FROM case_statute_refs WHERE statute_id IN "
                 "(SELECT id FROM statutes WHERE trust_grade='법령')")
    cases = conn.execute(
        "SELECT id, ref_text FROM cases WHERE ref_text IS NOT NULL AND ref_text != ''"
    ).fetchall()
    batch = []
    for case_id, ref in cases:
        for sid, sname in statutes.items():
            if len(sname) >= 3 and sname in ref:  # '의료법'(3자) 포함되도록
                batch.append((case_id, sid, 1))
    conn.executemany("INSERT OR IGNORE INTO case_statute_refs VALUES (?,?,?)", batch)
    conn.commit()
    return conn.execute(
        "SELECT COUNT(*) FROM case_statute_refs WHERE statute_id IN "
        "(SELECT id FROM statutes WHERE trust_grade='법령')"
    ).fetchone()[0]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="data/medilaw.db")
    args = p.parse_args()

    conn = sqlite3.connect(args.db)
    total_articles = 0
    for base in BASE_LAWS:
        for v in VARIANTS:
            name = base + v
            found = find_current(name)
            if not found:
                continue
            mst, url = found
            meta, rows = fetch_law(mst)
            if not meta.get("name"):
                print(f"  [건너뜀] {name} (본문 없음)")
                continue
            sid = upsert_statute(conn, meta, url)
            insert_articles(conn, sid, rows)
            total_articles += len(rows)
            print(f"  ✅ {meta['name']:35s} 조문 {len(rows):>4}개  (시행 {meta['effective_from']})")
            time.sleep(0.3)

    print("\n[인용 그래프 재구성 중...]")
    n_refs = rebuild_refs(conn)

    print("[articles FTS 재구성 중...]")
    conn.execute("INSERT INTO articles_fts(articles_fts) VALUES('rebuild')")
    conn.commit()
    conn.close()

    print(f"\n=== 완료 ===")
    print(f"  적재 조문 합계 : {total_articles:,}")
    print(f"  법령↔판례 인용 : {n_refs:,}건")


if __name__ == "__main__":
    main()
