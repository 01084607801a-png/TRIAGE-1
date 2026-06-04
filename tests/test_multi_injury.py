#!/usr/bin/env python
"""TRIAGE-1 복수 손상 테스트 (AND 필터 + 전문과 점수 검증)"""

from datetime import datetime
import os
import subprocess
import sys
import time

import requests

BASE_URL = "http://127.0.0.1:5000"
LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "test_multi_injury.log")


def wait_until_ready(url, timeout_sec=25):
    start = time.time()
    while time.time() - start < timeout_sec:
        try:
            r = requests.get(url, timeout=2)
            if r.status_code in (200, 404):
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def start_server():
    proc = subprocess.Popen(
        [sys.executable, "app.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if not wait_until_ready(BASE_URL, timeout_sec=25):
        proc.terminate()
        raise RuntimeError("Flask server failed to start within timeout")
    return proc


def log(line):
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run_case(case):
    payload = {
        "gcs_motor": case["gcs_motor"],
        "sbp": case["sbp"],
        "rr": case["rr"],
        "injuries": case["injuries"],
        "age": case["age"],
        "lat": case["lat"],
        "lng": case["lng"],
    }

    log("-" * 90)
    log(f"[CASE] {case['name']}")
    log(f"입력: gcs_motor={case['gcs_motor']}, sbp={case['sbp']}, rr={case['rr']}, injuries={case['injuries']}, 좌표=({case['lat']}, {case['lng']})")

    try:
        resp = requests.post(f"{BASE_URL}/api/recommend", json=payload, timeout=30)
    except Exception as e:
        log(f"결과: 요청 실패 - {e}")
        return

    if resp.status_code != 200:
        log(f"결과: HTTP {resp.status_code}")
        log(resp.text[:400])
        return

    data = resp.json()
    matched = data.get("matched", [])
    if not matched:
        log("결과: 추천 병원 없음")
        return

    log("출력: 상위 3개 병원")
    for idx, h in enumerate(matched[:3], start=1):
        services = h.get("services", [])
        services_str = ", ".join(services[:8]) if services else "(정보없음)"
        score = h.get("score")
        s_score = h.get("specialty_match_score")
        req_specs = h.get("required_specialties", [])
        req_specs_str = ", ".join(req_specs) if req_specs else "(없음)"

        log(f"  {idx}. {h.get('name')} | 거리 {h.get('dist_km', 0):.1f}km | 총점 {score:.3f} | 전문과점수 {s_score:.3f}")
        log(f"     - 필수전문과: {req_specs_str}")
        log(f"     - 보유전문과: {services_str}")

    # 검증: AND 필터는 specialty_match_score==1.0인 후보만 남아야 정상
    all_and_ok = all((h.get("specialty_match_score", 0.0) >= 0.999) for h in matched)
    if all_and_ok:
        log("검증: AND 필터 통과 (필수 전문과 미충족 병원 제외됨)")
    else:
        log("검증: AND 필터 실패 가능성 있음 (specialty_match_score < 1.0 존재)")


if __name__ == "__main__":
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write(f"TRIAGE-1 multi-injury test log\nGenerated at: {datetime.now().isoformat()}\n\n")

    cases = [
        {
            "name": "여수-두부+흉부",
            "gcs_motor": 5,
            "sbp": 105,
            "rr": 22,
            "injuries": ["두부/경부", "흉부"],
            "age": 47,
            "lat": 34.7604,
            "lng": 127.6622,
        },
        {
            "name": "여수-복부+하지",
            "gcs_motor": 6,
            "sbp": 118,
            "rr": 20,
            "injuries": ["복부", "하지"],
            "age": 58,
            "lat": 34.7604,
            "lng": 127.6622,
        },
        {
            "name": "여수-척추+흉부",
            "gcs_motor": 4,
            "sbp": 95,
            "rr": 28,
            "injuries": ["척추", "흉부"],
            "age": 66,
            "lat": 34.7604,
            "lng": 127.6622,
        },
        {
            "name": "여수-두부+복부+흉부",
            "gcs_motor": 3,
            "sbp": 82,
            "rr": 32,
            "injuries": ["두부/경부", "복부", "흉부"],
            "age": 38,
            "lat": 34.7604,
            "lng": 127.6622,
        },
        {
            "name": "여수-상지+하지",
            "gcs_motor": 6,
            "sbp": 122,
            "rr": 18,
            "injuries": ["상지", "하지"],
            "age": 29,
            "lat": 34.7604,
            "lng": 127.6622,
        },
    ]

    server_proc = None
    try:
        log("서버 시작 중...")
        server_proc = start_server()
        log("서버 시작 완료")

        for c in cases:
            run_case(c)

        log("-" * 90)
        log(f"로그 파일 저장 완료: {LOG_FILE}")

    except Exception as e:
        log(f"테스트 실행 오류: {e}")
    finally:
        if server_proc is not None:
            server_proc.terminate()
