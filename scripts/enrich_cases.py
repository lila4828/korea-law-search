"""
기존 law.db에 판례 본문(판례내용)·판시사항·참조조문을 추가 보강.
법령(statutes/articles) 데이터는 건드리지 않고 판례 zip만 재파싱한다.

사용법: python3 scripts/enrich_cases.py [--db data/law.db] [--zip /home/user1/law/cases-판례.zip]
"""
import argparse
import os
import sqlite3
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ingest import parse_case_md, build_citation_graph  # noqa: E402


def add_columns(conn: sqlite3.Connection):
    existing = {r[1] for r in conn.execute("PRAGMA table_info(cases)")}
    for col in ("issues", "ref_text", "body"):
        if col not in existing:
            conn.execute(f"ALTER TABLE cases ADD COLUMN {col} TEXT")
            print(f"  + 컬럼 추가: {col}")
    conn.commit()


def enrich(conn: sqlite3.Connection, zip_path: str):
    print(f"[판례 재파싱] {zip_path}")
    updated = matched = 0
    batch = []
    with zipfile.ZipFile(zip_path) as z:
        names = [n for n in z.namelist() if n.endswith(".md")]
        total = len(names)
        for i, name in enumerate(names):
            if i % 10000 == 0:
                print(f"  {i}/{total}... (업데이트 {updated})")
            try:
                text = z.read(name).decode("utf-8", errors="ignore")
                row = parse_case_md(text)
            except Exception:
                continue
            if not row["seq_no"]:
                continue
            batch.append((row["summary"], row["issues"], row["ref_text"], row["body"], row["seq_no"]))
            if len(batch) >= 500:
                matched += _flush(conn, batch)
                updated += len(batch)
                batch = []
    if batch:
        matched += _flush(conn, batch)
        updated += len(batch)
    print(f"  완료: {updated}건 처리, {matched}건 매칭 업데이트")


def _flush(conn: sqlite3.Connection, batch: list) -> int:
    cur = conn.executemany(
        "UPDATE cases SET summary=?, issues=?, ref_text=?, body=? WHERE seq_no=?",
        batch,
    )
    conn.commit()
    return cur.rowcount


def rebuild_cases_fts(conn: sqlite3.Connection):
    """cases_fts를 본문·판시사항 포함 스키마로 재생성 (articles_fts는 건드리지 않음)"""
    print("[cases_fts 재구성 중...]")
    conn.execute("DROP TABLE IF EXISTS cases_fts")
    conn.executescript("""
        CREATE VIRTUAL TABLE cases_fts USING fts5(
            case_no, case_name, summary, issues, body,
            content=cases, content_rowid=id,
            tokenize='unicode61'
        );
    """)
    conn.execute("INSERT INTO cases_fts(cases_fts) VALUES('rebuild')")
    conn.commit()


def main():
    parser = argparse.ArgumentParser(description="판례 본문·참조조문 보강")
    parser.add_argument("--db", default="data/law.db")
    parser.add_argument("--zip", default="/home/user1/law/cases-판례.zip")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    add_columns(conn)
    enrich(conn, args.zip)
    rebuild_cases_fts(conn)

    print("[인용 그래프 재구성: 기존 관계 삭제 후 참조조문 기반으로 재생성]")
    conn.execute("DELETE FROM case_statute_refs")
    conn.commit()
    build_citation_graph(conn)

    print("[VACUUM 및 최적화...]")
    conn.execute("PRAGMA optimize")
    conn.commit()
    conn.close()

    size_mb = os.path.getsize(args.db) / 1024 / 1024
    print(f"\n완료: {args.db} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
