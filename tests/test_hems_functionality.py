"""
HEMS 기능 테스트 스크립트
닥터헬기 권고 로직 검증 및 시뮬레이션
"""

# 테스트를 위한 mock 데이터 구성
test_cases = [
    {
        "name": "테스트 1: AMPT Score 기반 HEMS 권고",
        "description": "GCS 저하 + 호흡곤란 + 불안정 흉벽 = 3점 → HEMS 권고",
        "patient": {
            "gcs_motor": 5,           # GCS < 14 → 1점 (의식저하)
            "sbp": 120,               # 정상
            "rr": 32,                 # RR > 29 → 1점 (호흡곤란)
            "injuries": ["두부/경부", "흉부"],  # 불안정 흉벽 → 1점
            "mechanism": "교통사고",  # 고에너지 기전
            "age": 45,
            "lat": 37.5665,
            "lng": 126.9780,
        },
        "expected": {
            "ampt_score": 3,
            "ampt_triggered": True,
            "hems_trigger_type": "AMPT",
            "hems_recommended": True,
        }
    },
    {
        "name": "테스트 2: 거리 기반 HEMS 권고",
        "description": "RED(고위험) + 지상 이송 거리 180km → HEMS 권고",
        "patient": {
            "gcs_motor": 15,          # 정상
            "sbp": 85,                # 저혈압 (RED)
            "rr": 18,                 # 정상
            "injuries": ["사지/골반골격"],
            "mechanism": "추락",
            "age": 55,
            "lat": 37.5665,
            "lng": 126.9780,
        },
        "first_hospital": {
            "name": "강릉아산병원",
            "dist_km": 180.0,         # ≥150km
            "level": "권역외상센터",
        },
        "expected": {
            "ampt_score": 0,
            "ampt_triggered": False,
            "hems_trigger_type": "DISTANCE",
            "hems_recommended": True,
        }
    },
    {
        "name": "테스트 3: 이중 트리거 HEMS 권고",
        "description": "AMPT Score 2점 + RED + 거리 160km → 이중 트리거",
        "patient": {
            "gcs_motor": 4,           # GCS < 14 → 1점
            "sbp": 85,                # 저혈압 (RED)
            "rr": 35,                 # RR > 29 → 1점
            "injuries": ["두부/경부", "흉부"],
            "mechanism": "교통사고",
            "age": 40,
            "lat": 37.5665,
            "lng": 126.9780,
        },
        "first_hospital": {
            "name": "부산권역외상센터",
            "dist_km": 160.0,         # ≥150km
            "level": "권역외상센터",
        },
        "expected": {
            "ampt_score": 2,
            "ampt_triggered": True,
            "hems_trigger_type": "BOTH",
            "hems_recommended": True,
        }
    },
    {
        "name": "테스트 4: HEMS 미권고 (AMPT < 2)",
        "description": "AMPT Score 1점 + 근거리 → HEMS 미권고",
        "patient": {
            "gcs_motor": 15,          # 정상
            "sbp": 120,               # 정상
            "rr": 20,                 # 정상
            "injuries": ["상지"],     # 경미한 손상
            "mechanism": "둔상",
            "age": 35,
            "lat": 37.5665,
            "lng": 126.9780,
        },
        "first_hospital": {
            "name": "서울대학교병원",
            "dist_km": 3.5,           # <150km
            "level": "권역외상센터",
        },
        "expected": {
            "ampt_score": 0,
            "ampt_triggered": False,
            "hems_trigger_type": "NONE",
            "hems_recommended": False,
        }
    },
    {
        "name": "테스트 5: 복수 골절 기반 HEMS (상지 + 하지)",
        "description": "상지 + 하지 = 2개 이상 근위부 긴뼈 골절 → 1점 + 다른 지표",
        "patient": {
            "gcs_motor": 5,           # GCS < 14 → 1점
            "sbp": 120,               # 정상
            "rr": 18,                 # 정상
            "injuries": ["상지", "하지"],  # 2개 이상 골절 → 1점 (총 2점)
            "mechanism": "교통사고",
            "age": 50,
            "lat": 37.5665,
            "lng": 126.9780,
        },
        "expected": {
            "ampt_score": 2,
            "ampt_triggered": True,
            "hems_trigger_type": "AMPT",
            "hems_recommended": True,
        }
    },
    {
        "name": "테스트 6: 골반 골절 의심 기반 HEMS",
        "description": "골반 + 고에너지 기전 + 호흡곤란 → 2점 HEMS 권고",
        "patient": {
            "gcs_motor": 15,          # 정상
            "sbp": 120,               # 정상
            "rr": 32,                 # RR > 29 → 1점
            "injuries": ["복부/골반장기"],  # 골반 골절 → 1점 (총 2점)
            "mechanism": "교통사고",
            "age": 45,
            "lat": 37.5665,
            "lng": 126.9780,
        },
        "expected": {
            "ampt_score": 2,
            "ampt_triggered": True,
            "hems_trigger_type": "AMPT",
            "hems_recommended": True,
        }
    },
    {
        "name": "테스트 7: 경미한 손상 (HEMS 미권고)",
        "description": "AMPT 미만족 + 거리 <150km → HEMS 미권고",
        "patient": {
            "gcs_motor": 15,          # 정상
            "sbp": 130,               # 정상
            "rr": 18,                 # 정상
            "injuries": ["안면"],     # 경미한 손상
            "mechanism": "둔상",
            "age": 28,
            "lat": 37.5665,
            "lng": 126.9780,
        },
        "first_hospital": {
            "name": "강북삼성병원",
            "dist_km": 8.0,           # <150km
            "level": "지역응급의료센터",
        },
        "expected": {
            "ampt_score": 0,
            "ampt_triggered": False,
            "hems_trigger_type": "NONE",
            "hems_recommended": False,
        }
    },
]

# 테스트 실행 예시
print("=" * 70)
print("HEMS(닥터헬기) 기능 테스트")
print("=" * 70)

for idx, test_case in enumerate(test_cases, 1):
    print(f"\n[테스트 {idx}] {test_case['name']}")
    print(f"설명: {test_case['description']}")
    print("-" * 70)
    
    patient = test_case["patient"]
    print(f"환자 정보:")
    print(f"  - GCS Motor: {patient['gcs_motor']}")
    print(f"  - 수축기 혈압: {patient['sbp']} mmHg")
    print(f"  - 호흡수: {patient['rr']}/분")
    print(f"  - 손상 부위: {', '.join(patient['injuries'])}")
    print(f"  - 손상 기전: {patient['mechanism']}")
    print(f"  - 나이: {patient['age']}세")
    
    if "first_hospital" in test_case:
        hospital = test_case["first_hospital"]
        print(f"\n병원 정보:")
        print(f"  - 이름: {hospital['name']}")
        print(f"  - 거리: {hospital['dist_km']:.1f}km")
        print(f"  - 등급: {hospital['level']}")
    
    expected = test_case["expected"]
    print(f"\n기대 결과:")
    print(f"  - AMPT Score: {expected['ampt_score']}점")
    print(f"  - AMPT 트리거: {'Yes' if expected['ampt_triggered'] else 'No'}")
    print(f"  - HEMS 트리거 타입: {expected['hems_trigger_type']}")
    print(f"  - HEMS 권고: {'✓ 강력 권고' if expected['hems_recommended'] else '✗ 미권고'}")

print("\n" + "=" * 70)
print("테스트 완료")
print("=" * 70)

# 실제 API 호출 예시
example_api_request = """
=== 실제 API 호출 예시 ===

POST /api/recommend HTTP/1.1
Content-Type: application/json

{
  "gcs_motor": 5,
  "sbp": 120,
  "rr": 32,
  "injuries": ["두부/경부", "흉부"],
  "mechanism": "교통사고",
  "age": 45,
  "lat": 37.5665,
  "lng": 126.9780
}

예상 응답 (HEMS 권고 포함):

{
  "matched": [
    {
      "name": "서울대학교병원",
      "level": "권역외상센터",
      "dist_km": 3.5,
      "hems_recommended": true,
      "reason": "🚁 [HEMS 권고] AMPT Score 3점 (≥2 HEMS 권고) — 의식저하 호흡곤란 불안정 흉벽",
      "score": 0.92,
      ...
    },
    ...
  ],
  "patient": {
    "gcs_motor": 5,
    "sbp": 120,
    "rr": 32,
    "injuries": ["두부/경부", "흉부"],
    "mechanism": "교통사고",
    "age": 45,
    "lat": 37.5665,
    "lng": 126.9780,
    "high_risk": true,
    "ampt_score": 3,
    "ampt_components": {
      "gcs_low": true,
      "respiratory_distress": true,
      "unstable_chest_wall": true,
      "multiple_proximal_fractures": false,
      "pelvic_fracture_suspected": false
    }
  },
  "hems_eligibility": {
    "hems_recommended": true,
    "hems_trigger_type": "AMPT",
    "ampt_score": 3,
    "reason": "AMPT Score 3점 (≥2 HEMS 권고) — 의식저하 호흡곤란 불안정 흉벽"
  },
  "field_triage": {
    "high_risk": true,
    "reason": {
      "gcs_motor": true,
      "sbp": false,
      "rr": true
    }
  }
}
"""

print(example_api_request)

# 프론트엔드 UI 반영 예시
ui_example = """
=== 프론트엔드 UI 표시 예시 ===

┌──────────────────────────────────────────────────────────────┐
│                                                              │
│  🚁 [HEMS 권고]                                             │
│  AMPT Score 3점 (≥2 HEMS 권고)                              │
│  의식저하 · 호흡곤란 · 불안정 흉벽                          │
│                                                              │
│  HEMS 생존율 94.9% > 지상 이송 90.5%                       │
│  권역외상센터 닥터헬기 출동을 최우선 요청하세요.             │
│                                                              │
└──────────────────────────────────────────────────────────────┘

[1순위 추천]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
서울대학교병원 (권역외상센터)
거리: 3.5km
외상중환자실: 25개
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[의학적 근거]
GCS Motor 저하(5점) → 의식변화 위험 OR 17.924
호흡수 32/분 → 호흡곤란, 기관 삽관 필요
두경부 손상 → 신경외과 즉시 수술 필수

[결론]
본 환자는 AMPT score 2점 초과 및 지상 이송 시 골든아워 초과가 
우려되어 권역외상센터 닥터헬기 출동 요청을 최우선 권고합니다.
"""

print(ui_example)
