# TRIAGE-1 v2.0

AI 기반 외상 환자 최적 병원 매칭 시스템 프로토타입

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

**보안 주의**: 실제 API 키는 GitHub에 업로드하지 않도록 주의하세요. `.env` 파일 사용 권장:
1. 프로젝트 루트에 `.env` 파일 생성
2. `NEMC_API_KEY=your_actual_key` 입력  
3. `.gitignore`에 `.env` 추가됨 (이미 설정)

## 실행

```powershell
python app.py
```

브라우저에서 `http://localhost:5000` 접속

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

## 주요 개선사항 v2.0

- **전국 확대**: 광주 지역에서 전국 병원 데이터베이스로 확장 (50km 반경 내 50개 병원)
- **치료 우선순위**: 단순 거리순이 아닌 치료 가능성 기반 매칭
- **실시간 데이터**: NEMC API를 통한 실제 병원 정보 및 병상 현황
- **모바일 최적화**: 현장 구급대원을 위한 터치 인터페이스

## ⚠️ 데이터 품질 참고사항

- **병상 정보**: NEMC API에서 음수 병상 값(-4, -2 등)이 빈번히 발생하며, 이는 "정보 없음"을 의미하는 것으로 보임
- **API 한계**: 실시간 병상 가용성 데이터가 대부분 "정보 없음" 상태로, 신뢰할 수 있는 실시간 데이터 확보 필요
- **데이터 정확성**: 실시간 병상 가용성은 API 데이터 품질에 따라 제한적일 수 있음
- **추천 신뢰성**: 병원 등급과 전문과 매칭을 우선으로 하며, 병상 정보는 참고용으로 사용

## 확장

- Claude API 연동: `generate_claude_explanation`에 실제 호출 추가
- NEMC API 연동: 외부 실시간 병원 정보 조회
- E-Gen API 연동: 응급의료 네트워크 데이터 연계
