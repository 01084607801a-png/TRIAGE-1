# Week4-개선사항4: 사용자 업로드 데이터(data/data)로 학습 연결

## 문제
- 사용자가 `data` 폴더에 실제 데이터를 넣었지만 파일명이 `data/data`(확장자 없음)라,
  기존 학습 스크립트가 기대하던 `data/synthetic_trauma_data.csv` 경로와 불일치했다.
- 결과적으로 "CSV인지 아닌지"와 "이 데이터로 바로 학습 가능한지"가 불명확했다.

## 프롬프트(요약)
- 업로드한 파일이 CSV 구조인지 먼저 검증하라.
- CSV가 맞다면 현재 학습 코드가 해당 파일을 자동 인식해 학습하도록 수정하라.
- 수정 후 실제 학습을 실행해 성능과 산출물 생성까지 확인하라.

## 결과
- `data/data` 파일은 UTF-8 CSV 구조(2000 x 15)로 확인됨.
- `train_model.py`를 수정해 아래 경로를 순차 탐색하도록 변경:
  1. `data/synthetic_trauma_data.csv`
  2. `data/data`
- 실제 학습 실행 성공:
  - CV 평균 성능(요약):
    - Logistic Regression AUC: 0.9372
    - Random Forest AUC: 0.9446
    - XGBoost AUC: 0.9400
  - Test 성능(요약):
    - Random Forest Accuracy 93.3%, F1 0.939, AUC 0.942
- 생성 파일 정상 확인:
  - models/triage_classifier.pkl
  - models/feature_importance.png
  - models/learning_curve.png
  - models/confusion_matrix.png
  - models/roc_curve.png
  - models/xgb_eval_curve.png
  - models/sensitivity_analysis.csv

## AI 시행착오 흔적
- 초기 진단에서 파일 내용이 한글 깨짐처럼 보여 인코딩 문제를 의심했으나,
  pandas 기준 UTF-8로 정상 파싱되어 핵심 이슈가 "확장자/경로 불일치"임을 확인.
- 즉, 데이터 품질 문제보다 로더 경로 가정이 원인이었고,
  프롬프트를 "형식 검증 후 경로 자동 인식"으로 바꿔 해결.

## 증거 파일
- data/data
- train_model.py
- models/feature_importance.png
- models/learning_curve.png
- models/confusion_matrix.png
- models/roc_curve.png
- models/xgb_eval_curve.png
- models/sensitivity_analysis.csv

## 관련 커밋
- (이번 항목 반영 커밋에서 기록)
