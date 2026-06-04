# -*- coding: utf-8 -*-
"""
TRIAGE-1 입력 데이터 검증 모듈

모든 환자 데이터를 의료 기준에 맞게 검증합니다.
- GCS Motor: 3-15
- SBP: 0-300
- RR: 0-60
- Age: 0-150
- Lat: -90~90
- Lng: -180~180
- Injuries: 필수, 유효한 목록
- Mechanism: 유효한 기전
"""

import logging

logger = logging.getLogger(__name__)

# 유효한 값 목록
VALID_MECHANISMS = ['교통사고', '낙상', '기계부상', '화상', '기타']
VALID_INJURIES = ['두부', '흉부', '복부', '골반', '사지']


def validate_patient_input(data: dict) -> tuple:
    """
    환자 입력값 종합 검증
    
    Args:
        data: 클라이언트에서 받은 JSON 데이터
    
    Returns:
        (validated_data: dict 또는 None, errors: list)
        - 성공: (환자_데이터_dict, [])
        - 실패: (None, [오류1, 오류2, ...])
    
    오류 구조:
        {
            'field': 'gcs_motor',
            'message': 'GCS Motor must be 3-15',
            'value': -1
        }
    """
    errors = []
    validated_data = {}
    
    # ============================================================
    # 1. GCS Motor: 3-15 범위
    # ============================================================
    try:
        gcs = int(data.get('gcs_motor', 0))
        if not (3 <= gcs <= 15):
            errors.append({
                'field': 'gcs_motor',
                'message': 'GCS Motor must be 3-15',
                'value': gcs
            })
        else:
            validated_data['gcs_motor'] = gcs
    except (ValueError, TypeError):
        errors.append({
            'field': 'gcs_motor',
            'message': 'GCS Motor must be integer',
            'value': data.get('gcs_motor')
        })
    
    # ============================================================
    # 2. SBP (Systolic Blood Pressure): 0-300 범위
    # ============================================================
    try:
        sbp = int(data.get('sbp', 0))
        if not (0 <= sbp <= 300):
            errors.append({
                'field': 'sbp',
                'message': 'SBP must be 0-300 mmHg',
                'value': sbp
            })
        else:
            validated_data['sbp'] = sbp
    except (ValueError, TypeError):
        errors.append({
            'field': 'sbp',
            'message': 'SBP must be integer',
            'value': data.get('sbp')
        })
    
    # ============================================================
    # 3. RR (Respiratory Rate): 0-60 범위
    # ============================================================
    try:
        rr = int(data.get('rr', 0))
        if not (0 <= rr <= 60):
            errors.append({
                'field': 'rr',
                'message': 'RR must be 0-60 breaths/min',
                'value': rr
            })
        else:
            validated_data['rr'] = rr
    except (ValueError, TypeError):
        errors.append({
            'field': 'rr',
            'message': 'RR must be integer',
            'value': data.get('rr')
        })
    
    # ============================================================
    # 4. Age: 0-150 범위
    # ============================================================
    try:
        age_raw = data.get('age')
        if age_raw is None or age_raw == '' or age_raw == 0:
            validated_data['age'] = None
        else:
            age = int(age_raw)
            if not (0 <= age <= 150):
                errors.append({
                    'field': 'age',
                    'message': 'Age must be 0-150 years',
                    'value': age
                })
            else:
                validated_data['age'] = age
    except (ValueError, TypeError):
        errors.append({
            'field': 'age',
            'message': 'Age must be integer or empty',
            'value': data.get('age')
        })
    
    # ============================================================
    # 5. Latitude: -90 to 90
    # ============================================================
    try:
        lat = float(data.get('lat', 0))
        if not (-90 <= lat <= 90):
            errors.append({
                'field': 'lat',
                'message': 'Latitude must be -90 to 90',
                'value': lat
            })
        else:
            validated_data['lat'] = lat
    except (ValueError, TypeError):
        errors.append({
            'field': 'lat',
            'message': 'Latitude must be float',
            'value': data.get('lat')
        })
    
    # ============================================================
    # 6. Longitude: -180 to 180
    # ============================================================
    try:
        lng = float(data.get('lng', 0))
        if not (-180 <= lng <= 180):
            errors.append({
                'field': 'lng',
                'message': 'Longitude must be -180 to 180',
                'value': lng
            })
        else:
            validated_data['lng'] = lng
    except (ValueError, TypeError):
        errors.append({
            'field': 'lng',
            'message': 'Longitude must be float',
            'value': data.get('lng')
        })
    
    # ============================================================
    # 7. Mechanism: 유효한 기전
    # ============================================================
    mechanism = str(data.get('mechanism', '기타')).strip()
    if mechanism not in VALID_MECHANISMS:
        errors.append({
            'field': 'mechanism',
            'message': f'Mechanism must be one of {VALID_MECHANISMS}',
            'value': mechanism
        })
    else:
        validated_data['mechanism'] = mechanism
    
    # ============================================================
    # 8. Injuries: 필수, 유효한 값만
    # ============================================================
    injuries = data.get('injuries', [])
    
    if not injuries or len(injuries) == 0:
        errors.append({
            'field': 'injuries',
            'message': 'At least one injury must be selected',
            'value': injuries
        })
    else:
        # 유효하지 않은 부상 검사
        invalid_injuries = [i for i in injuries if i not in VALID_INJURIES]
        if invalid_injuries:
            errors.append({
                'field': 'injuries',
                'message': f'Invalid injuries: {invalid_injuries}. Valid: {VALID_INJURIES}',
                'value': injuries
            })
        else:
            validated_data['injuries'] = injuries
    
    # ============================================================
    # 결과 반환
    # ============================================================
    if errors:
        logger.warning(f"Input validation failed: {len(errors)} error(s)", extra={'errors': errors})
        return None, errors
    else:
        logger.debug("Input validation passed")
        return validated_data, []
