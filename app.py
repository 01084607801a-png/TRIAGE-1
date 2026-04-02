from flask import Flask, render_template, request, jsonify
import os
import requests
import xml.etree.ElementTree as ET
import math
import json
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__, static_folder='static', template_folder='templates')

# NEMC API Configuration
NEMC_API_KEY = os.getenv("NEMC_API_KEY")  # Read from .env file for security
BED_API_KEY = "9405GX6ZR03O0L21"  # Real-time bed info API key
BASE_URL = "http://apis.data.go.kr/B552657/ErmctInfoInqireService"
BED_API_URL = "http://apis.data.go.kr/V2/api/DSSP-IF-00242"

# 병상 정보 캐시 (메모리에 저장, 중복 조회 방지)
bed_info_cache = {}

# Injury Specialty Map (AIS-based, simplified to 7 regions)
INJURY_SPECIALTY_MAP = {
    "두부/경부": ["신경외과"],          # Head & Neck
    "안면":     ["성형외과", "이비인후과"],  # Face
    "흉부":     ["흉부외과"],           # Thorax
    "복부":     ["외과"],              # Abdomen & Pelvic contents
    "척추":     ["신경외과", "정형외과"],  # Spine
    "상지":     ["정형외과"],           # Upper Extremity
    "하지":     ["정형외과"],           # Lower Extremity & Pelvis
}

LEVEL_SCORE = {
    "권역외상센터": 100,
    "지역외상센터": 70,
    "권역응급의료센터": 60,
    "지역응급의료센터": 40,
    "지역응급의료기관": 20,
}

def cdc_field_triage_2021(gcs_motor, sbp, rr, age=None):
    """
    CDC 2021 Field Triage Guideline
    - gcs_motor: GCS Motor Score (1-6)
    - sbp: Systolic BP (mmHg)
    - rr: Respiratory Rate (/min)
    - age: Age (65+ for SBP cutoff adjustment)
    """
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
    """Calculate distance between two coordinates in km"""
    R = 6371
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = math.sin(d_lat/2)**2 + math.cos(math.radians(lat1)) * \
        math.cos(math.radians(lat2)) * math.sin(d_lng/2)**2
    return R * 2 * math.asin(math.sqrt(a))

def calc_distance_score(patient_lat, patient_lng, hospital_lat, hospital_lng, max_km=50):
    dist_km = haversine(patient_lat, patient_lng, hospital_lat, hospital_lng)
    score = max(0, 1 - dist_km / max_km)  # Closer is better
    return score, dist_km

def fetch_bed_info(hospital_id, hospital_name=None):
    """
    신규 병상 정보 API 호출 (정확한 매칭 필수!)
    
    Args:
        hospital_id: BFR_INST_ID (예: A2800015)
        hospital_name: 검증용 병원명 (오류 방지)
    
    Returns:
        병상 정보 dict 또는 None
    """
    try:
        # 캐시 확인 (같은 병원 재조회 방지)
        if hospital_id in bed_info_cache:
            return bed_info_cache[hospital_id]
        
        # API 호출
        params = {
            "serviceKey": BED_API_KEY,
            "BFR_INST_ID": hospital_id
        }
        
        resp = requests.get(BED_API_URL, params=params, timeout=5)
        
        if resp.status_code != 200:
            print(f"Bed API error for {hospital_id}: {resp.status_code}")
            return None
        
        # JSON 응답 파싱
        data = resp.json()
        
        # 🔍 DEBUG: Log raw API response for field inspection
        print(f"[BED_API_RAW] Hospital ID: {hospital_id}")
        print(f"[BED_API_RAW] Response keys: {data.keys() if data else 'None'}")
        if data and "response" in data:
            print(f"[BED_API_RAW] Response.body keys: {data['response'].get('body', {}).keys()}")
        
        # API 응답 구조에 따라 처리
        # 보통 result 또는 response.body.items 구조
        if not data or "response" not in data:
            print(f"[BED_API_ERROR] No response key in data for {hospital_id}")
            return None
        
        response_data = data.get("response", {})
        items = response_data.get("body", {}).get("items", [])
        
        if not items:
            print(f"[BED_API_WARNING] No items in response for {hospital_id}")
            return None
        
        bed_data = items[0]
        print(f"[BED_API_RAW] Bed data fields: {bed_data.keys()}")
        
        # ⚠️ 이름으로 검증 (혼동 방지)
        if hospital_name and "hospitalName" in bed_data:
            if hospital_name.strip() not in bed_data.get("hospitalName", ""):
                print(f"WARNING: Hospital name mismatch! {hospital_name} != {bed_data.get('hospitalName')}")
                # 이름이 다르면 안전상 조회하지 않음
                return None
        
        # 병상 정보 추출
        bed_info = {
            "EMRO": int(bed_data.get("EMRO", 0)) if bed_data.get("EMRO") else 0,  # 응급실
            "OPRO": int(bed_data.get("OPRO", 0)) if bed_data.get("OPRO") else 0,  # 수술실
            "WARD": int(bed_data.get("WARD", 0)) if bed_data.get("WARD") else 0,  # 입원실
            "CRDT_ICU": int(bed_data.get("CRDT_ICU", -1)) if bed_data.get("CRDT_ICU") else -1,  # 외상중환자실 ⭐
            "GNRL_ICU": int(bed_data.get("GNRL_ICU", 0)) if bed_data.get("GNRL_ICU") else 0,  # 일반중환자실
            "INME_ICU": int(bed_data.get("INME_ICU", 0)) if bed_data.get("INME_ICU") else 0,  # 내과중환자실
            "SUDE_ICU": int(bed_data.get("SUDE_ICU", 0)) if bed_data.get("SUDE_ICU") else 0,  # 외과중환자실
            "CT_AVBL": bed_data.get("CT_AVBL_YN") == "Y",
            "MRI_AVBL": bed_data.get("MRI_AVBL_YN") == "Y",
            "VENT_AVBL": bed_data.get("VENT_AVBL_YN") == "Y",
        }
        
        # 음수 병상은 "정보없음" 처리
        for key, value in bed_info.items():
            if isinstance(value, int) and value < 0:
                bed_info[key] = None  # 정보없음으로 표시
        
        # 캐시 저장
        bed_info_cache[hospital_id] = bed_info
        return bed_info
    
    except Exception as e:
        print(f"fetch_bed_info error for {hospital_id}: {e}")
        return None

def get_bed_display(bed_info, bed_type="CRDT_ICU"):
    """병상 정보를 표시용으로 포맷팅"""
    if not bed_info:
        return "정보 없음"
    
    bed_count = bed_info.get(bed_type)
    if bed_count is None or bed_count < 0:
        return "정보 없음"
    
    return str(bed_count)

def calc_capability_score(hospital):
    base = LEVEL_SCORE.get(hospital.get("level", ""), 20)
    return base / 100  # Normalize to 0-1

def fetch_nearby_hospitals(lat, lng, radius_km=50):  # Smaller radius for faster response
    """Fetch emergency hospitals from NEMC API within radius using location parameters"""
    try:
        all_hospitals = []
        
        # Fetch multiple pages with location-based filtering
        # CRITICAL: Add location parameters to API so it returns hospitals near patient location
        for page in range(1, 4):  # Get up to 3 pages (300 hospitals) to ensure coverage
            url = f"{BASE_URL}/getEgytListInfoInqire"
            params = {
                "serviceKey": NEMC_API_KEY,
                "wgs84Lat": lat,      # ⭐ Location parameter: Patient latitude
                "wgs84Lon": lng,      # ⭐ Location parameter: Patient longitude
                "radius": radius_km,  # ⭐ Location parameter: Search radius in km
                "pageNo": page,
                "numOfRows": 100,  # Max per page (300 total max)
            }
            resp = requests.get(url, params=params, timeout=5)  # Shorter timeout
            
            if resp.status_code != 200:
                print(f"API call page {page} failed with status {resp.status_code}")
                break  # Stop pagination if API fails
            
            root = ET.fromstring(resp.content)
            
            page_hospitals = []
            for item in root.iter("item"):
                h_lat = float(item.findtext("wgs84Lat") or 0)
                h_lng = float(item.findtext("wgs84Lon") or 0)
                
                if h_lat == 0 or h_lng == 0:
                    continue  # Skip hospitals without coordinates
                    
                dist = haversine(lat, lng, h_lat, h_lng)
                
                # Additional filter just in case API params don't work
                if dist > radius_km:
                    continue  # Skip hospitals outside radius
                
                # Assign level based on hospital name patterns
                level = item.findtext("dutyLevel", "")
                if not level or level == "N/A":
                    name = item.findtext("dutyName", "")
                    if any(keyword in name for keyword in ["전남대학교", "빛고을", "서울대", "삼성", "아산", "세브란스", "서울아산", "고대안암", "고대구로"]):
                        level = "권역외상센터"
                    elif any(keyword in name for keyword in ["병원", "의료원", "기독", "성모", "중앙", "동아", "인하", "가천", "한림", "강남", "강동"]):
                        level = "지역응급의료센터"
                    else:
                        level = "지역응급의료기관"
                
                page_hospitals.append({
                    "name":     name,
                    "address":  item.findtext("dutyAddr", ""),
                    "lat":      h_lat,
                    "lng":      h_lng,
                    "tel":      item.findtext("dutyTel3", ""),
                    "services": ["내과", "외과", "정형외과", "신경외과", "흉부외과"],  # Default services
                    "level":    level,
                    "hpid":     item.findtext("hpid", ""),
                    "bfr_inst_id": item.findtext("hpid", ""),  # Assuming same as hpid, will use for bed info
                    "distance": dist,
                    "bed_info": None,  # Will be filled later
                })
            
            all_hospitals.extend(page_hospitals)
            
            # If this page has less than 100 hospitals, we've reached the end
            if len(page_hospitals) < 100:
                break
        
        # ⚠️ 정확한 매칭: 병상 정보 조회 (병원별로)
        for hospital in all_hospitals:
            bed_info = fetch_bed_info(
                hospital_id=hospital["bfr_inst_id"],
                hospital_name=hospital["name"]  # 검증용 병원명
            )
            hospital["bed_info"] = bed_info
            
            # 🔍 DEBUG: Log bed info retrieval
            if bed_info:
                print(f"[BED_INFO] {hospital['name']}: CRDT_ICU={bed_info.get('CRDT_ICU')}, GNRL_ICU={bed_info.get('GNRL_ICU')}")
            else:
                print(f"[BED_INFO] {hospital['name']}: API returned None")
        
        # Sort by distance and return top 50 closest
        all_hospitals.sort(key=lambda x: x["distance"])
        return all_hospitals[:50]
        
    except Exception as e:
        print(f"NEMC API error: {e}")
        return []

def fetch_realtime_status(hpid):
    """Fetch real-time ER status"""
    try:
        url = f"{BASE_URL}/getEmrrmRltmUsefulSckbdInfoInqire"
        params = {
            "serviceKey": NEMC_API_KEY,
            "HPID": hpid,
            "pageNo": 1,
            "numOfRows": 1,
        }
        resp = requests.get(url, params=params, timeout=5)
        root = ET.fromstring(resp.content)
        item = next(root.iter("item"), None)
        if item is None:
            return {"hvec": None, "hvoc": None}  # No data available
        
        hvec_raw = item.findtext("hvec")
        hvoc_raw = item.findtext("hvoc")
        
        hvec = int(hvec_raw or 0)
        hvoc = int(hvoc_raw or 0)
        
        # Handle negative or invalid values (negative likely means "no data")
        if hvec < 0:
            hvec = None  # No data available
        if hvoc < 0:
            hvoc = None  # No data available
        
        return {
            "hvec": hvec,   # Available ER beds
            "hvoc": hvoc,   # Available OR beds
        }
    except Exception as e:
        print(f"Status API error for {hpid}: {e}")
        # ⚠️ CRITICAL FIX: No hardcoded fallback!
        # Return None instead of hardcoded "5" to avoid static bed counts
        return {"hvec": None, "hvoc": None}

def match_hospital(patient, hospitals):
    """
    병원 추천 로직 (병상 정보 포함)
    ⚠️ 정확한 병원-병상 매칭 필수!
    """
    results = []
    for h in hospitals:
        # 전문과 필터링
        required = []
        for injury in patient["injuries"]:
            required += INJURY_SPECIALTY_MAP.get(injury, [])
        if required and not any(s in h["services"] for s in set(required)):
            continue  # Skip hospitals that don't have required specialties

        # 기존 실시간 상태 조회 (기존 API)
        status = fetch_realtime_status(h["hpid"])
        if status["hvec"] is not None and status["hvec"] < 1:  # Skip if known to have 0 beds
            continue  # But allow hospitals with unknown bed status

        # 점수 계산
        cap = calc_capability_score(h)  # 병원 등급 (100점)
        dist_score, dist_km = calc_distance_score(
            patient["lat"], patient["lng"], h["lat"], h["lng"]
        )  # 거리 (0-1점)
        
        # ⭐ 신규 병상 정보 활용 (외상중환자실 우선)
        bed_score = 0.0
        bed_info = h.get("bed_info")
        if bed_info and bed_info.get("CRDT_ICU") is not None and bed_info.get("CRDT_ICU") > 0:
            # 외상중환자실 병상이 있으면 가산점
            bed_score = min(bed_info.get("CRDT_ICU", 0) / 10, 1.0)  # Max 0-1 (10개 이상이면 1.0)
        elif bed_info and bed_info.get("GNRL_ICU") is not None and bed_info.get("GNRL_ICU") > 0:
            # 일반중환자실도 활용 (우선순위 낮음)
            bed_score = min(bed_info.get("GNRL_ICU", 0) / 15, 0.7)  # Max 0.7
        
        # 기존 API 상태 (참고용)
        if status["hvec"] is not None:
            sat = min(status["hvec"] / 20, 1.0)  # Normalize based on 20 beds
        else:
            sat = 0.5  # Neutral score for unknown availability
        
        # 최종 점수: 70% 역량, 15% 거리, 10% 신규_병상, 5% 기존상태
        score = 0.7 * cap + 0.15 * dist_score + 0.1 * bed_score + 0.05 * sat
        
        results.append({
            **h, 
            "score": score, 
            "dist_km": dist_km, 
            "status": status,
            "bed_score": bed_score,
        })

    return sorted(results, key=lambda x: x["score"], reverse=True)[:3]

def generate_explanation(patient, hospital):
    # Placeholder for Claude API integration
    injuries_str = ", ".join(patient["injuries"])
    risk = "고위험" if patient["high_risk"] else "중등도"
    
    return (
        f"{hospital['name']}을(를) 추천합니다. "
        f"환자 위험도: {risk}, 손상 부위: {injuries_str}. "
        f"거리 {hospital['dist_km']:.1f}km, 등급: {hospital['level']}."
    )


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/recommend', methods=['POST'])
def recommend():
    data = request.json
    try:
        patient = {
            'gcs_motor': int(data['gcs_motor']),
            'sbp': int(data['sbp']),
            'rr': int(data['rr']),
            'injuries': data['injuries'],  # List of injuries
            'age': int(data['age']) if data.get('age') is not None else None,
            'lat': float(data['lat']),
            'lng': float(data['lng']),
        }
    except Exception as e:
        return jsonify({'error': '입력값을 확인하세요', 'detail': str(e)}), 400

    # Fetch real hospitals
    hospitals = fetch_nearby_hospitals(patient['lat'], patient['lng'])
    if not hospitals:
        # Fallback to dummy data if API fails
        hospitals = [
            {'name': '전남대학교병원', 'lat': 35.17, 'lng': 126.92, 'services': ['신경외과', '정형외과', '외과'], 'level': '권역외상센터', 'hpid': 'test1'},
            {'name': '빛고을전남대병원', 'lat': 35.17, 'lng': 126.90, 'services': ['흉부외과', '외과'], 'level': '지역외상센터', 'hpid': 'test2'},
            {'name': '세인트병원', 'lat': 35.18, 'lng': 126.86, 'services': ['정형외과', '외과', '신경외과'], 'level': '권역응급의료센터', 'hpid': 'test3'},
        ]

    triage_result = cdc_field_triage_2021(patient['gcs_motor'], patient['sbp'], patient['rr'], patient['age'])
    patient['high_risk'] = triage_result['high_risk']

    matched = match_hospital(patient, hospitals)
    for h in matched:
        h['reason'] = generate_explanation(patient, h)

    return jsonify({
        'matched': matched, 
        'field_triage': triage_result,
        'patient': patient
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
