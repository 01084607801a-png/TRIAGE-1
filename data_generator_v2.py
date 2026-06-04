"""
TRIAGE-1 데이터 생성기 v2 — ISS 기반 3단계 등급 라벨
=====================================================
Model 1 학습용. 핵심 변경(v1 대비):
  - 라벨이 '입력 규칙의 복사본(needs_rtc≈high_risk)' → '해부학적 ISS 기반 3단계(required_tier)'
  - ISS는 라벨 산출에만 쓰고 '학습 피처에서 제외' → 순환 탈출
  - HR(맥박) 추가 → Shock Index 등 파생지표 가능
  - '잠복 중증'(ISS≥16이나 생리지표 정상) 케이스가 자연 발생 → undertriage 실험 대상

[데이터 한계 고지]
KTDB 원자료 아님(IRB 필요). 공개 통계·논문 집계치에서 보정한 합성 데이터.
분포·OR 근거: 2024/2022 외상등록체계 통계연보, Kang et al.(2022),
            최윤희 외(2022, KTDB 10,865명) 등.
"""

import numpy as np
import pandas as pd

# ── 손상 기전별 중증도 분포 (2024 통계연보 + Kang 2022) ──
MECHANISM_CONFIG = {
    "교통사고":          {"pop": 0.358, "severe_rate": 0.42, "iss_sev": (20, 8), "iss_mild": (7, 4), "high_energy": True},
    "보행자 사고":        {"pop": 0.060, "severe_rate": 0.50, "iss_sev": (22, 9), "iss_mild": (8, 4), "high_energy": True},
    "미끄러짐":          {"pop": 0.205, "severe_rate": 0.15, "iss_sev": (16, 5), "iss_mild": (5, 3), "high_energy": False},
    "추락":             {"pop": 0.210, "severe_rate": 0.48, "iss_sev": (22, 9), "iss_mild": (8, 4), "high_energy": True},
    "부딪힘":            {"pop": 0.069, "severe_rate": 0.20, "iss_sev": (17, 6), "iss_mild": (6, 3), "high_energy": False},
    "관통상":            {"pop": 0.055, "severe_rate": 0.55, "iss_sev": (24, 10), "iss_mild": (9, 5), "high_energy": False},
    "기타":             {"pop": 0.043, "severe_rate": 0.25, "iss_sev": (16, 6), "iss_mild": (6, 3), "high_energy": False},
}

# ── 손상 부위별 출현율 (전체율, 중증율) — 2024 통계연보 ──
INJURY_REGION_RATES = {
    "head_neck":   (0.379, 0.683),   # 두부/경부 — 중증서 압도적
    "thorax":      (0.339, 0.610),   # 흉부 — 중증서 압도적
    "abdomen":     (0.215, 0.350),   # 복부/골반장기
    "extremity":   (0.477, 0.450),   # 사지/골반골격
    "spine":       (0.120, 0.230),   # 척추
}

AGE_DIST = {
    "overall": (0.043, 0.539, 0.419),   # 소아/성인/고령
    "severe":  (0.024, 0.575, 0.401),
}


def _sample_age(is_severe):
    p = np.array(AGE_DIST["severe"] if is_severe else AGE_DIST["overall"], dtype=float)
    p = p / p.sum()   # 부동소수점 정규화
    g = np.random.choice(["ped", "adult", "eld"], p=p)
    if g == "ped":
        return int(np.clip(np.random.uniform(1, 15), 1, 14))
    if g == "adult":
        return int(np.clip(np.random.normal(42, 13), 15, 64))
    return int(np.clip(np.random.normal(74, 7), 65, 100))


def generate(n=5000, seed=42):
    np.random.seed(seed)
    mechs = list(MECHANISM_CONFIG.keys())
    probs = np.array([MECHANISM_CONFIG[m]["pop"] for m in mechs])
    probs = probs / probs.sum()

    rows = []
    for _ in range(n):
        mech = np.random.choice(mechs, p=probs)
        cfg = MECHANISM_CONFIG[mech]
        is_severe = np.random.random() < cfg["severe_rate"]

        # ── ISS (해부학적 중증도 — 숨은 변수, 피처 아님) ──
        if is_severe:
            m, s = cfg["iss_sev"]
            iss = int(np.clip(np.random.normal(m, s), 16, 75))
        else:
            m, s = cfg["iss_mild"]
            iss = int(np.clip(np.random.normal(m, s), 1, 15))

        # ── 활력징후 ──
        # 중증 중 ~30%는 '잠복 중증(occult)': 생리지표 정상이라 CDC 규칙이 놓침
        #   근거: 생리기준 민감도 ~72% (Kang 2022) → 약 28% occult
        #   단, 보상성 쇼크로 HR만 상승(SBP 정상) → Shock Index로만 포착 가능
        occult = False
        if is_severe:
            occult = np.random.random() < 0.30
            if occult:
                # 겉보기 안정: GCS 정상, SBP 정상, RR 정상 — 그러나 보상성 빈맥
                gcs = 6
                sbp = int(np.clip(np.random.normal(125, 12), 95, 175))
                rr = int(np.clip(np.random.normal(19, 3), 12, 28))
                hr = int(np.clip(np.random.normal(108, 16), 80, 160))   # SI↑ 신호
            else:
                # 명백한 생리 이상 (규칙이 잡음)
                gcs = int(np.random.choice([1, 2, 3, 4, 5], p=[0.14, 0.17, 0.25, 0.27, 0.17]))
                sbp = int(np.clip(np.random.normal(82, 16), 50, 130))
                rr = int(np.clip(np.random.normal(24, 7), 6, 44))
                hr = int(np.clip(np.random.normal(118, 22), 55, 185))
        else:
            gcs = int(np.random.choice([5, 6], p=[0.2, 0.8]))
            sbp = int(np.clip(np.random.normal(124, 16), 85, 185))
            rr = int(np.clip(np.random.normal(17, 4), 10, 30))
            hr = int(np.clip(np.random.normal(86, 14), 55, 140))

        age = int(np.clip(_sample_age(is_severe), 1, 100))

        # ── 손상 부위 (중증일수록 두경부·흉부 ↑) ──
        regions = {}
        for r, (overall, severe) in INJURY_REGION_RATES.items():
            rate = severe if is_severe else overall
            regions[r] = int(np.random.random() < rate)
        if sum(regions.values()) == 0:
            regions["extremity"] = 1   # 최소 1부위 보장

        # ── 해부학적 핵심 기준 (관통 몸통 등 — 현장서 관찰 가능) ──
        penetrating_torso = int(mech == "관통상" and (regions["thorax"] or regions["abdomen"]))

        # ── 필요 등급 라벨 (Tier 1/2/3) ──
        sbp_cut = 110 if age >= 65 else 90
        cdc_red = (gcs < 6) or (sbp < sbp_cut) or (rr < 10) or (rr > 29) or bool(penetrating_torso)
        if (iss >= 16) or cdc_red:
            tier = 1
        elif (9 <= iss <= 15) or cfg["high_energy"]:
            tier = 2
        else:
            tier = 3

        rows.append({
            "mechanism": mech,
            "age": age, "gcs_motor": gcs, "sbp": sbp, "rr": rr, "hr": hr,
            **regions,
            "penetrating_torso": penetrating_torso,
            "estimated_iss": iss,          # 라벨 산출용 — 학습 피처 아님
            "is_severe_iss16": int(iss >= 16),
            "occult_severe": int(is_severe and occult),
            "cdc_red": int(cdc_red),       # 규칙 baseline 비교용
            "required_tier": tier,         # ← 라벨
        })

    return pd.DataFrame(rows)


def report(df):
    print("=" * 60)
    print(f"생성 {len(df)}건")
    print("=" * 60)
    print("\n[Tier 분포]")
    for t, c in df["required_tier"].value_counts().sort_index().items():
        name = {1: "권역외상센터", 2: "권역/지역응급", 3: "지역응급기관"}[t]
        print(f"  Tier {t} ({name}): {c}건 ({c/len(df):.1%})")

    print(f"\n[중증(ISS≥16) 비율]: {df['is_severe_iss16'].mean():.1%} (통계연보 ~31%)")

    # ── 핵심: 잠복 중증 (ISS≥16인데 CDC 생리규칙엔 안 걸림) = undertriage 대상 ──
    severe = df[df["is_severe_iss16"] == 1]
    occult = severe[severe["cdc_red"] == 0]
    print(f"\n[★ 잠복 중증 케이스] ISS≥16 총 {len(severe)}건 중")
    print(f"  CDC 생리규칙이 놓치는(occult) 케이스: {len(occult)}건 ({len(occult)/len(severe):.1%})")
    print(f"  → 규칙만으로는 이들을 undertriage. ML이 손상부위·기전·나이로 잡아내야 함")

    # 규칙 baseline의 Tier1 민감도
    tier1 = df[df["required_tier"] == 1]
    rule_catch = tier1["cdc_red"].mean()
    print(f"\n[규칙 baseline] Tier1 {len(tier1)}건 중 CDC 규칙이 잡는 비율(민감도): {rule_catch:.1%}")
    print(f"  → 나머지 {1-rule_catch:.1%}가 ML이 보완해야 할 몫")


if __name__ == "__main__":
    df = generate(n=5000, seed=42)
    df.to_csv("data/trauma_tier_v2.csv", index=False, encoding="utf-8-sig")
    print("저장: data/trauma_tier_v2.csv\n")
    report(df)
