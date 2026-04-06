"""
TRIAGE-1 합성 데이터 생성기 v1.1
==============================
KTDB 원자료 대체용 — 향후 KTDB 연동 시 이 모듈 전체 교체 예정

근거 문헌:
  - Kang et al. (2022). BMC Emergency Medicine.
    "Accuracy and influencing factors of the Field Triage Decision Scheme
     for adult trauma patients at a level-1 trauma center in Korea"
  - 2024 외상등록체계(KTDB) 통계연보. 중앙응급의료센터.
  - 2022 외상등록체계(KTDB) 통계연보. 중앙응급의료센터.

[데이터 한계 고지]
본 데이터는 KTDB 원자료가 아님.
공개된 논문 통계치 및 집계 통계에서 역산한 합성 데이터임.
IRB 승인 및 기관 신청이 필요한 KTDB 원자료는 향후 연구 단계에서 확보 예정.
"""

import numpy as np
import pandas as pd


# ============================================================
# 손상 기전별 중증도 분포
# 근거: 2024 외상등록체계 통계연보 (전체 외상환자 26,840건)
#       중증 외상환자(ISS>15) 기준 별도 비율 적용
# 근거: Kang et al. (2022) Table 1 — ISS 평균 13.3±11.3, 중증 35.0%
# 근거: 2022 외상등록체계 통계연보 — 둔상 91.8%, 관통상 6.6%
# ============================================================
MECHANISM_CONFIG = {
    "교통사고": {
        # 2024 통계연보: 전체 35.8%, 중증 46.2%
        "population_rate":      0.358,
        "severe_population_rate": 0.462,
        "severe_rate":          0.42,   # 중증 비율 (교통사고는 중증 비율 높음)
        "iss_mean_severe":      20.0,
        "iss_std_severe":       8.0,
        "iss_mean_mild":        7.0,
        "iss_std_mild":         4.0,
    },
    "미끄러짐": {
        # 2024 통계연보: 전체 22.5% (경증 위주)
        "population_rate":      0.225,
        "severe_population_rate": 0.08,
        "severe_rate":          0.15,
        "iss_mean_severe":      16.0,
        "iss_std_severe":       5.0,
        "iss_mean_mild":        5.0,
        "iss_std_mild":         3.0,
    },
    "추락": {
        # 2024 통계연보: 전체 21.0%, 중증 29.7%
        "population_rate":      0.210,
        "severe_population_rate": 0.297,
        "severe_rate":          0.48,   # 추락은 중증 비율 높음
        "iss_mean_severe":      22.0,
        "iss_std_severe":       9.0,
        "iss_mean_mild":        8.0,
        "iss_std_mild":         4.0,
    },
    "부딪힘": {
        # 2024 통계연보: 6.9%
        "population_rate":      0.069,
        "severe_population_rate": 0.03,
        "severe_rate":          0.20,
        "iss_mean_severe":      17.0,
        "iss_std_severe":       6.0,
        "iss_mean_mild":        6.0,
        "iss_std_mild":         3.0,
    },
    "베임/찔림(관통상)": {
        # 2024 통계연보: 5.5% / 2022 통계연보: 관통상 6.6%
        # Kang 2022: 관통 몸통 손상 → 수술 OR 7.108
        "population_rate":      0.055,
        "severe_population_rate": 0.06,
        "severe_rate":          0.55,   # 관통상은 중증 비율 매우 높음
        "iss_mean_severe":      24.0,
        "iss_std_severe":       10.0,
        "iss_mean_mild":        9.0,
        "iss_std_mild":         5.0,
    },
    "기타": {
        "population_rate":      0.083,
        "severe_population_rate": 0.047,
        "severe_rate":          0.25,
        "iss_mean_severe":      16.0,
        "iss_std_severe":       6.0,
        "iss_mean_mild":        6.0,
        "iss_std_mild":         3.0,
    },
}

# ============================================================
# 손상 부위별 분포
# 근거: 2024 외상등록체계 통계연보 (전체 vs 중증 비교)
# 한 환자가 여러 부위 손상 가능 (중복 집계)
# ============================================================
INJURY_REGION_RATES = {
    # (전체 비율, 중증(ISS>15) 비율)
    "사지/골반골격": (0.477, 0.45),
    "체표면/기타":  (0.459, 0.30),
    "두부/경부":    (0.379, 0.683),  # 중증에서 압도적으로 높음
    "흉부":        (0.339, 0.610),  # 중증에서 압도적으로 높음
    "복부/골반장기": (0.215, 0.35),
    "안면":        (0.150, 0.10),
}

# ============================================================
# 24시간 사망 연관 인자 OR값
# 근거: Kang et al. (2022) Table 4
# ============================================================
MORTALITY_OR = {
    "altered_mental_status": 17.924,   # GCS Motor < 6
    "sbp_lt_90":              3.535,   # SBP < 90mmHg
    "pedestrian":             2.473,   # 보행자 사고
}

# ============================================================
# 24시간 수술 필요 연관 인자 OR값
# 근거: Kang et al. (2022) Table 5
# ============================================================
SURGERY_OR = {
    "penetrating_torso":       7.108,   # 관통 몸통 손상
    "proximal_long_bone_fx":   4.134,   # 근위부 장골 2개 이상 골절
    "crushed_extremity":       8.477,   # 압궤/박피/절단
    "amputation":             42.964,   # 근위부 절단
    "fall_from_height":        2.141,   # 추락
}

# ============================================================
# 연령 분포
# 근거: 2024 외상등록체계 통계연보
#   전체: 15세 미만 4.3%, 15~64세 53.9%, 65세 이상 41.9%
#   중증: 15세 미만 2.4%, 15~64세 57.5%, 65세 이상 40.1%
# ============================================================
AGE_DISTRIBUTION = {
    "overall": {
        "pediatric_rate": 0.043,   # 15세 미만
        "adult_rate":     0.539,   # 15~64세
        "elderly_rate":   0.419,   # 65세 이상
    },
    "severe": {
        "pediatric_rate": 0.024,
        "adult_rate":     0.575,
        "elderly_rate":   0.401,
    }
}


def sample_age(is_severe: bool) -> int:
    """연령 샘플링 — 2024 외상등록체계 통계연보 기반"""
    dist = AGE_DISTRIBUTION["severe"] if is_severe else AGE_DISTRIBUTION["overall"]
    group = np.random.choice(
        ["pediatric", "adult", "elderly"],
        p=[dist["pediatric_rate"], dist["adult_rate"], dist["elderly_rate"]]
    )
    if group == "pediatric":
        return int(np.random.uniform(1, 15))
    elif group == "adult":
        return int(np.random.normal(42, 13))
    else:
        return int(np.random.normal(74, 7))


def sample_injury_regions(is_severe: bool) -> list:
    """
    손상 부위 샘플링
    근거: 2024 외상등록체계 통계연보
    중증일수록 두경부·흉부 비율 높음
    """
    regions = []
    for region, (overall_rate, severe_rate) in INJURY_REGION_RATES.items():
        rate = severe_rate if is_severe else overall_rate
        if np.random.random() < rate:
            regions.append(region)

    # 최소 1개 손상 부위 보장
    if not regions:
        regions = ["체표면/기타"]

    return regions


def generate_synthetic_patient(n: int = 1000, seed: int = 42) -> pd.DataFrame:
    """
    합성 외상 환자 데이터 생성

    Parameters:
        n: 생성할 환자 수
        seed: 재현성을 위한 난수 시드

    Returns:
        DataFrame with columns:
            mechanism, gcs_motor, sbp, rr, age, injuries,
            is_severe_iss_gt15, estimated_iss,
            needs_surgery_24h (OR 기반 확률적 판단)

    [한계]
    - KTDB 원자료 아님. 공개 통계에서 역산한 합성 데이터.
    - 기전별 중증 비율은 Kang 2022(수원 단일기관) + 2024 통계연보 혼합.
    - 향후 KTDB 원자료 확보 시 전면 교체 필요.
    """
    np.random.seed(seed)

    mechanisms = list(MECHANISM_CONFIG.keys())
    mechanism_probs = [MECHANISM_CONFIG[m]["population_rate"] for m in mechanisms]
    # 합이 1이 되도록 정규화
    total = sum(mechanism_probs)
    mechanism_probs = [p / total for p in mechanism_probs]

    patients = []

    for _ in range(n):
        # 손상 기전 샘플링
        mechanism = np.random.choice(mechanisms, p=mechanism_probs)
        cfg = MECHANISM_CONFIG[mechanism]

        # 중증 여부
        is_severe = np.random.random() < cfg["severe_rate"]

        # ISS 추정
        if is_severe:
            estimated_iss = int(np.clip(
                np.random.normal(cfg["iss_mean_severe"], cfg["iss_std_severe"]), 16, 75
            ))
            gcs_motor = int(np.random.choice([1, 2, 3, 4, 5, 6],
                                              p=[0.10, 0.12, 0.18, 0.25, 0.20, 0.15]))
            sbp = int(np.clip(np.random.normal(88, 18), 50, 180))
            rr = int(np.clip(np.random.normal(22, 6), 6, 40))
        else:
            estimated_iss = int(np.clip(
                np.random.normal(cfg["iss_mean_mild"], cfg["iss_std_mild"]), 1, 15
            ))
            gcs_motor = int(np.random.choice([5, 6], p=[0.25, 0.75]))
            sbp = int(np.clip(np.random.normal(122, 18), 80, 180))
            rr = int(np.clip(np.random.normal(17, 4), 10, 30))

        # 연령
        age = int(np.clip(sample_age(is_severe), 1, 100))

        # 65세 이상 SBP 기준 조정 (CDC 2021)
        sbp_cutoff = 110 if age >= 65 else 90

        # 손상 부위
        injuries = sample_injury_regions(is_severe)

        # 24시간 수술 필요 여부 (OR 기반 확률적 판단)
        surgery_prob = 0.1  # baseline
        if mechanism in ["베임/찔림(관통상)"]:
            surgery_prob *= SURGERY_OR["penetrating_torso"] / 5
        if mechanism in ["추락"]:
            surgery_prob *= SURGERY_OR["fall_from_height"] / 2
        if is_severe:
            surgery_prob = min(surgery_prob * 3, 0.85)
        needs_surgery_24h = np.random.random() < surgery_prob

        patients.append({
            "mechanism":          mechanism,
            "gcs_motor":          gcs_motor,
            "sbp":                sbp,
            "rr":                 rr,
            "age":                age,
            "injuries":           "|".join(injuries),
            "is_severe_iss_gt15": is_severe,
            "estimated_iss":      estimated_iss,
            "needs_surgery_24h":  needs_surgery_24h,
            "sbp_cutoff_applied": sbp_cutoff,
            "high_risk_flag":     (gcs_motor < 6) or (sbp < sbp_cutoff) or (rr < 10) or (rr > 29),
        })

    return pd.DataFrame(patients)


def validate_output(df: pd.DataFrame):
    """생성된 데이터 통계 검증 — 통계연보 기준치와 비교"""
    print("\n" + "="*60)
    print("합성 데이터 검증 리포트")
    print("="*60)

    severe_rate = df["is_severe_iss_gt15"].mean()
    print(f"\n[중증(ISS>15) 비율]")
    print(f"  생성값: {severe_rate:.1%}")
    print(f"  통계연보 기준: ~31.0% (8,332/26,840)")

    print(f"\n[손상 기전 분포]")
    for mech, count in df["mechanism"].value_counts().items():
        pct = count / len(df)
        expected = MECHANISM_CONFIG[mech]["population_rate"]
        print(f"  {mech}: {pct:.1%} (통계연보 기준: {expected:.1%})")

    severe_df = df[df["is_severe_iss_gt15"]]
    print(f"\n[중증 환자 두경부 손상 비율]")
    head_rate = severe_df["injuries"].str.contains("두부/경부").mean()
    print(f"  생성값: {head_rate:.1%}")
    print(f"  통계연보 기준: 68.3%")

    print(f"\n[중증 환자 흉부 손상 비율]")
    chest_rate = severe_df["injuries"].str.contains("흉부").mean()
    print(f"  생성값: {chest_rate:.1%}")
    print(f"  통계연보 기준: 61.0%")

    print(f"\n[전체 사망률 근사 — 고위험 플래그]")
    high_risk_rate = df["high_risk_flag"].mean()
    print(f"  고위험 판정률: {high_risk_rate:.1%}")

    print("\n" + "="*60)
    print("[데이터 한계 고지]")
    print("본 데이터는 KTDB 원자료가 아닙니다.")
    print("Kang et al. (2022) 및 외상등록체계 통계연보 집계값에서")
    print("역산한 합성 데이터입니다.")
    print("향후 KTDB 원자료 확보 시 이 모듈 전체를 교체할 예정입니다.")
    print("="*60 + "\n")


if __name__ == "__main__":
    print("TRIAGE-1 합성 데이터 생성 시작...")
    df = generate_synthetic_patient(n=2000, seed=42)
    df.to_csv("synthetic_trauma_data.csv", index=False, encoding="utf-8-sig")
    print(f"생성 완료: {len(df)}건 → synthetic_trauma_data.csv")
    validate_output(df)