# TRIAGE-1: AI-Powered Trauma Hospital Recommendation System

> 중증 외상 환자의 골든아워 내 최적 병원 이송을 지원하는 AI 의사결정 시스템

## 프로젝트 개요
본 시스템은 현장 구급대원이 입력하는 생리적 지표(GCS, SBP, RR)와 손상 부위를 기반으로,
CDC 2021 Field Triage 가이드라인 및 실시간 공공 API를 결합하여 최적의 이송 병원을 추천한다.

## 설계 근거
- **중증도 판정**: CDC 2021 Field Triage Guidelines (RED/YELLOW 기준)
- **손상 분류**: AIS/ISS 6부위 체계 (Baker et al., 1974)
- **병원 역량 기준**: 보건복지부 권역외상센터 지정기준 (별표 7의2)
- **한국 현장 적용 근거**: Kang et al. (2022), BMC Emergency Medicine

## 핵심 알고리즘
1. CDC 2021 Step 1 (생리적 기준) → RED/YELLOW 판정
2. AIS 기반 손상 부위 → 필요 전문과/장비 도출 (기본룰)
3. 실시간 병상 API (NEMC, DSSP-IF-00242) → 가용 병상 확인
4. Claude API → 추천 근거 자연어 설명 생성 (XAI)

## 데이터 전략
### 현재 (v3.0)
- 공공 API 기반 실시간 병상 정보
- CDC 가이드라인 + 논문 기반 규칙 시스템
- Kang et al. (2022) 수치 기반 알고리즘 보정

### 향후 계획
- KTDB(외상등록체계) 연동을 통한 예측 모델 전환
  - 신청 경로: dw.nemc.or.kr (기관 단위 신청, IRB 필요)
  - 대상 기간: ver 2.1~3.0 (2017~2021)
  - 공개 항목: 138개 (손상 기전, 외상팀 활성화 시간, 최종 ISS 등)
  - 활용 목표: Pre-hospital ISS Predictor, 데이터 기반 가중치 산출

## 알려진 한계 및 개선 과제
1. bfr_inst_id ≠ hpid 매핑 미검증 → API 응답 필드 확인 필요
2. 병원 등급 키워드 하드코딩 → dutyLevel 필드 정상화 후 제거 예정
3. 가중치 (역량 70%:거리 15%:병상 10%:상태 5%) → 통계적 근거 미확보, KTDB 연동 후 회귀분석으로 대체 예정
4. INJURY_SPECIALTY_MAP → ACS Orange Book 2022 확보 후 재설계 예정

## 참고 문헌
- Baker SP et al. The injury severity score. *J Trauma*, 1974
- Kang BH et al. Accuracy and influencing factors of the Field Triage Decision Scheme. *BMC Emergency Medicine*, 2022
- CDC. 2021 Field Triage Guidelines
- 보건복지부. 권역외상센터 지정기준 (응급의료에 관한 법률 시행규칙 별표 7의2)

## 기술 스택
- Backend: Python Flask
- APIs: NEMC 응급의료기관 정보, DSSP-IF-00242 병상정보
- AI: Claude API (claude-sonnet-4-20250514)
- 중증도 판별: CDC 2021 Field Triage (RED/YELLOW)

---

## 설치

1. Python 3.10+ 설치
2. 가상환경 생성 및 활성화

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 환경변수 설정

### NEMC 병상정보 API 키 설정

국립중앙의료원에서 발급받은 API 키를 환경변수로 설정합니다:

```powershell
$env:NEMC_API_KEY = "YOUR_NEMC_API_KEY_HERE"
```

### Claude API 키 설정 (선택사항)

지능형 추천문구 생성을 위해 Anthropic Claude API 키 설정:

```powershell
$env:CLAUDE_API_KEY = "sk-ant-YOUR_CLAUDE_KEY_HERE"
```

**설정하지 않으면**: 기본 휴리스틱 설명 사용 (Claude 없이도 작동)

**보안 주의**: 실제 API 키는 GitHub에 업로드하지 않도록 주의하세요. `.env` 파일 사용 권장:
1. 프로젝트 루트에 `.env` 파일 생성
2. `NEMC_API_KEY=your_nemc_key` 입력
3. `CLAUDE_API_KEY=your_claude_key` 입력 (선택)
4. `.gitignore`에 `.env` 추가됨 (이미 설정)

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

## 기능

- GCS/SBP/RR/손상유형/나이/위치 입력
- CDC Field Triage 중증도 판별
- **전국 병원 데이터베이스 검색** (NEMC API 연동)
- **전문과 필터링**: 상해부위에 맞는 전문의를 보유한 병원 우선 추천
- 실시간 병상 가용성 확인
- 상위 3개 병원 추천, AI 설명(Claude 기반)

## 주요 개선사항

### v3.0 (현재) ⭐ 중요 버그 수정 + AI 통합 + 의학적 근거 추가
- **CRITICAL BUG FIX**: 위치 파라미터 추가 - 위도/경도 변경 시 추천 병원이 이제 제대로 변경됨
- **CRITICAL BUG FIX**: 하드코딩된 병상 수 제거 - 더 이상 모든 병원에서 "5개" 표시 안 함
- **Claude AI 통합**: 손상 분류별 최적 병상 유형 자동 판단 → 전문적 추천 근거 생성
- **API 응답 확장**: 앱 버전 정보 + Claude 활성화 상태 포함
- **향상된 진단**: 병상 API 응답 원본 로깅으로 ID 매핑 검증
- **문헌 기반 설계 명시화**: CDC 2021, Baker 1974, Kang 2022 등 근거 문헌 기록
- **미해결 과제 투명화**: KTDB 연동, 가중치 통계화 등 향후 개선사항 명시

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
- AI 생존 예측 모델 (KTDB 연동 후)
- 국제 확장