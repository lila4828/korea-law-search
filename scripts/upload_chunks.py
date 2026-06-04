"""
DB 파일을 청크로 분할해서 Railway에 업로드
사용법: python3 scripts/upload_chunks.py
"""
import os
import sys
import urllib.request

DB_PATH = "data/law.db"
CHUNK_SIZE = 50 * 1024 * 1024  # 50MB
BASE_URL = "https://korea-law-search-production.up.railway.app"
TOKEN = "mylaw"


def upload_chunk(index: int, data: bytes) -> bool:
    boundary = "----ChunkBoundary"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="chunk"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + data + f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        f"{BASE_URL}/admin/upload-chunk/{index}",
        data=body,
        headers={
            "x-upload-token": TOKEN,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            print(f"  청크 {index}: {resp.read().decode()}")
            return True
    except Exception as e:
        print(f"  청크 {index} 실패: {e}")
        return False


def finalize() -> bool:
    req = urllib.request.Request(
        f"{BASE_URL}/admin/finalize-db",
        data=b"",
        headers={"x-upload-token": TOKEN},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            print(f"  finalize: {resp.read().decode()}")
            return True
    except Exception as e:
        print(f"  finalize 실패: {e}")
        return False


def main():
    size = os.path.getsize(DB_PATH)
    total_chunks = (size + CHUNK_SIZE - 1) // CHUNK_SIZE
    print(f"DB 크기: {size / 1024 / 1024:.1f}MB / {total_chunks}개 청크 (각 50MB)")

    with open(DB_PATH, "rb") as f:
        for i in range(total_chunks):
            data = f.read(CHUNK_SIZE)
            if not data:
                break
            mb = len(data) / 1024 / 1024
            print(f"[{i+1}/{total_chunks}] {mb:.1f}MB 업로드 중...")
            if not upload_chunk(i, data):
                print("업로드 실패. 중단합니다.")
                sys.exit(1)

    print("모든 청크 완료. 합치는 중...")
    finalize()
    print("완료!")


if __name__ == "__main__":
    main()
