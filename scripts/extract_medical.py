"""
law.db(전국 법령·판례) → medilaw.db(의료 도메인) 추출 스크립트

기존 law.db에서 의료/헬스케어 관련 판례 + 보건의료 행정규칙만 추려
경량 medilaw.db를 만든다. 4대 법령(의료법·개인정보보호법·생명윤리법·정보통신망법)
본문은 이 DB에 없으므로 이후 Open API ingest 단계에서 같은 스키마로 채운다.

원본 law.db는 ATTACH READONLY로만 접근 → 절대 수정하지 않음.
사용법: python scripts/extract_medical.py --src data/law.db --out data/medilaw.db
"""
import argparse
import os
import sqlite3

# --- 의료 도메인 필터 (튜닝 포인트) ---------------------------------------
# 판례: 아래 키워드 중 하나라도 case_name/issues/summary/ref_text/body에 포함되면 포함.
# '병원'처럼 오탐이 큰 단독어는 제외하고, 의료법 맥락 식별력이 높은 어휘 위주.
# 4대 법령 도메인별로 구성 (의료법만이 아니라 4개 법 전부 커버).
# "의사" 단독은 제외 — "의사표시"(민법) 등 오탐이 3만건+.
CASE_KEYWORDS = [
    # 의료법
    "의료법", "의료기관", "의료인", "의료광고", "의료과실", "의료행위",
    "진료기록", "진료", "환자", "한의사", "치과의사", "약사",
    "요양기관", "보건의료", "건강보험",
    # 개인정보보호법
    "개인정보", "민감정보", "가명정보", "정보주체", "개인정보처리자",
    # 생명윤리법
    "생명윤리", "인체유래물", "배아", "유전자검사", "연구대상자", "인간대상연구",
    # 정보통신망법
    "정보통신망", "정보통신서비스", "광고성 정보",
]

# 법령/행정규칙: 소관이 보건복지부이거나, 이름에 보건의료 어휘가 들어간 것.
STATUTE_KEYWORDS = [
    "의료", "의약", "진료", "환자", "보건", "병원", "의원", "약사", "약국",
    "건강", "개인정보", "생명윤리", "혈액", "감염병", "정신건강",
]
STATUTE_SIDO = ["보건복지부", "식품의약품안전처", "질병관리청"]


def _like_or(column_exprs, keywords):
    """(col1 LIKE ? OR col1 LIKE ? OR col2 LIKE ? ...) 절과 파라미터 생성"""
    clauses, params = [], []
    for col in column_exprs:
        for kw in keywords:
            clauses.append(f"{col} LIKE ?")
            params.append(f"%{kw}%")
    return "(" + " OR ".join(clauses) + ")", params


def init_schema(conn):
    """ingest.py와 동일한 스키마 — API ingest와 호환되도록 맞춤."""
    conn.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS cases (
            id INTEGER PRIMARY KEY, seq_no TEXT, case_no TEXT, case_name TEXT,
            court TEXT, court_level TEXT, case_type TEXT, date TEXT,
            summary TEXT, issues TEXT, ref_text TEXT, body TEXT, source_url TEXT
        );
        CREATE TABLE IF NOT EXISTS statutes (
            id INTEGER PRIMARY KEY, law_id TEXT UNIQUE, name TEXT, kind TEXT,
            region_sido TEXT, region_sigungu TEXT, region_branch TEXT,
            promulgated_on TEXT, effective_from TEXT, source_url TEXT,
            trust_grade TEXT, version_count INTEGER DEFAULT 1, estrev_label TEXT
        );
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY, statute_id INTEGER REFERENCES statutes(id),
            article_no TEXT, article_title TEXT, content TEXT
        );
        CREATE TABLE IF NOT EXISTS case_statute_refs (
            case_id INTEGER, statute_id INTEGER, ref_count INTEGER DEFAULT 1,
            PRIMARY KEY (case_id, statute_id)
        );
        CREATE INDEX IF NOT EXISTS idx_cases_date     ON cases(date);
        CREATE INDEX IF NOT EXISTS idx_cases_type     ON cases(case_type);
        CREATE INDEX IF NOT EXISTS idx_statutes_kind  ON statutes(kind);
        CREATE INDEX IF NOT EXISTS idx_articles_statute ON articles(statute_id);
    """)
    conn.commit()


def extract_cases(conn):
    where, params = _like_or(
        ["case_name", "issues", "summary", "ref_text", "body"], CASE_KEYWORDS
    )
    conn.execute(
        f"""INSERT INTO cases
            (id,seq_no,case_no,case_name,court,court_level,case_type,date,
             summary,issues,ref_text,body,source_url)
            SELECT id,seq_no,case_no,case_name,court,court_level,case_type,date,
                   summary,issues,ref_text,body,source_url
            FROM src.cases WHERE {where}""",
        params,
    )
    conn.commit()
    return conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]


def extract_statutes(conn):
    name_where, params = _like_or(["name"], STATUTE_KEYWORDS)
    sido_ph = ",".join("?" * len(STATUTE_SIDO))
    conn.execute(
        f"""INSERT OR IGNORE INTO statutes
            SELECT * FROM src.statutes
            WHERE region_sido IN ({sido_ph}) OR {name_where}""",
        STATUTE_SIDO + params,
    )
    # 추출된 법령의 조문만 복사
    conn.execute(
        """INSERT INTO articles (id,statute_id,article_no,article_title,content)
           SELECT a.id,a.statute_id,a.article_no,a.article_title,a.content
           FROM src.articles a
           WHERE a.statute_id IN (SELECT id FROM statutes)"""
    )
    conn.commit()
    s = conn.execute("SELECT COUNT(*) FROM statutes").fetchone()[0]
    a = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    return s, a


def copy_refs(conn):
    """기존 인용 그래프 중 살아남은 판례·법령 쌍만 복사 (대부분 API 적재 후 재구성됨)."""
    conn.execute(
        """INSERT OR IGNORE INTO case_statute_refs
           SELECT * FROM src.case_statute_refs
           WHERE case_id IN (SELECT id FROM cases)
             AND statute_id IN (SELECT id FROM statutes)"""
    )
    conn.commit()
    return conn.execute("SELECT COUNT(*) FROM case_statute_refs").fetchone()[0]


def build_fts(conn):
    conn.executescript("""
        CREATE VIRTUAL TABLE IF NOT EXISTS cases_fts USING fts5(
            case_no, case_name, summary, issues, body,
            content=cases, content_rowid=id, tokenize='unicode61');
        CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
            article_no, article_title, content,
            content=articles, content_rowid=id, tokenize='unicode61');
    """)
    conn.execute("INSERT INTO cases_fts(cases_fts) VALUES('rebuild')")
    conn.execute("INSERT INTO articles_fts(articles_fts) VALUES('rebuild')")
    conn.commit()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--src", default="data/law.db")
    p.add_argument("--out", default="data/medilaw.db")
    args = p.parse_args()

    if os.path.exists(args.out):
        os.remove(args.out)
    conn = sqlite3.connect(args.out, uri=True)
    # 원본은 read-only로만 ATTACH → 절대 수정되지 않음
    conn.execute(f"ATTACH DATABASE 'file:{os.path.abspath(args.src)}?mode=ro' AS src")

    init_schema(conn)
    n_cases = extract_cases(conn)
    n_stat, n_art = extract_statutes(conn)
    n_refs = copy_refs(conn)
    build_fts(conn)
    conn.execute("DETACH DATABASE src")  # 원본 분리 후 최적화 (readonly 쓰기 방지)
    conn.execute("PRAGMA optimize")
    conn.close()

    size_mb = os.path.getsize(args.out) / 1024 / 1024
    print("=== medilaw.db 추출 완료 ===")
    print(f"  판례(cases)        : {n_cases:,}")
    print(f"  법령/행정규칙       : {n_stat:,}")
    print(f"  조문(articles)     : {n_art:,}")
    print(f"  인용 그래프(refs)   : {n_refs:,}  (API 법령 적재 후 재구성 예정)")
    print(f"  파일 크기          : {size_mb:.1f} MB")


if __name__ == "__main__":
    main()
