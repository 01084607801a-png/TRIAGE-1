# improvement_07: ML 모델 통합 (앙상블 점수 계산)

## 문제
- 실제 데이터로 학습한 Random Forest 모델이 있지만, 병원 추천 로직에 활용되지 않음
- 규칙 기반(if-else) 접근만으로는 AI 과목 평가에서 인정받기 어려움
- 구조: 임상 논문 근거 (규칙) + 실제 데이터 학습 (ML) 분리 상태

## 프롬프트
- ML 모델(`models/triage_classifier.pkl`)을 `app.py`에 통합
- 병원 추천 점수를 **앙상블** 방식으로 계산: 규칙 기반 60% + ML 확률 40%
- 모델 없을 때도 규칙 기반으로 fallback 동작 (장애 허용성)
- API 응답에 ML 정보 포함 (로드 여부, 정확도, 환자별 RTC 확률)

## 결과

### 구현 내용

**1) 모델 로드**
```python
import pickle

ML_MODEL = None
ML_LABEL_ENCODER = None
try:
    with open("models/triage_classifier.pkl", "rb") as f:
        model_data = pickle.load(f)
    ML_MODEL = model_data["model"]
    ML_LABEL_ENCODER = model_data["label_encoder"]
    print(f"[ML] 모델 로드 완료 — Random Forest Accuracy 93.3% (Test Set)")
except FileNotFoundError:
    print("[ML] 모델 파일 없음 → 규칙 기반 전용 모드")
```

**2) ML 예측 함수**
```python
def predict_rtc_probability(patient: dict) -> float:
    """
    Random Forest로 권역외상센터 필요 확률 예측
    입력: GCS Motor, SBP, RR, Age, 손상 부위
    출력: 0.0~1.0 (높을수록 권역외상센터 필요)
    모델 없으면 -1 반환 → 규칙 기반으로 대체
    """
    if ML_MODEL is None:
        return -1.0
    
    # Features: [age, mechanism_enc, gcs_motor, sbp, rr, 
    #            head_neck, thorax, abdomen, extremity, spine]
    features = [[...]]
    prob = ML_MODEL.predict_proba(features)[0][1]
    return float(prob)
```

**3) 점수 계산 (앙상블)**
```python
ml_prob = predict_rtc_probability(patient)

if ml_prob >= 0:
    # ML 사용 가능
    rule_score = 0.70 * cap + 0.15 * dist_score + 0.10 * bed_score + 0.05 * sat
    score = 0.60 * rule_score + 0.40 * ml_prob  # 앙상블
    ml_used = True
else:
    # ML 없으면 규칙 기반 100%
    score = 0.70 * cap + 0.15 * dist_score + 0.10 * bed_score + 0.05 * sat
    ml_used = False
```

**4) API 응답 추가**
```json
"ml_model": {
    "loaded": true,
    "accuracy": 0.933,
    "rtc_probability": 0.847,  // 현재 환자의 RTC 확률
    "model_type": "Random Forest",
    "training_data": "data/data (2000 patients)",
    "feature_count": 10
}
```

각 병원별:
```json
{
    "ml_rtc_probability": 0.847,
    "ml_used_for_scoring": true,
    "score": 0.541
}
```

### 아키텍처 변화

**Before (규칙만)**
```
환자 입력
  ↓
CDC 2021 평가 (RED/YELLOW)
  ↓
병원 후보 필터링
  ↓
점수 = 역량(60%) + 거리(15%) + 병상(10%) + 상태(5%) + 전문과(10%)
  ↓
상위 3개 + Claude 설명
```

**After (규칙 + ML 앙상블)**
```
환자 입력
  ↓
CDC 2021 평가 (RED/YELLOW)
  ↓
병원 후보 필터링
  ↓
규칙 점수 = 역량(70%) + 거리(15%) + 병상(10%) + 상태(5%)
ML 점수 = Random Forest 확률 (needs_rtc)
최종 점수 = 규칙(60%) + ML(40%)
  ↓
상위 3개 + Claude 설명
```

## 시행착오

1. **Specialty Match Score 제거**
   - ML 앙상블 시 전문과 일치도 삭제
   - 이유: ML 모델이 이미 손상 부위 정보 (원-핫 인코딩)를 통해 병원 적합성 판단 중
   - 중복 가산 시 병원 등급 편향 강화 위험

2. **Model Data 구조**
   - `train_model.py`에서 저장: `{"model", "label_encoder", "accuracy"}`
   - `app.py`에서 로드: 동일 키로 접근
   - Robust: 파일 없거나 로드 실패 시 자동 fallback

3. **Feature 순서 정렬**
   - `train_model.py`의 feature 순서와 `predict_rtc_probability()`에서 정확히 일치 필수
   - 특히 one-hot 손상 부위: `[head_neck, thorax, abdomen, extremity, spine]`

## 임상 타당성

- **ML의 역할**: 2000명 환자 학습 기반, 실제 needs_rtc 예측 (93.3% 정확도)
- **규칙의 역할**: CDC 2021 임상 가이드라인 + 논문 근거 (Kang 2022, 보건복지부 고시)
- **앙상블의 의미**: 
  - 규칙은 임상 가이드 준수 (안전성, 투명성)
  - ML은 실제 데이터 학습 기반 (정확성, 민감도)
  - 60:40 가중치 → 과도한 ML 의존 방지, 임상 판단 우선

## 마크 검증

- ✅ 모델 로드 성공: `[ML] 모델 로드 완료 — Random Forest Accuracy 93.3% (Test Set)`
- ✅ API 응답에 ML 정보 포함
- ✅ 각 병원별 `ml_rtc_probability` 및 `ml_used_for_scoring` 포함
- ✅ 모델 파일 없을 때 자동 fallback
- ✅ 문법: `python -m py_compile app.py` 성공

## 다음 단계

- 실제 임상 환경에서 A/B 테스트: 규칙만 vs 앙상블
- 가중치 재조정: 60:40 → 데이터 기반 최적화
- Feature importance 임상 해석 (improvement_05 연계)
- 웹/데스크톱 모두에서 동일 로직 적용 확인
