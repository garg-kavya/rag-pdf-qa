"""Test all unique PDF types in the uploads folder against the live RAG system."""
from __future__ import annotations

import json
import os
import time
import urllib.request
import urllib.error
from pathlib import Path

BASE = "http://localhost:8000/api/v1"
UPLOADS = Path(__file__).parent.parent / "uploads"
TIMEOUT_SECS = 600   # max wait per file for ingestion (OCR PDFs can take 5-10 min)
POLL_INTERVAL = 5
UPLOAD_DELAY = 7     # seconds between uploads (rate limit: 10/min on /documents)

# ── one representative file per unique name ──────────────────────────────────
UNIQUE_FILES: dict[str, str] = {
    "1500VegWhey(120-140)pOPTIMALTODIRTY.pdf": "58d3537a-ded4-400a-8ea1-fc0bedbc2867_1500VegWhey(120-140)pOPTIMALTODIRTY.pdf",
    "62Macro-FriendlyRecipes.pdf":              "3f0313ec-5d66-4755-85dd-ee7c23f2945b_62Macro-FriendlyRecipes.pdf",
    "biostor-140092.pdf":                       "e150fe45-e24f-47ae-ae88-7cf5c75dce81_biostor-140092.pdf",
    "deep_learning_guide.pdf":                  "4c14090a-f898-4326-a5bc-6046ddf4f70b_deep_learning_guide.pdf",
    "Kanishk_Bajpai_CV_2026.pdf":               "3e0b26e0-1b4b-4d60-8021-dd69706f92ca_Kanishk_Bajpai_CV_2026.pdf",
    "Kavya_Garg_ATS.pdf":                       "604051e9-f5ca-46f7-98e6-9f07331ac2d0_Kavya_Garg_ATS.pdf",
    "Kavya_Garg_Final (1).pdf":                 "67ad6af6-6033-40fc-93e6-901c7d67425c_Kavya_Garg_Final (1).pdf",
    "Kavya_Garg_Resume_compressed.pdf":         "122de67b-945d-4d1b-a0cb-60902c45eebf_Kavya_Garg_Resume_compressed.pdf",
    "machine_learning_intro.pdf":               "61d9aa52-3356-4f7f-a24d-dacd239f5f81_machine_learning_intro.pdf",
    "Module 4.pdf":                             "677d4406-b955-436a-9607-cff05ddab5b5_Module 4.pdf",
    "Module-1.pdf":                             "846892ef-048a-4c5f-bddd-9f06c8fd0fc1_Module-1.pdf",
    "nlp_fundamentals.pdf":                     "06bd232b-f2bf-49cf-b3ca-d890f5e23851_nlp_fundamentals.pdf",
    "test.pdf":                                 "09e680b1-7131-4123-aba3-2306dabcf517_test.pdf",
    "test_ml.pdf":                              "26192ac3-1634-4ff6-9a67-2c797c0fd5bd_test_ml.pdf",
    "TheETFcookbook.pdf":                       "a7c2be8e-5d1f-404a-9754-42300a5b1d29_TheETFcookbook.pdf",
}


# ── helpers ──────────────────────────────────────────────────────────────────

def _req(method: str, path: str, token: str, data=None, content_type="application/json"):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(
        f"{BASE}{path}", data=body, method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": content_type},
    )
    resp = urllib.request.urlopen(req, timeout=30)
    return json.loads(resp.read())


def login() -> str:
    data = json.dumps({"email": "test@example.com", "password": "testpass123"}).encode()
    req = urllib.request.Request(
        f"{BASE}/auth/login", data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=30)
    return json.loads(resp.read())["access_token"]


def upload_file(file_path: Path, filename: str, token: str) -> dict:
    """Multipart upload."""
    boundary = "----DocMindBoundary"
    with open(file_path, "rb") as f:
        file_data = f.read()

    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: application/pdf\r\n\r\n"
    ).encode() + file_data + f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        f"{BASE}/documents/upload", data=body, method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    resp = urllib.request.urlopen(req, timeout=30)
    return json.loads(resp.read())


def poll_status(doc_id: str, token: str) -> tuple[str, str | None]:
    """Poll until ready/error or timeout. Returns (status, error_message)."""
    deadline = time.time() + TIMEOUT_SECS
    while time.time() < deadline:
        try:
            result = _req("GET", f"/documents/{doc_id}", token)
            st = result["status"]
            if st in ("ready", "error"):
                return st, result.get("error_message")
        except Exception:
            pass  # server may be busy with OCR — retry next interval
        time.sleep(POLL_INTERVAL)
    return "timeout", "Ingestion did not complete within timeout"


def query_doc(doc_id: str, token: str) -> str:
    """Create session, ask a question, return answer."""
    sess = _req("POST", "/sessions", token, {"document_ids": [doc_id]})
    session_id = sess["session_id"]
    result = _req("POST", "/query", token, {
        "question": "What is this document about? Give a one-sentence summary.",
        "session_id": session_id,
    })
    _req("DELETE", f"/sessions/{session_id}", token)
    return result.get("answer", "")


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    print("Logging in...")
    token = login()
    print("OK\n")

    results: list[dict] = []

    for display_name, stored_name in UNIQUE_FILES.items():
        file_path = UPLOADS / stored_name
        if not file_path.exists():
            results.append({"file": display_name, "status": "SKIP", "detail": "File not found on disk"})
            continue

        size_kb = file_path.stat().st_size // 1024
        print(f"[{display_name}] ({size_kb} KB) — uploading...", end="", flush=True)

        try:
            upload_resp = upload_file(file_path, display_name, token)
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode()
            except Exception:
                body = "(could not read response body)"
            if e.code == 429:
                print(f" RATE LIMITED — waiting 65s...", end="", flush=True)
                time.sleep(65)
                try:
                    upload_resp = upload_file(file_path, display_name, token)
                except Exception as e2:
                    results.append({"file": display_name, "status": "FAIL", "detail": f"Upload retry failed: {e2}"})
                    print(f" RETRY FAIL")
                    continue
            else:
                results.append({"file": display_name, "status": "FAIL", "detail": f"Upload HTTP {e.code}: {body[:200]}"})
                print(f" UPLOAD FAIL ({e.code})")
                continue
        except Exception as e:
            results.append({"file": display_name, "status": "FAIL", "detail": f"Upload error: {e}"})
            print(f" UPLOAD FAIL ({e})")
            continue

        doc_id = upload_resp["document_id"]
        print(f" uploaded ({doc_id[:8]}), polling...", end="", flush=True)
        time.sleep(UPLOAD_DELAY)  # respect rate limit between uploads

        st, err = poll_status(doc_id, token)
        if st == "error":
            # Scanned/image-only PDFs fail when OCR tools aren't installed locally
            err_str = err or ""
            if "scanned" in err_str.lower() or "no extractable text" in err_str.lower() or "ocr" in err_str.lower():
                results.append({"file": display_name, "status": "EXPECTED_FAIL",
                                 "detail": "Scanned/image-only PDF — needs OCR (tesseract+poppler not installed locally; works in Docker)"})
                print(f" EXPECTED FAIL (scanned PDF, OCR unavailable locally)")
            else:
                results.append({"file": display_name, "status": "FAIL", "detail": f"Ingestion error: {err_str}"})
                print(f" INGESTION ERROR: {err_str}")
            continue
        if st == "timeout":
            results.append({"file": display_name, "status": "FAIL", "detail": "Ingestion timeout"})
            print(" TIMEOUT")
            continue

        print(f" ready, querying...", end="", flush=True)

        try:
            answer = query_doc(doc_id, token)
            if answer and len(answer.strip()) > 10:
                results.append({"file": display_name, "status": "PASS", "detail": answer[:120]})
                print(f" PASS")
            else:
                results.append({"file": display_name, "status": "FAIL", "detail": f"Empty/short answer: '{answer}'"})
                print(f" FAIL (empty answer)")
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode()
            except Exception:
                body = "(could not read response body)"
            results.append({"file": display_name, "status": "FAIL", "detail": f"Query HTTP {e.code}: {body[:200]}"})
            print(f" QUERY FAIL ({e.code})")
        except Exception as e:
            results.append({"file": display_name, "status": "FAIL", "detail": f"Query error: {e}"})
            print(f" QUERY FAIL ({e})")

    # ── summary ──────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print(f"{'FILE':<45} {'STATUS':<8} DETAIL")
    print("=" * 70)
    passed = failed = skipped = expected_fail = 0
    for r in results:
        if r["status"] == "PASS":
            icon = "PASS"; passed += 1
        elif r["status"] == "SKIP":
            icon = "SKIP"; skipped += 1
        elif r["status"] == "EXPECTED_FAIL":
            icon = "XFAIL"; expected_fail += 1
        else:
            icon = "FAIL"; failed += 1
        print(f"[{icon}] {r['file']:<43} {r['detail'][:55]}")
    print("=" * 70)
    print(f"PASSED: {passed}  FAILED: {failed}  EXPECTED_FAIL: {expected_fail}  SKIPPED: {skipped}  TOTAL: {len(results)}")

    return failed


if __name__ == "__main__":
    exit(main())
