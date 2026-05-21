"""
seed_data.py — генерация синтетических данных для демонстрационного MVP.
Запускается один раз при старте контейнера, если БД пуста.

Запуск:
    python -m seed.seed_data       (из каталога backend/)
    python seed/seed_data.py       (тоже из backend/)
"""
import sys
import os

# Добавляем родительский каталог backend/ в sys.path,
# чтобы при прямом запуске работали импорты вида `from core.database ...`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import random
import math
from datetime import datetime, timedelta, date

import numpy as np
from sqlalchemy.orm import Session

from core.database import engine, init_db, SessionLocal
from models import (
    User, AssetType, Asset, Inspection, Repair,
    FailureEvent, SensorSnapshot, WeatherSnapshot,
)
from core.security import get_password_hash

random.seed(42)
np.random.seed(42)

# ─── Константы ──────────────────────────────────────────────────────────────────

REGIONS = ["Северный", "Южный", "Восточный", "Западный", "Центральный"]

VOLTAGE_CLASSES = {
    "transformer": ["10кВ", "35кВ", "110кВ"],
    "line":        ["0.4кВ", "10кВ", "35кВ", "110кВ"],
    "substation":  ["35кВ", "110кВ"],
    "cable":       ["0.4кВ", "10кВ"],
}

ASSET_TYPES_DEF = [
    {"name": "Трансформатор 10кВ",    "category": "transformer", "lifetime": 25, "crit": 0.7},
    {"name": "Трансформатор 35кВ",    "category": "transformer", "lifetime": 30, "crit": 0.8},
    {"name": "Трансформатор 110кВ",   "category": "transformer", "lifetime": 35, "crit": 0.9},
    {"name": "ВЛ 0.4кВ",              "category": "line",        "lifetime": 40, "crit": 0.3},
    {"name": "ВЛ 10кВ",               "category": "line",        "lifetime": 35, "crit": 0.5},
    {"name": "ВЛ 110кВ",              "category": "line",        "lifetime": 40, "crit": 0.8},
    {"name": "Подстанция 35кВ",       "category": "substation",  "lifetime": 40, "crit": 0.8},
    {"name": "Подстанция 110кВ",      "category": "substation",  "lifetime": 45, "crit": 0.95},
    {"name": "Кабельная линия 10кВ",  "category": "cable",       "lifetime": 30, "crit": 0.6},
    {"name": "Кабельная линия 0.4кВ", "category": "cable",       "lifetime": 25, "crit": 0.4},
]

NUM_ASSETS = 50
NUM_WEATHER_DAYS = 365


# ─── Вспомогательные функции ────────────────────────────────────────────────────

def asset_age_years(asset: Asset) -> float:
    if not asset.installed_date:
        return 10.0
    delta = date.today() - asset.installed_date
    return delta.days / 365.25


# ─── Заполнение БД ──────────────────────────────────────────────────────────────

def seed(db: Session):
    if db.query(User).count() > 0:
        print("БД уже заполнена, пропускаем seed.")
        return

    print("Генерация синтетических данных...")

    # --- Пользователи ---
    users = [
        User(username="admin",     full_name="Администратор",          role="admin",     email="admin@grid.local",   hashed_password=get_password_hash("admin123"),    is_active=True),
        User(username="engineer",  full_name="Иванов Сергей Петрович", role="engineer",  email="ivanov@grid.local",  hashed_password=get_password_hash("engineer123"), is_active=True),
        User(username="inspector", full_name="Петрова Анна Ивановна",  role="inspector", email="petrova@grid.local", hashed_password=get_password_hash("inspect123"),  is_active=True),
        User(username="viewer",    full_name="Просмотр (демо)",        role="viewer",    email="viewer@grid.local",  hashed_password=get_password_hash("viewer123"),   is_active=True),
    ]
    db.add_all(users)
    db.flush()

    # --- Типы объектов ---
    asset_types = []
    for td in ASSET_TYPES_DEF:
        at = AssetType(
            name=td["name"], category=td["category"],
            base_lifetime_years=td["lifetime"], criticality_default=td["crit"],
        )
        db.add(at)
        asset_types.append(at)
    db.flush()

    # --- Объекты сети ---
    assets = []
    type_weights = [0.12, 0.08, 0.05,   # трансформаторы
                    0.15, 0.15, 0.08,   # ВЛ
                    0.07, 0.05,         # подстанции
                    0.12, 0.13]         # кабели

    for i in range(NUM_ASSETS):
        atype = random.choices(asset_types, weights=type_weights)[0]
        age_years = max(0.5, np.random.lognormal(mean=2.5, sigma=0.7))
        age_years = min(age_years, 55)
        installed = (datetime.utcnow() - timedelta(days=int(age_years * 365))).date()

        criticality = float(np.clip(
            np.random.beta(2, 5) * 0.5 + atype.criticality_default * 0.5, 0.1, 1.0
        ))

        # Координаты: имитируем сеть в районе 56°N 37°E (Московская обл.)
        lat = 55.5 + random.uniform(-1.5, 1.5)
        lon = 37.0 + random.uniform(-2.0, 2.0)

        asset = Asset(
            name=f"{atype.name} №{i+1:03d}",
            asset_type_id=atype.id,
            location_lat=round(lat, 6),
            location_lon=round(lon, 6),
            region=random.choice(REGIONS),
            installed_date=installed,
            voltage_class=random.choice(VOLTAGE_CLASSES.get(atype.category, ["10кВ"])),
            criticality=round(criticality, 3),
            status=random.choices(
                ["active", "maintenance", "failed"],
                weights=[0.88, 0.08, 0.04],
            )[0],
        )
        db.add(asset)
        assets.append(asset)
    db.flush()

    # --- Осмотры ---
    inspections = []
    for asset in assets:
        age = asset_age_years(asset)
        n_insp = max(1, int(age * 0.8) + random.randint(0, 3))
        for j in range(n_insp):
            days_back = random.randint(j * 180, j * 180 + 360)
            insp_dt = datetime.utcnow() - timedelta(days=days_back)
            condition = random.choices([1, 2, 3, 4, 5], weights=[3, 8, 25, 40, 24])[0]
            inspections.append(Inspection(
                asset_id=asset.id,
                inspector_id=random.choice([users[2].id, users[1].id]),
                inspected_at=insp_dt,
                condition_score=condition,
                defects_found=(
                    "Трещины на изоляторах" if condition <= 2 else
                    ("Незначительный износ" if condition == 3 else None)
                ),
                notes=f"Плановый осмотр #{j+1}",
            ))
    db.add_all(inspections)
    db.flush()

    # --- Ремонты ---
    repairs = []
    for asset in assets:
        age = asset_age_years(asset)
        n_rep = max(0, int(age / 5) + random.randint(0, 2))
        for j in range(n_rep):
            start_dt = datetime.utcnow() - timedelta(days=random.randint(30, max(31, int(age * 365 * 0.9))))
            duration_h = random.uniform(4, 72)
            rep_type = random.choices(["planned", "emergency", "capital"], weights=[6, 3, 1])[0]
            repairs.append(Repair(
                asset_id=asset.id,
                repair_type=rep_type,
                started_at=start_dt,
                completed_at=start_dt + timedelta(hours=duration_h),
                cost=round(random.uniform(5000, 500000), 2),
                work_description=(
                    "Плановое ТО объекта " + asset.name if rep_type == "planned"
                    else "Аварийный ремонт объекта " + asset.name
                ),
                performed_by=f"Бригада №{random.randint(1, 8)}",
            ))
    db.add_all(repairs)
    db.flush()

    # --- Отказы ---
    failures = []
    for asset in assets:
        age = asset_age_years(asset)
        lam = age / 15 * asset.criticality
        n_fail = np.random.poisson(lam)
        for j in range(n_fail):
            fail_dt = datetime.utcnow() - timedelta(days=random.randint(0, max(1, int(age * 365 * 0.95))))
            sev = random.choices(["minor", "major", "critical"], weights=[5, 3, 2])[0]
            downtime = {
                "minor":    random.uniform(1, 8),
                "major":    random.uniform(8, 48),
                "critical": random.uniform(24, 120),
            }[sev]
            failures.append(FailureEvent(
                asset_id=asset.id,
                failed_at=fail_dt,
                failure_type=random.choice([
                    "Пробой изоляции", "Механическое повреждение",
                    "Перегрев", "Короткое замыкание", "Износ контактов",
                ]),
                severity=sev,
                downtime_hours=round(downtime, 1),
                root_cause=random.choice([
                    "Износ оборудования", "Атмосферные воздействия",
                    "Перегрузка", "Механическое воздействие", "Производственный дефект",
                ]),
                resolved_at=fail_dt + timedelta(hours=downtime + random.uniform(0, 4)),
            ))
    db.add_all(failures)
    db.flush()

    # --- Погода (365 дней по регионам) ---
    weather_records = []
    for region in REGIONS:
        for day_offset in range(NUM_WEATHER_DAYS):
            dt = datetime.utcnow() - timedelta(days=day_offset)
            month = dt.month
            base_temp = -10 + 25 * math.sin(math.pi * (month - 3) / 6)
            temp = base_temp + random.gauss(0, 4)
            humidity = random.uniform(40, 95)
            wind = abs(random.gauss(5, 3))
            precip = max(0, random.gauss(2, 3))
            is_storm = (wind > 15 and precip > 10)
            weather_records.append(WeatherSnapshot(
                region=region,
                recorded_at=dt,
                temperature_c=round(temp, 1),
                humidity_percent=round(humidity, 1),
                wind_speed_ms=round(wind, 1),
                precipitation_mm=round(precip, 1),
                is_storm=is_storm,
            ))
    db.add_all(weather_records)
    db.flush()

    # --- Телеметрия датчиков (последние 30 дней, 4 снимка/сутки) ---
    sensor_records = []
    for asset in assets:
        age = asset_age_years(asset)
        for day_offset in range(30):
            for hour in [0, 6, 12, 18]:
                dt = datetime.utcnow() - timedelta(days=day_offset, hours=hour)
                month = dt.month
                seasonal_load = 0.15 if month in (12, 1, 2) else (0.08 if month in (6, 7, 8) else 0.0)
                load = float(np.clip(np.random.normal(65 + seasonal_load * 20, 12), 10, 105))
                temp_env = -10 + 25 * math.sin(math.pi * (month - 3) / 6) + random.gauss(0, 3)
                sensor_records.append(SensorSnapshot(
                    asset_id=asset.id,
                    recorded_at=dt,
                    load_percent=round(load, 1),
                    temperature_c=round(temp_env, 1),
                    voltage_deviation=round(random.gauss(0, 2.5), 2),
                    current_a=round(load * random.uniform(0.8, 1.2), 1),
                    vibration_level=round(max(0, random.gauss(0.1 + age * 0.005, 0.05)), 3),
                ))
    db.add_all(sensor_records)
    db.flush()

    db.commit()
    print(
        f"Seed done: {len(assets)} assets, {len(inspections)} inspections, "
        f"{len(repairs)} repairs, {len(failures)} failures, "
        f"{len(weather_records)} weather snapshots, {len(sensor_records)} telemetry rows."
    )


if __name__ == "__main__":
    init_db()
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()
