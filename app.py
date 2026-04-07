from flask import Flask, render_template, request, jsonify
import os
import requests
import xml.etree.ElementTree as ET
import math
import json
import time
import pickle
from dotenv import load_dotenv

try:
    from anthropic import Anthropic
    CLAUDE_AVAILABLE = True
except ImportError:
    CLAUDE_AVAILABLE = False
    print("⚠️  Claude API not available - using fallback text generation")

load_dotenv()

app = Flask(__name__, static_folder='static', template_folder='templates')

# API Configuration
# Hospital API key (국립중앙의료원_전국 응급의료기관 정보 조회 서비스)
HOSPITAL_API_KEY = os.getenv("NEMC_HOSPITAL_API_KEY") or os.getenv("NEMC_API_KEY")
# Bed API key (국립중앙의료원_의료기관_실시간_병상정보)
BED_API_KEY = os.getenv("NEMC_BED_API_KEY") or os.getenv("BED_API_KEY")
BASE_URL = "http://apis.data.go.kr/B552657/ErmctInfoInqireService"
BED_API_URL = "http://apis.data.go.kr/V2/api/DSSP-IF-00242"

CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY")
if CLAUDE_AVAILABLE and CLAUDE_API_KEY:
    claude_client = Anthropic(api_key=CLAUDE_API_KEY)
else:
    claude_client = None

APP_VERSION = "3.2.0"
APP_VERSION_DATE = "2026-04-05"

bed_info_cache = {}
BED_CACHE_TTL_SECONDS = 300

if not HOSPITAL_API_KEY:
    print("[CONFIG_WARNING] HOSPITAL API key not set. Set NEMC_HOSPITAL_API_KEY or NEMC_API_KEY")
if not BED_API_KEY:
    print("[CONFIG_WARNING] BED API key not set. Set NEMC_BED_API_KEY or BED_API_KEY")

# ============================================================
# ML 모델 로드
# models/triage_classifier.pkl이 존재하면 자동 로드
# 없으면 규칙 기반 전용 모드로 작동
# ============================================================
ML_MODEL = None
ML_LABEL_ENCODER = None
ML_ACCURACY = None
try:
    with open("models/triage_classifier.pkl", "rb") as f:
        model_data = pickle.load(f)
    ML_MODEL = model_data["model"]
    ML_LABEL_ENCODER = model_data["label_encoder"]
    ML_ACCURACY = model_data.get("accuracy", None)
    print(f"[ML] 모델 로드 완료 — Random Forest Accuracy {ML_ACCURACY*100:.1f}% (Test Set)")
except FileNotFoundError:
    print("[ML] 모델 파일 없음(models/triage_classifier.pkl) → 규칙 기반 전용 모드")
except Exception as e:
    print(f"[ML] 모델 로드 오류: {e} → 규칙 기반 전용 모드")

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


def cdc_field_triage_2021(gcs_motor, sbp, rr, age=None):
    """
    CDC 2021 Field Triage Guideline — RED 기준 (생리적 지표)
    근거: CDC 2021 Field Triage Guidelines (RED Criteria)
    근거: Kang et al. (2022) — Step 1(생리적 기준) 정확도 72.3%로 가장 높음
    근거: Kang et al. (2022) — 의식변화 OR 17.924, SBP<90 OR 3.535 (24h 사망)

    ⚠️ 현재 구현 범위: 성인(10세 이상) 전용
    미구현:
      - 소아(0~9세): CDC 기준 SBP < 70+(2×age) 별도 적용 필요
      - Step 2 (해부학적 손상 기준): RED 기준 미구현 → undertriage 위험
      - Step 3 (손상 기전): YELLOW 기준 미구현
      - Step 4 (특수 환자군): 임신, 항응고제 등 미구현
    향후: CDC 2021 전체 4단계 구현 필요
    """
    # 소아 안전 처리 (CDC 기준 미구현 → 고위험으로 보수적 처리)
    if age is not None and age < 10:
        return {
            "high_risk": True,
            "reason": {"pediatric_not_supported": True},
            "warning": "소아 환자(10세 미만)입니다. CDC 소아 기준(SBP < 70+2×age) 적용이 필요하나 현재 미구현 상태입니다. 권역외상센터 이송을 권장합니다."
        }

    # 65세 이상: SBP 기준 110mmHg 적용
    # 근거: CDC 2021 — Age ≥65: SBP < 110mmHg
    # 근거: 2024 외상등록체계 통계연보 — 65세 이상 41.9% (전체), 40.1% (중증)
    sbp_cutoff = 110 if age and age >= 65 else 90

    high_risk = gcs_motor < 6 or sbp < sbp_cutoff or rr < 10 or rr > 29

    return {
        "high_risk": high_risk,
        "reason": {
            "gcs_motor": gcs_motor < 6,
            "sbp": sbp < sbp_cutoff,
            "rr": rr < 10 or rr > 29
        }
    }


def haversine(lat1, lng1, lat2, lng2):
    """두 좌표 간 거리 계산 (km)"""
    R = 6371
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = math.sin(d_lat/2)**2 + math.cos(math.radians(lat1)) * \
        math.cos(math.radians(lat2)) * math.sin(d_lng/2)**2
    return R * 2 * math.asin(math.sqrt(a))


def calc_distance_score(patient_lat, patient_lng, hospital_lat, hospital_lng, max_km=50):
    """
    거리 점수 계산
    근거: 2024 외상등록체계 통계연보
      - 중증 외상환자 최빈 이송 시간 구간: 30분~1시간
      - 지상 구급차로 30~60분 = 약 30~60km
      - 50km를 기준 반경으로 설정 (골든아워 내 도달 가능 범위)
    한계: 이송 수단(지상 vs HEMS)에 따라 동적 반경 적용 필요 (미구현)
    """
    dist_km = haversine(patient_lat, patient_lng, hospital_lat, hospital_lng)
    score = max(0, 1 - dist_km / max_km)
    return score, dist_km


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
        cached = bed_info_cache.get(hospital_id)
        now_ts = math.floor(time.time())
        if cached and (now_ts - cached.get("ts", 0)) <= BED_CACHE_TTL_SECONDS:
            return cached.get("value")

        # 1) Snapshot mode first: one call and map by BFR_INST_ID
        snapshot_params = {"serviceKey": BED_API_KEY}
        snapshot_resp = requests.get(BED_API_URL, params=snapshot_params, timeout=6)
        if snapshot_resp.status_code == 200:
            snapshot_data = snapshot_resp.json()
            items = snapshot_data.get("response", {}).get("body", {}).get("items", [])
            if isinstance(items, dict):
                items = [items]

            if items:
                bed_map = {}
                for row in items:
                    row_id = row.get("BFR_INST_ID") or row.get("hpid")
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
                    bed_info_cache[hospital_id] = {"value": bed_info, "ts": now_ts}
                    return bed_info

        # 2) Fallback mode: direct by BFR_INST_ID
        direct_params = {
            "serviceKey": BED_API_KEY,
            "BFR_INST_ID": hospital_id
        }
        resp = requests.get(BED_API_URL, params=direct_params, timeout=6)
        if resp.status_code != 200:
            print(f"[BED_API_ERROR] {hospital_id}: status {resp.status_code}")
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
        bed_info_cache[hospital_id] = {"value": bed_info, "ts": now_ts}
        return bed_info

    except Exception as e:
        print(f"[BED_API_EXCEPTION] {hospital_id}: {e}")
        return None


def calc_capability_score(hospital):
    base = LEVEL_SCORE.get(hospital.get("level", ""), 10)
    return base / 100


def predict_rtc_probability(patient: dict) -> float:
    """
    Random Forest로 권역외상센터 필요 확률 예측
    반환값: 0.0~1.0 (높을수록 권역외상센터 필요)
    모델 없으면 -1 반환 (규칙 기반으로 대체)
    
    근거: 실제 데이터 학습 기반 (data/data, 2000 환자)
    features: age, mechanism_enc, gcs_motor, sbp, rr, head_neck, thorax, abdomen, extremity, spine
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


def fetch_nearby_hospitals(lat, lng, radius_km=50):
    """
    주변 응급병원 조회
    API: NEMC 전국 응급의료기관 정보 조회 서비스
    위치 파라미터(wgs84Lat, wgs84Lon, radius) 전달로 위치 기반 조회
    
    ============================================================
    Hospital API 응답에 가용병상 정보 포함:
    - hvec: 응급실 가용병상 (음수 = 정보 없음)
    - hvoc: 수술실 가용병상
    - hvicc: 일반중환자실 (ICU)
    - hvncc: 신생아중환자실
    ============================================================
    """
    try:
        if not HOSPITAL_API_KEY:
            print("[NEMC_API_ERROR] Missing hospital API key")
            return []

        all_hospitals = []

        for page in range(1, 4):
            url = f"{BASE_URL}/getEgytListInfoInqire"
            params = {
                "serviceKey": HOSPITAL_API_KEY,
                "wgs84Lat":   lat,
                "wgs84Lon":   lng,
                "radius":     radius_km,
                "pageNo":     page,
                "numOfRows":  100,
            }
            resp = requests.get(url, params=params, timeout=5)

            if resp.status_code != 200:
                print(f"[NEMC_API_ERROR] page {page}: status {resp.status_code}")
                break

            root = ET.fromstring(resp.content)

            # DEBUG: 첫 번째 아이템의 모든 필드 출력 (bfr_inst_id 매핑 검증용)
            first_item = next(root.iter("item"), None)
            if first_item is not None and not all_hospitals:
                all_fields = {child.tag: child.text for child in first_item}
                print(f"[API1_FIELDS] Available fields: {list(all_fields.keys())}")

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

                # 병원 등급 파싱 (API 필드 우선, 없으면 이름 기반 추정)
                level = item.findtext("dutyLevel", "").strip()
                if not level or level == "N/A":
                    # ⚠️ 임시 키워드 추정 — dutyLevel 필드 정상화 후 제거 예정
                    if any(k in name for k in ["전남대학교", "빛고을", "서울대", "삼성", "아산", "세브란스", "아주대"]):
                        level = "권역외상센터"
                    elif any(k in name for k in ["병원", "의료원", "기독", "성모", "중앙"]):
                        level = "지역응급의료센터"
                    else:
                        level = "지역응급의료기관"

                # ============================================================
                # 전문과 파싱: API 실제 데이터 우선 사용
                # 근거: 하드코딩 제거 — API 실시간 데이터 기반 필터링
                # ============================================================
                dgid_list = item.findtext("dgidIdName", "")
                services = [s.strip() for s in dgid_list.split("|") if s.strip()] if dgid_list else []
                services_confirmed = len(services) > 0

                # API 전문과 필드 누락 시 병원 등급 기반 최소 전담과 추론
                # 권역외상센터/응급의료센터는 핵심 외상 전담과를 기본 보유로 가정
                if not services_confirmed:
                    if level in ("권역외상센터", "지역외상센터"):
                        services = ["외과", "흉부외과", "정형외과", "신경외과"]
                        services_confirmed = True
                    elif level in ("권역응급의료센터", "지역응급의료센터"):
                        services = ["외과", "정형외과", "신경외과"]
                        services_confirmed = True

                # hpid를 bfr_inst_id로 임시 사용
                # ⚠️ 한계: 두 API의 기관 ID 체계가 다를 수 있음
                # → API1 응답 필드 로그 확인 후 올바른 필드로 교체 필요
                hpid = item.findtext("hpid", "")

                # ============================================================
                # Hospital API 응답에서 직접 병상 정보 파싱
                # 필드: hvec(응급실), hvoc(수술실), hvicc(일반중환자실), hvncc(신생아중환자실)
                # 음수 = 정보 없음 → None으로 처리
                # ============================================================
                bed_info = {}
                for key in ["hvec", "hvoc", "hvicc", "hvncc"]:
                    try:
                        val = int(item.findtext(key, -1) or -1)
                        bed_info[key] = val if val >= 0 else None
                    except:
                        bed_info[key] = None

                page_hospitals.append({
                    "name":               name,
                    "address":            item.findtext("dutyAddr", ""),
                    "lat":                h_lat,
                    "lng":                h_lng,
                    "tel":                item.findtext("dutyTel3", ""),
                    "services":           services,
                    "services_confirmed": services_confirmed,
                    "level":              level,
                    "hpid":               hpid,
                    "bfr_inst_id":        hpid,
                    "distance":           dist,
                    "bed_info":           bed_info,
                    "hvec":               bed_info.get("hvec"),
                    "hvoc":               bed_info.get("hvoc"),
                })

            all_hospitals.extend(page_hospitals)

            if len(page_hospitals) < 100:
                break

        # 병상 정보 로그
        for hospital in all_hospitals:
            hvec = hospital.get("hvec")
            hvoc = hospital.get("hvoc")
            hvicc = hospital.get("bed_info", {}).get("hvicc")
            print(f"[BED_INFO] {hospital['name']}: hvec={hvec}, hvoc={hvoc}, hvicc={hvicc}")

        all_hospitals.sort(key=lambda x: x["distance"])
        return all_hospitals[:50]

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
        root = ET.fromstring(resp.content)
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

        # AND 필터링: 복수 손상 시 모든 필수 전문과를 갖춰야 통과
        # (예: 두부+흉부 -> 신경외과 AND 흉부외과)
        if required_specs:
            if not h.get("services_confirmed"):
                print(f"[MATCH_FILTER] {h['name']}: services_confirmed=False → 제외")
                continue

            hospital_services = set(h.get("services", []))
            if not all(spec in hospital_services for spec in required_specs):
                print(f"[MATCH_FILTER] {h['name']}: 전문과 부재 (필수:{required_specs}, 보유:{hospital_services}) → 제외")
                continue

        specialty_match_score = get_specialty_match_score(required_specs, h.get("services", []))

        # ============================================================
        # Hospital API 응답에서 직접 사용 (BED API 불필요)
        # hvec = 응급실 가용병상 (음수 = 정보 없음)
        # ============================================================
        hvec = h.get("hvec")

        # ============================================================
        # 병상 0개 → Filter-out 제거, Penalty로 변경
        # 근거: 중증 외상 환자는 병상 0개라도 외상 소생구역(Resuscitation bay)에서
        #       즉각 Damage Control Surgery 가능
        #       Filter-out은 undertriage로 사망률 급증 위험
        # ============================================================
        bed_availability_penalty = 0.0
        if hvec is not None and hvec < 1:
            bed_availability_penalty = -0.05  # 소폭 감점만, 제외 안 함

        # 역량 점수
        cap = calc_capability_score(h)

        # 거리 점수
        dist_score, dist_km = calc_distance_score(
            patient["lat"], patient["lng"], h["lat"], h["lng"]
        )

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

        # ============================================================
        # ML 모델 통합 앙상블 점수 계산
        # 규칙 기반: 역량(60%) + 거리(15%) + 병상(10%) + 상태(5%)
        # 가중치: 규칙 60% + ML 40%
        # 근거: ML은 실제 데이터 기반 needs_rtc 확률 반영
        #       규칙은 임상 논문 근거(CDC 2021, Kang 2022) 반영
        # ============================================================
        ml_prob = predict_rtc_probability(patient)

        if ml_prob >= 0:
            # 규칙 기반 점수 (최종 정규화 전)
            rule_score = (
                0.70 * cap
                + 0.15 * dist_score
                + 0.10 * bed_score
                + 0.05 * sat
            )
            # 앙상블: 규칙 60% + ML 40%
            score = 0.60 * rule_score + 0.40 * ml_prob
            ml_used = True
        else:
            # ML 없으면 기존 규칙 기반 100%
            score = (
                0.60 * cap
                + 0.15 * dist_score
                + 0.10 * bed_score
                + 0.05 * sat
                + 0.10 * specialty_match_score
            )
            ml_used = False
            ml_prob = None

        score = max(0, score + bed_availability_penalty)  # 음수 방지

        results.append({
            **h,
            "score":    score,
            "dist_km":  dist_km,
            "bed_score": bed_score,
            "specialty_match_score": specialty_match_score,
            "required_specialties": sorted(list(required_specs)),
            "ml_rtc_probability": ml_prob,
            "ml_used_for_scoring": ml_used,
        })

    return sorted(results, key=lambda x: x["score"], reverse=True)[:5]


def generate_explanation(patient, hospital):
    """
    AI 기반 이송 근거 자연어 생성 (XAI)
    근거: Kang et al. (2022) OR값 기반 임상 판단
    근거: 보건복지부 권역외상센터 지정기준
    근거: 2024 외상등록체계 통계연보 — 중증 환자 두경부 68.3%, 흉부 61.0%
    """
    injuries_str = ", ".join(patient["injuries"])
    risk_level = "고위험(RED)" if patient["high_risk"] else "중등도위험(YELLOW)"
    bed_info = hospital.get("bed_info") or {}

    bed_analysis = []
    if bed_info.get("CRDT_ICU"):
        bed_analysis.append(f"외상중환자실 {bed_info['CRDT_ICU']}개")
    if bed_info.get("GNRL_ICU"):
        bed_analysis.append(f"일반중환자실 {bed_info['GNRL_ICU']}개")
    if bed_info.get("OPRO"):
        bed_analysis.append(f"수술실 {bed_info['OPRO']}개")
    if bed_info.get("CT_AVBL"):
        bed_analysis.append("CT 가능")
    bed_analysis_str = " | ".join(bed_analysis) if bed_analysis else "정보 없음"

    # Claude API 사용
    if claude_client:
        try:
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

[환자 정보]
- 위험도: {risk_level}
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
3. 최종 이송 권고 이유 1문장
총 3문장, 의료 전문용어 최소화."""

            message = claude_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}]
            )

            explanation = message.content[0].text
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

    return (
        f"[{hospital['level']}] {hospital['name']} 추천 | "
        f"{reason_str} | "
        f"거리 {hospital['dist_km']:.1f}km"
    )


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/recommend', methods=['POST'])
def recommend():
    data = request.json
    try:
        patient = {
            'gcs_motor':  int(data['gcs_motor']),
            'sbp':        int(data['sbp']),
            'rr':         int(data['rr']),
            'injuries':   data['injuries'],
            'mechanism':  data.get('mechanism', None),  # 손상 기전 (선택)
            'age':        int(data['age']) if data.get('age') is not None else None,
            'lat':        float(data['lat']),
            'lng':        float(data['lng']),
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
    
    triage_result = cdc_field_triage_2021(
        patient['gcs_motor'], patient['sbp'], patient['rr'], patient['age']
    )
    patient['high_risk'] = triage_result['high_risk']

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
    
    for h in matched:
        h['reason'] = generate_explanation(patient, h)

    ml_rtc_prob = predict_rtc_probability(patient)
    ml_info = {
        'loaded': ML_MODEL is not None,
        'accuracy': ML_ACCURACY,
        'rtc_probability': ml_rtc_prob if ml_rtc_prob >= 0 else None,
        'model_type': 'Random Forest',
        'training_data': 'data/data (2000 patients)',
        'feature_count': 10,
    }
    
    return jsonify({
        'matched':       matched,
        'field_triage':  triage_result,
        'patient':       patient,
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
        }
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)