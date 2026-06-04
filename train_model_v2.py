"""
TRIAGE-1 Model 1 학습 v2 — 필요 병원 등급 예측기
====================================================
1) 특징공학 (Shock Index, rSIG 등 임상 파생지표)
2) 지도학습: 3단계 등급(required_tier) 분류 + 확률 보정
3) ★ undertriage 실험: 규칙(CDC) baseline 대비 ML이 잠복 중증을 얼마나 더 잡나
4) 비지도: 위험 표현형 군집
출력: models/tier_model.pkl, models/*.png
"""
import os, json, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")

from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.model_selection import train_test_split, StratifiedKFold, cross_val_score
from sklearn.calibration import CalibratedClassifierCV
from sklearn.cluster import KMeans
from sklearn.metrics import (classification_report, confusion_matrix,
                             recall_score, f1_score, roc_auc_score)
try:
    from xgboost import XGBClassifier
    HAS_XGB = True
except ImportError:
    HAS_XGB = False

import joblib
DATA = "data/trauma_tier_v2.csv"
MODELS = "models"

# 학습 피처 (현장 관찰 가능 + 파생). ISS/severe/cdc_red/tier/occult 은 절대 제외(누설 방지)
RAW_FEATURES = ["age", "gcs_motor", "sbp", "rr", "hr",
                "head_neck", "thorax", "abdomen", "extremity", "spine",
                "penetrating_torso", "mechanism_enc"]
DERIVED = ["shock_index", "rsig", "n_regions"]
FEATURES = RAW_FEATURES + DERIVED


def engineer(df):
    """임상 파생지표 — 규칙이 못 보는 상호작용을 모델에 제공"""
    df = df.copy()
    df["shock_index"] = df["hr"] / df["sbp"].clip(lower=1)          # >0.9 → 쇼크 의심(SBP 정상이어도)
    df["rsig"] = (df["sbp"] / df["hr"].clip(lower=1)) * df["gcs_motor"]  # reverse SI × GCS
    df["n_regions"] = df[["head_neck", "thorax", "abdomen", "extremity", "spine"]].sum(axis=1)
    return df


def cdc_rule_tier(row):
    """규칙 baseline: CDC 생리기준만으로 등급 추정 (현장 구급대원 방식)"""
    sbp_cut = 110 if row["age"] >= 65 else 90
    red = (row["gcs_motor"] < 6) or (row["sbp"] < sbp_cut) or (row["rr"] < 10) or (row["rr"] > 29) or (row["penetrating_torso"] == 1)
    if red:
        return 1
    if row["mechanism"] in ("교통사고", "추락", "보행자 사고"):
        return 2
    return 3


def main():
    os.makedirs(MODELS, exist_ok=True)
    df = pd.read_csv(DATA)
    print(f"[데이터] {len(df)}건 로드")

    le = LabelEncoder()
    df["mechanism_enc"] = le.fit_transform(df["mechanism"])
    df = engineer(df)

    X = df[FEATURES]
    y = df["required_tier"]

    Xtr, Xte, ytr, yte, idx_tr, idx_te = train_test_split(
        X, y, df.index, test_size=0.2, random_state=42, stratify=y)
    print(f"[분할] Train {len(Xtr)} / Test {len(Xte)}")

    # ── 지도학습: RandomForest (+ XGBoost 비교) ──
    rf = RandomForestClassifier(n_estimators=300, max_depth=10, min_samples_leaf=4,
                                class_weight="balanced", random_state=42, n_jobs=-1)
    cv = StratifiedKFold(5, shuffle=True, random_state=42)
    cv_f1 = cross_val_score(rf, Xtr, ytr, cv=cv, scoring="f1_macro", n_jobs=-1)
    print(f"[CV] RandomForest macro-F1: {cv_f1.mean():.3f} ± {cv_f1.std():.3f}")

    rf.fit(Xtr, ytr)
    best, best_name = rf, "RandomForest"
    if HAS_XGB:
        xgb = XGBClassifier(n_estimators=300, max_depth=5, learning_rate=0.05,
                            random_state=42, eval_metric="mlogloss", n_jobs=-1)
        xgb.fit(Xtr, ytr - 1)  # xgb는 0-base
        f1_rf = f1_score(yte, rf.predict(Xte), average="macro")
        f1_xgb = f1_score(yte, xgb.predict(Xte) + 1, average="macro")
        print(f"[Test macro-F1] RF {f1_rf:.3f} | XGB {f1_xgb:.3f}")
        if f1_xgb > f1_rf:
            best, best_name = xgb, "XGBoost"

    # 확률 보정 (의미있는 위험확률)
    calib = CalibratedClassifierCV(rf, method="isotonic", cv=5)
    calib.fit(Xtr, ytr)

    # ── 3단계 성능 ──
    yp = rf.predict(Xte)
    print(f"\n[선정 모델] {best_name}")
    print("\n[3단계 분류 성능 — Test]")
    print(classification_report(yte, yp, target_names=["Tier1 권역외상", "Tier2 권역/지역", "Tier3 지역"]))

    # ── ★ undertriage 핵심 실험 ──
    test = df.loc[idx_te].copy()
    test["ml_tier"] = yp
    test["rule_tier"] = test.apply(cdc_rule_tier, axis=1)

    # 진짜 major trauma(ISS≥16) 기준, "Tier1로 보냈는가"(민감도)
    major = test[test["is_severe_iss16"] == 1]
    rule_sens = (major["rule_tier"] == 1).mean()
    ml_sens = (major["ml_tier"] == 1).mean()

    # 잠복 중증(규칙이 구조적으로 못 잡는 케이스)에서의 회수율
    occult = major[major["cdc_red"] == 0]
    rule_occult = (occult["rule_tier"] == 1).mean()
    ml_occult = (occult["ml_tier"] == 1).mean()

    print("=" * 60)
    print("★ undertriage 실험 — 중증 외상(ISS≥16)을 Tier1로 보낸 비율(민감도)")
    print("=" * 60)
    print(f"  규칙(CDC) baseline : {rule_sens:.1%}")
    print(f"  ML (Model 1)       : {ml_sens:.1%}   (Δ +{(ml_sens-rule_sens)*100:.1f}%p)")
    print(f"\n  [잠복 중증 {len(occult)}건 — 규칙이 구조적으로 못 잡는 케이스]")
    print(f"    규칙 회수율: {rule_occult:.1%}")
    print(f"    ML  회수율: {ml_occult:.1%}   ← ML이 새로 잡아낸 몫")
    print("=" * 60)

    # ── 비지도: 위험 표현형 군집 ──
    scaler = StandardScaler()
    Xs = scaler.fit_transform(df[FEATURES])
    km = KMeans(n_clusters=4, random_state=42, n_init=10)
    df["cluster"] = km.fit_predict(Xs)
    print("\n[비지도 군집 — 표현형별 중증/잠복중증 비율]")
    for c in sorted(df["cluster"].unique()):
        g = df[df["cluster"] == c]
        print(f"  C{c}: n={len(g):4d} | ISS≥16 {g['is_severe_iss16'].mean():5.1%} | "
              f"잠복중증 {g['occult_severe'].mean():5.1%} | "
              f"평균SI {g['shock_index'].mean():.2f} | 평균나이 {g['age'].mean():.0f}")

    # ── 저장 ──
    bundle = {
        "model": rf, "calibrated": calib, "label_encoder": le, "scaler": scaler,
        "kmeans": km, "features": FEATURES, "derived": DERIVED,
        "classes": [1, 2, 3],
        "metrics": {
            "cv_f1_macro": float(cv_f1.mean()),
            "rule_sensitivity": float(rule_sens),
            "ml_sensitivity": float(ml_sens),
            "occult_n": int(len(occult)),
            "ml_occult_recovery": float(ml_occult),
        },
    }
    joblib.dump(bundle, os.path.join(MODELS, "tier_model.pkl"))
    print(f"\n[저장] {MODELS}/tier_model.pkl")
    with open(os.path.join(MODELS, "tier_metrics.json"), "w", encoding="utf-8") as f:
        json.dump(bundle["metrics"], f, ensure_ascii=False, indent=2)

    # ── 그래프 (실패해도 무시) ──
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        # 1) 특징 중요도
        imp = rf.feature_importances_
        order = np.argsort(imp)
        plt.figure(figsize=(8, 5))
        plt.barh([FEATURES[i] for i in order], imp[order], color="#16a34a")
        plt.title("Model 1 - Feature Importance (RandomForest)")
        plt.tight_layout(); plt.savefig(f"{MODELS}/tier_feature_importance.png", dpi=140); plt.close()
        # 2) undertriage 비교
        plt.figure(figsize=(6, 5))
        plt.bar(["Rule (CDC)", "ML (Model 1)"], [rule_sens*100, ml_sens*100], color=["#94a3a0", "#16a34a"])
        plt.ylabel("중증외상 Tier1 민감도 (%)"); plt.ylim(0, 100)
        plt.title("Undertriage 감소: 규칙 vs ML")
        for i, v in enumerate([rule_sens*100, ml_sens*100]):
            plt.text(i, v+1.5, f"{v:.1f}%", ha="center", fontweight="bold")
        plt.tight_layout(); plt.savefig(f"{MODELS}/tier_undertriage.png", dpi=140); plt.close()
        print(f"[그래프] {MODELS}/tier_feature_importance.png, tier_undertriage.png")
    except Exception as e:
        print(f"[그래프 생략] {e}")


if __name__ == "__main__":
    main()
