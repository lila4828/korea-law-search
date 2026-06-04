"""
판례의 ## 참조판례 섹션을 파싱해 판례→판례 인용 테이블(case_case_refs)을 구성.
- 로컬 data/law.db에 테이블 생성
- 라이브 병합용으로 data/case_refs.json (행 목록) 출력

사용법: python3 scripts/build_case_refs.py
"""
import argparse
import json
import os
import re
import sqlite3
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ingest import _section  # noqa: E402

# 사건번호 패턴: 연도(2~4자리) + 한글 1~3자 + 숫자
CASE_NO_RE = re.compile(r"\d{2,4}[가-힣]{1,3}\d{1,6}")

DDL = """
CREATE TABLE IF NOT EXISTS case_case_refs (
    citing_id     INTEGER NOT NULL,
    cited_case_no TEXT    NOT NULL,
    cited_id      INTEGER,
    PRIMARY KEY (citing_id, cited_case_no)
);
"""


def build(db_path: str, zip_path: str, json_out: str):
    conn = sqlite3.connect(db_path)
    conn.executescript(DDL)
    conn.execute("DELETE FROM case_case_refs")
    conn.commit()

    # 매핑 로드
    seq_to_id = {s: i for i, s in conn.execute("SELECT id, seq_no FROM cases WHERE seq_no!=''")}
    caseno_to_id = {cn: i for i, cn in conn.execute("SELECT id, case_no FROM cases WHERE case_no!=''")}
    print(f"매핑: seq_no {len(seq_to_id):,} / case_no {len(caseno_to_id):,}")

    rows = []
    seen = set()
    matched = 0
    with zipfile.ZipFile(zip_path) as z:
        names = [n for n in z.namelist() if n.endswith(".md")]
        total = len(names)
        for idx, name in enumerate(names):
            if idx % 20000 == 0:
                print(f"  {idx}/{total}... (refs {len(rows):,})")
            try:
                text = z.read(name).decode("utf-8", errors="ignore")
            except Exception:
                continue
            # frontmatter에서 seq_no
            seq = ""
            if text.startswith("---"):
                end = text.find("---", 3)
                if end != -1:
                    for line in text[3:end].splitlines():
                        if line.startswith("판례일련번호"):
                            seq = line.partition(":")[2].strip().strip("'\"")
                            break
                    body = text[end + 3:]
                else:
                    body = text
            else:
                body = text
            citing_id = seq_to_id.get(seq)
            if not citing_id:
                continue
            ref_sec = _section(body, "참조판례")
            if not ref_sec:
                continue
            for cn in set(CASE_NO_RE.findall(ref_sec)):
                key = (citing_id, cn)
                if key in seen:
                    continue
                seen.add(key)
                cited_id = caseno_to_id.get(cn)
                if cited_id == citing_id:  # 자기참조 제외
                    continue
                rows.append((citing_id, cn, cited_id))
                if cited_id:
                    matched += 1

    conn.executemany("INSERT OR IGNORE INTO case_case_refs VALUES (?,?,?)", rows)
    conn.commit()
    conn.close()

    with open(json_out, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False)

    print(f"\n완료: 인용관계 {len(rows):,}건 (DB 매칭 {matched:,}건)")
    print(f"  테이블: {db_path}:case_case_refs")
    print(f"  병합용 JSON: {json_out} ({os.path.getsize(json_out)/1024/1024:.1f} MB)")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="data/law.db")
    p.add_argument("--zip", default="/home/user1/law/cases-판례.zip")
    p.add_argument("--json", default="data/case_refs.json")
    a = p.parse_args()
    build(a.db, a.zip, a.json)


if __name__ == "__main__":
    main()
