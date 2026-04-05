# TRIAGE-1 v3.2

AI 기반 외상 환자 최적 병원 매칭 시스템

**최종 업데이트**: 2026-04-05 | **버전**: 3.2 (운영 안정화 + 문제 해결)

## 설치

1. Python 3.10+ 설치
2. 가상환경 생성 및 활성화

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 환경변수 설정

### NEMC API 키 설정 (2개)

국립중앙의료원 API는 병원조회용/병상조회용 키를 분리해 설정합니다:

```powershell
$env:NEMC_HOSPITAL_API_KEY = "YOUR_HOSPITAL_API_KEY_HERE"
$env:NEMC_BED_API_KEY = "YOUR_BED_API_KEY_HERE"
```

### Claude API 키 설정 (선택사항)

지능형 추천문구 생성을 위해 Anthropic Claude API 키 설정:

```powershell
$env:CLAUDE_API_KEY = "sk-ant-YOUR_CLAUDE_KEY_HERE"
```

**설정하지 않으면**: 기본 휴리스틱 설명 사용 (Claude 없이도 작동)

**보안 주의**: 실제 API 키는 GitHub에 업로드하지 않도록 주의하세요. `.env` 파일 사용 권장:
1. 프로젝트 루트에 `.env` 파일 생성
2. `NEMC_HOSPITAL_API_KEY=your_hospital_api_key` 입력
3. `NEMC_BED_API_KEY=your_bed_api_key` 입력
4. `CLAUDE_API_KEY=your_claude_key` 입력 (선택)
5. `.gitignore`에 `.env` 추가됨 (이미 설정)

## 실행

### 로컬 개발 환경
```powershell
python app.py
```
browser: `http://localhost:5000` 접속

### 웹 배포 (외부 접근 가능)
실제 운영 환경에서는 클라우드 배포 권장:
- **Heroku**: `pip install gunicorn` → `gunicorn app:app`
- **AWS/Azure/GCP**: Docker 컨테이너 배포
- **임시 테스트**: ngrok 터널링
  ```powershell
  pip install pyngrok
  # app.py 내용에 ngrok 통합, 또는 별도로 ngrok 실행
  ngrok http 5000
  ```

## 실행 화면 스크린샷

![TRIAGE-1 실행 화면](./assets/triage-1-screenshot.png)

*이미지가 보이지 않으면 브라우저 새로고침(F5) 또는 GitHub에서 Raw 버튼을 클릭해보세요.*

## 기능

- GCS/SBP/RR/손상유형/나이/위치 입력
- CDC Field Triage 중증도 판별
- **전국 병원 데이터베이스 검색** (NEMC API 연동)
- **전문과 필터링**: 상해부위에 맞는 전문의를 보유한 병원 우선 추천
- 실시간 병상 가용성 확인
- 상위 3개 병원 추천, AI 설명(placeholder)

## 주요 개선사항

### v3.2 (현재) ⭐ 운영 안정화
- **실패 시 더미 병원 제거**: API 실패 시 특정 병원명 하드코딩 반환 제거, 503 오류를 명시적으로 반환
- **API 키 분리 적용**: 병원조회/병상조회 키를 분리해 잘못된 키 혼용 방지
- **병상 캐시 TTL 적용**: 5분 만료로 오래된 병상 스냅샷 자동 갱신
- **UI-백엔드 손상부위 매핑 정합성 개선**: 복부/척추/상지/하지 입력 정확히 반영

### v3.0
- **CRITICAL BUG FIX**: 위치 파라미터 추가 - 위도/경도 변경 시 추천 병원이 이제 제대로 변경됨
- **CRITICAL BUG FIX**: 하드코딩된 병상 수 제거 - 더 이상 모든 병원에서 "5개" 표시 안 함
- **Claude AI 통합**: 손상 분류별 최적 병상 유형 자동 판단 → 전문적 추천 근거 생성
- **API 응답 확장**: 앱 버전 정보 + Claude 활성화 상태 포함
- **향상된 진단**: 병상 API 응답 원본 로깅으로 ID 매핑 검증

### v2.1
- 병상정보 API 통합: 국립중앙의료원 실시간 병상정보 API 연동
- 정확한 병원-병상 매칭: 이중 검증 (ID + 병원명) 으로 혼동 방지
- 외상중환자실 우선: CRDT_ICU 병상 수 기반 우선순위
- 안전한 데이터 처리: 음수 병상값 → "정보없음" 변환

### v2.0
- 전국 병원 데이터베이스: 사용자 위치 중심 전국 병원 검색 (50km 반경 내)
- 치료 우선순위: 단순 거리순이 아닌 치료 가능성 기반 매칭
- 실시간 데이터: NEMC API를 통한 실제 병원 정보 및 병상 현황
- 모바일 최적화: 현장 구급대원을 위한 터치 인터페이스

## ⚠️ V.3.0에서 수정된 버그

### BUG #1: 위치 좌표 무시 (고정된 병원만 추천)
**문제**: fetch_nearby_hospitals()에서 API 호출 시 위경도 파라미터를 전혀 보내지 않음
- 결과: 항상 전국 첫 100개 병원만 가져옴 → 사용자 위치와 무관하게 같은 병원만 추천

**수정**: wgs84Lat, wgs84Lon, radius 파라미터 추가
- 결과: ✅ 좌표 변경 시 추천 병원이 그 위치에 따라 제대로 변경됨

### BUG #2: 고정된 병상 수 (모든 병원 "5개")
**문제**: fetch_realtime_status() 예외 발생 시 {"hvec": 5, "hvoc": 2} 하드코딩 폴백
- 결과: API 조회 실패 때마다 무조건 "5개" 표시 → 모든 병원이 5개로 표시됨

**수정**: 하드코딩 제거, {"hvec": None, "hvoc": None} 반환
- 결과: ✅ 실제 데이터 or "정보 없음" 표시 (더 이상 가짜 "5개" 안 나옴)

### 추가 개선
- 병상 API 응답 원본 로깅 ([BED_API_RAW] 태그)
- 두 API 간 ID 체계 불일치 디버깅 가능

## 향후 개선 계획

### 단기 (v3.1+)
- 웹 배포: Heroku/AWS로 공개 서비스화
- 병상 API 확장: 추가 데이터 필드 활용 (CT/MRI/인공호흡기)
- 모바일 앱: React Native 기반 앱 개발

### 중기 (v4.0)
- 다중 언어 지원
- 실시간 병원 현황 대시보드
- 구급대원 협업 기능

### 장기
- AI 생존 예측 모델
- 국제 확장
