from app import match_hospital, CRITICAL_SPECIALTIES, SUPPORTIVE_SPECIALTIES
import json

def test_facial_injury_undertriage():
    print("=== [TEST] Week 5: 안면 손상 환자 Undertriage 해결 검증 ===")
    
    # 1. 환자 정의 (RED 환자, 안면 + 흉부 손상)
    patient = {
        "gcs_motor": 6,
        "sbp": 80,  # SBP < 90 이므로 RED(고위험)로 분류됨 (app.py 로직 상)
        "rr": 20,
        "age": 45,
        "lat": 37.5665,
        "lng": 126.9780,
        "injuries": ["안면", "흉부"],  # 안면(성형외과, 이비인후과), 흉부(흉부외과) 필요
        "high_risk": True  # RED 환자
    }

    # 2. 가상의 권역외상센터 정의 (API 누락 발생 시뮬레이션)
    # 흉부외과는 있지만, 성형외과/이비인후과가 API에서 누락된 경우
    mock_hospital = {
        "name": "테스트 권역외상센터",
        "level": "권역외상센터",
        "lat": 37.5665,
        "lng": 126.9880,
        "services": ["외과", "흉부외과", "신경외과", "정형외과"], # 핵심과만 있음
        "services_confirmed": True,
        "hpid": "TEST001",
        "distance": 5.0,
        "bed_info": {"hvicc": 10},
        "hvec": 5,
        "hvoc": 2
    }

    print("\n[환자 정보]")
    print(f"- 중증도: {'RED(위독)' if patient['high_risk'] else 'YELLOW(양호)'}")
    print(f"- 손상 부위: {patient['injuries']}")
    print(f"- 필요 전문과: ['성형외과', '이비인후과', '흉부외과']")

    print("\n[병원 정보 (API 전문과 누락 상황)]")
    print(f"- 병원명: {mock_hospital['name']}")
    print(f"- 등급: {mock_hospital['level']}")
    print(f"- 보유 전문과: {mock_hospital['services']}")

    print("\n[매칭 결과 (추천 로직 실행)]")
    results = match_hospital(patient, [mock_hospital])

    if results:
        matched = results[0]
        print(f"✅ 테스트 성공: 병원이 추천 목록에 포함되었습니다!")
        print(f"   - 병원명: {matched['name']}")
        print(f"   - 누락된 지원 전문과: {matched['missing_specialties']}")
        print(f"   - 전원 지연 페널티: {matched['transfer_delay_penalty']:.2f}점 감점 (Soft Filter 적용)")
        print(f"   - 최종 적합도 점수: {matched['score']:.3f}점")
    else:
        print(f"❌ 테스트 실패: 병원이 추천 목록에서 제외되었습니다 (Hard Filter 발생).")

if __name__ == "__main__":
    test_facial_injury_undertriage()
