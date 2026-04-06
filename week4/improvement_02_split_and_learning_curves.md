# Week4-개선사항2: 70/15/15 분할 + 학습 곡선/ROC/혼동행렬

## 문제
- 기존 8:2 분할은 튜닝 근거(Validation)와 최종 성능(Test) 분리가 불충분했다.
- 보고서용 시각화(수렴/분류오류/ROC)가 부족했다.

## 프롬프트(요약)
- Train/Validation/Test를 70/15/15로 분리하라.
- Random Forest learning curve를 생성하라.
- 3모델 confusion matrix(1x3)와 ROC 비교 그래프를 저장하라.
- 그래프 저장 시 dpi=150, bbox_inches=tight를 적용하라.

## 결과
- 데이터 분할 체계 개선.
- 아래 산출물 저장 로직 구현:
  - models/learning_curve.png
  - models/confusion_matrix.png
  - models/roc_curve.png

## AI 시행착오 흔적
- 첫 시도에서 Validation이 모델 선택에 반영되지 않아 재수정.
- 프롬프트에 "Validation AUC로 최고 모델 선정"을 명시해 저장 모델 기준을 일관화.
- 시각화 제목/축 표기가 누락되던 문제를 프롬프트 체크리스트로 정리해 해결.

## 증거 파일
- train_model.py

## 관련 커밋
- d1af04b
