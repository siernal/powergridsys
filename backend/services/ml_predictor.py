"""
services/ml_predictor.py
Модуль прогнозирования отказов + обучение модели на синтетических данных.

Алгоритм: ансамбль VotingClassifier (RandomForest + GradientBoosting, soft voting).
Гиперпараметры подбираются через GridSearchCV (5-fold, scoring=roc_auc).
"""
import os
import math
import pickle
import random
import logging
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd
from sklearn.ensemble import (
    RandomForestClassifier,
    GradientBoostingClassifier,
    VotingClassifier,
)
from sklearn.model_selection import train_test_split, GridSearchCV
from sklearn.metrics import roc_auc_score, f1_score

logger = logging.getLogger(__name__)
MODEL_VERSION = "2.0"

# Нормативные сроки службы по категории (для признака age_ratio)
CATEGORY_LIFETIME = {
    "transformer": 30.0,
    "line":        37.5,
    "substation":  42.5,
    "cable":       27.5,
}


# ─── Генерация обучающего датасета ───────────────────────────────────────────

DEFAULT_FORECAST_HORIZON_DAYS = 90  # квартал — стандартное окно ТОиР


def generate_training_data(
    n_samples: int = 10_000,
    horizon_days: int = DEFAULT_FORECAST_HORIZON_DAYS,
) -> pd.DataFrame:
    """
    Синтетический датасет для бинарной классификации:
    «откажет ли объект в течение horizon_days дней?».

    Логика: вычисляется балл деградации, далее он трактуется как годовая
    интенсивность отказов (hazard rate) в логистической форме, и из неё
    выводится вероятность отказа в окне длительностью horizon_days.

    Чем больше horizon_days — тем выше доля положительных примеров и тем
    проще модели уловить долгосрочные тренды. Чем короче — тем ближе
    задача к классической «авария в ближайший месяц».
    """
    np.random.seed(42)
    rng = np.random.default_rng(42)
    # Доля года, на которую делаем прогноз. 1.0 = весь год, 0.25 ≈ 90 дней.
    horizon_factor = horizon_days / 365.0
    # Логарифм горизонта смещает базовую вероятность: при коротком окне
    # вероятность ниже, при длинном — выше.
    horizon_bias = math.log(horizon_factor) * 0.9

    categories = ["transformer", "line", "substation", "cable"]
    cat_risk_bias = {"transformer": 0.10, "line": 0.00, "substation": 0.15, "cable": 0.05}

    records = []
    for _ in range(n_samples):
        cat = random.choice(categories)
        age = float(np.clip(rng.lognormal(2.5, 0.7), 0.5, 55))

        failures_count  = int(rng.poisson(age / 15 + cat_risk_bias[cat] * 3))
        repairs_count   = int(rng.poisson(age / 6))
        criticality     = float(np.clip(rng.beta(2, 5) * 0.5 + 0.3, 0.05, 1.0))
        load_pct        = float(np.clip(rng.normal(65, 15), 10, 105))
        days_since_maint = float(rng.uniform(0, 1200))
        days_since_insp  = float(rng.uniform(0, 800))

        month = random.randint(1, 12)
        season_factor = 0.15 if month in (12, 1, 2) else (0.08 if month in (6, 7, 8) else 0.0)
        is_storm  = random.random() < 0.07
        humidity  = float(rng.uniform(35, 98))
        temperature = float(-10 + 25 * math.sin(math.pi * (month - 3) / 6) + rng.normal(0, 5))

        # ── Новые производные признаки ──────────────────────────────────────
        failure_rate         = failures_count / max(age, 1.0)           # отказов/год
        repair_effectiveness = min(repairs_count / (failures_count + 1), 5.0)  # ремонтов/отказ
        age_ratio            = min(age / CATEGORY_LIFETIME.get(cat, 30.0), 1.5)  # износ ресурса
        load_trend           = float(rng.normal(0, 0.5))                # тренд нагрузки

        score = (
              0.045 * age
            + 0.280 * failures_count
            - 0.180 * min(repairs_count, 10)
            + 0.550 * criticality
            + 0.012 * max(0, load_pct - 70)
            + 0.0005 * days_since_maint
            + 0.0003 * days_since_insp
            + 0.200 * int(is_storm)
            + season_factor
            + cat_risk_bias[cat]
            # вклад новых признаков
            + 0.300 * failure_rate
            - 0.100 * repair_effectiveness
            + 0.250 * age_ratio
            + 0.050 * max(0, load_trend)
            + rng.normal(0, 0.15)   # шум
            - 3.2                   # сдвиг (~25 % позитивных при годовом окне)
            + horizon_bias          # коррекция на длительность прогнозного окна
        )
        p = 1 / (1 + math.exp(-score))
        label = int(rng.binomial(1, p))

        records.append({
            "category":               cat,
            "age_years":              round(age, 2),
            "failures_count":         failures_count,
            "repairs_count":          repairs_count,
            "criticality":            round(criticality, 3),
            "load_percent":           round(load_pct, 1),
            "days_since_maintenance": round(days_since_maint, 1),
            "days_since_inspection":  round(days_since_insp, 1),
            "month":                  month,
            "is_storm":               int(is_storm),
            "humidity":               round(humidity, 1),
            "temperature":            round(temperature, 1),
            # новые признаки
            "failure_rate":           round(failure_rate, 4),
            "repair_effectiveness":   round(repair_effectiveness, 3),
            "age_ratio":              round(age_ratio, 3),
            "load_trend":             round(load_trend, 3),
            "failure_label":          label,
        })

    df = pd.DataFrame(records)
    pos_rate = df["failure_label"].mean()
    logger.info(f"Dataset generated: {len(df)} rows, {pos_rate:.1%} positive")
    return df


# ─── Feature Engineering ──────────────────────────────────────────────────────

NUMERIC_FEATURES = [
    "age_years", "failures_count", "repairs_count", "criticality",
    "load_percent", "days_since_maintenance", "days_since_inspection",
    "month", "is_storm", "humidity", "temperature",
    # новые признаки
    "failure_rate", "repair_effectiveness", "age_ratio", "load_trend",
]
CATEGORICAL_FEATURES = ["category"]


def build_feature_matrix(df: pd.DataFrame) -> pd.DataFrame:
    cat_dummies = pd.get_dummies(df["category"], prefix="cat")
    X = pd.concat([df[NUMERIC_FEATURES], cat_dummies], axis=1)
    return X.fillna(0)


# ─── Обучение модели ─────────────────────────────────────────────────────────

def train_model(
    model_path: str,
    horizon_days: int = DEFAULT_FORECAST_HORIZON_DAYS,
) -> dict:
    """
    Обучить модель прогнозирования отказов на горизонте horizon_days дней.
    Горизонт по умолчанию — 90 дней (квартал, типовой цикл планирования ТОиР).
    """
    # Обучение можно облегчить через переменные окружения — это нужно для деплоя
    # на хостинге с малым объёмом памяти (например, Render free-tier, 512 МБ),
    # где полный GridSearchCV с n_jobs=-1 не помещается в память.
    fast = os.getenv("ML_FAST_TRAIN") == "1"
    n_jobs = int(os.getenv("ML_N_JOBS", "-1"))
    n_samples = 3_000 if fast else 10_000

    df = generate_training_data(n_samples, horizon_days=horizon_days)
    X = build_feature_matrix(df)
    y = df["failure_label"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    rf = RandomForestClassifier(
        min_samples_leaf=8,
        class_weight="balanced",
        random_state=42,
        n_jobs=n_jobs,
    )
    gb = GradientBoostingClassifier(
        max_depth=5,
        subsample=0.8,
        random_state=42,
    )

    ensemble = VotingClassifier(
        estimators=[("rf", rf), ("gb", gb)],
        voting="soft",
    )

    # Обычный режим: 4 комбинации × 5 folds = 20 подгонок.
    # Облегчённый (ML_FAST_TRAIN=1): 1 комбинация × 3 folds — чтобы уложиться
    # в память и таймаут бесплатного хостинга.
    if fast:
        param_grid = {
            "rf__n_estimators":   [200],
            "gb__n_estimators":   [150],
            "gb__learning_rate":  [0.1],
        }
        cv = 3
    else:
        param_grid = {
            "rf__n_estimators":   [300, 500],
            "gb__n_estimators":   [200, 300],
            "gb__learning_rate":  [0.05, 0.1],
        }
        cv = 5

    search = GridSearchCV(
        ensemble, param_grid,
        cv=cv, scoring="roc_auc",
        n_jobs=n_jobs, verbose=1,
        refit=True,
    )
    logger.info(f"GridSearchCV started (fast={fast}, cv={cv}, n_jobs={n_jobs})...")
    search.fit(X_train, y_train)
    best = search.best_estimator_
    logger.info(f"Best params: {search.best_params_}")

    y_pred = best.predict(X_test)
    y_prob = best.predict_proba(X_test)[:, 1]
    auc = roc_auc_score(y_test, y_prob)
    f1  = f1_score(y_test, y_pred, average="macro")

    # Важность признаков из RF-компоненты ансамбля
    rf_clf = best.named_estimators_["rf"]
    feat_imp = list(zip(list(X.columns), rf_clf.feature_importances_.tolist()))

    metrics = {
        "roc_auc":                round(auc, 4),
        "f1_macro":                round(f1, 4),
        "n_train":                 len(X_train),
        "n_test":                  len(X_test),
        "positive_rate":           round(float(y.mean()), 4),
        "feature_columns":         list(X.columns),
        "model_version":           MODEL_VERSION,
        "trained_at":              datetime.utcnow().isoformat(),
        "best_params":             search.best_params_,
        "forecast_horizon_days":   horizon_days,
    }
    logger.info(f"Model trained: AUC={auc:.4f}, F1={f1:.4f}, "
                f"horizon={horizon_days} days")

    os.makedirs(os.path.dirname(model_path), exist_ok=True)
    with open(model_path, "wb") as f:
        pickle.dump({
            "model":                 best,
            "feature_columns":       list(X.columns),
            "feature_importances":   feat_imp,
            "metrics":               metrics,
            "forecast_horizon_days": horizon_days,
        }, f)

    return metrics


# ─── Инференс ────────────────────────────────────────────────────────────────

class FailurePredictor:
    def __init__(self, model_path: str):
        self.model_path = model_path
        self._bundle: Optional[dict] = None

    def _load(self):
        if self._bundle is None:
            if not os.path.exists(self.model_path):
                logger.warning("Model not found, training now...")
                train_model(self.model_path)
            with open(self.model_path, "rb") as f:
                self._bundle = pickle.load(f)

    def _make_row(self, asset_data: dict) -> pd.DataFrame:
        self._load()
        age            = float(asset_data.get("age_years", 10))
        failures_count = int(asset_data.get("failures_count", 0))
        repairs_count  = int(asset_data.get("repairs_count", 0))
        cat            = asset_data.get("category", "line")
        load_pct       = float(asset_data.get("load_percent", 65))

        row = {feat: 0.0 for feat in self._bundle["feature_columns"]}
        row.update({
            "age_years":              age,
            "failures_count":         failures_count,
            "repairs_count":          repairs_count,
            "criticality":            float(asset_data.get("criticality", 0.5)),
            "load_percent":           load_pct,
            "days_since_maintenance": float(asset_data.get("days_since_maintenance", 365)),
            "days_since_inspection":  float(asset_data.get("days_since_inspection", 180)),
            "month":                  int(asset_data.get("month", datetime.utcnow().month)),
            "is_storm":               int(asset_data.get("is_storm", False)),
            "humidity":               float(asset_data.get("humidity", 60)),
            "temperature":            float(asset_data.get("temperature", 10)),
            # вычисляемые признаки
            "failure_rate":           failures_count / max(age, 1.0),
            "repair_effectiveness":   min(repairs_count / (failures_count + 1), 5.0),
            "age_ratio":              min(age / CATEGORY_LIFETIME.get(cat, 30.0), 1.5),
            "load_trend":             float(asset_data.get("load_trend", 0.0)),
        })
        cat_col = f"cat_{cat}"
        if cat_col in row:
            row[cat_col] = 1.0
        return pd.DataFrame([row])

    def predict(self, asset_data: dict) -> dict:
        self._load()
        X   = self._make_row(asset_data)
        clf = self._bundle["model"]
        prob = float(clf.predict_proba(X)[0, 1])

        if prob < 0.30:
            level = "low"
        elif prob < 0.60:
            level = "medium"
        else:
            level = "high"

        feat_imp = self._bundle.get("feature_importances", [])
        top_features = sorted(feat_imp, key=lambda x: x[1], reverse=True)[:5]
        horizon = self._bundle.get("forecast_horizon_days", DEFAULT_FORECAST_HORIZON_DAYS)

        return {
            "risk_probability":      round(prob, 4),
            "risk_percent":          round(prob * 100, 1),
            "risk_level":            level,
            "forecast_horizon_days": horizon,
            "top_features":          [{"name": n, "importance": round(v, 4)} for n, v in top_features],
            "model_version":         MODEL_VERSION,
        }

    def get_metrics(self) -> dict:
        self._load()
        m = dict(self._bundle.get("metrics", {}))
        # Подстраховка для старых .pkl, где горизонт не сохранялся в метриках
        m.setdefault(
            "forecast_horizon_days",
            self._bundle.get("forecast_horizon_days", DEFAULT_FORECAST_HORIZON_DAYS),
        )
        return m
