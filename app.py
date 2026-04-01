from flask import Flask, render_template, request, jsonify
import os
import requests
import xml.etree.ElementTree as ET
import math
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__, static_folder='static', template_folder='templates')

# NEMC API Configuration
NEMC_API_KEY = os.getenv("NEMC_API_KEY")  # Read from .env file for security
BASE_URL = "http://apis.data.go.kr/B552657/ErmctInfoInqireService"

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

def calc_capability_score(hospital):
    base = LEVEL_SCORE.get(hospital.get("level", ""), 20)
    return base / 100  # Normalize to 0-1

def fetch_nearby_hospitals(lat, lng, radius_km=50):  # Smaller radius for faster response
    """Fetch emergency hospitals nationwide from NEMC API"""
    try:
        all_hospitals = []
        
        # Get only first page for faster response
        for page in range(1, 2):  # Get only first page (100 hospitals)
            url = f"{BASE_URL}/getEgytListInfoInqire"
            params = {
                "serviceKey": NEMC_API_KEY,
                # Remove Q0 for nationwide search
                "pageNo": page,
                "numOfRows": 100,  # Max per page
            }
            resp = requests.get(url, params=params, timeout=5)  # Shorter timeout
            root = ET.fromstring(resp.content)
            
            page_hospitals = []
            for item in root.iter("item"):
                h_lat = float(item.findtext("wgs84Lat") or 0)
                h_lng = float(item.findtext("wgs84Lon") or 0)
                
                if h_lat == 0 or h_lng == 0:
                    continue  # Skip hospitals without coordinates
                    
                dist = haversine(lat, lng, h_lat, h_lng)
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
                    "distance": dist,
                })
            
            all_hospitals.extend(page_hospitals)
            
            # If this page has less than 100 hospitals, we've reached the end
            if len(page_hospitals) < 100:
                break
        
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
        return {"hvec": 5, "hvoc": 2}  # Fallback values

def match_hospital(patient, hospitals):
    results = []
    for h in hospitals:
        # Re-enable specialty filtering - use default services for now
        required = []
        for injury in patient["injuries"]:
            required += INJURY_SPECIALTY_MAP.get(injury, [])
        if required and not any(s in h["services"] for s in set(required)):
            continue  # Skip hospitals that don't have required specialties

        # Check real-time bed availability (require at least 1 bed or unknown data)
        status = fetch_realtime_status(h["hpid"])
        if status["hvec"] is not None and status["hvec"] < 1:  # Skip if known to have 0 beds
            continue  # But allow hospitals with unknown bed status

        # Calculate scores - prioritize capability over distance for treatable hospitals
        cap = calc_capability_score(h)
        dist_score, dist_km = calc_distance_score(
            patient["lat"], patient["lng"], h["lat"], h["lng"]
        )
        # Handle unknown bed availability
        if status["hvec"] is not None:
            sat = min(status["hvec"] / 20, 1.0)  # Normalize based on 20 beds
        else:
            sat = 0.5  # Neutral score for unknown availability
        
        # Adjust scoring: 70% capability, 20% distance, 10% availability
        score = 0.7 * cap + 0.2 * dist_score + 0.1 * sat
        results.append({**h, "score": score, "dist_km": dist_km, "status": status})

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
