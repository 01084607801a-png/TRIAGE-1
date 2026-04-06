# Week4-개선사항3: XGBoost eval 추적 + 민감도 분석 + 최종 요약표

## 문제
- 에포크 유사 관점의 수렴 검증과 가중치 민감도 분석, 최종 결과 표준 출력이 부족했다.

## 프롬프트(요약)
- XGBoost eval_set으로 라운드별 train/validation logloss를 추적하라.
- 추천 가중치 시나리오 5개 x 케이스 5개의 민감도 분석표를 저장하라.
- 콘솔에 보고서용 최종 요약 박스를 출력하라.

## 결과
- xgb_eval_curve 저장 로직 추가.
- sensitivity_analysis.csv 저장 및 표 출력 구현.
- TRIAGE-1 v4.0 요약 박스 출력 구현.
- 최고 성능 모델을 triage_classifier.pkl로 저장하도록 유지/확장.

## AI 시행착오 흔적
- 초안은 모델 성능만 출력하고 실무 가중치 변화 영향이 누락됨.
- 프롬프트를 "모델 성능 + 의사결정 민감도" 2축으로 분리해 분석 범위를 확대.
- 데이터 파일 부재 상황에서 조용히 실패하던 문제를 명시적 안내 메시지로 보완.

## 증거 파일
- train_model.py
- models/xgb_eval_curve.png (실행 시 생성)
- models/sensitivity_analysis.csv (실행 시 생성)

## 관련 커밋
- d1af04b
