"""
TRIAGE-1 모델 학습 (v4.0)
입력: data/synthetic_trauma_data.csv
출력: models/triage_classifier.pkl
      models/feature_importance.png
      models/learning_curve.png
      models/confusion_matrix.png
      models/roc_curve.png
      models/xgb_eval_curve.png
      models/sensitivity_analysis.csv
"""

import os
import pickle
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    ConfusionMatrixDisplay,
    RocCurveDisplay,
    accuracy_score,
    classification_report,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import (
    StratifiedKFold,
    cross_validate,
    learning_curve,
    train_test_split,
)
from sklearn.preprocessing import LabelEncoder

try:
    from xgboost import XGBClassifier
except ImportError:
    print("[오류] xgboost 패키지가 설치되어 있지 않습니다.")
    print("       먼저 다음 명령을 실행하세요: pip install xgboost")
    sys.exit(1)


DATA_CANDIDATE_PATHS = [
    'data/synthetic_trauma_data.csv',
    'data/data',
]
MODELS_DIR = 'models'

FEATURES = [
    'age', 'mechanism_enc', 'gcs_motor', 'sbp', 'rr',
    'head_neck', 'thorax', 'abdomen', 'extremity', 'spine',
]
FEATURE_LABELS_KO = [
    '나이', '손상 기전', 'GCS Motor', 'SBP', '호흡수',
    '두경부 손상', '흉부 손상', '복부 손상', '사지 손상', '척추 손상',
]


def configure_korean_font():
    # 기존 한글 폰트 설정 유지
    font_paths = [
        '/usr/share/fonts/truetype/nanum/NanumGothic.ttf',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    ]
    font_set = False
    for fp in font_paths:
        if os.path.exists(fp):
            fm.fontManager.addfont(fp)
            plt.rcParams['font.family'] = fm.FontProperties(fname=fp).get_name()
            font_set = True
            break
    if not font_set:
        plt.rcParams['font.family'] = 'DejaVu Sans'

    plt.rcParams['axes.unicode_minus'] = False


def build_models():
    return {
        'Logistic Regression': LogisticRegression(
            max_iter=1000,
            class_weight='balanced',
            random_state=42,
        ),
        'Random Forest': RandomForestClassifier(
            n_estimators=200,
            max_depth=8,
            min_samples_leaf=5,
            class_weight='balanced',
            random_state=42,
            n_jobs=-1,
        ),
        'XGBoost': XGBClassifier(
            n_estimators=200,
            max_depth=6,
            learning_rate=0.05,
            scale_pos_weight=1,
            random_state=42,
            eval_metric='logloss',
        ),
    }


def print_cv_results(cv_results):
    print()
    print('=' * 72)
    print('[모델 비교] 10-Fold Stratified Cross Validation 결과 (mean +/- std)')
    print('=' * 72)
    for model_name, metrics in cv_results.items():
        print(f'[{model_name}]')
        print(f"  Accuracy : {metrics['accuracy_mean']:.4f} +/- {metrics['accuracy_std']:.4f}")
        print(f"  Precision: {metrics['precision_mean']:.4f} +/- {metrics['precision_std']:.4f}")
        print(f"  Recall   : {metrics['recall_mean']:.4f} +/- {metrics['recall_std']:.4f}")
        print(f"  F1       : {metrics['f1_mean']:.4f} +/- {metrics['f1_std']:.4f}")
        print(f"  AUC-ROC  : {metrics['roc_auc_mean']:.4f} +/- {metrics['roc_auc_std']:.4f}")
        print('-' * 72)


def compute_metrics(y_true, y_pred, y_prob):
    return {
        'accuracy': accuracy_score(y_true, y_pred),
        'precision': precision_score(y_true, y_pred, zero_division=0),
        'recall': recall_score(y_true, y_pred, zero_division=0),
        'f1': f1_score(y_true, y_pred, zero_division=0),
        'auc': roc_auc_score(y_true, y_prob),
    }


def plot_feature_importance(rf_model, test_metrics):
    importances = rf_model.feature_importances_
    sorted_idx = np.argsort(importances)[::-1]

    fig, ax = plt.subplots(figsize=(10, 6))
    colors = ['#E74C3C' if importances[i] > 0.10 else '#3498DB' for i in sorted_idx]

    bars = ax.barh(
        [FEATURE_LABELS_KO[i] for i in sorted_idx[::-1]],
        importances[sorted_idx[::-1]],
        color=colors[::-1],
        edgecolor='white',
        height=0.6,
    )

    ax.set_xlabel('Feature Importance', fontsize=12)
    ax.set_title(
        'TRIAGE-1 - Feature Importance (Random Forest)\n'
        f"Test Acc {test_metrics['accuracy']*100:.1f}% | "
        f"F1 {test_metrics['f1']:.3f} | AUC {test_metrics['auc']:.3f}",
        fontsize=13,
        fontweight='bold',
    )

    for bar, imp in zip(bars, importances[sorted_idx[::-1]]):
        ax.text(imp + 0.002, bar.get_y() + bar.get_height() / 2, f'{imp:.3f}', va='center', fontsize=10)

    ax.set_xlim(0, max(importances) * 1.25)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    plt.tight_layout()

    path = os.path.join(MODELS_DIR, 'feature_importance.png')
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f'[그래프] {path} 저장 완료')


def plot_learning_curve(X_train, y_train):
    train_sizes, train_scores, val_scores = learning_curve(
        RandomForestClassifier(
            n_estimators=200,
            max_depth=8,
            min_samples_leaf=5,
            class_weight='balanced',
            random_state=42,
            n_jobs=-1,
        ),
        X_train,
        y_train,
        train_sizes=np.linspace(0.1, 1.0, 10),
        cv=5,
        scoring='f1',
        n_jobs=-1,
    )

    train_mean = train_scores.mean(axis=1)
    train_std = train_scores.std(axis=1)
    val_mean = val_scores.mean(axis=1)
    val_std = val_scores.std(axis=1)

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(train_sizes, train_mean, marker='o', label='Train F1', color='#1f77b4')
    ax.plot(train_sizes, val_mean, marker='s', label='Validation F1', color='#ff7f0e')
    ax.fill_between(train_sizes, train_mean - train_std, train_mean + train_std, color='#1f77b4', alpha=0.15)
    ax.fill_between(train_sizes, val_mean - val_std, val_mean + val_std, color='#ff7f0e', alpha=0.15)

    ax.set_title('TRIAGE-1 Learning Curve (Random Forest) - F1 Score by Training Size')
    ax.set_xlabel('Training Sample Size')
    ax.set_ylabel('F1 Score')
    ax.grid(alpha=0.3)
    ax.legend()
    plt.tight_layout()

    path = os.path.join(MODELS_DIR, 'learning_curve.png')
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f'[그래프] {path} 저장 완료')


def plot_confusion_matrices(trained_models, X_test, y_test):
    fig, axes = plt.subplots(1, 3, figsize=(15, 4))
    for ax, (name, model) in zip(axes, trained_models.items()):
        ConfusionMatrixDisplay.from_predictions(
            y_test,
            model.predict(X_test),
            display_labels=['불필요', '필요'],
            ax=ax,
            colorbar=False,
            cmap='Blues',
        )
        ax.set_title(name)

    plt.tight_layout()
    path = os.path.join(MODELS_DIR, 'confusion_matrix.png')
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f'[그래프] {path} 저장 완료')


def plot_roc_curve(trained_models, X_test, y_test):
    fig, ax = plt.subplots(figsize=(8, 6))
    for name, model in trained_models.items():
        RocCurveDisplay.from_predictions(
            y_test,
            model.predict_proba(X_test)[:, 1],
            name=name,
            ax=ax,
        )

    ax.set_title('TRIAGE-1 - ROC Curve Comparison')
    ax.grid(alpha=0.3)
    plt.tight_layout()
    path = os.path.join(MODELS_DIR, 'roc_curve.png')
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f'[그래프] {path} 저장 완료')


def plot_xgb_eval_curve(X_train, y_train, X_val, y_val):
    xgb_model = XGBClassifier(
        n_estimators=200,
        max_depth=6,
        learning_rate=0.05,
        scale_pos_weight=1,
        random_state=42,
        eval_metric='logloss',
    )

    xgb_model.fit(
        X_train,
        y_train,
        eval_set=[(X_train, y_train), (X_val, y_val)],
        verbose=False,
    )

    results = xgb_model.evals_result()
    train_loss = results['validation_0']['logloss']
    val_loss = results['validation_1']['logloss']

    fig, ax = plt.subplots(figsize=(8, 6))
    rounds = np.arange(1, len(train_loss) + 1)
    ax.plot(rounds, train_loss, label='Train Log Loss', color='#1f77b4')
    ax.plot(rounds, val_loss, label='Validation Log Loss', color='#d62728')
    ax.set_xlabel('Round')
    ax.set_ylabel('Log Loss')
    ax.set_title('XGBoost Training vs Validation Loss (Log Loss by Round)')
    ax.grid(alpha=0.3)
    ax.legend()
    plt.tight_layout()

    path = os.path.join(MODELS_DIR, 'xgb_eval_curve.png')
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f'[그래프] {path} 저장 완료')


def run_sensitivity_analysis():
    weight_scenarios = [
        {'name': '현재 (역량 우선)', 'cap': 0.70, 'dist': 0.15, 'bed': 0.10, 'sat': 0.05},
        {'name': '거리 우선', 'cap': 0.40, 'dist': 0.45, 'bed': 0.10, 'sat': 0.05},
        {'name': '균등 배분', 'cap': 0.25, 'dist': 0.25, 'bed': 0.25, 'sat': 0.25},
        {'name': '병상 강조', 'cap': 0.50, 'dist': 0.15, 'bed': 0.30, 'sat': 0.05},
        {'name': '극단적 역량 우선', 'cap': 0.90, 'dist': 0.05, 'bed': 0.03, 'sat': 0.02},
    ]

    hospitals = {
        '권역외상센터A': {'cap': 1.00, 'dist': 0.30, 'bed': 0.90, 'sat': 0.70},
        '권역응급센터B': {'cap': 0.75, 'dist': 0.75, 'bed': 0.55, 'sat': 0.65},
        '지역응급센터C': {'cap': 0.55, 'dist': 0.92, 'bed': 0.40, 'sat': 0.72},
        '지역응급기관D': {'cap': 0.35, 'dist': 1.00, 'bed': 0.20, 'sat': 0.50},
    }

    case_modifiers = [
        {'CASE': 'CASE-1 중증 두부외상', 'cap_bias': 1.00, 'dist_bias': 0.85, 'bed_bias': 1.00, 'sat_bias': 0.90},
        {'CASE': 'CASE-2 흉복부 다발성', 'cap_bias': 1.00, 'dist_bias': 0.75, 'bed_bias': 1.00, 'sat_bias': 1.00},
        {'CASE': 'CASE-3 비교적 안정', 'cap_bias': 0.85, 'dist_bias': 1.00, 'bed_bias': 0.80, 'sat_bias': 0.95},
        {'CASE': 'CASE-4 야간 병상부족', 'cap_bias': 0.90, 'dist_bias': 0.85, 'bed_bias': 1.00, 'sat_bias': 1.00},
        {'CASE': 'CASE-5 고령 저혈압', 'cap_bias': 1.00, 'dist_bias': 0.80, 'bed_bias': 0.95, 'sat_bias': 1.00},
    ]

    rows = []
    for case in case_modifiers:
        row = {'CASE': case['CASE']}
        for scenario in weight_scenarios:
            best_name = None
            best_score = -1.0
            for hospital_name, values in hospitals.items():
                score = (
                    scenario['cap'] * values['cap'] * case['cap_bias']
                    + scenario['dist'] * values['dist'] * case['dist_bias']
                    + scenario['bed'] * values['bed'] * case['bed_bias']
                    + scenario['sat'] * values['sat'] * case['sat_bias']
                )
                if score > best_score:
                    best_score = score
                    best_name = hospital_name
            row[scenario['name']] = best_name
        rows.append(row)

    sensitivity_df = pd.DataFrame(rows)
    path = os.path.join(MODELS_DIR, 'sensitivity_analysis.csv')
    sensitivity_df.to_csv(path, index=False, encoding='utf-8-sig')
    print(f'[분석] {path} 저장 완료')
    print('\n[민감도 분석 결과 표]')
    print(sensitivity_df.to_string(index=False))


def print_final_summary(test_results):
    best_model_name = max(test_results.items(), key=lambda x: x[1]['auc'])[0]
    best_auc = test_results[best_model_name]['auc']

    print()
    print('╔══════════════════════════════════════════════════════════════╗')
    print('║           TRIAGE-1 v4.0 — ML 실험 결과 요약                  ║')
    print('╠══════════════════════════════════════════════════════════════╣')
    print('║ 모델                │ Accuracy │ Precision │ Recall │ F1   ║')
    print('╠══════════════════════════════════════════════════════════════╣')
    for name in ['Logistic Regression', 'Random Forest', 'XGBoost']:
        m = test_results[name]
        print(
            f"║ {name:<19} │ {m['accuracy']*100:>6.1f}%  │"
            f"   {m['precision']:.3f}   │ {m['recall']:.3f}  │{m['f1']:.3f}║"
        )
    print('╚══════════════════════════════════════════════════════════════╝')
    print(f'최고 성능 모델: {best_model_name} — AUC {best_auc:.3f}')
    print('생성된 파일:')
    print('  models/triage_classifier.pkl')
    print('  models/feature_importance.png')
    print('  models/learning_curve.png')
    print('  models/confusion_matrix.png')
    print('  models/roc_curve.png')
    print('  models/xgb_eval_curve.png')
    print('  models/sensitivity_analysis.csv')


def main():
    configure_korean_font()
    os.makedirs(MODELS_DIR, exist_ok=True)

    data_path = None
    for candidate in DATA_CANDIDATE_PATHS:
        if os.path.exists(candidate):
            data_path = candidate
            break

    if data_path is None:
        print('[오류] 학습 데이터 파일이 없습니다.')
        print('      확인 경로: data/synthetic_trauma_data.csv 또는 data/data')
        print('      먼저 다음 명령을 실행하세요: python synthetic_data_generator.py')
        return

    # 1) 데이터 로드
    df = pd.read_csv(data_path)
    print(f'[데이터] {len(df)}건 로드 완료 (source={data_path})')

    le = LabelEncoder()
    df['mechanism_enc'] = le.fit_transform(df['mechanism'])

    X = df[FEATURES]
    y = df['needs_rtc']

    # 2) 10-Fold Stratified CV 모델 비교
    scoring = ['accuracy', 'precision', 'recall', 'f1', 'roc_auc']
    cv = StratifiedKFold(n_splits=10, shuffle=True, random_state=42)

    cv_results = {}
    for name, model in build_models().items():
        scores = cross_validate(model, X, y, scoring=scoring, cv=cv, n_jobs=-1)
        cv_results[name] = {
            'accuracy_mean': scores['test_accuracy'].mean(),
            'accuracy_std': scores['test_accuracy'].std(),
            'precision_mean': scores['test_precision'].mean(),
            'precision_std': scores['test_precision'].std(),
            'recall_mean': scores['test_recall'].mean(),
            'recall_std': scores['test_recall'].std(),
            'f1_mean': scores['test_f1'].mean(),
            'f1_std': scores['test_f1'].std(),
            'roc_auc_mean': scores['test_roc_auc'].mean(),
            'roc_auc_std': scores['test_roc_auc'].std(),
        }
    print_cv_results(cv_results)

    # 3) Train/Validation/Test (70/15/15)
    X_temp, X_test, y_temp, y_test = train_test_split(
        X,
        y,
        test_size=0.15,
        random_state=42,
        stratify=y,
    )
    X_train, X_val, y_train, y_val = train_test_split(
        X_temp,
        y_temp,
        test_size=0.176,
        random_state=42,
        stratify=y_temp,
    )
    print(f'[분할] Train: {len(X_train)} / Validation: {len(X_val)} / Test: {len(X_test)}')
    print('[참고] Validation set은 하이퍼파라미터 튜닝 근거, Test set은 최종 성능 보고용')

    # 4) 모델 학습 + 검증 + 테스트
    trained_models = {}
    val_results = {}
    test_results = {}

    for name, model in build_models().items():
        model.fit(X_train, y_train)
        trained_models[name] = model

        val_pred = model.predict(X_val)
        val_prob = model.predict_proba(X_val)[:, 1]
        val_results[name] = compute_metrics(y_val, val_pred, val_prob)

        test_pred = model.predict(X_test)
        test_prob = model.predict_proba(X_test)[:, 1]
        test_results[name] = compute_metrics(y_test, test_pred, test_prob)

        print(f"\n[테스트 성능] {name}")
        print(f"  Accuracy : {test_results[name]['accuracy']*100:.1f}%")
        print(f"  Precision: {test_results[name]['precision']:.3f}")
        print(f"  Recall   : {test_results[name]['recall']:.3f}")
        print(f"  F1       : {test_results[name]['f1']:.3f}")
        print(f"  AUC-ROC  : {test_results[name]['auc']:.3f}")

    best_model_name = max(val_results.items(), key=lambda x: x[1]['auc'])[0]
    best_model = trained_models[best_model_name]
    print(f"\n[선정] Validation AUC 기준 최고 모델: {best_model_name}")

    # 5) 분류 보고서(최고 모델)
    y_pred_best = best_model.predict(X_test)
    print('\n[분류 보고서 - 최고 모델(Test)]')
    print(classification_report(y_test, y_pred_best, target_names=['권역외상센터 불필요', '권역외상센터 필요']))

    # 6) 그래프 저장
    rf_test_metrics = test_results['Random Forest']
    plot_feature_importance(trained_models['Random Forest'], rf_test_metrics)
    plot_learning_curve(X_train, y_train)
    plot_confusion_matrices(trained_models, X_test, y_test)
    plot_roc_curve(trained_models, X_test, y_test)
    plot_xgb_eval_curve(X_train, y_train, X_val, y_val)

    # 7) 민감도 분석
    run_sensitivity_analysis()

    # 8) 최고 성능 모델 저장 (기존 로직 유지 + 최고 모델로 교체)
    best_test = test_results[best_model_name]
    model_data = {
        'model': best_model,
        'best_model_name': best_model_name,
        'label_encoder': le,
        'features': FEATURES,
        'split': {'train': 0.70, 'val': 0.15, 'test': 0.15},
        'cv': {'folds': 10, 'stratified': True, 'random_state': 42},
        'accuracy': best_test['accuracy'],
        'precision': best_test['precision'],
        'recall': best_test['recall'],
        'f1_score': best_test['f1'],
        'auc': best_test['auc'],
        'cv_results': cv_results,
    }
    pkl_path = os.path.join(MODELS_DIR, 'triage_classifier.pkl')
    with open(pkl_path, 'wb') as f:
        pickle.dump(model_data, f)
    print(f'\n[모델] {pkl_path} 저장 완료')

    # 9) 최종 요약 표 출력
    print_final_summary(test_results)


if __name__ == '__main__':
    main()
