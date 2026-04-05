from flask import Flask, render_template, request, jsonify
import os
import requests
import xml.etree.ElementTree as ET
import math
import json
import time
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


def fetch_nearby_hospitals(lat, lng, radius_km=50):
    """
    주변 응급병원 조회
    API: NEMC 전국 응급의료기관 정보 조회 서비스
    위치 파라미터(wgs84Lat, wgs84Lon, radius) 전달로 위치 기반 조회
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

                # hpid를 bfr_inst_id로 임시 사용
                # ⚠️ 한계: 두 API의 기관 ID 체계가 다를 수 있음
                # → API1 응답 필드 로그 확인 후 올바른 필드로 교체 필요
                hpid = item.findtext("hpid", "")

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
                    "bed_info":           None,
                })

            all_hospitals.extend(page_hospitals)

            if len(page_hospitals) < 100:
                break

        # 병상 정보 조회
        for hospital in all_hospitals:
            bed_info = fetch_bed_info(
                hospital_id=hospital["bfr_inst_id"],
                hospital_name=hospital["name"]
            )
            hospital["bed_info"] = bed_info

            if bed_info:
                print(f"[BED_INFO] {hospital['name']}: CRDT_ICU={bed_info.get('CRDT_ICU')}, GNRL_ICU={bed_info.get('GNRL_ICU')}")
            else:
                print(f"[BED_INFO] {hospital['name']}: None")

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

    최종 점수 = 0.70 * 역량 + 0.15 * 거리 + 0.10 * 병상 + 0.05 * 상태 + 병상패널티
    가중치 근거:
      - 역량(0.70): 중증 외상은 역량 우선이 사망률 감소와 직결 (Kang 2022, 보건복지부 고시)
      - 거리(0.15): 중증 환자 최빈 이송 시간 30~60분 (2024 외상 통계연보)
      - 병상(0.10): 외상중환자실 가용 여부
      - 상태(0.05): 실시간 응급실 포화도
    ⚠️ 한계: KTDB 다변량 회귀분석 전까지 잠정값
    """
    results = []

    for h in hospitals:
        # 전문과 필터링 (실제 데이터 있을 때만 적용)
        required = []
        for injury in patient["injuries"]:
            required += INJURY_SPECIALTY_MAP.get(injury, [])

        if required and h.get("services_confirmed"):
            if not any(s in h["services"] for s in set(required)):
                # 실제 전문과 데이터 있는데 해당 과 없으면 제외
                continue
        # services_confirmed=False면 필터링 건너뜀 (undertriage 방지)

        # 실시간 상태 조회
        status = fetch_realtime_status(h["hpid"])

        # ============================================================
        # 병상 0개 → Filter-out 제거, Penalty로 변경
        # 근거: 중증 외상 환자는 병상 0개라도 외상 소생구역(Resuscitation bay)에서
        #       즉각 Damage Control Surgery 가능
        #       Filter-out은 undertriage로 사망률 급증 위험
        # ============================================================
        bed_availability_penalty = 0.0
        if status["hvec"] is not None and status["hvec"] < 1:
            bed_availability_penalty = -0.05  # 소폭 감점만, 제외 안 함

        # 역량 점수
        cap = calc_capability_score(h)

        # 거리 점수
        dist_score, dist_km = calc_distance_score(
            patient["lat"], patient["lng"], h["lat"], h["lng"]
        )

        # ============================================================
        # 병상 점수
        # 외상중환자실 만점 기준: 20개 (보건복지부 고시 최소 기준)
        # 기존 10개 → 20개로 상향 (법적 최소 요건 반영)
        # 일반중환자실 상한: 0.6 (외상중환자실 대비 우선순위 낮음)
        # ============================================================
        bed_score = 0.0
        bed_info = h.get("bed_info")
        if bed_info:
            if bed_info.get("CRDT_ICU") is not None and bed_info.get("CRDT_ICU") > 0:
                # [근거] 보건복지부 고시: 권역외상센터 외상중환자실 최소 20병상
                bed_score = min(bed_info["CRDT_ICU"] / 20, 1.0)
            elif bed_info.get("GNRL_ICU") is not None and bed_info.get("GNRL_ICU") > 0:
                # 일반중환자실: 외상 전용 아니므로 상한 0.6
                bed_score = min(bed_info["GNRL_ICU"] / 20, 0.6)

        # 실시간 포화도 점수
        if status["hvec"] is not None:
            sat = min(status["hvec"] / 20, 1.0)
        else:
            # ============================================================
            # 병상 정보 None → 중립값 0.5
            # 한계: API 통신 오류 시 임의 처리
            # 향후: historical occupancy rate 데이터로 대체 예정
            # ============================================================
            sat = 0.5

        # 최종 점수
        score = (
            0.70 * cap
            + 0.15 * dist_score
            + 0.10 * bed_score
            + 0.05 * sat
            + bed_availability_penalty
        )
        score = max(0, score)  # 음수 방지

        results.append({
            **h,
            "score":    score,
            "dist_km":  dist_km,
            "status":   status,
            "bed_score": bed_score,
        })

    return sorted(results, key=lambda x: x["score"], reverse=True)[:3]


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

    hospitals = fetch_nearby_hospitals(patient['lat'], patient['lng'])

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

    triage_result = cdc_field_triage_2021(
        patient['gcs_motor'], patient['sbp'], patient['rr'], patient['age']
    )
    patient['high_risk'] = triage_result['high_risk']

    matched = match_hospital(patient, hospitals)
    for h in matched:
        h['reason'] = generate_explanation(patient, h)

    return jsonify({
        'matched':       matched,
        'field_triage':  triage_result,
        'patient':       patient,
        'app_version': {
            'version':         APP_VERSION,
            'date':            APP_VERSION_DATE,
            'claude_enabled':  claude_client is not None,
        },
        'data_sources': {
            'triage_guideline': 'CDC 2021 Field Triage Guidelines',
            'injury_classification': 'AIS/ISS — Baker et al. (1974)',
            'korea_accuracy': 'Kang et al. (2022), BMC Emergency Medicine',
            'hospital_standard': '보건복지부 권역외상센터 지정기준 (별표 7의2)',
            'epidemiology': '2024 외상등록체계 통계연보 (중앙응급의료센터)',
            'synthetic_data': 'KTDB 원자료 미확보 — 논문 통계치 기반 합성 데이터 사용',
        }
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)