"""
triage_model.py
- load models/triage_classifier.pkl with joblib (secure)
- provide explain_patient_shap(patient) -> {'top_features': [...], 'nl': '...'}
"""
import os
import logging
import numpy as np

# Use joblib instead of pickle (safer)
try:
    import joblib
    JOBLIB_AVAILABLE = True
except ImportError:
    JOBLIB_AVAILABLE = False

# SHAP availability probe (app.py imports this flag)
try:
    import shap  # noqa: F401
    SHAP_AVAILABLE = True
except Exception:
    SHAP_AVAILABLE = False

logger = logging.getLogger(__name__)

MODEL_PATH = os.path.join('models', 'triage_classifier.pkl')

_model_data = None
_model = None
_label_encoder = None
_features = None

try:
    if not os.path.exists(MODEL_PATH):
        logger.warning(f"Model file not found at {MODEL_PATH} - using heuristic mode only")
    else:
        if JOBLIB_AVAILABLE:
            _model_data = joblib.load(MODEL_PATH)
            logger.info("Model loaded successfully with joblib")
        else:
            import pickle
            with open(MODEL_PATH, 'rb') as f:
                _model_data = pickle.load(f)
            logger.warning("Model loaded with pickle (prefer joblib for security)")
        
        _model = _model_data.get('model')
        _label_encoder = _model_data.get('label_encoder')
        _features = _model_data.get('features')
except FileNotFoundError:
    logger.warning(f"Model file not found: {MODEL_PATH}")
    _model_data = None
    _model = None
    _label_encoder = None
    _features = None
except Exception as e:
    logger.exception(f"Failed to load model from {MODEL_PATH}: {e}")
    _model_data = None
    _model = None
    _label_encoder = None
    _features = None


def _build_feature_vector(patient: dict):
    if not _features:
        return None
    vec = []
    for feat in _features:
        if feat == 'mechanism_enc':
            mech = patient.get('mechanism') or '기타'
            try:
                enc = int(_label_encoder.transform([mech])[0])
            except Exception:
                enc = 0
            vec.append(enc)
        else:
            vec.append(patient.get(feat, 0))
    return np.array(vec).reshape(1, -1)


def explain_patient_shap(patient: dict):
    """
    Return top 3 contributing features using SHAP (TreeExplainer).
    If shap is not available or model missing, return None.
    """
    try:
        import shap
    except Exception as e:
        raise RuntimeError('shap 패키지 필요: pip install shap')

    if _model is None or _features is None:
        raise RuntimeError('모델이 로드되어 있지 않습니다 (models/triage_classifier.pkl)')

    x = _build_feature_vector(patient)
    if x is None:
        raise RuntimeError('피처 벡터 생성 실패')

    try:
        explainer = shap.TreeExplainer(_model)
        shap_values = explainer.shap_values(x)
        # shap_values may be list (for classification) — pick class 1 if present
        if isinstance(shap_values, list) or isinstance(shap_values, tuple):
            sv = shap_values[1] if len(shap_values) > 1 else shap_values[0]
        else:
            sv = shap_values

        sv = np.array(sv).reshape(-1)
        abs_sv = np.abs(sv)
        idx_sorted = np.argsort(-abs_sv)
        top_idx = idx_sorted[:3]

        results = []
        total_abs = float(abs_sv.sum()) if abs_sv.sum() != 0 else 1.0
        for i in top_idx:
            feat = _features[i]
            val = float(x[0, i])
            contrib = float(sv[i])
            pct = float(abs_sv[i]) / total_abs * 100.0
            results.append({'feature': feat, 'value': val, 'shap': contrib, 'contrib_pct': pct})

        # Natural language example
        nl_sentences = []
        for r in results:
            sign = '증가' if r['shap'] > 0 else '감소'
            nl_sentences.append(f"예: {r['feature']} {r['value']}가 중증도 판정에 {r['contrib_pct']:.0f}% 기여({sign})")

        return {'top_features': results, 'nl': ' ; '.join(nl_sentences)}

    except Exception as e:
        raise RuntimeError(f'SHAP 분석 중 오류: {e}')