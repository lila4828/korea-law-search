#!/usr/bin/env python3
"""
기능 9 — CLI 검색 도구
사용법:
  python cli/search.py cases "과징금" --type 세무
  python cli/search.py statutes "직소민원" --sido 광주
  python cli/search.py articles "잠재지문" --limit 5
"""
import argparse
import os
import sqlite3
import sys

DB_PATH = os.environ.get("DB_PATH", "data/law.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def cmd_cases(args):
    conn = get_db()
    params = []
    if args.query:
        sql = """SELECT c.id,c.case_no,c.case_name,c.court,c.case_type,c.date
                 FROM cases_fts f JOIN cases c ON c.id=f.rowid
                 WHERE cases_fts MATCH ?"""
        params.append(args.query)
    else:
        sql = "SELECT id,case_no,case_name,court,case_type,date FROM cases WHERE 1=1"

    prefix = "c." if args.query else ""
    if args.type:
        sql += f" AND {prefix}case_type=?"
        params.append(args.type)
    if args.court:
        sql += f" AND {prefix}court LIKE ?"
        params.append(f"%{args.court}%")
    sql += f" LIMIT {args.limit}"

    rows = conn.execute(sql, params).fetchall()
    print(f"{'ID':>6}  {'사건번호':<30}  {'사건명':<25}  {'법원':<15}  {'종류':<8}  선고일")
    print("-" * 100)
    for r in rows:
        print(f"{r['id']:>6}  {(r['case_no'] or ''):<30}  {(r['case_name'] or ''):<25}  "
              f"{(r['court'] or ''):<15}  {(r['case_type'] or ''):<8}  {r['date'] or ''}")


def cmd_statutes(args):
    conn = get_db()
    params = []
    if args.query:
        sql = """SELECT DISTINCT s.id,s.name,s.kind,s.region_sido,s.effective_from,s.trust_grade
                 FROM articles_fts f JOIN articles a ON a.id=f.rowid
                 JOIN statutes s ON s.id=a.statute_id
                 WHERE articles_fts MATCH ?"""
        params.append(args.query)
        prefix = "s."
    else:
        sql = "SELECT id,name,kind,region_sido,effective_from,trust_grade FROM statutes WHERE 1=1"
        prefix = ""

    if args.sido:
        sql += f" AND {prefix}region_sido LIKE ?"
        params.append(f"%{args.sido}%")
    if args.kind:
        sql += f" AND {prefix}kind=?"
        params.append(args.kind)
    sql += f" LIMIT {args.limit}"

    rows = conn.execute(sql, params).fetchall()
    print(f"{'ID':>6}  {'법령명':<40}  {'종류':<8}  {'시도':<15}  시행일        신뢰")
    print("-" * 95)
    for r in rows:
        print(f"{r['id']:>6}  {(r['name'] or ''):<40}  {(r['kind'] or ''):<8}  "
              f"{(r['region_sido'] or ''):<15}  {(r['effective_from'] or ''):<12}  {r['trust_grade'] or ''}")


def cmd_articles(args):
    conn = get_db()
    params = [args.query]
    sql = """SELECT a.id,a.article_no,a.article_title,s.name statute_name,
                    SUBSTR(a.content,1,200) preview
             FROM articles_fts f JOIN articles a ON a.id=f.rowid
             JOIN statutes s ON s.id=a.statute_id
             WHERE articles_fts MATCH ?
             LIMIT ?"""
    params.append(args.limit)
    rows = conn.execute(sql, params).fetchall()
    for r in rows:
        print(f"\n[{r['statute_name']}] {r['article_no']} {r['article_title']}")
        print(r['preview'])


def main():
    parser = argparse.ArgumentParser(description="법률 데이터 CLI 검색")
    sub = parser.add_subparsers(dest="cmd")

    p_cases = sub.add_parser("cases", help="판례 검색")
    p_cases.add_argument("query", nargs="?", default="")
    p_cases.add_argument("--type", help="사건종류")
    p_cases.add_argument("--court", help="법원명")
    p_cases.add_argument("--limit", type=int, default=20)

    p_st = sub.add_parser("statutes", help="법령 검색")
    p_st.add_argument("query", nargs="?", default="")
    p_st.add_argument("--sido", help="시도")
    p_st.add_argument("--kind", help="종류 (예규|훈령|고시)")
    p_st.add_argument("--limit", type=int, default=20)

    p_art = sub.add_parser("articles", help="조문 전문 검색")
    p_art.add_argument("query")
    p_art.add_argument("--limit", type=int, default=10)

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        sys.exit(1)

    if not os.path.exists(DB_PATH):
        print(f"DB 없음: {DB_PATH}\npython scripts/ingest.py 를 먼저 실행하세요.")
        sys.exit(1)

    {"cases": cmd_cases, "statutes": cmd_statutes, "articles": cmd_articles}[args.cmd](args)


if __name__ == "__main__":
    main()
