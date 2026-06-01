"""
zip 파일 → SQLite 변환 스크립트
사용법: python scripts/ingest.py --data-dir /path/to/zips --db data/law.db
"""
import argparse
import json
import os
import re
import sqlite3
import struct
import sys
import zipfile
import zlib
from pathlib import Path

LOCAL_SIG = b'PK\x03\x04'
DD_SIG = b'PK\x07\x08'


def stream_zip(zip_path):
    """ZIP 로컬 헤더를 직접 읽어 스트리밍. 중앙 디렉토리 미사용 → 메모리 O(1)"""
    with open(zip_path, 'rb') as f:
        while True:
            sig = f.read(4)
            if len(sig) < 4 or sig != LOCAL_SIG:
                break
            raw = f.read(26)
            if len(raw) < 26:
                break
            # 로컬 헤더 26바이트: 5×H + 3×I + 2×H
            (_, flags, compression, _, _, _,
             comp_size, uncomp_size, fn_len, extra_len) = struct.unpack('<HHHHHIIIHH', raw)

            filename = f.read(fn_len).decode('utf-8', errors='ignore')
            f.read(extra_len)

            # 디렉토리 엔트리 — 데이터 없음
            if filename.endswith('/'):
                if comp_size > 0:
                    f.read(comp_size)
                continue

            has_dd = bool(flags & 0x08)  # bit3: 데이터 디스크립터 플래그

            if has_dd:
                # 압축 크기 미정 → 다음 PK 시그니처까지 스캔
                buf = b''
                found = False
                while True:
                    chunk = f.read(8192)
                    if not chunk:
                        break
                    buf += chunk
                    for marker in (DD_SIG, LOCAL_SIG):
                        idx = buf.find(marker)
                        if idx != -1:
                            comp_data = buf[:idx]
                            back = len(buf) - idx - (12 if marker == DD_SIG else 0)
                            if back > 0:
                                f.seek(-back, 1)
                            if marker == DD_SIG:
                                f.read(12)
                            found = True
                            break
                    if found:
                        break
                    buf = buf[-8:]
                if not found:
                    continue
            else:
                comp_data = f.read(comp_size)

            try:
                if compression == 8:
                    content = zlib.decompress(comp_data, -15)
                elif compression == 0:
                    content = comp_data
                else:
                    continue
            except Exception:
                continue
            yield filename, content


ZIPS = {
    "cases": "cases-판례.zip",
    "admrule": "statutes-행정규칙.zip",
    "gwangju": "statutes-광주광역시.zip",
    "sejong": "statutes-세종특별자치시.zip",
    "jeonnam": "statutes-전라남도.zip",
    "jeonbuk": "statutes-전북특별자치도.zip",
}


def init_db(conn: sqlite3.Connection):
    conn.executescript("""
        PRAGMA journal_mode=WAL;
        PRAGMA synchronous=NORMAL;

        CREATE TABLE IF NOT EXISTS cases (
            id          INTEGER PRIMARY KEY,
            seq_no      TEXT,
            case_no     TEXT,
            case_name   TEXT,
            court       TEXT,
            court_level TEXT,
            case_type   TEXT,
            date        TEXT,
            summary     TEXT,
            source_url  TEXT
        );

        CREATE TABLE IF NOT EXISTS statutes (
            id              INTEGER PRIMARY KEY,
            law_id          TEXT UNIQUE,
            name            TEXT,
            kind            TEXT,
            region_sido     TEXT,
            region_sigungu  TEXT,
            region_branch   TEXT,
            promulgated_on  TEXT,
            effective_from  TEXT,
            source_url      TEXT,
            trust_grade     TEXT,
            version_count   INTEGER DEFAULT 1,
            estrev_label    TEXT
        );

        CREATE TABLE IF NOT EXISTS articles (
            id          INTEGER PRIMARY KEY,
            statute_id  INTEGER REFERENCES statutes(id),
            article_no  TEXT,
            article_title TEXT,
            content     TEXT
        );

        CREATE TABLE IF NOT EXISTS case_statute_refs (
            case_id    INTEGER REFERENCES cases(id),
            statute_id INTEGER REFERENCES statutes(id),
            ref_count  INTEGER DEFAULT 1,
            PRIMARY KEY (case_id, statute_id)
        );

        CREATE INDEX IF NOT EXISTS idx_cases_date       ON cases(date);
        CREATE INDEX IF NOT EXISTS idx_cases_type       ON cases(case_type);
        CREATE INDEX IF NOT EXISTS idx_cases_court      ON cases(court);
        CREATE INDEX IF NOT EXISTS idx_statutes_sido    ON statutes(region_sido);
        CREATE INDEX IF NOT EXISTS idx_statutes_kind    ON statutes(kind);
        CREATE INDEX IF NOT EXISTS idx_statutes_date    ON statutes(effective_from);
        CREATE INDEX IF NOT EXISTS idx_articles_statute ON articles(statute_id);
    """)
    conn.commit()


def create_fts(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE VIRTUAL TABLE IF NOT EXISTS cases_fts USING fts5(
            case_no, case_name, summary,
            content=cases, content_rowid=id,
            tokenize='unicode61'
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
            article_no, article_title, content,
            content=articles, content_rowid=id,
            tokenize='unicode61'
        );
    """)
    conn.execute("INSERT INTO cases_fts(cases_fts) VALUES('rebuild')")
    conn.execute("INSERT INTO articles_fts(articles_fts) VALUES('rebuild')")
    conn.commit()


def parse_case_md(text: str) -> dict:
    """YAML frontmatter + Markdown 판례 파싱"""
    meta = {}
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            for line in text[3:end].splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    meta[k.strip()] = v.strip().strip("'\"")
            text = text[end + 3:]

    summary = ""
    m = re.search(r"##\s*판결요지\s*\n+(.*?)(?=\n##|\Z)", text, re.DOTALL)
    if m:
        summary = m.group(1).strip()[:2000]

    return {
        "seq_no":      meta.get("판례일련번호", ""),
        "case_no":     meta.get("사건번호", ""),
        "case_name":   meta.get("사건명", ""),
        "court":       meta.get("법원명", ""),
        "court_level": meta.get("법원등급", ""),
        "case_type":   meta.get("사건종류", ""),
        "date":        meta.get("선고일자", ""),
        "summary":     summary,
        "source_url":  meta.get("출처", ""),
    }


def ingest_cases(conn: sqlite3.Connection, zip_path: str):
    print(f"[판례] {zip_path}")
    rows = []
    with zipfile.ZipFile(zip_path) as z:
        names = [n for n in z.namelist() if n.endswith(".md")]
        total = len(names)
        for i, name in enumerate(names):
            if i % 10000 == 0:
                print(f"  {i}/{total}...")
            try:
                text = z.read(name).decode("utf-8", errors="ignore")
                row = parse_case_md(text)
                rows.append(row)
            except Exception:
                continue
            if len(rows) >= 500:
                _insert_cases(conn, rows)
                rows = []
    if rows:
        _insert_cases(conn, rows)
    print(f"  완료: {total}건")


def _insert_cases(conn: sqlite3.Connection, rows: list):
    conn.executemany(
        """INSERT OR IGNORE INTO cases
           (seq_no,case_no,case_name,court,court_level,case_type,date,summary,source_url)
           VALUES (:seq_no,:case_no,:case_name,:court,:court_level,:case_type,:date,:summary,:source_url)""",
        rows,
    )
    conn.commit()


def ingest_statutes_streaming(conn: sqlite3.Connection, zip_path: str, label: str):
    """로컬 헤더 스트리밍 — 중앙 디렉토리 없이 O(1) 메모리로 대용량 zip 처리"""
    print(f"[법령(스트리밍):{label}] {zip_path}")
    current_statute_id = None
    current_base = ""
    article_rows: list = []
    statute_count = 0

    def flush():
        if article_rows and current_statute_id:
            conn.executemany(
                "INSERT INTO articles (statute_id,article_no,article_title,content) VALUES (?,?,?,?)",
                article_rows,
            )
            conn.commit()
            article_rows.clear()

    for filename, content in stream_zip(zip_path):
        if filename.endswith("meta.json"):
            flush()
            try:
                meta = json.loads(content.decode("utf-8", errors="ignore"))
            except Exception:
                current_statute_id = None
                continue
            region = meta.get("region", {}) or {}
            law_id = meta.get("alr_bdt_id", "") or meta.get("law_id", "")
            cur = conn.execute(
                """INSERT OR IGNORE INTO statutes
                   (law_id,name,kind,region_sido,region_sigungu,region_branch,
                    promulgated_on,effective_from,source_url,trust_grade,version_count,estrev_label)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (law_id, meta.get("ord_name",""), meta.get("ord_kind",""),
                 region.get("sido",""), region.get("sigungu",""), region.get("branch",""),
                 meta.get("promulgated_on",""), meta.get("effective_from",""),
                 meta.get("source_url",""), meta.get("trust_grade",""),
                 meta.get("version_count",1), meta.get("estrev_label","")),
            )
            current_statute_id = cur.lastrowid or None
            current_base = filename.replace("meta.json", "current.articles/")
            statute_count += 1
            if statute_count % 2000 == 0:
                print(f"  {statute_count}개 처리 중...")

        elif "current.articles" in filename and filename.endswith(".txt"):
            if not current_statute_id:
                continue
            if not filename.startswith(current_base):
                continue
            try:
                text = content.decode("utf-8", errors="ignore")
                fname = Path(filename).stem
                parts = fname.split("_", 2)
                article_no = parts[1] if len(parts) > 1 else ""
                article_title = parts[2].replace("_", " ") if len(parts) > 2 else ""
                article_rows.append((current_statute_id, article_no, article_title, text))
            except Exception:
                continue

    flush()
    print(f"  완료: {statute_count}개 법령")


def ingest_statutes(conn: sqlite3.Connection, zip_path: str, label: str):
    """메모리 효율적 법령 ingest — zip을 한 번만 순회해서 O(n) 처리"""
    print(f"[법령:{label}] {zip_path}")
    with zipfile.ZipFile(zip_path) as z:
        # 1단계: 단일 순회로 meta 경로와 조문 경로를 분류·인덱싱
        print("  인덱싱 중...")
        meta_paths = []
        article_index: dict[str, list[str]] = {}  # statute_base → [art_paths]

        for name in z.namelist():
            if name.endswith("meta.json"):
                meta_paths.append(name)
            elif "current.articles" in name and name.endswith(".txt"):
                base = name.split("current.articles/")[0] + "current.articles/"
                article_index.setdefault(base, []).append(name)

        total = len(meta_paths)
        print(f"  법령 수: {total}, 조문 그룹: {len(article_index)}")

        # 2단계: 각 법령 처리
        for i, meta_path in enumerate(meta_paths):
            if i % 2000 == 0:
                print(f"  {i}/{total}...")
            try:
                meta = json.loads(z.read(meta_path).decode("utf-8", errors="ignore"))
            except Exception:
                continue

            region = meta.get("region", {}) or {}
            law_id = meta.get("alr_bdt_id", "") or meta.get("law_id", "")

            cur = conn.execute(
                """INSERT OR IGNORE INTO statutes
                   (law_id,name,kind,region_sido,region_sigungu,region_branch,
                    promulgated_on,effective_from,source_url,trust_grade,version_count,estrev_label)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    law_id,
                    meta.get("ord_name", ""),
                    meta.get("ord_kind", ""),
                    region.get("sido", ""),
                    region.get("sigungu", ""),
                    region.get("branch", ""),
                    meta.get("promulgated_on", ""),
                    meta.get("effective_from", ""),
                    meta.get("source_url", ""),
                    meta.get("trust_grade", ""),
                    meta.get("version_count", 1),
                    meta.get("estrev_label", ""),
                ),
            )
            statute_id = cur.lastrowid
            if statute_id == 0:
                continue

            # O(1) 조문 조회 — 인덱스 활용
            base = meta_path.replace("meta.json", "current.articles/")
            article_rows = []
            for art_name in article_index.get(base, []):
                try:
                    content = z.read(art_name).decode("utf-8", errors="ignore")
                    fname = Path(art_name).stem
                    parts = fname.split("_", 2)
                    article_no = parts[1] if len(parts) > 1 else ""
                    article_title = parts[2].replace("_", " ") if len(parts) > 2 else ""
                    article_rows.append((statute_id, article_no, article_title, content))
                except Exception:
                    continue

            if article_rows:
                conn.executemany(
                    "INSERT INTO articles (statute_id,article_no,article_title,content) VALUES (?,?,?,?)",
                    article_rows,
                )
            conn.commit()

        # 처리 후 article_index 메모리 해제
        article_index.clear()
    print(f"  완료")


def build_citation_graph(conn: sqlite3.Connection):
    """판례 summary에서 법령명 추출 → case_statute_refs 구성"""
    print("[인용 그래프 구성 중...]")
    statute_names = {
        row[0]: row[1]
        for row in conn.execute("SELECT id, name FROM statutes WHERE name != ''")
    }
    cases = conn.execute("SELECT id, summary FROM cases WHERE summary != ''").fetchall()
    batch = []
    for case_id, summary in cases:
        for sid, sname in statute_names.items():
            if len(sname) > 4 and sname in summary:
                batch.append((case_id, sid, 1))
        if len(batch) >= 1000:
            conn.executemany(
                "INSERT OR IGNORE INTO case_statute_refs VALUES (?,?,?)", batch
            )
            conn.commit()
            batch = []
    if batch:
        conn.executemany(
            "INSERT OR IGNORE INTO case_statute_refs VALUES (?,?,?)", batch
        )
        conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM case_statute_refs").fetchone()[0]
    print(f"  인용 관계: {total}건")


def main():
    parser = argparse.ArgumentParser(description="법률 데이터 zip → SQLite 변환")
    parser.add_argument("--data-dir", default="/home/user1/law", help="zip 파일 디렉토리")
    parser.add_argument("--db", default="data/law.db", help="출력 SQLite 경로")
    parser.add_argument(
        "--skip",
        nargs="*",
        default=[],
        help="건너뛸 소스 키 (cases admrule gwangju sejong jeonnam jeonbuk)",
    )
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.db) or ".", exist_ok=True)
    conn = sqlite3.connect(args.db)
    init_db(conn)

    data_dir = args.data_dir
    for key, fname in ZIPS.items():
        if key in args.skip:
            print(f"[SKIP] {key}")
            continue
        path = os.path.join(data_dir, fname)
        if not os.path.exists(path):
            print(f"[없음] {path}")
            continue
        if key == "cases":
            ingest_cases(conn, path)
        elif key in ("jeonnam", "jeonbuk"):
            # 대용량 zip → 중앙 디렉토리 없는 스트리밍 방식
            ingest_statutes_streaming(conn, path, key)
        else:
            ingest_statutes(conn, path, key)

    build_citation_graph(conn)

    print("[FTS 인덱스 구성 중...]")
    create_fts(conn)

    conn.execute("PRAGMA optimize")
    conn.close()

    size_mb = os.path.getsize(args.db) / 1024 / 1024
    print(f"\n완료: {args.db} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
