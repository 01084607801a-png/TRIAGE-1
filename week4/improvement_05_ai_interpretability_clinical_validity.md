# Week4-개선사항5: AI 해석 및 임상적 타당성 문서화

## 문제
- 모델 성능 수치만으로는 의료 맥락에서 "왜 이런 판단이 나왔는지" 설명이 부족했다.
- 교수님 평가 포인트인 "AI를 활용한 시행착오 흔적 + 해석 가능성"을 보고서/PPT에서 바로 제시할 문서가 필요했다.

## 프롬프트(요약)
- feature importance와 생성된 성능 그래프를 바탕으로 입력 컬럼의 영향도를 쉽게 설명하라.
- 임상적으로 타당한 해석(활력징후 우선 판단)인지 점검하고, 한계도 함께 적시하라.
- Week4 아카이브에 정식 항목으로 저장하라.

## 결과
- 최고 성능 모델(Random Forest)의 중요도 기반 해석을 정리했다.
- 핵심 해석(5줄 요약):
  1. `gcs_motor`(0.5708)가 가장 큰 영향으로, 의식/신경학적 상태가 이송 필요 판단을 주도했다.
  2. `sbp`(0.2770)가 두 번째로 커서 저혈압 신호가 중증 분류에 강하게 반영됐다.
  3. `age`(0.0572), `rr`(0.0502)는 보정 변수로 작동해 위험도 조정에 기여했다.
  4. 손상기전/부위(`mechanism_enc`, `thorax`, `head_neck` 등)는 보조 신호로 반영됐다.
  5. 종합적으로 모델은 "활력징후 중심 + 손상정보 보조" 구조로 판단한다.

## 그래프 기반 해석

### 1) Feature Importance
- 파일: `models/feature_importance.png`
- 의미: 어떤 입력 변수가 `needs_rtc` 예측에 많이 기여했는지 시각화.
- 해석: GCS/SBP 중심 구조가 뚜렷하여 임상 상식(의식저하, 저혈압 위험)과 방향이 일치.

### 2) Learning Curve (Random Forest)
- 파일: `models/learning_curve.png`
- 의미: 학습 데이터 수가 늘어날 때 Train/Validation F1 변화 확인.
- 해석: 두 곡선 간 극단적 괴리가 크지 않아 과적합이 심하지 않은 것으로 해석 가능.

### 3) Confusion Matrix (3모델)
- 파일: `models/confusion_matrix.png`
- 의미: 필요/불필요를 각각 얼마나 맞추고 틀렸는지 확인.
- 해석: 오탐/미탐 패턴을 통해 실제 운영에서 어떤 오류가 더 위험한지(undertriage 우선 관리) 판단 가능.

### 4) ROC Curve 비교
- 파일: `models/roc_curve.png`
- 의미: 임계값 변화에 따른 민감도-특이도 trade-off 비교.
- 해석: RF/XGBoost가 유사하게 높은 곡선을 보여 분류 성능이 안정적임.

### 5) XGBoost Eval Curve
- 파일: `models/xgb_eval_curve.png`
- 의미: 라운드별 train/validation logloss 수렴 확인.
- 해석: 학습 라운드 증가에 따른 수렴 양상을 관찰하여 과적합 여부를 점검할 수 있음.

## 임상적 타당성 평가 (현 단계)
- 타당한 점:
  - 모델이 활력징후(GCS, SBP)를 가장 크게 반영하여 중증 선별의 임상 우선순위와 부합.
  - Test 기준 성능(Accuracy 93.3%, F1 0.939, AUC 0.942)으로 분류 안정성 양호.
- 한계:
  - 현재 라벨은 `needs_rtc`로, 실제 병원명 이송 라벨이 아니라 "이송 필요성" 분류에 한정.
  - 외부 병원 운영 데이터(실시간 수용, 교통시간, 전원 이력)와 결합한 검증은 추가 필요.

## AI 시행착오 흔적
- 초기에는 "그래프 생성"만 중점이라 해석 문장이 약해 보고서 활용도가 떨어졌다.
- 프롬프트를 "수치 + 임상 의미 + 한계" 3단 구조로 재설계해 문서형 해석으로 정리.
- 한글 인코딩 깨짐이 데이터 문제처럼 보였으나, 실제로는 터미널 표시 이슈였고 pandas 파싱은 정상임을 검증 후 해석에 반영.

## 증거 파일
- `models/triage_classifier.pkl`
- `models/feature_importance.png`
- `models/learning_curve.png`
- `models/confusion_matrix.png`
- `models/roc_curve.png`
- `models/xgb_eval_curve.png`
- `models/sensitivity_analysis.csv`
- `train_model.py`

## 관련 커밋
- b2aec6f (사용자 데이터 기반 학습 및 산출물 생성)
- (이번 항목 반영 커밋)
