# -*- coding: utf-8 -*-
"""
TRIAGE-1 Flask Application
AI-based trauma patient hospital matching system
"""

from flask import Flask, render_template, request, jsonify
import os
import requests
import math
import json
import time
import threading
import pickle
import warnings

# sklearn: RandomForest에 feature name 없이 예측 시 발생하는 경고 억제 (기능 영향 없음)
warnings.filterwarnings("ignore", message="X does not have valid feature names")
from dotenv import load_dotenv

# [Phase 1] Security & Stability Improvements
from defusedxml import ElementTree as SafeET
from logging_config import setup_logging
from utils.validation import validate_patient_input
from utils.api_client import APIClient
from utils.cache import TTLCache

try:
    from anthropic import Anthropic
    CLAUDE_AVAILABLE = True
except ImportError:
    CLAUDE_AVAILABLE = False

load_dotenv()

# ============================================================
# 로깅 설정 (Phase 1)
# ============================================================
logger = setup_logging()

app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-key-change-in-production')

# ------------------------------------------------------------
# Rate Limiting (Phase: 보안 강화)
# 기본: IP당 분당 200회. 비용 큰 엔드포인트는 개별 제한.
# 미설치 환경에서도 앱이 죽지 않도록 graceful 처리.
# ------------------------------------------------------------
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address

    limiter = Limiter(
        key_func=get_remote_address,
        app=app,
        default_limits=["200 per minute"],
        storage_uri="memory://",
    )

    @app.errorhandler(429)
    def _ratelimit_handler(e):
        return jsonify({
            'error': 'rate_limit_exceeded',
            'message': '요청이 너무 많습니다. 잠시 후 다시 시도하세요.',
            'detail': str(e.description),
        }), 429

    RATE_LIMIT_ENABLED = True
    logger.info("Rate limiting enabled (Flask-Limiter)")
except ImportError:
    limiter = None
    RATE_LIMIT_ENABLED = False
    logger.warning("Flask-Limiter 미설치 - rate limiting 비활성")

    # limiter.limit 데코레이터가 없어도 동작하도록 no-op 대체
    class _NoopLimiter:
        def limit(self, *args, **kwargs):
            def deco(fn):
                return fn
            return deco

        def exempt(self, fn):
            return fn
    if limiter is None:
        limiter = _NoopLimiter()

logger.info("TRIAGE-1 Flask app initialized")
logger.debug(f"Environment: {os.getenv('FLASK_ENV', 'production')}")

# ============================================================
# 유틸 함수들 (Phase 1)
# ============================================================

def safe_json_parse(response: requests.Response) -> dict:
    """
    안전한 JSON 파싱 (오류 로깅)
    
    Args:
        response: requests.Response 객체
    
    Returns:
        파싱된 dict 또는 None
    """
    try:
        return response.json()
    except json.JSONDecodeError as e:
        logger.error(
            "JSON parse error",
            extra={
                'url': response.url,
                'status': response.status_code,
                'body_preview': response.text[:200],
                'error': str(e)
            }
        )
        return None
    except Exception as e:
        logger.exception(f"Unexpected JSON parsing error: {e}")
        return None


def get_cached_osrm_route(cache_key: str):
    """스레드 안전한 OSRM 캐시 조회"""
    with cache_lock:
        return osrm_cache.get(cache_key)


def set_cached_osrm_route(cache_key: str, route_data: dict):
    """스레드 안전한 OSRM 캐시 저장"""
    with cache_lock:
        osrm_cache.set(cache_key, route_data)


def get_cached_bed_info(hospital_id: str):
    """스레드 안전한 병상 정보 캐시 조회"""
    with cache_lock:
        return bed_cache.get(hospital_id)


def set_cached_bed_info(hospital_id: str, bed_info: dict):
    """스레드 안전한 병상 정보 캐시 저장"""
    with cache_lock:
        bed_cache.set(hospital_id, bed_info)


# ============================================================
# 엔드포인트: Geocoding (주소 → 좌표)
# ============================================================
@app.route('/api/geocode')
@limiter.limit("60 per minute")
def api_geocode():
    q = request.args.get('q', '').strip()
    if not q:
        logger.warning("Geocode request with missing query")
        return jsonify({'error': 'missing_query'}), 400

    try:
        nominatim_url = 'https://nominatim.openstreetmap.org/search'
        params = {
            'format': 'json',
            'limit': 5,
            'q': q,
            'accept-language': 'ko'
        }
        headers = {
            'User-Agent': 'TRIAGE-1/1.0 (contact: no-reply@local)'
        }
        resp = requests.get(nominatim_url, params=params, headers=headers, timeout=6)
        if resp.status_code != 200:
            return jsonify({'error': 'geocode_failed', 'status': resp.status_code, 'body': resp.text[:200]}), 502

        data = resp.json()
        # return raw list for client
        return jsonify({'results': data})
    except Exception as e:
        return jsonify({'error': 'exception', 'detail': str(e)}), 500

# API Configuration (Phase 1: 통합 설정)
API_CONFIG = {
    'nominatim': {'timeout': 6.0, 'max_retries': 2},
    'osrm': {'timeout': 5.0, 'max_retries': 2},
    'hospital_api': {'timeout': 5.0, 'max_retries': 3},
    'bed_api': {'timeout': 6.0, 'max_retries': 2},
    'claude_api': {'timeout': 30.0, 'max_retries': 1},
}

# Hospital API key (국립중앙의료원_전국 응급의료기관 정보 조회 서비스)
HOSPITAL_API_KEY = os.getenv("NEMC_HOSPITAL_API_KEY") or os.getenv("NEMC_API_KEY")
# Bed API key (국립중앙의료원_의료기관_실시간_병상정보)
BED_API_KEY = os.getenv("NEMC_BED_API_KEY") or os.getenv("BED_API_KEY")
BASE_URL = "http://apis.data.go.kr/B552657/ErmctInfoInqireService"
BED_API_URL = "http://apis.data.go.kr/V2/api/DSSP-IF-00199"

OSRM_URL = os.getenv("OSRM_URL", "http://router.project-osrm.org")
OSRM_PROFILE = os.getenv("OSRM_PROFILE", "driving")

# API 클라이언트 인스턴스 (재시도 로직 포함)
api_client = APIClient(max_retries=3, timeout=5.0)

# Claude API
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY")
if CLAUDE_AVAILABLE and CLAUDE_API_KEY:
    claude_client = Anthropic(api_key=CLAUDE_API_KEY)
    logger.info("Claude API initialized")
else:
    claude_client = None
    logger.warning("Claude API not available - using fallback text generation")

APP_VERSION = "3.4.0"  # Updated for Phase 1
APP_VERSION_DATE = "2026-05-31"

# Optional SHAP/triage helper
try:
    from triage_model import explain_patient_shap, SHAP_AVAILABLE
except Exception:
    explain_patient_shap = None
    SHAP_AVAILABLE = False
    logger.debug("SHAP not available - using heuristic mode")

# ============================================================
# 캐시 설정 (Phase 1: 스레드 안전 + 크기 제한)
# ============================================================
bed_cache = TTLCache(ttl_seconds=300, max_size=5000)
osrm_cache = TTLCache(ttl_seconds=600, max_size=10000)
cache_lock = threading.RLock()

logger.info("Caches initialized (TTL-based with size limits)")

# ============================================================
# 설정 검증
# ============================================================
if not HOSPITAL_API_KEY:
    logger.error("HOSPITAL API key not set. Set NEMC_HOSPITAL_API_KEY or NEMC_API_KEY")
if not BED_API_KEY:
    logger.error("BED API key not set. Set NEMC_BED_API_KEY or BED_API_KEY")

# ============================================================
# ML 모델 로드
# models/triage_classifier.pkl이 존재하면 자동 로드
# 없으면 규칙 기반 전용 모드로 작동
# ============================================================
ML_MODEL = None
ML_LABEL_ENCODER = None
ML_ACCURACY = None


def _load_model_data(path: str):
    """joblib 우선(보안), 미설치 시 pickle 폴백으로 모델 로드"""
    try:
        import joblib
        return joblib.load(path)
    except ImportError:
        with open(path, "rb") as f:
            data = pickle.load(f)
        logger.warning("joblib 미설치 — pickle로 모델 로드(보안상 joblib 권장)")
        return data


try:
    model_data = _load_model_data("models/triage_classifier.pkl")
    ML_MODEL = model_data["model"]
    ML_LABEL_ENCODER = model_data["label_encoder"]
    ML_ACCURACY = model_data.get("accuracy", None)
    acc_str = f"{ML_ACCURACY*100:.1f}%" if ML_ACCURACY is not None else "N/A"
    print(f"[ML] 모델 로드 완료 - Random Forest Accuracy {acc_str} (Test Set)")
except FileNotFoundError:
    print("[ML] 모델 파일 없음(models/triage_classifier.pkl) → 규칙 기반 전용 모드")
except Exception as e:
    print(f"[ML] 모델 로드 오류: {e} → 규칙 기반 전용 모드")

# ============================================================
# Model 1 (v2): 필요 병원 등급 예측기 (tier_model.pkl)
# 현장정보 → 3단계 필요등급 + 확률. CDC 안전 오버라이드 포함.
# ============================================================
TIER_BUNDLE = None
try:
    TIER_BUNDLE = _load_model_data("models/tier_model.pkl")
    _m = TIER_BUNDLE.get("metrics", {})
    print(f"[Model1] tier 모델 로드 완료 — 규칙 {_m.get('rule_sensitivity',0)*100:.0f}% → "
          f"ML {_m.get('ml_sensitivity',0)*100:.0f}% (undertriage 보완)")
except FileNotFoundError:
    print("[Model1] tier_model.pkl 없음 → 규칙 기반 등급 판정으로 폴백")
except Exception as e:
    print(f"[Model1] tier 모델 로드 오류: {e} → 규칙 폴백")

# ============================================================
# 손상 부위 → 전문과 매핑
# 근거: 보건복지부 권역외상센터 지정기준 (별표 7의2)
# 권역외상센터 필수 전담과: 외과, 흉부외과, 정형외과, 신경외과
# 초기 소생 및 Damage Control Surgery는 이 4개과가 1차 담당
# 세부 과(비뇨기과, 혈관외과 등)는 응급 이송 단계에서 단순화
# 한계: ACS Orange Book 2022 확보 후 재검토 예정
# ============================================================
INJURY_SPECIALTY_MAP = {
    "두부/경부":    ["신경외과"],
    "안면":        ["성형외과", "이비인후과"],
    "흉부":        ["흉부외과"],
    "복부/골반장기": ["외과"],
    "사지/골반골격": ["정형외과"],
    "체표면/기타":  ["외과", "성형외과"],
    # UI 입력값 호환
    "복부":        ["외과"],
    "척추":        ["신경외과", "정형외과"],
    "상지":        ["정형외과"],
    "하지":        ["정형외과"],
}

# ============================================================
# Week 5: 계층화 필터 전문과 분류 (Critical vs Supportive)
# 근거: 권역외상센터 지정기준 필수 4대 분과 및 Harrington et al. (2005)
# ============================================================
CRITICAL_SPECIALTIES = {"외과", "흉부외과", "신경외과", "정형외과"}
SUPPORTIVE_SPECIALTIES = {"성형외과", "이비인후과", "안과"}
TRANSFER_DELAY_PENALTY_WEIGHT = 0.15  # 전문과 누락으로 인한 전원 지연 페널티 (Harrington 162분 대응)

# ============================================================
# 병원 등급 점수
# 근거: 보건복지부 권역외상센터 지정기준 (별표 7의2)
# - 권역외상센터: 외상 전담 전문의 24시간 상주 + 전용 수술실 2개 + 외상중환자실 20병상 의무
# - 권역응급의료센터: 외상 전담팀 상주 의무 없음 → 중증 외상 처치 역량 압도적 차이
# - 격차를 55점으로 확대하여 undertriage 방지
# 한계: KTDB 다변량 회귀분석으로 통계적 검증 필요 (현재 잠정값)
# ============================================================
LEVEL_SCORE = {
    "권역외상센터":    100,
    "지역외상센터":     65,
    "권역응급의료센터":  45,
    "지역응급의료센터":  25,
    "지역응급의료기관":  10,
}

# 요청 사양: 병원 등급 점수 1.0 ~ 0.1
LEVEL_SCORE_NORM = {
    "권역외상센터": 1.0,
    "지역외상센터": 0.8,
    "권역응급의료센터": 0.6,
    "지역응급의료센터": 0.3,
    "지역응급의료기관": 0.1,
}

MECHANISM_RISK_MAP = {
    "교통사고": 0.75,
    "보행자 사고": 0.80,
    "추락": 0.70,
    "관통상": 0.85,
    "둔상": 0.55,
    "화상": 0.60,
    "기타": 0.50,
}

INJURY_RISK_MAP = {
    "두부/경부": 0.90,
    "안면": 0.45,
    "흉부": 0.85,
    "복부/골반장기": 0.80,
    "복부": 0.80,
    "사지/골반골격": 0.55,
    "상지": 0.35,
    "하지": 0.45,
    "척추": 0.70,
    "체표면/기타": 0.40,
}


def calculate_ampt_score(patient: dict) -> dict:
    """
    AMPT Score 계산 (초중증 환자 HEMS 트리거)
    근거: HEMS 예후 연구 — 지상 이송 90.5% vs HEMS 94.9% 생존율
    
    생리학적 지표 (Physiological):
      - GCS Motor < 14 (1점): 의식변화 — OR 17.924 (Kang 2022)
      - 호흡수 < 10 또는 > 29 (1점): 호흡곤란
    
    해부학적 지표 (Anatomical):
      - 불안정한 흉벽 (1점): 일반적으로 3개 이상 골절 또는 심한 타박
      - 2개 이상 근위부 긴뼈 골절 (1점): 대퇴골, 상완골 등
      - 골반 골절 의심 (1점): 고에너지 손상 기전
    
    트리거: AMPT Score ≥ 2 → HEMS 이송 강력 권고
    """
    score = 0
    components = {}
    
    # ============================================================
    # 생리학적 지표
    # ============================================================
    # GCS Motor < 14 (실제로는 GCS Motor 6은 매우 극심함, GCS Total < 14)
    # 편의상 GCS Motor < 6 대신 patient의 gcs_motor 필드 사용
    gcs_motor = int(patient.get("gcs_motor", 15))
    if gcs_motor < 14:
        score += 1
        components["gcs_low"] = True
    else:
        components["gcs_low"] = False
    
    # 호흡수 < 10 또는 > 29
    rr = int(patient.get("rr", 16))
    if rr < 10 or rr > 29:
        score += 1
        components["respiratory_distress"] = True
    else:
        components["respiratory_distress"] = False
    
    # ============================================================
    # 해부학적 지표 (손상 부위 기반 추정)
    # ============================================================
    injuries = patient.get("injuries", [])
    
    # 불안정한 흉벽 → "흉부" 손상에서 추정
    # 실제 임상에서는 신체 검사로 확인하나, UI 입력 기반으로 추정
    unstable_chest_wall = "흉부" in injuries and patient.get("mechanism") in ["교통사고", "추락", "둔상"]
    if unstable_chest_wall:
        score += 1
        components["unstable_chest_wall"] = True
    else:
        components["unstable_chest_wall"] = False
    
    # 2개 이상 근위부 긴뼈 골절 → "사지/골반골격" 손상 다중화
    # 실제에는 X-ray 필요하나, 손상 기전 + 다중 부위 손상으로 추정
    multiple_proximal_fractures = (
        injuries.count("사지/골반골격") > 0 or injuries.count("상지") > 0
    ) and ("사지/골반골격" in injuries or "상지" in injuries or "하지" in injuries)
    # 더 정확하게: 복수 사지 손상 또는 다중 손상 기전
    if len([i for i in injuries if i in ["사지/골반골격", "상지", "하지"]]) >= 2:
        score += 1
        components["multiple_proximal_fractures"] = True
    else:
        components["multiple_proximal_fractures"] = False
    
    # 골반 골절 의심 → "사지/골반골격" 또는 "복부/골반장기" + 고에너지 기전
    pelvic_fracture_suspected = (
        "사지/골반골격" in injuries and patient.get("mechanism") in ["교통사고", "추락"]
    ) or "복부/골반장기" in injuries
    if pelvic_fracture_suspected:
        score += 1
        components["pelvic_fracture_suspected"] = True
    else:
        components["pelvic_fracture_suspected"] = False
    
    # ============================================================
    # 거리 기반 추가 트리거 (별도 반환)
    # ============================================================
    hems_triggered_by_distance = False
    
    return {
        "ampt_score": score,
        "ampt_triggered": score >= 2,
        "components": components,
        "hems_triggered_by_distance": hems_triggered_by_distance,
    }


def check_hems_eligibility(patient: dict, first_hospital: dict = None, ampt_result: dict = None) -> dict:
    """
    HEMS 이송 적격성 판단 (종합)
    
    트리거 1: AMPT Score ≥ 2
    트리거 2: RED 환자 + 1순위 병원까지 거리 ≥ 150km
    
    반환:
      {
        "hems_recommended": bool,
        "hems_trigger_type": str (AMPT / DISTANCE / BOTH / NONE),
        "ampt_score": int,
        "reason": str
      }
    """
    if ampt_result is None:
        ampt_result = calculate_ampt_score(patient)
    
    is_red = patient.get("high_risk", False)
    hems_recommended = False
    trigger_type = "NONE"
    reason_parts = []
    
    # 트리거 1: AMPT Score ≥ 2
    if ampt_result.get("ampt_triggered"):
        hems_recommended = True
        trigger_type = "AMPT"
        reason_parts.append(
            f"AMPT Score {ampt_result['ampt_score']}점 (≥2 HEMS 권고) — "
            f"{'의식저하' if ampt_result['components'].get('gcs_low') else ''} "
            f"{'호흡곤란' if ampt_result['components'].get('respiratory_distress') else ''} "
            f"{'불안정 흉벽' if ampt_result['components'].get('unstable_chest_wall') else ''} "
            f"{'복수 골절' if ampt_result['components'].get('multiple_proximal_fractures') else ''} "
            f"{'골반 골절' if ampt_result['components'].get('pelvic_fracture_suspected') else ''}"
        )
    
    # 트리거 2: RED 환자 + 거리 ≥ 150km
    if is_red and first_hospital:
        dist_km = first_hospital.get("dist_km", 0)
        if dist_km >= 150:
            if not hems_recommended:
                hems_recommended = True
                trigger_type = "DISTANCE"
            else:
                trigger_type = "BOTH"
            
            reason_parts.append(
                f"RED(위독) 환자 + 지상 이송 거리 {dist_km:.0f}km (≥150km 골든아워 초과) → "
                f"HEMS 생존율 94.9% vs 지상 90.5%"
            )
    
    final_reason = " | ".join(reason_parts) if reason_parts else "HEMS 적격 기준 미충족"
    
    return {
        "hems_recommended": hems_recommended,
        "hems_trigger_type": trigger_type,
        "ampt_score": ampt_result.get("ampt_score", 0),
        "ampt_components": ampt_result.get("components", {}),
        "reason": final_reason,
    }


def cdc_field_triage_2021(gcs_motor, sbp, rr, age=None,
                          anatomical_flags=None, mechanism_flags=None, special_flags=None):
    """
    CDC 2021 Field Triage Guideline — RED 기준 (생리적 지표)
    근거: CDC 2021 Field Triage Guidelines (RED Criteria)
    근거: Kang et al. (2022) — Step 1(생리적 기준) 정확도 72.3%로 가장 높음
    근거: Kang et al. (2022) — 의식변화 OR 17.924, SBP<90 OR 3.535 (24h 사망)

        # ⚠️ 현재 구현 범위: 성인(10세 이상) 전용
        # anatomical_flags: list of anatomy criteria strings (e.g., 'penetrating', 'skull_fracture', 'unstable_chest', 'pelvic_fracture', 'proximal_amputation')
        # mechanism_flags: list of mechanism strings (e.g., 'high_speed_traffic', 'fall_>=3m', 'pedestrian_struck')
        # special_flags: list of special population strings (e.g., 'on_anticoagulant', 'pregnancy_>20w', 'elderly_head_injury')
    """
    # 소아 안전 처리 (CDC 기준 미구현 → 고위험으로 보수적 처리)
    if age is not None and age < 10:
        return {
            "high_risk": True,
            "reason": {"pediatric_not_supported": True},
            "warning": "소아 환자(10세 미만)입니다. CDC 소아 기준(SBP < 70+2×age) 적용이 필요하나 현재 미구현 상태입니다. 권역외상센터 이송을 권장합니다."
        }

    # 65세 이상: SBP 기준 110mmHg 적용
    sbp_cutoff = 110 if age and age >= 65 else 90

    phys_high = gcs_motor < 6 or sbp < sbp_cutoff or rr < 10 or rr > 29

    # Step 2: Anatomical (RED if any anatomical high-risk present)
    anatomical_flags = anatomical_flags or []
    anat_match = False
    anat_matches = []
    # Common anatomical RED criteria
    anat_criteria = {
        'penetrating': '관통상',
        'skull_fracture': '두개골 골절',
        'unstable_chest': '흉벽 불안정',
        'pelvic_fracture': '골반골절',
        'proximal_amputation': '근위부 절단',
    }
    for f in anatomical_flags:
        if f in anat_criteria or f in anat_criteria.values():
            anat_match = True
            anat_matches.append(f)

    # Step 3: Mechanism (YELLOW triggers or can escalate to RED depending on combo)
    mechanism_flags = mechanism_flags or []
    mech_match = False
    mech_matches = []
    mech_criteria = {
        'high_speed_traffic': '고위험 교통사고',
        'fall_over_3m': '3m 이상 추락',
        'pedestrian_struck': '보행자 충돌',
    }
    for f in mechanism_flags:
        if f in mech_criteria or f in mech_criteria.values():
            mech_match = True
            mech_matches.append(f)

    # Step 4: Special patient groups (can escalate to RED)
    special_flags = special_flags or []
    special_match = False
    special_matches = []
    special_criteria = {
        'on_anticoagulant': '항응고제 복용',
        'pregnancy_over_20w': '임신 20주 초과',
        'elderly_head_injury': '65세 이상 두부 충격',
    }
    for f in special_flags:
        if f in special_criteria or f in special_criteria.values():
            special_match = True
            special_matches.append(f)

    # Final triage: RED if physiologic high OR anatomical match OR (special + physiologic/mechanism)
    high_risk = phys_high or anat_match or (special_match and (phys_high or mech_match))

    reason = {
        'physiologic': {
            'gcs_motor': gcs_motor < 6,
            'sbp': sbp < sbp_cutoff,
            'rr': rr < 10 or rr > 29
        },
        'anatomical': anat_matches,
        'mechanism': mech_matches,
        'special': special_matches,
    }

    return {
        'high_risk': high_risk,
        'reason': reason,
        'notes': 'CDC Steps 2-4 implemented: anatomical/mechanism/special flags considered'
    }


def haversine(lat1, lng1, lat2, lng2):
    """두 좌표 간 거리 계산 (km)"""
    R = 6371
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = math.sin(d_lat/2)**2 + math.cos(math.radians(lat1)) * \
        math.cos(math.radians(lat2)) * math.sin(d_lng/2)**2
    return R * 2 * math.asin(math.sqrt(a))


def get_route_distance_time(lat1, lng1, lat2, lng2):
    """OSRM 경로 기반 거리 및 예상 운행 시간 조회"""
    if not OSRM_URL:
        return None

    cache_key = f"{round(lat1,5)},{round(lng1,5)},{round(lat2,5)},{round(lng2,5)},{OSRM_PROFILE}"
    cached = get_cached_osrm_route(cache_key)
    if cached is not None:
        return cached

    url = f"{OSRM_URL}/route/v1/{OSRM_PROFILE}/{lng1},{lat1};{lng2},{lat2}"
    params = {
        "overview": "false",
        "alternatives": "false",
    }

    try:
        resp = requests.get(url, params=params, timeout=API_CONFIG['osrm']['timeout'])
        data = resp.json()
        routes = data.get("routes") or []
        if resp.status_code == 200 and routes:
            route = routes[0]
            route_distance_km = float(route.get("distance", 0)) / 1000.0
            travel_time_min = float(route.get("duration", 0)) / 60.0
            result = {
                "route_distance_km": route_distance_km,
                "travel_time_min": travel_time_min,
            }
            set_cached_osrm_route(cache_key, result)
            return result
        print(f"[OSRM_WARNING] invalid OSRM response {data}")
    except Exception as e:
        print(f"[OSRM_ERROR] {e}")
    return None


def calc_distance_score(patient_lat, patient_lng, hospital_lat, hospital_lng, max_km=50):
    """
    거리 점수 계산
    근거: 2024 외상등록체계 통계연보
      - 중증 외상환자 최빈 이송 시간 구간: 30분~1시간
      - 지상 구급차로 30~60분 = 약 30~60km
      - 50km를 기준 반경으로 설정 (골든아워 내 도달 가능 범위)
    한계: 이송 수단(지상 vs HEMS)에 따라 동적 반경 적용 필요 (미구현)
    """
    route_info = get_route_distance_time(patient_lat, patient_lng, hospital_lat, hospital_lng)
    if route_info and route_info.get("route_distance_km") is not None:
        dist_km = route_info["route_distance_km"]
        travel_time_min = route_info["travel_time_min"]
    else:
        dist_km = haversine(patient_lat, patient_lng, hospital_lat, hospital_lng)
        travel_time_min = None

    score = max(0, 1 - dist_km / max_km)
    return score, dist_km, travel_time_min


def fetch_bed_info(hospital_id, hospital_name=None):
    """
    실시간 병상 정보 API 호출
    API: DSSP-IF-00242 (국립중앙의료원 의료기관 실시간 병상정보)
    """
    def _to_int_or_none(value, default_if_empty=0):
        if value in (None, ""):
            return default_if_empty
        try:
            iv = int(value)
            return None if iv < 0 else iv
        except Exception:
            return default_if_empty

    def _parse_bed_item(item):
        return {
            "EMRO": _to_int_or_none(item.get("EMRO"), 0),
            "OPRO": _to_int_or_none(item.get("OPRO"), 0),
            "WARD": _to_int_or_none(item.get("WARD"), 0),
            "CRDT_ICU": _to_int_or_none(item.get("CRDT_ICU"), None),
            "GNRL_ICU": _to_int_or_none(item.get("GNRL_ICU"), 0),
            "INME_ICU": _to_int_or_none(item.get("INME_ICU"), 0),
            "SUDE_ICU": _to_int_or_none(item.get("SUDE_ICU"), 0),
            "CT_AVBL": item.get("CT_AVBL_YN") == "Y",
            "MRI_AVBL": item.get("MRI_AVBL_YN") == "Y",
            "VENT_AVBL": item.get("VENT_AVBL_YN") == "Y",
        }

    try:
        if not BED_API_KEY:
            return None

        # TTL cache
        cached = get_cached_bed_info(hospital_id)
        if cached is not None:
            return cached

        # 1) Snapshot mode first: one call and map by BFR_INST_ID
        snapshot_params = {"serviceKey": BED_API_KEY}
        print(f"[BED_API_CALL] snapshot {BED_API_URL} params={snapshot_params}")
        snapshot_resp = requests.get(BED_API_URL, params=snapshot_params, timeout=6)
        print(f"[BED_API_RESPONSE] snapshot status={snapshot_resp.status_code}")
        if snapshot_resp.status_code != 200:
            snapshot_text = snapshot_resp.text or ""
            print(f"[BED_API_ERROR] snapshot body={snapshot_text[:2000]}")
        if snapshot_resp.status_code == 200:
            try:
                snapshot_data = snapshot_resp.json()
            except Exception as exc:
                print(f"[BED_API_ERROR] snapshot JSON decode failed: {exc}")
                snapshot_data = {}
            items = snapshot_data.get("response", {}).get("body", {}).get("items", [])
            if isinstance(items, dict):
                items = [items]

            if items:
                bed_map = {}
                for row in items:
                    row_id = row.get("BFR_INST_ID") or row.get("phpid") or row.get("hpid")
                    if row_id:
                        bed_map[str(row_id).strip()] = row

                row = bed_map.get(str(hospital_id).strip())
                if row:
                    # 이름 검증(가능한 경우)
                    row_name = row.get("INST_NM") or row.get("hospitalName") or ""
                    if hospital_name and row_name and hospital_name.strip() not in row_name:
                        print(f"[BED_API_WARNING] Name mismatch: {hospital_name} != {row_name}")
                        return None

                    bed_info = _parse_bed_item(row)
                    set_cached_bed_info(hospital_id, bed_info)
                    return bed_info

        # 2) Fallback mode: direct by BFR_INST_ID
        direct_params = {
            "serviceKey": BED_API_KEY,
            "BFR_INST_ID": hospital_id
        }
        print(f"[BED_API_CALL] direct {BED_API_URL} params={direct_params}")
        resp = requests.get(BED_API_URL, params=direct_params, timeout=6)
        print(f"[BED_API_RESPONSE] direct status={resp.status_code}")
        if resp.status_code != 200:
            resp_text = resp.text or ""
            print(f"[BED_API_ERROR] {hospital_id}: status {resp.status_code} body={resp_text[:2000]}")
            return None

        data = resp.json()
        items = data.get("response", {}).get("body", {}).get("items", [])
        if isinstance(items, dict):
            items = [items]
        if not items:
            print(f"[BED_API_WARNING] {hospital_id}: no items")
            return None

        bed_data = items[0]
        bed_info = _parse_bed_item(bed_data)
        set_cached_bed_info(hospital_id, bed_info)
        return bed_info

    except Exception as e:
        print(f"[BED_API_EXCEPTION] {hospital_id}: {e}")
        return None


def calc_capability_score(hospital):
    base = LEVEL_SCORE.get(hospital.get("level", ""), 10)
    return base / 100


def calc_normalized_level_score(level: str) -> float:
    return float(LEVEL_SCORE_NORM.get(level or "", 0.1))


def calc_patient_severity(patient: dict, ml_prob: float = -1.0) -> float:
    """
    환자 측 입력(GCS, SBP, RR, 나이, 손상부위, 기전)을 0~1 중증도로 정규화
    """
    gcs_motor = int(patient.get("gcs_motor", 6))
    sbp = int(patient.get("sbp", 120))
    rr = int(patient.get("rr", 16))
    age = int(patient.get("age", 45) or 45)
    mechanism = str(patient.get("mechanism") or "기타")
    injuries = patient.get("injuries") or []

    gcs_risk = min(max((6 - gcs_motor) / 5, 0.0), 1.0)
    sbp_risk = 1.0 if sbp < 90 else (0.55 if sbp < 110 else 0.20)
    rr_risk = 1.0 if rr < 10 or rr > 29 else (0.50 if rr < 12 or rr > 24 else 0.20)
    age_risk = 0.75 if age >= 65 else (0.45 if age >= 50 else 0.20)
    mech_risk = MECHANISM_RISK_MAP.get(mechanism, 0.50)
    injury_risk = max([INJURY_RISK_MAP.get(i, 0.45) for i in injuries], default=0.45)

    severity = (
        0.25 * gcs_risk
        + 0.20 * sbp_risk
        + 0.15 * rr_risk
        + 0.12 * age_risk
        + 0.13 * injury_risk
        + 0.15 * mech_risk
    )

    # 외부 데이터(Pre_hospital_mortality) 활용 방향: 사망위험 확률을 severity에 보강
    if ml_prob is not None and ml_prob >= 0:
        severity = 0.70 * severity + 0.30 * float(ml_prob)

    return min(max(float(severity), 0.0), 1.0)


def calc_hospital_pair_suitability(patient: dict, hospital: dict, specialty_match_score: float, ml_prob: float):
    """
    환자-병원 조합 적합도 산출 (0~1)
    입력 피처:
      환자 측: GCS, SBP, RR, 나이, 손상부위, 기전
      병원 측: 등급, 외상중환자실 병상 수, 전문과 일치율, 거리, 실시간 가용 병상
    """
    severity = calc_patient_severity(patient, ml_prob)

    level_score = calc_normalized_level_score(hospital.get("level"))
    if hospital.get("route_distance_km") is not None:
        dist_km = float(hospital.get("route_distance_km"))
        dist_score = max(0, 1 - dist_km / 50)
    else:
        dist_score, dist_km, _ = calc_distance_score(
            patient["lat"], patient["lng"], hospital["lat"], hospital["lng"]
        )

    realtime_beds = hospital.get("hvec")
    if realtime_beds is None:
        realtime_beds = hospital.get("bed_info", {}).get("hvec")
    realtime_bed_score = 0.5 if realtime_beds is None else min(max(realtime_beds, 0) / 20, 1.0)

    trauma_icu_beds = hospital.get("bed_info", {}).get("CRDT_ICU")
    if trauma_icu_beds is None:
        trauma_icu_beds = hospital.get("bed_info", {}).get("hvicc")
    trauma_icu_score = 0.0 if trauma_icu_beds is None else min(max(trauma_icu_beds, 0) / 20, 1.0)

    # 중증일수록 역량/전문과/중환자실 비중을 높이고, 경증일수록 거리 비중을 높임
    w_level = 0.30 + 0.18 * severity
    w_icu = 0.12 + 0.08 * severity
    w_spec = 0.18 + 0.10 * severity
    w_dist = 0.28 - 0.28 * severity
    w_real = 0.12 - 0.08 * severity

    suitability = (
        w_level * level_score
        + w_icu * trauma_icu_score
        + w_spec * specialty_match_score
        + w_dist * dist_score
        + w_real * realtime_bed_score
    )

    suitability = min(max(suitability, 0.0), 1.0)

    return {
        "suitability_score": suitability,
        "patient_severity": severity,
        "hospital_level_score": level_score,
        "trauma_icu_beds": trauma_icu_beds,
        "trauma_icu_score": trauma_icu_score,
        "specialty_match_score": specialty_match_score,
        "distance_km": dist_km,
        "distance_score": dist_score,
        "realtime_available_beds": realtime_beds,
        "realtime_bed_score": realtime_bed_score,
    }


# 등급 → 권장 병원 레벨 매핑
TIER_LEVEL_NAME = {1: "권역외상센터", 2: "권역응급의료센터", 3: "지역응급의료기관"}

# 손상부위(UI 한글) → 모델 이진 피처
_INJURY_TO_REGION = {
    "두부/경부": "head_neck", "안면": "head_neck",
    "흉부": "thorax", "복부": "abdomen", "복부/골반장기": "abdomen",
    "척추": "spine", "상지": "extremity", "하지": "extremity", "사지/골반골격": "extremity",
}


def predict_required_tier(patient: dict) -> dict:
    """
    Model 1 (v2): 현장정보 → 필요 병원 등급(1/2/3) + 확률.
    1) 특징공학(Shock Index, rSIG 등) → 2) 보정 분류기 → 3) CDC RED 안전 오버라이드.
    모델 없으면 규칙 기반으로 폴백.
    """
    injuries = patient.get("injuries", []) or []
    regions = {"head_neck": 0, "thorax": 0, "abdomen": 0, "extremity": 0, "spine": 0}
    for inj in injuries:
        r = _INJURY_TO_REGION.get(inj)
        if r:
            regions[r] = 1

    age = int(patient.get("age") or 45)
    gcs = int(patient.get("gcs_motor", 6))
    sbp = int(patient.get("sbp", 120))
    rr = int(patient.get("rr", 16))
    hr = int(patient.get("hr") or 90)
    mech = str(patient.get("mechanism") or "기타")
    penetrating_torso = int(mech == "관통상" and (regions["thorax"] or regions["abdomen"]))

    # ── CDC RED 안전 기준 (오버라이드용) ──
    sbp_cut = 110 if age >= 65 else 90
    cdc_red = (gcs < 6) or (sbp < sbp_cut) or (rr < 10) or (rr > 29) or bool(penetrating_torso)

    ml_tier, tier_probs = None, None
    if TIER_BUNDLE is not None:
        try:
            le = TIER_BUNDLE["label_encoder"]
            try:
                mech_enc = int(le.transform([mech])[0])
            except Exception:
                mech_enc = int(le.transform(["기타"])[0]) if "기타" in list(le.classes_) else 0

            si = hr / max(sbp, 1)
            rsig = (sbp / max(hr, 1)) * gcs
            n_regions = sum(regions.values())
            feat = {
                "age": age, "gcs_motor": gcs, "sbp": sbp, "rr": rr, "hr": hr,
                **regions, "penetrating_torso": penetrating_torso, "mechanism_enc": mech_enc,
                "shock_index": si, "rsig": rsig, "n_regions": n_regions,
            }
            import numpy as _np
            X = _np.array([[feat[f] for f in TIER_BUNDLE["features"]]], dtype=float)
            clf = TIER_BUNDLE.get("calibrated") or TIER_BUNDLE["model"]
            proba = clf.predict_proba(X)[0]
            classes = list(getattr(clf, "classes_", TIER_BUNDLE["classes"]))
            tier_probs = {int(c): float(p) for c, p in zip(classes, proba)}
            ml_tier = int(classes[int(_np.argmax(proba))])
        except Exception as e:
            print(f"[Model1_ERROR] {e}")

    # 폴백: 모델 없으면 규칙으로 등급
    if ml_tier is None:
        if cdc_red:
            ml_tier = 1
        elif mech in ("교통사고", "추락", "보행자 사고"):
            ml_tier = 2
        else:
            ml_tier = 3

    # ── 안전 오버라이드: CDC RED면 ML과 무관하게 최소 Tier1 ──
    final_tier = min(ml_tier, 1) if cdc_red else ml_tier
    overridden = cdc_red and ml_tier != 1

    return {
        "required_tier": final_tier,
        "required_level": TIER_LEVEL_NAME.get(final_tier, "지역응급의료기관"),
        "ml_tier": ml_tier,
        "tier_probs": tier_probs,
        "cdc_red_override": overridden,
        "model_used": TIER_BUNDLE is not None,
    }


def predict_rtc_probability(patient: dict) -> float:
    """
    [구버전 보조] Random Forest로 권역외상센터 필요 확률 예측
    반환값: 0.0~1.0 / 모델 없으면 -1
    """
    if ML_MODEL is None:
        return -1.0

    try:
        injuries = patient.get("injuries", [])
        mech_raw = patient.get("mechanism", "기타")

        # 기전 인코딩
        try:
            mech_enc = ML_LABEL_ENCODER.transform([mech_raw])[0]
        except:
            mech_enc = 0

        # train_model.py와 동일한 순서로 피처 구성
        features = [[
            patient.get("age", 40),
            mech_enc,
            patient.get("gcs_motor", 6),
            patient.get("sbp", 120),
            patient.get("rr", 16),
            int("두부/경부" in injuries),
            int("흉부" in injuries),
            int("복부/골반장기" in injuries),
            int("사지/골반골격" in injuries),
            int("척추" in injuries),
        ]]

        prob = ML_MODEL.predict_proba(features)[0][1]
        return float(prob)

    except Exception as e:
        print(f"[ML_PREDICT_ERROR] {e}")
        return -1.0


def get_specialty_match_score(required_specs, hospital_services):
    """
    전문과 일치도 점수 계산
    score = (일치 전문과 수 / 필수 전문과 수) * 100
    반환값은 0.0~1.0 범위로 정규화
    """
    required_set = set(required_specs)
    if not required_set:
        return 1.0

    hospital_set = set(hospital_services or [])
    matched = len(required_set.intersection(hospital_set))
    score_percent = (matched / len(required_set)) * 100
    return score_percent / 100


# ============================================================
# 시도(광역) 중심 좌표 — NEMC Q0/STAGE1 지역 필터에 사용
# 근거: getEgytListInfoInqire는 wgs84 좌표 필터가 동작하지 않고
#       전국 가나다순 목록을 반환함 → Q0(시도) 필터로 우회 + 실시간
#       병상 API(STAGE1)와 hpid로 조인하여 좌표·등급·병상을 결합
# ============================================================
KOREA_PROVINCES = [
    ("서울특별시", 37.5665, 126.9780), ("부산광역시", 35.1796, 129.0756),
    ("대구광역시", 35.8714, 128.6014), ("인천광역시", 37.4563, 126.7052),
    ("광주광역시", 35.1595, 126.8526), ("대전광역시", 36.3504, 127.3845),
    ("울산광역시", 35.5384, 129.3114), ("세종특별자치시", 36.4800, 127.2890),
    ("경기도", 37.4138, 127.5183), ("강원특별자치도", 37.8228, 128.1555),
    ("충청북도", 36.6357, 127.4917), ("충청남도", 36.5184, 126.8000),
    ("전북특별자치도", 35.7175, 127.1530), ("전라남도", 34.8679, 126.9910),
    ("경상북도", 36.4919, 128.8889), ("경상남도", 35.4606, 128.2132),
    ("제주특별자치도", 33.4996, 126.5312),
]
# NEMC가 구 명칭을 쓰는 경우 대비 별칭 병행
PROVINCE_ALIASES = {
    "강원특별자치도": ["강원특별자치도", "강원도"],
    "전북특별자치도": ["전북특별자치도", "전라북도"],
    "제주특별자치도": ["제주특별자치도", "제주도"],
}


def nearest_provinces(lat, lng, n=3):
    """환자 좌표에서 가까운 시도 n개 (경계 지역 커버 위해 복수 조회)"""
    ranked = sorted(KOREA_PROVINCES, key=lambda p: haversine(lat, lng, p[1], p[2]))
    return [p[0] for p in ranked[:n]]


def _bed_int(v):
    """병상 정수 변환 (음수/빈값 → None = 정보없음)"""
    try:
        iv = int(v)
        return iv if iv >= 0 else None
    except Exception:
        return None


def fetch_realtime_beds_by_region(province):
    """
    STAGE1(시도) 기준 실시간 가용병상을 hpid별로 조회.
    API: getEmrrmRltmUsefulSckbdInfoInqire (실시간 가용병상 — 지역 필터 + 병상 동시 제공)
    반환: { hpid: {hvec, hvoc, hvicc, hvcc, hvgc, hvncc, CT_AVBL, MRI_AVBL, VENT_AVBL, updated} }
    """
    if not HOSPITAL_API_KEY:
        return {}
    bed_map = {}
    for nm in PROVINCE_ALIASES.get(province, [province]):
        try:
            for page in range(1, 4):
                resp = requests.get(
                    f"{BASE_URL}/getEmrrmRltmUsefulSckbdInfoInqire",
                    params={"serviceKey": HOSPITAL_API_KEY, "STAGE1": nm,
                            "pageNo": page, "numOfRows": 100},
                    timeout=API_CONFIG['hospital_api']['timeout'],
                )
                if resp.status_code != 200:
                    break
                root = SafeET.fromstring(resp.content)
                items = list(root.iter("item"))
                for it in items:
                    hp = (it.findtext("hpid", "") or "").strip()
                    if not hp:
                        continue
                    bed_map[hp] = {
                        "hvec":  _bed_int(it.findtext("hvec")),   # 응급실 가용
                        "hvoc":  _bed_int(it.findtext("hvoc")),   # 수술실
                        "hvicc": _bed_int(it.findtext("hvicc")),  # 외상중환자실
                        "hvcc":  _bed_int(it.findtext("hvcc")),   # 중환자실
                        "hvgc":  _bed_int(it.findtext("hvgc")),   # 입원실
                        "hvncc": _bed_int(it.findtext("hvncc")),  # 신생아중환자
                        "CT_AVBL":   it.findtext("hvctayn") == "Y",
                        "MRI_AVBL":  it.findtext("hvmriayn") == "Y",
                        "VENT_AVBL": it.findtext("hvventiayn") == "Y",
                        "updated":   it.findtext("hvidate", ""),
                    }
                if len(items) < 100:
                    break
            if bed_map:
                break  # 별칭 중 데이터가 나오면 종료
        except Exception as e:
            print(f"[RTBED_EXCEPTION] {nm}: {e}")
    return bed_map


def _iter_region_list_roots(province_list):
    """Q0(시도) 기준 응급의료기관 목록 XML root를 순차 yield (좌표·등급용)"""
    for province in province_list:
        for nm in PROVINCE_ALIASES.get(province, [province]):
            got_any = False
            try:
                for page in range(1, 4):
                    resp = requests.get(
                        f"{BASE_URL}/getEgytListInfoInqire",
                        params={"serviceKey": HOSPITAL_API_KEY, "Q0": nm,
                                "pageNo": page, "numOfRows": 100},
                        timeout=API_CONFIG['hospital_api']['timeout'],
                    )
                    if resp.status_code != 200:
                        break
                    root = SafeET.fromstring(resp.content)
                    items = list(root.iter("item"))
                    if items:
                        got_any = True
                        yield root
                    if len(items) < 100:
                        break
            except Exception as e:
                print(f"[LIST_EXCEPTION] {nm}: {e}")
            if got_any:
                break  # 별칭 중 데이터가 나오면 다음 시도로


def fetch_nearby_hospitals(lat, lng, radius_km=50):
    """
    주변 응급병원 조회 (시도 기반 2-API 조인)
    - 좌표·등급: getEgytListInfoInqire (Q0=시도)
    - 실시간 병상: getEmrrmRltmUsefulSckbdInfoInqire (STAGE1=시도)
    - hpid로 조인 후 haversine 거리로 필터링
    
    ============================================================
    """
    try:
        if not HOSPITAL_API_KEY:
            print("[NEMC_API_ERROR] Missing hospital API key")
            return []

        province_list = nearest_provinces(lat, lng, n=3)

        # 실시간 병상 맵(hpid → 병상) 선조회 (지역 단위 1회씩)
        bed_map = {}
        for _prov in province_list:
            bed_map.update(fetch_realtime_beds_by_region(_prov))

        all_hospitals = []
        sample_logged = False

        for root in _iter_region_list_roots(province_list):

            # DEBUG: 첫 번째 아이템의 전체 필드와 샘플 값 출력 (bfr_inst_id 매핑 검증용)
            first_item = next(root.iter("item"), None)
            if first_item is not None and not sample_logged:
                all_fields = {child.tag: child.text for child in first_item}
                phpid_sample = first_item.findtext("phpid", "")
                hpid_sample = first_item.findtext("hpid", "")
                print(f"[API1_FIELDS] Available fields: {list(all_fields.keys())}")
                print(f"[API1_SAMPLE] phpid={phpid_sample}, hpid={hpid_sample}")
                print(f"[API1_SAMPLE] full item sample: {all_fields}")
                sample_logged = True

            page_hospitals = []
            for item in root.iter("item"):
                h_lat = float(item.findtext("wgs84Lat") or 0)
                h_lng = float(item.findtext("wgs84Lon") or 0)

                if h_lat == 0 or h_lng == 0:
                    continue

                dist = haversine(lat, lng, h_lat, h_lng)
                if dist > radius_km:
                    continue

                name = item.findtext("dutyName", "")

                # ============================================================
                # 병원 등급 파싱 — NEMC API의 dutyEmclsName(응급의료기관 분류) 사용
                # 근거: getEgytListInfoInqire는 dutyLevel을 주지 않으나
                #       dutyEmclsName으로 정확한 등급을 제공함 (이름 키워드 추측 제거)
                # ============================================================
                emcls_name = (item.findtext("dutyEmclsName", "") or "").strip()
                EMCLS_LEVEL_MAP = {
                    "권역응급의료센터": "권역응급의료센터",
                    "전문응급의료센터": "권역응급의료센터",
                    "지역응급의료센터": "지역응급의료센터",
                    "지역응급의료기관": "지역응급의료기관",
                    "응급실운영신고기관": "지역응급의료기관",
                }
                level = EMCLS_LEVEL_MAP.get(emcls_name, "지역응급의료기관")
                # 권역외상센터 보조 인식 (별도 분류가 없어 대학·외상 키워드로 승급)
                if any(k in name for k in ["권역외상", "외상센터"]):
                    level = "권역외상센터"
                elif level == "권역응급의료센터" and any(
                    k in name for k in ["전남대학교", "조선대학교", "서울대학교병원",
                                        "세브란스", "서울아산", "삼성서울", "아주대"]):
                    level = "권역외상센터"

                # ============================================================
                # 전문과 파싱: 실제 API 데이터(dgidIdName) vs 등급 기반 추론을 구분
                # services_from_api=True 일 때만 하드필터에 사용 (undertriage 방지)
                # ============================================================
                dgid_list = item.findtext("dgidIdName", "")
                services = [s.strip() for s in dgid_list.split("|") if s.strip()] if dgid_list else []
                services_from_api = len(services) > 0   # 실제 확정 데이터 여부

                # API 전문과 누락 시 등급 기반 추론 (참고용 — 하드필터 금지, 점수에만 반영)
                if not services_from_api:
                    if level in ("권역외상센터", "지역외상센터", "권역응급의료센터"):
                        # 권역급 이상은 흉부외과 포함 외상 전담 4과 보유로 가정
                        services = ["외과", "흉부외과", "정형외과", "신경외과"]
                    elif level == "지역응급의료센터":
                        services = ["외과", "정형외과", "신경외과"]
                services_confirmed = len(services) > 0

                phpid = item.findtext("phpid", "")
                hpid = item.findtext("hpid", "")
                bfr_inst_id = phpid or hpid

                # hpid/phpid를 bfr_inst_id로 임시 사용
                # ⚠️ 두 API의 기관 ID 체계가 다를 수 있음
                # → API1 응답 필드 로그 확인 후 올바른 필드를 고정해야 함
                if not bfr_inst_id:
                    print(f"[API1_ID_WARNING] Missing hpid/phpid for {name}")

                # ============================================================
                # 실시간 병상 API(STAGE1) 결과를 hpid로 조인
                # 근거: 목록 API에는 병상 필드가 없음 → 실시간 병상 API와 결합 필수
                # ============================================================
                _beds = bed_map.get(hpid) or bed_map.get(phpid) or {}
                bed_info = {
                    "hvec":  _beds.get("hvec"),
                    "hvoc":  _beds.get("hvoc"),
                    "hvicc": _beds.get("hvicc") if _beds.get("hvicc") is not None else _beds.get("hvcc"),
                    "hvncc": _beds.get("hvncc"),
                    "CT_AVBL":   _beds.get("CT_AVBL"),
                    "MRI_AVBL":  _beds.get("MRI_AVBL"),
                    "VENT_AVBL": _beds.get("VENT_AVBL"),
                    "updated":   _beds.get("updated"),
                }

                page_hospitals.append({
                    "name":               name,
                    "address":            item.findtext("dutyAddr", ""),
                    "lat":                h_lat,
                    "lng":                h_lng,
                    "tel":                item.findtext("dutyTel3", ""),
                    "services":           services,
                    "services_confirmed": services_confirmed,
                    "services_from_api":  services_from_api,
                    "level":              level,
                    "hpid":               hpid,
                    "phpid":              phpid,
                    "bfr_inst_id":        bfr_inst_id,
                    "distance":           dist,
                    "bed_info":           bed_info,
                    "hvec":               bed_info.get("hvec"),
                    "hvoc":               bed_info.get("hvoc"),
                })

            all_hospitals.extend(page_hospitals)

        # hpid 중복 제거 (시도 별칭/경계 중복) + 거리순 정렬
        seen = set()
        unique = []
        for h in sorted(all_hospitals, key=lambda x: x["distance"]):
            k = h.get("hpid") or h.get("name")
            if k in seen:
                continue
            seen.add(k)
            unique.append(h)

        with_beds = sum(1 for h in unique if h.get("hvec") is not None)
        print(f"[NEMC] {len(unique)}개 병원 (실시간 병상 {with_beds}개), 반경 {radius_km}km, 시도={province_list}")
        return unique[:50]

    except Exception as e:
        print(f"[NEMC_API_EXCEPTION] {e}")
        return []


def fetch_realtime_status(hpid):
    """실시간 응급실 가용 병상 조회"""
    try:
        if not HOSPITAL_API_KEY:
            return {"hvec": None, "hvoc": None}

        url = f"{BASE_URL}/getEmrrmRltmUsefulSckbdInfoInqire"
        params = {
            "serviceKey": HOSPITAL_API_KEY,
            "HPID": hpid,
            "pageNo": 1,
            "numOfRows": 1,
        }
        resp = requests.get(url, params=params, timeout=5)
        root = SafeET.fromstring(resp.content)
        item = next(root.iter("item"), None)

        if item is None:
            return {"hvec": None, "hvoc": None}

        hvec = int(item.findtext("hvec") or 0)
        hvoc = int(item.findtext("hvoc") or 0)

        if hvec < 0:
            hvec = None
        if hvoc < 0:
            hvoc = None

        return {"hvec": hvec, "hvoc": hvoc}

    except Exception as e:
        print(f"[STATUS_API_EXCEPTION] {hpid}: {e}")
        # ⚠️ fallback 하드코딩 제거 — None 반환으로 정보없음 처리
        return {"hvec": None, "hvoc": None}


def match_hospital(patient, hospitals):
    """
    병원 추천 점수 계산

    최종 점수 = 0.60 * 역량 + 0.15 * 거리 + 0.10 * 병상 + 0.05 * 상태 + 0.10 * 전문과일치 + 병상패널티
    가중치 근거:
      - 역량(0.70): 중증 외상은 역량 우선이 사망률 감소와 직결 (Kang 2022, 보건복지부 고시)
      - 거리(0.15): 중증 환자 최빈 이송 시간 30~60분 (2024 외상 통계연보)
      - 병상(0.10): 외상중환자실 가용 여부
      - 상태(0.05): 실시간 응급실 포화도
    ⚠️ 한계: KTDB 다변량 회귀분석 전까지 잠정값
    """
    results = []
    
    # 디버그: 필수 전문과 계산
    required = []
    for injury in patient.get("injuries", []):
        required += INJURY_SPECIALTY_MAP.get(injury, [])
    required_specs = set(required)
    print(f"[MATCH] 필수전문과: {required_specs}, 손상부위: {patient.get('injuries')}")

    for h in hospitals:
        # 복수 손상 필수 전문과 계산 (중복 제거)
        required = []
        for injury in patient["injuries"]:
            required += INJURY_SPECIALTY_MAP.get(injury, [])

        required_specs = set(required)

        # ============================================================
        # Week 5: 하이브리드 계층화 필터 (Hierarchical Filter & Cost Function)
        # 환자 중증도(RED/YELLOW) 및 전문과 계층(Critical/Supportive)에 따른 필터링
        # ============================================================
        is_red = patient.get("high_risk", False)
        hospital_services = set(h.get("services", []))
        # 전문과 데이터가 API 실측인지 여부 — 추론값이면 하드필터 금지
        specs_confirmed = h.get("services_from_api", False)

        missing_specs = required_specs - hospital_services
        missing_critical = missing_specs & CRITICAL_SPECIALTIES
        missing_supportive = missing_specs & SUPPORTIVE_SPECIALTIES

        transfer_delay_penalty = 0.0

        if required_specs:
            if is_red:
                # RED 환자 (위독)
                if missing_critical and specs_confirmed:
                    # 핵심 전문과 '확정' 누락 시에만 Hard Filter (제외)
                    # ⚠️ 추론된 전문과로는 제외하지 않음 — undertriage(사망률 급증) 방지
                    print(f"[MATCH_FILTER] {h['name']}: RED 핵심 전문과 확정 부재 ({missing_critical}) → 제외")
                    continue
                if missing_critical and not specs_confirmed:
                    # 추론 데이터 기반 누락 → 소프트 감점만 (전문과 미확인 불확실성 반영)
                    transfer_delay_penalty = len(missing_critical) * TRANSFER_DELAY_PENALTY_WEIGHT * 0.5
                    print(f"[MATCH_FILTER] {h['name']}: RED 핵심 전문과 추론 부재 → Soft 감점(미확정)")
                if missing_supportive:
                    transfer_delay_penalty += len(missing_supportive) * TRANSFER_DELAY_PENALTY_WEIGHT
            else:
                # YELLOW 환자 (양호) — 항상 소프트
                if missing_specs:
                    transfer_delay_penalty = len(missing_specs) * TRANSFER_DELAY_PENALTY_WEIGHT

        specialty_match_score = get_specialty_match_score(required_specs, hospital_services)

        # 실시간 병상은 fetch_nearby_hospitals에서 hpid 조인 완료 → 병원별 추가 호출 제거
        # (무한로딩 원인이던 per-hospital 스냅샷/실시간/OSRM 호출 삭제)
        hvec = h.get("hvec")

        # ============================================================
        # 병상 0개 → Filter-out 대신 소폭 Penalty (undertriage 방지)
        # 근거: 중증 외상은 병상 0개라도 소생구역에서 즉각 처치 가능
        # ============================================================
        bed_availability_penalty = 0.0
        if hvec is not None and hvec < 1:
            bed_availability_penalty = -0.05

        # 역량 점수
        cap = calc_capability_score(h)

        # 거리: haversine 직선거리 사용 (OSRM 경로는 최종 상위 결과만 별도 산출 — 성능)
        dist_km = h.get("distance")
        if dist_km is None:
            dist_km = haversine(patient["lat"], patient["lng"], h["lat"], h["lng"])
        dist_score = max(0, 1 - dist_km / 50)
        # 예상 이송시간: 직선거리×1.3(도로 보정) ÷ 45km/h (도심 구급차) → 분
        travel_time_min = round(dist_km * 1.3 / 45 * 60) if dist_km is not None else None
        h["travel_time_min"] = travel_time_min
        h["route_distance_km"] = dist_km

        # ============================================================
        # 병상 점수
        # 응급실 가용병상 기준: 최대 20개 기준
        # 응급실 병상이 없으면 중환자실 대용
        # ============================================================
        bed_score = 0.0
        bed_info = h.get("bed_info", {})
        
        if hvec is not None and hvec > 0:
            # 응급실 가용병상 우선
            bed_score = min(hvec / 20, 1.0)
        elif bed_info.get("hvicc") is not None and bed_info.get("hvicc") > 0:
            # 일반중환자실 대용 (응급실 우선순위 낮음)
            bed_score = min(bed_info["hvicc"] / 20, 0.6)

        # 응급실 포화도 점수 (hvec 기반)
        if hvec is not None and hvec >= 0:
            sat = min(hvec / 20, 1.0)
        else:
            # ============================================================
            # 병상 정보 None → 중립값 0.5
            # 한계: API 통신 오류 시 임의 처리
            # 향후: historical occupancy rate 데이터로 대체 예정
            # ============================================================
            sat = 0.5

        # 환자-병원 조합 적합도 계산 (요청 사양 0~1)
        ml_prob = predict_rtc_probability(patient)

        pair_score = calc_hospital_pair_suitability(
            patient=patient,
            hospital=h,
            specialty_match_score=specialty_match_score,
            ml_prob=ml_prob,
        )
        score = pair_score["suitability_score"]
        ml_used = ml_prob >= 0
        if not ml_used:
            ml_prob = None

        # ============================================================
        # Model 1 → Model 2 연결: 필요등급(required_tier) 대비 병원 역량 정렬
        # 중증(Tier1)인데 역량 부족 병원이면 감점, 최상위 역량이면 보너스
        # ============================================================
        req_tier = patient.get("required_tier")
        tier_alignment = 0.0
        if req_tier:
            HOSP_TIER = {"권역외상센터": 1, "지역외상센터": 1, "권역응급의료센터": 1,
                         "지역응급의료센터": 2, "지역응급의료기관": 3}
            h_tier = HOSP_TIER.get(h.get("level", ""), 3)
            gap = h_tier - req_tier  # >0 = 필요보다 역량 부족
            if gap > 0:
                tier_alignment = -0.10 * gap
            elif req_tier == 1 and h_tier == 1:
                tier_alignment = 0.06

        # S_final 산출: 전원 페널티 + 병상 페널티 + 등급 정렬
        score = score - transfer_delay_penalty
        score = max(0, score + bed_availability_penalty + tier_alignment)  # 음수 방지

        results.append({
            **h,
            "score":    score,
            "tier_alignment": tier_alignment,
            "dist_km":  dist_km,
            "route_distance_km": dist_km,
            "travel_time_min": travel_time_min,
            "bed_score": bed_score,
            "specialty_match_score": specialty_match_score,
            "required_specialties": sorted(list(required_specs)),
            "missing_specialties": sorted(list(missing_specs)),
            "transfer_delay_penalty": transfer_delay_penalty,
            "ml_rtc_probability": ml_prob,
            "ml_used_for_scoring": ml_used,
            "suitability": pair_score,
            "status": {
                "hvec": h.get("hvec"),
                "hvoc": h.get("hvoc"),
            },
        })

    return sorted(results, key=lambda x: x["score"], reverse=True)[:5]


def generate_explanation(patient, hospital, hems_eligibility=None):
    """
    AI 기반 이송 근거 자연어 생성 (XAI)
    HEMS 권고 로직 통합
    근거: Kang et al. (2022) OR값 기반 임상 판단
    근거: 보건복지부 권역외상센터 지정기준
    근거: 2024 외상등록체계 통계연보 — 중증 환자 두경부 68.3%, 흉부 61.0%
    근거: HEMS 생존율 비교 — 지상 이송 90.5% vs HEMS 94.9%
    """
    injuries_str = ", ".join(patient["injuries"])
    risk_level = "고위험(RED)" if patient["high_risk"] else "중등도위험(YELLOW)"
    bed_info = hospital.get("bed_info") or {}
    
    # HEMS 권고 상태
    hems_recommended = (hems_eligibility and hems_eligibility.get("hems_recommended", False)) if hems_eligibility else False
    hems_reason = (hems_eligibility.get("reason", "") if hems_eligibility else "")

    bed_analysis = []
    if bed_info.get("CRDT_ICU"):
        bed_analysis.append(f"외상중환자실 {bed_info['CRDT_ICU']}개")
    if bed_info.get("GNRL_ICU"):
        bed_analysis.append(f"일반중환자실 {bed_info['GNRL_ICU']}개")
    if bed_info.get("OPRO"):
        bed_analysis.append(f"수술실 {bed_info['OPRO']}개")
    if bed_info.get("CT_AVBL"):
        bed_analysis.append("CT 가능")
    bed_analysis_str = " | ".join(bed_analysis) if bed_analysis else "실시간 조회 불가 (API 미승인)"

    # Claude API 사용
    if claude_client:
        try:
            hems_context = ""
            if hems_recommended:
                hems_context = f"""
[HEMS 최우선 권고]
이 환자는 HEMS(닥터헬기) 이송을 최우선 권고합니다:
- {hems_reason}
- HEMS 생존율(94.9%) > 지상 이송(90.5%)
- 해당 병원(권역외상센터)이 HEMS 최적 수령 기관입니다."""
            
            prompt = f"""당신은 외상 전문 응급의학과 의사입니다.
아래 환자 정보와 병원 역량을 분석하여 구급대원에게 전달할 이송 근거를 생성하세요.

[임상 근거 — 반드시 반영]
- Kang et al. (2022), BMC Emergency Medicine:
  · 의식 변화(GCS Motor<6)는 24시간 사망과 OR 17.924로 가장 강하게 연관
  · SBP<90mmHg는 24시간 사망과 OR 3.535로 연관
  · 관통 몸통 손상은 24시간 수술과 OR 7.108로 연관
- 2024 외상등록체계 통계연보:
  · 중증 외상 환자(ISS>15) 두경부 손상 68.3%, 흉부 손상 61.0%
  · 중증 외상 사망률 20.2% (전체 8.4% 대비 2.4배)
  · 중증 환자 직접 이송률 71.3% — 직접 이송이 예후에 유리
- 보건복지부 고시: 권역외상센터는 외과·흉부외과·신경외과·정형외과 24시간 전담 의무
- CDC 2021: RED 기준 환자는 최고 수준 외상센터로 직접 이송
- HEMS 생존율: 지상 이송 90.5% vs HEMS 94.9% (거리 및 중증도 조정 후){hems_context}

[환자 정보]
- 위험도: {risk_level}
- AMPT Score: {patient.get('ampt_score', 0)}/5
- 손상 부위(AIS 분류): {injuries_str}
- 손상 기전: {patient.get('mechanism', '미입력')}
- GCS Motor: {patient['gcs_motor']}/6
- 수축기 혈압: {patient['sbp']} mmHg
- 호흡수: {patient['rr']}/분
- 나이: {patient.get('age', '미입력')}세

[병원 역량]
- 등급: {hospital['level']}
- 거리: {hospital['dist_km']:.1f}km
- 병상 현황: {bed_analysis_str}
- 외상중환자실: {bed_info.get('CRDT_ICU', '정보없음')}개 (권역외상센터 기준: 최소 20개)

[지시]
다음 3문장을 한국어로 작성하세요. 구급대원이 현장에서 즉시 이해할 수 있는 수준으로.
1. 이 환자에게 지금 당장 필요한 핵심 처치 (논문 수치 근거 포함)
2. 위 병원이 그 처치를 제공할 수 있는지 여부
3. 최종 이송 권고 이유 1문장{' HEMS 권고를 포함하여' if hems_recommended else ''}
총 3문장, 의료 전문용어 최소화."""

            message = claude_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=250,
                messages=[{"role": "user", "content": prompt}]
            )

            explanation = message.content[0].text
            
            # HEMS 권고 시 상단에 배지 표시
            if hems_recommended:
                explanation = f"🚁 [HEMS 권고] {hems_reason}\n\n{explanation}"
            
            print(f"[CLAUDE] {hospital['name']}: {explanation[:80]}...")
            return explanation

        except Exception as e:
            print(f"[CLAUDE_ERROR] {hospital['name']}: {e}")

    # ============================================================
    # Fallback: Claude 미사용 시 규칙 기반 설명
    # 근거: Kang et al. (2022), 2024 외상등록체계 통계연보
    # ============================================================
    reason_parts = []

    if "두부/경부" in patient["injuries"]:
        reason_parts.append("두경부 손상 — 신경외과 즉시 수술 가능 병원 필요 (중증 외상의 68.3%에서 두경부 손상)")
    if "흉부" in patient["injuries"]:
        reason_parts.append("흉부 손상 — 흉부외과 전담 처치 필요 (중증 외상의 61.0%에서 흉부 손상)")
    if "복부/골반장기" in patient["injuries"]:
        reason_parts.append("복부 손상 — 관통상 시 수술 OR 7.1 (Kang 2022)")

    if patient["gcs_motor"] < 6:
        reason_parts.append("의식 저하 — 24시간 사망 OR 17.9 (Kang 2022), 즉각 처치 필요")
    if patient["sbp"] < 90:
        reason_parts.append("저혈압 — 24시간 사망 OR 3.5 (Kang 2022)")

    if bed_info.get("CRDT_ICU"):
        reason_parts.append(f"외상중환자실 {bed_info['CRDT_ICU']}개 보유")

    reason_str = " / ".join(reason_parts[:2]) if reason_parts else "권역 중심 외상 처치 가능 기관"
    
    explanation = (
        f"[{hospital['level']}] {hospital['name']} 추천 | "
        f"{reason_str} | "
        f"거리 {hospital['dist_km']:.1f}km"
    )
    
    # HEMS 권고 시 설명에 포함
    if hems_recommended:
        explanation = f"🚁 [HEMS 권고] {hems_reason}\n{explanation}"
    
    return explanation


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/pitch')
@limiter.exempt
def pitch():
    """발표용 인터랙티브 슬라이드 (자체 완결형 HTML)"""
    from flask import send_file
    return send_file('presentation.html')


@app.route('/pitch2')
@limiter.exempt
def pitch2():
    """최종발표용 v.2 (모듈 구성 + 인터랙티브 시연)"""
    from flask import send_file
    return send_file('presentation_v2.html')


@app.route('/health')
@limiter.exempt
def health_check():
    """서비스 상태 체크 (로드밸런서 / 모니터링용)"""
    status = {
        'status': 'ok',
        'version': APP_VERSION,
        'checks': {
            'hospital_api_key': bool(HOSPITAL_API_KEY),
            'bed_api_key': bool(BED_API_KEY),
            'claude_available': claude_client is not None,
            'ml_model_loaded': ML_MODEL is not None,
        }
    }
    if not HOSPITAL_API_KEY or not BED_API_KEY:
        status['status'] = 'degraded'
        return jsonify(status), 503
    return jsonify(status), 200


@app.route('/api/feedback', methods=['POST'])
@limiter.limit("60 per minute")
def feedback():
    """
    피드백 수집 — 추천 결과의 적절성/전원 여부를 받아 실데이터로 축적.
    이 로그가 쌓이면 Model 1을 '실제 결과'로 재학습할 수 있다 (전향적 검증).
    저장: logs/feedback.jsonl (한 줄 = 한 건)
    """
    data = request.json or {}
    try:
        record = {
            'ts': time.strftime('%Y-%m-%dT%H:%M:%S'),
            # 현장 입력 (재학습 피처)
            'patient': {
                k: data.get('patient', {}).get(k)
                for k in ['age', 'gcs_motor', 'sbp', 'rr', 'hr', 'mechanism', 'injuries']
            },
            'required_tier': data.get('required_tier'),       # Model 1 예측
            'recommended': data.get('recommended', []),        # 추천 병원 목록
            'chosen_hospital': data.get('chosen_hospital'),    # 실제 선택
            # ── 실제 결과 라벨 (ground truth) ──
            'feedback': {
                'appropriate': data.get('feedback', {}).get('appropriate'),       # 적절했나
                'transferred': data.get('feedback', {}).get('transferred'),        # 전원 발생(=목적지 부적절)
                'actual_tier_needed': data.get('feedback', {}).get('actual_tier_needed'),
                'outcome': data.get('feedback', {}).get('outcome'),
                'note': data.get('feedback', {}).get('note'),
            },
        }
        os.makedirs('logs', exist_ok=True)
        with cache_lock:  # 동시 쓰기 보호
            with open('logs/feedback.jsonl', 'a', encoding='utf-8') as f:
                f.write(json.dumps(record, ensure_ascii=False) + '\n')
        logger.info(f"Feedback 저장: tier={record['required_tier']} "
                    f"transferred={record['feedback']['transferred']}")
        return jsonify({'status': 'ok', 'message': '피드백이 저장되었습니다. 감사합니다.'}), 200
    except Exception as e:
        logger.exception(f"Feedback 저장 실패: {e}")
        return jsonify({'error': 'feedback_save_failed', 'detail': str(e)}), 500


@app.route('/api/feedback/stats')
@limiter.exempt
def feedback_stats():
    """축적된 피드백 요약 (재학습 가능 데이터량 모니터링)"""
    path = 'logs/feedback.jsonl'
    if not os.path.exists(path):
        return jsonify({'total': 0, 'transferred': 0, 'appropriate': 0})
    total = transferred = appropriate = 0
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                total += 1
                fb = rec.get('feedback', {})
                if fb.get('transferred'):
                    transferred += 1
                if fb.get('appropriate'):
                    appropriate += 1
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    return jsonify({
        'total': total, 'transferred': transferred, 'appropriate': appropriate,
        'note': '전원(transferred) 발생 건이 목적지 오판 라벨 — 재학습 시 음성 사례로 활용',
    })


@app.route('/api/recommend', methods=['POST'])
@limiter.limit("30 per minute")
def recommend():
    data = request.json
    try:
        patient = {
            'gcs_motor':  int(data['gcs_motor']),
            'sbp':        int(data['sbp']),
            'rr':         int(data['rr']),
            'injuries':   data.get('injuries', []) or [],
            'mechanism':  data.get('mechanism', None),  # 손상 기전 (선택)
            'age':        int(data['age']) if data.get('age') is not None else None,
            'lat':        float(data['lat']),
            'lng':        float(data['lng']),
            'hr':         int(data.get('hr')) if data.get('hr') is not None else None,
            'anatomical_flags': data.get('anatomical_flags') or [],
            'mechanism_flags': data.get('mechanism_flags') or [],
            'special_flags': data.get('special_flags') or [],
        }
    except Exception as e:
        return jsonify({'error': '입력값을 확인하세요', 'detail': str(e)}), 400

    hospitals = fetch_nearby_hospitals(patient['lat'], patient['lng'], radius_km=50)

    if not hospitals:
        return jsonify({
            'error': '실시간 병원 조회에 실패했습니다.',
            'detail': 'API 키 설정 또는 외부 API 응답 상태를 확인하세요.',
            'app_version': {
                'version': APP_VERSION,
                'date': APP_VERSION_DATE,
                'claude_enabled': claude_client is not None,
            }
        }), 503

    print(f"[RECOMMEND] 초기 조회 병원 수: {len(hospitals)}, 손상부위: {patient['injuries']}")
    
    # ============================================================
    # CDC 기반 Triage 판정
    # ============================================================
    triage_result = cdc_field_triage_2021(
        patient['gcs_motor'], patient['sbp'], patient['rr'], patient['age'],
        anatomical_flags=patient.get('anatomical_flags'),
        mechanism_flags=patient.get('mechanism_flags'),
        special_flags=patient.get('special_flags')
    )
    patient['high_risk'] = triage_result['high_risk']
    
    # ============================================================
    # AMPT Score 계산 (HEMS 기반)
    # ============================================================
    ampt_result = calculate_ampt_score(patient)
    patient['ampt_score'] = ampt_result['ampt_score']
    patient['ampt_components'] = ampt_result['components']

    # ============================================================
    # Model 1: 필요 병원 등급 예측 (현장정보 → Tier 1/2/3 + 확률)
    # ============================================================
    tier_result = predict_required_tier(patient)
    patient['required_tier'] = tier_result['required_tier']
    patient['required_level'] = tier_result['required_level']
    patient['tier_detail'] = tier_result

    # ============================================================
    # 환자 상태 정량화 점수
    # ============================================================
    ml_prob = predict_rtc_probability(patient)
    patient['severity'] = calc_patient_severity(patient, ml_prob)
    patient['rtc_probability'] = ml_prob if ml_prob >= 0 else None

    matched = match_hospital(patient, hospitals)
    print(f"[RECOMMEND] 50km 매칭 결과: {len(matched)}개")

    # AND 필터로 결과가 5개 미만인 경우 반경 확장 재탐색
    # 50km -> 120km -> 200km 순으로 확대하여 최대 5개까지 수집
    search_radius_used = 50
    if len(matched) < 5:
        for radius in (120, 200):
            if len(matched) >= 5:
                break
            print(f"[RECOMMEND] {radius}km 반경으로 재탐색...")
            hospitals_wide = fetch_nearby_hospitals(patient['lat'], patient['lng'], radius_km=radius)
            print(f"[RECOMMEND] {radius}km 조회 병원: {len(hospitals_wide)}개")
            if not hospitals_wide:
                continue
            matched_wide = match_hospital(patient, hospitals_wide)
            print(f"[RECOMMEND] {radius}km 매칭 결과: {len(matched_wide)}개")
            if matched_wide:
                # 기존 결과와 추가 결과 합치기 (중복 제거)
                matched_ids = {h["hpid"] for h in matched}
                for h in matched_wide:
                    if h["hpid"] not in matched_ids and len(matched) < 5:
                        matched.append(h)
                        matched_ids.add(h["hpid"])
                if len(matched) > 0:
                    search_radius_used = radius
    
    print(f"[RECOMMEND] 최종 매칭 결과: {len(matched)}개 (반경: {search_radius_used}km)")
    if not matched:
        print(f"[RECOMMEND_WARN] 추천 가능한 병원 없음")
    
    # ============================================================
    # HEMS 적격성 판단 (첫 번째 추천 병원 기반)
    # ============================================================
    first_hospital = matched[0] if matched else None
    hems_eligibility = check_hems_eligibility(patient, first_hospital, ampt_result)
    
    for h in matched:
        h['reason'] = generate_explanation(patient, h, hems_eligibility)
        # HEMS 권고 여부를 각 병원에 추가 (첫 번째는 HEMS 권고 대상이면 표시)
        h['hems_recommended'] = (h == first_hospital) and hems_eligibility['hems_recommended']

    ml_rtc_prob = predict_rtc_probability(patient)
    _tm = (TIER_BUNDLE or {}).get("metrics", {}) if TIER_BUNDLE else {}
    ml_info = {
        'loaded': TIER_BUNDLE is not None,
        'model_type': 'Model 1 — 필요등급 예측기 (RandomForest, 3-class)',
        'required_tier': patient.get('required_tier'),
        'required_level': patient.get('required_level'),
        'tier_probs': tier_result.get('tier_probs'),
        'cdc_red_override': tier_result.get('cdc_red_override'),
        'rtc_probability': ml_rtc_prob if ml_rtc_prob >= 0 else None,
        'validation': {
            'rule_sensitivity': _tm.get('rule_sensitivity'),
            'ml_sensitivity': _tm.get('ml_sensitivity'),
            'occult_recovery': _tm.get('ml_occult_recovery'),
        },
        'training_data': 'data/trauma_tier_v2.csv (5000, 문헌 보정 합성)',
    }
    
    # ============================================================
    # MTP 및 수술 예측 모듈
    # ============================================================
    hr = patient.get('hr')
    si = None
    rsig = None
    mtp_recommended = False
    mtp_reasons = []
    if hr is not None and patient.get('sbp'):
        try:
            si = float(hr) / float(patient['sbp']) if patient['sbp'] > 0 else None
            rsig = (float(patient['sbp']) / float(hr)) * float(patient['gcs_motor']) if hr > 0 else None
        except Exception:
            si = None
            rsig = None

    if si is not None and si >= 1.0:
        mtp_recommended = True
        mtp_reasons.append('Shock Index ≥ 1.0')
    if rsig is not None and rsig < 6:
        mtp_recommended = True
        mtp_reasons.append('rSIG < 6')

    # Kang et al. 2022 기반 ORs로 24시간 내 수술 확률 추정 (간단한 OR 곱 기반 추정)
    or_map = {
        'penetrating': 7.108,
        'crush': 8.477,
        'fall': 2.141,
    }
    baseline_p0 = 0.05
    baseline_odds = baseline_p0 / (1 - baseline_p0)
    or_product = 1.0
    # 해부학적/기전 플래그에 기반한 OR 적용
    for f in (patient.get('anatomical_flags') or []):
        if f == 'penetrating' or f == '관통상':
            or_product *= or_map['penetrating']
        if f == 'crush' or f == '압궤' or f == '압궤상':
            or_product *= or_map['crush']

    for f in (patient.get('mechanism_flags') or []):
        if f == 'fall_over_3m' or f == 'fall' or f == '3m 이상 추락':
            or_product *= or_map['fall']

    est_odds = baseline_odds * or_product
    surgery_prob = est_odds / (1 + est_odds)
    notify_hospital = True if surgery_prob >= 0.70 else False
    notify_reason = []
    if notify_hospital:
        notify_reason.append(f'예상 24시간 내 수술 확률 {surgery_prob*100:.1f}% ≥ 70%')

    treatment_prediction = {
        'shock_index': si,
        'rSIG': rsig,
        'mtp_recommended': mtp_recommended,
        'mtp_reasons': mtp_reasons,
        'surgery_probability_24h': surgery_prob,
        'notify_hospital': notify_hospital,
        'notify_reason': notify_reason,
    }

    # ============================================================
    # SHAP 기반 XAI (환자별 설명) — 존재 시 호출
    # ============================================================
    xai = None
    if SHAP_AVAILABLE and explain_patient_shap is not None:
        try:
            xai = explain_patient_shap(patient)
        except Exception as e:
            print(f"[SHAP_ERROR] {e}")

    return jsonify({
        'matched':       matched,
        'field_triage':  triage_result,
        'patient':       patient,
        'hems_eligibility': hems_eligibility,
        'treatment_prediction': treatment_prediction,
        'xai': xai,
        'app_version': {
            'version':         APP_VERSION,
            'date':            APP_VERSION_DATE,
            'claude_enabled':  claude_client is not None,
        },
        'ml_model': ml_info,
        'search_radius_km': search_radius_used,
        'data_sources': {
            'triage_guideline': 'CDC 2021 Field Triage Guidelines',
            'injury_classification': 'AIS/ISS — Baker et al. (1974)',
            'korea_accuracy': 'Kang et al. (2022), BMC Emergency Medicine',
            'hospital_standard': '보건복지부 권역외상센터 지정기준 (별표 7의2)',
            'epidemiology': '2024 외상등록체계 통계연보 (중앙응급의료센터)',
            'ml_training': 'Real patient data + Random Forest classification',
            'synthetic_data': 'KTDB 원자료 미확보 — 논문 통계치 기반 합성 데이터 사용',
            'hems_guideline': 'HEMS 생존율 근거 — 지상 이송 90.5% vs HEMS 94.9%',
        }
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    desktop_mode = os.environ.get('TRIAGE_DESKTOP') == '1'
    app.run(
        host='0.0.0.0',
        port=port,
        debug=not desktop_mode,
        use_reloader=not desktop_mode,
    )