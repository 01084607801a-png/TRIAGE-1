# TRIAGE-1 v4.0

AI 기반 외상 환자 최적 병원 매칭 시스템

**최종 업데이트**: 2026-04-06 | **버전**: 4.0 (Week2~Week4 통합 정리 + ML 고도화)

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

## Week 시리즈 요약 (보고서/PPT 기준)

README는 Week2~Week4 전체를 요약하는 허브이며,
세부 내용은 각 주차 폴더의 개선사항 파일(문제-프롬프트-결과-시행착오)에서 확인할 수 있습니다.

### Week 2 (초기 구축 + 문서 + 보안)
- 핵심: 기본 서비스 골격, README 시각화, API 키 보안 전환
- 상세 폴더: ./week2
- 항목:
  - ./week2/improvement_01_initial_build.md
  - ./week2/improvement_02_readme_screenshot.md
  - ./week2/improvement_03_security_env_migration.md

### Week 3 (V3: 임상/운영 안정화)
- 핵심: 위치 파라미터 버그 수정, 병상 fallback 고정값 제거, 복수 손상 AND 필터 + XAI
- 상세 폴더: ./week3
- 항목:
  - ./week3/improvement_01_location_parameter_fix.md
  - ./week3/improvement_02_bed_fallback_fix.md
  - ./week3/improvement_03_multi_injury_and_xai.md

### Week 4 (ML 학습 고도화)
- 핵심: 3모델 비교, 10-Fold CV, 70/15/15 분할, Learning/ROC/Confusion 시각화, 민감도 분석
- 상세 폴더: ./week4
- 항목:
  - ./week4/improvement_01_multi_model_cv.md
  - ./week4/improvement_02_split_and_learning_curves.md
  - ./week4/improvement_03_sensitivity_and_summary.md

## 생성 산출물 (Week4 학습)

- models/triage_classifier.pkl
- models/feature_importance.png
- models/learning_curve.png
- models/confusion_matrix.png
- models/roc_curve.png
- models/xgb_eval_curve.png
- models/sensitivity_analysis.csv

## 중복 문서 정리

주차별 아카이브와 내용이 중복되던 상위 레벨 문서는 정리했습니다.
이후 변경 이력은 week2/week3/week4 폴더 중심으로 누적합니다.
