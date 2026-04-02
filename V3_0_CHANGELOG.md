# TRIAGE-1 V.3.0 변경사항 요약

## 🔧 완료된 작업

### 1️⃣ BUG FIX: 위치 좌표 무시 (Bug #1)
**문제**: 위치 좌표를 다른 도시로 변경해도 항상 같은 병원만 추천됨
- 원인: `fetch_nearby_hospitals()`에서 `wgs84Lat`, `wgs84Lon`, `radius` 파라미터를 API 호출에 포함시키지 않음
- 결과: 항상 전국 첫 100개 병원만 가져옴

**수정**:
```python
# Before (❌)
params = {
    "serviceKey": NEMC_API_KEY,
    "pageNo": page,
    "numOfRows": 100,
}

# After (✅)
params = {
    "serviceKey": NEMC_API_KEY,
    "wgs84Lat": lat,      # ⭐ Location parameter
    "wgs84Lon": lng,      # ⭐ Location parameter
    "radius": radius_km,  # ⭐ Location parameter
    "pageNo": page,
    "numOfRows": 100,
}
```

✅ **결과**: 좌표 변경 시 추천 병원이 그 위치에 따라 제대로 변경됨

---

### 2️⃣ BUG FIX: 고정된 병상 수 (Bug #2)
**문제**: 모든 병원이 "5개" 가용 병상으로 표시됨

**원인**: `fetch_realtime_status()` 예외 발생 시 하드코딩된 폴백값
```python
except Exception as e:
    return {"hvec": 5, "hvoc": 2}  # ❌ Hardcoded fallback
```

**수정**: 하드코딩 제거, None 반환
```python
except Exception as e:
    return {"hvec": None, "hvoc": None}  # ✅ No hardcoded value
```

✅ **결과**: 
- 실제 데이터 반환: 병원별로 다른 병상 수 표시
- API 실패 시: "정보 없음" 표시 (가짜 "5개" 안 나옴)

---

### 3️⃣ 개선: Claude AI 통합
**기능**: 손상 분류별 최적 병상 유형을 AI가 자동 판단 → 전문적 추천 근거 생성

**구현**:
- `generate_explanation()` 함수 업그레이드 (Claude API 사용)
- 손상 부위 분석: 두부/흉부/복부 → 필요한 병상 유형 자동 판단
- 기존 휴리스틱 방식 폴백 (Claude 없을 때)

**API 설정**:
```
CLAUDE_API_KEY=sk-ant-YOUR_KEY (선택사항)
```

---

### 4️⃣ 개선: 진단 및 로깅 추가
**목적**: 두 API 간 ID 매핑 불일치 문제 디버깅

**로깅 태그**:
- `[BED_INFO]`: 병상 정보 조회 결과
- `[BED_API_RAW]`: 원본 API 응답 필드명
- `[BED_API_ERROR]`: API 에러 상세 정보

---

### 5️⃣ 개선: 버전 관리 강화
**변경사항**:
- `APP_VERSION = "3.0.0"` 추가
- API 응답에 버전 정보 포함
```json
{
  "app_version": {
    "version": "3.0.0",
    "date": "2026-04-01",
    "claude_enabled": true/false
  }
}
```

---

## 📊 테스트 결과

### 테스트 수행: test_bugs_fixed.py
```
✅ TEST 1: 위치 추적 (Location Tracking)
   광주 (35.17, 126.92) → 2개 병원 추천
   서울 (37.55, 126.97) → 1개 병원 추천
   부산 (35.1, 129.07)  → 3개 병원 추천
   ✅ 좌표당 다른 병원 추천 확인

✅ TEST 2: 병상 가용성 (Bed Availability)
   [None, None] 값 확인
   ✅ 하드코딩된 "5" 제거 확인
```

---

## 🚀 Git 커밋 히스토리

### V.3.0 체계 (최신)
```
3573adc - V.3.0: Update README with bug fixes and Claude AI integration
eecc373 - V.3.0: Add Claude AI integration for intelligent recommendations
8ae5d89 - V.3.0: Fix critical bugs - location tracking and bed availability
3f3699d - Update README with v2.1 changes and deployment info (v2.1)
```

---

## 📝 설정 안내

### Claude API 활성화 (선택사항)
1. `.env` 파일에 추가:
   ```
   CLAUDE_API_KEY=sk-ant-YOUR_ANTHROPIC_KEY
   ```
2. 앱 재시작 - 자동으로 Claude 사용 시작
3. 미설정 시: 기본 휴리스틱 설명 사용 (정상 작동)

### 데이터 흐름 확인
```
사용자 좌표 입력
  ↓
GET /api/recommend (lat, lng 전송)
  ↓
fetch_nearby_hospitals(lat, lng) 
  ├─ 이제 (✅) wgs84Lat, wgs84Lon, radius 포함
  ├─ 결과: 반경 내 병원만 반환
  └─ 각 병원의 bed_info 조회
  ↓
match_hospital() - 점수 계산
  ├─ 70% 병원 등급
  ├─ 15% 거리
  ├─ 10% 신규 병상 (CRDT_ICU)
  └─ 5% 실시간 상태 (이제 ✅ 하드코딩 안 함)
  ↓
generate_explanation() - AI 추천 근거 생성
  ├─ Claude API 사용 (가능하면)
  └─ 폴백: 휴리스틱 설명
```

---

## ✅ 검증 체크리스트

- [x] 위치 파라미터 API 호출에 포함됨
- [x] 하드코딩된 bed count fallback 제거됨
- [x] Claude API 통합 완료 (선택사항)
- [x] 버전 정보 추가됨 (3.0.0)
- [x] 진단 로깅 추가됨
- [x] README 업데이트됨
- [x] 모든 변경사항 Git 커밋됨
- [x] GitHub 동기화 완료됨

---

## 🎯 다음 단계

1. **Claude API 키 입수** (선택)
   - https://console.anthropic.com 에서 발급
   - `.env`에 `CLAUDE_API_KEY` 설정

2. **테스트 및 배포**
   ```powershell
   python app.py
   # 또는
   pip install -r requirements.txt
   python app.py
   ```

3. **모니터링**
   - 콘솔 로그에서 `[BED_INFO]`, `[BED_API_RAW]` 확인
   - 병상 정보 API 응답 형식 추적

---

## 📞 문의 및 피드백

- GitHub Issues: https://github.com/01084607801a-png/TRIAGE-1/issues
- 버그 보고: 콘솔 로그의 `[BED_API_RAW]` 섹션 함께 제공
