# Week4-개선사항1: 3모델 비교 + 10-Fold CV

## 문제
- Random Forest 단일 학습만으로 모델 선택 근거가 약했다.

## 프롬프트(요약)
- Logistic Regression, Random Forest, XGBoost 3개 모델을 동일 데이터에서 비교하라.
- 10-Fold Stratified CV로 Accuracy/Precision/Recall/F1/AUC 평균±표준편차를 출력하라.

## 결과
- 3모델 실험 파이프라인 구축.
- 교차검증 기반 비교 지표 출력 로직 추가.

## AI 시행착오 흔적
- 초기 프롬프트는 모델 정의만 있고 평가 프로토콜이 불명확했다.
- 후속 프롬프트에서 CV 방식, scoring 리스트, random_state를 고정해 재현성을 확보.
- xgboost 미설치 시 실패하던 점을 사전 안내 로직으로 보완.

## 증거 파일
- train_model.py
- requirements.txt

## 관련 커밋
- d1af04b
