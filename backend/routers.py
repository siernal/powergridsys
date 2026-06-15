"""
routers.py — все REST API роутеры приложения.

Структура:
  auth_router        — /api/auth        — аутентификация (JWT)
  assets_router      — /api/assets      — CRUD объектов электросети
  inspections_router — /api/inspections — добавление/чтение осмотров
  repairs_router     — /api/repairs     — добавление/чтение ремонтов
  failures_router    — /api/failures    — регистрация/чтение отказов
  risk_router        — /api/risk        — расчёт рисков, переобучение ML
  maintenance_router — /api/maintenance — генерация и управление планом ТОиР
  twin_router        — /api/twin        — управление цифровой копией сети
  analytics_router   — /api/analytics   — агрегированная аналитика
  simulation_router  — /api/simulation  — управление симулятором
  ws_router          — /ws/simulation   — WebSocket live-feed
"""
import os
import asyncio
import logging
import shutil
from datetime import datetime, date, timedelta
from typing import List, Optional

import json
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, desc

from core.database import get_db
from core.security import (
    verify_password, create_access_token, get_current_user, get_password_hash
)
from core.config import get_settings
from models import (
    User, Asset, AssetType, Inspection, Repair,
    FailureEvent, RiskScore, MaintenancePlan, SensorSnapshot
)
from schemas import (
    Token, UserOut, AssetCreate, AssetUpdate, AssetOut, AssetDetail,
    InspectionCreate, InspectionUpdate, InspectionOut,
    RepairCreate, RepairUpdate, RepairOut,
    FailureCreate, FailureUpdate, FailureOut,
    RiskScoreOut, MaintenancePlanOut,
    AnalyticsSummary,
)
from services.ml_predictor import FailurePredictor, train_model
from services.digital_twin import get_twin, asset_age
from services.maintenance_planner import generate_plan, days_since_last_maintenance
from services.transformer_simulator import get_simulator, Scenario

settings = get_settings()
logger = logging.getLogger(__name__)

# Singleton-предиктор: загружается из pickle при первом обращении
predictor = FailurePredictor(settings.ml_model_path)


# ─── Аутентификация ───────────────────────────────────────────────────────────

auth_router = APIRouter(prefix="/api/auth", tags=["Auth"])


@auth_router.post("/token", response_model=Token)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """Выдать JWT-токен по логину и паролю.

    Используется фронтендом при входе в систему.
    Токен действителен 480 минут (8 часов).
    """
    user = db.query(User).filter(User.username == form.username).first()
    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    token = create_access_token({"sub": user.username})
    return {"access_token": token, "token_type": "bearer"}


@auth_router.get("/me", response_model=UserOut)
def me(current_user=Depends(get_current_user)):
    """Вернуть данные текущего авторизованного пользователя."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Не авторизован")
    return current_user


# ─── Объекты электросети ──────────────────────────────────────────────────────

assets_router = APIRouter(prefix="/api/assets", tags=["Assets"])


@assets_router.get("", response_model=List[AssetOut])
def list_assets(
    skip: int = 0, limit: int = 100,
    category: Optional[str] = None,    # фильтр по категории (transformer/line/…)
    region: Optional[str] = None,      # фильтр по региону
    status: Optional[str] = None,      # фильтр по статусу (active/failed/…)
    db: Session = Depends(get_db),
):
    """Список объектов с опциональной фильтрацией.

    Используется страницей «Реестр объектов» для отображения таблицы.
    joinedload(Asset.asset_type) предотвращает N+1 запросов.
    """
    q = db.query(Asset).options(joinedload(Asset.asset_type))
    if category:
        q = q.join(AssetType).filter(AssetType.category == category)
    if region:
        q = q.filter(Asset.region == region)
    if status:
        q = q.filter(Asset.status == status)
    return q.offset(skip).limit(limit).all()


@assets_router.get("/types", response_model=List[dict])
def list_asset_types(db: Session = Depends(get_db)):
    """Справочник типов оборудования (для заполнения выпадающих списков)."""
    types = db.query(AssetType).all()
    return [{"id": t.id, "name": t.name, "category": t.category} for t in types]


@assets_router.post("", response_model=AssetOut, status_code=201)
def create_asset(body: AssetCreate, db: Session = Depends(get_db)):
    """Создать новый объект электросети."""
    asset = Asset(**body.model_dump())
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


@assets_router.get("/{asset_id}", response_model=AssetDetail)
def get_asset(asset_id: int, db: Session = Depends(get_db)):
    """Карточка объекта с агрегированными данными.

    Помимо базовых полей, вычисляет:
    - возраст (age_years)
    - количество отказов и ремонтов
    - дней с последнего ТО
    - последний результат осмотра
    - текущий риск из ML-модели
    - health-score из digital twin
    """
    asset = (
        db.query(Asset)
        .options(
            joinedload(Asset.asset_type),
            joinedload(Asset.repairs),
            joinedload(Asset.failures),
            joinedload(Asset.inspections),
            joinedload(Asset.risk_scores),
        )
        .filter(Asset.id == asset_id)
        .first()
    )
    if not asset:
        raise HTTPException(404, "Объект не найден")

    age = asset_age(asset.installed_date)
    dsm = days_since_last_maintenance(asset)

    # Последний риск-скор и последний осмотр (по дате)
    latest_risk = (
        max(asset.risk_scores, key=lambda r: r.calculated_at)
        if asset.risk_scores else None
    )
    latest_insp = (
        max(asset.inspections, key=lambda i: i.inspected_at)
        if asset.inspections else None
    )

    # Состояние узла в digital twin (health-score)
    twin = get_twin()
    node_state = twin.get_node_state(asset_id) or {}

    result = AssetDetail.model_validate(asset)
    result.age_years               = round(age, 2)
    result.failures_count          = len(asset.failures)
    result.repairs_count           = len(asset.repairs)
    result.days_since_maintenance  = round(dsm, 1)
    result.latest_inspection_score = latest_insp.condition_score if latest_insp else None
    result.latest_risk_probability = latest_risk.risk_probability if latest_risk else None
    result.latest_risk_level       = latest_risk.risk_level if latest_risk else None
    result.health_score            = node_state.get("health")
    return result


@assets_router.put("/{asset_id}/status")
def update_status(asset_id: int, status: str, db: Session = Depends(get_db)):
    """Изменить статус объекта (например, пометить как «В ремонте»)."""
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(404, "Объект не найден")
    allowed = {"active", "maintenance", "failed", "decommissioned"}
    if status not in allowed:
        raise HTTPException(400, f"Статус должен быть одним из: {allowed}")
    asset.status = status
    db.commit()
    return {"ok": True, "status": status}


@assets_router.post("/{asset_id}/image")
def upload_asset_image(
    asset_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Загрузить изображение объекта.

    Изображение сохраняется в директорию static/assets/, доступную по
    относительному URL /static/assets/<имя>. Поле image_url объекта
    обновляется этим URL и возвращается клиенту.
    """
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(404, "Объект не найден")

    # Допустимые расширения
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        raise HTTPException(
            400,
            "Поддерживаются только изображения PNG, JPG, JPEG, WEBP, GIF"
        )

    # Сохранение файла
    upload_dir = "static/assets"
    os.makedirs(upload_dir, exist_ok=True)
    filename = f"{asset_id}_{int(datetime.utcnow().timestamp())}{ext}"
    file_path = os.path.join(upload_dir, filename)
    with open(file_path, "wb") as buf:
        shutil.copyfileobj(file.file, buf)

    # Обновление URL в БД
    asset.image_url = f"/static/assets/{filename}"
    db.commit()
    db.refresh(asset)
    return {"image_url": asset.image_url}


@assets_router.delete("/{asset_id}/image", status_code=204)
def delete_asset_image(asset_id: int, db: Session = Depends(get_db)):
    """Удалить изображение объекта (сбросить image_url и удалить файл)."""
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(404, "Объект не найден")
    if asset.image_url:
        path = asset.image_url.lstrip("/")
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
        asset.image_url = None
        db.commit()
    return None


@assets_router.put("/{asset_id}", response_model=AssetOut)
def update_asset(asset_id: int, body: AssetUpdate, db: Session = Depends(get_db)):
    """Полное редактирование объекта.

    Применяются только те поля, которые переданы в теле (model_dump(exclude_unset=True)).
    Если меняется статус — также валидируется по разрешённому списку.
    """
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(404, "Объект не найден")
    data = body.model_dump(exclude_unset=True)
    if "status" in data:
        allowed = {"active", "maintenance", "failed", "decommissioned"}
        if data["status"] not in allowed:
            raise HTTPException(400, f"Статус должен быть одним из: {allowed}")
    if "asset_type_id" in data:
        if not db.query(AssetType).filter(AssetType.id == data["asset_type_id"]).first():
            raise HTTPException(400, "Указан несуществующий тип оборудования")
    for k, v in data.items():
        setattr(asset, k, v)
    db.commit()
    db.refresh(asset)
    return asset


@assets_router.delete("/{asset_id}", status_code=204)
def delete_asset(asset_id: int, db: Session = Depends(get_db)):
    """Каскадное удаление объекта.

    Удаляет сам объект и все связанные записи (осмотры, ремонты, отказы,
    риск-скоры, планы, телеметрия). Используется только из административной
    карточки объекта по подтверждению.
    """
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(404, "Объект не найден")
    # Каскад вручную, потому что в моделях нет ON DELETE CASCADE
    db.query(Inspection).filter(Inspection.asset_id == asset_id).delete()
    db.query(Repair).filter(Repair.asset_id == asset_id).delete()
    db.query(FailureEvent).filter(FailureEvent.asset_id == asset_id).delete()
    db.query(RiskScore).filter(RiskScore.asset_id == asset_id).delete()
    db.query(MaintenancePlan).filter(MaintenancePlan.asset_id == asset_id).delete()
    db.query(SensorSnapshot).filter(SensorSnapshot.asset_id == asset_id).delete()
    db.delete(asset)
    db.commit()
    return None


# ─── Осмотры ─────────────────────────────────────────────────────────────────

inspections_router = APIRouter(prefix="/api/inspections", tags=["Inspections"])


@inspections_router.post("", response_model=InspectionOut, status_code=201)
def add_inspection(body: InspectionCreate, db: Session = Depends(get_db)):
    """Зафиксировать результат осмотра объекта."""
    asset = db.query(Asset).filter(Asset.id == body.asset_id).first()
    if not asset:
        raise HTTPException(404, "Объект не найден")
    insp = Inspection(**body.model_dump())
    db.add(insp)
    db.commit()
    db.refresh(insp)
    return insp


@inspections_router.get("/asset/{asset_id}", response_model=List[InspectionOut])
def get_asset_inspections(asset_id: int, db: Session = Depends(get_db)):
    """История осмотров конкретного объекта (от новых к старым)."""
    return (
        db.query(Inspection)
        .filter(Inspection.asset_id == asset_id)
        .order_by(desc(Inspection.inspected_at))
        .all()
    )


@inspections_router.put("/{insp_id}", response_model=InspectionOut)
def update_inspection(insp_id: int, body: InspectionUpdate, db: Session = Depends(get_db)):
    """Редактирование записи об осмотре."""
    insp = db.query(Inspection).filter(Inspection.id == insp_id).first()
    if not insp:
        raise HTTPException(404, "Осмотр не найден")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(insp, k, v)
    db.commit()
    db.refresh(insp)
    return insp


@inspections_router.delete("/{insp_id}", status_code=204)
def delete_inspection(insp_id: int, db: Session = Depends(get_db)):
    """Удаление записи об осмотре."""
    insp = db.query(Inspection).filter(Inspection.id == insp_id).first()
    if not insp:
        raise HTTPException(404, "Осмотр не найден")
    db.delete(insp)
    db.commit()
    return None


# ─── Ремонты ─────────────────────────────────────────────────────────────────

repairs_router = APIRouter(prefix="/api/repairs", tags=["Repairs"])


@repairs_router.post("", response_model=RepairOut, status_code=201)
def add_repair(body: RepairCreate, db: Session = Depends(get_db)):
    """Зафиксировать факт ремонта или ТО."""
    repair = Repair(**body.model_dump())
    db.add(repair)
    db.commit()
    db.refresh(repair)
    return repair


@repairs_router.get("", response_model=List[RepairOut])
def list_repairs(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """Список всех ремонтов (от новых к старым), с пагинацией."""
    return (
        db.query(Repair)
        .order_by(desc(Repair.started_at))
        .offset(skip)
        .limit(limit)
        .all()
    )


@repairs_router.get("/asset/{asset_id}", response_model=List[RepairOut])
def get_asset_repairs(asset_id: int, db: Session = Depends(get_db)):
    """История ремонтов конкретного объекта (от новых к старым)."""
    return (
        db.query(Repair)
        .filter(Repair.asset_id == asset_id)
        .order_by(desc(Repair.started_at))
        .all()
    )


@repairs_router.put("/{rep_id}", response_model=RepairOut)
def update_repair(rep_id: int, body: RepairUpdate, db: Session = Depends(get_db)):
    """Редактирование записи о ремонте."""
    rep = db.query(Repair).filter(Repair.id == rep_id).first()
    if not rep:
        raise HTTPException(404, "Ремонт не найден")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(rep, k, v)
    db.commit()
    db.refresh(rep)
    return rep


@repairs_router.delete("/{rep_id}", status_code=204)
def delete_repair(rep_id: int, db: Session = Depends(get_db)):
    """Удаление записи о ремонте."""
    rep = db.query(Repair).filter(Repair.id == rep_id).first()
    if not rep:
        raise HTTPException(404, "Ремонт не найден")
    db.delete(rep)
    db.commit()
    return None


# ─── Отказы ──────────────────────────────────────────────────────────────────

failures_router = APIRouter(prefix="/api/failures", tags=["Failures"])


@failures_router.post("", response_model=FailureOut, status_code=201)
def add_failure(body: FailureCreate, db: Session = Depends(get_db)):
    """Зарегистрировать факт отказа оборудования."""
    failure = FailureEvent(**body.model_dump())
    db.add(failure)
    db.commit()
    db.refresh(failure)
    return failure


@failures_router.get("", response_model=List[FailureOut])
def list_failures(skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    """Список всех отказов (от новых к старым), с пагинацией."""
    return db.query(FailureEvent).order_by(desc(FailureEvent.failed_at)).offset(skip).limit(limit).all()


@failures_router.get("/asset/{asset_id}", response_model=List[FailureOut])
def get_asset_failures(asset_id: int, db: Session = Depends(get_db)):
    """История отказов конкретного объекта (от новых к старым)."""
    return (
        db.query(FailureEvent)
        .filter(FailureEvent.asset_id == asset_id)
        .order_by(desc(FailureEvent.failed_at))
        .all()
    )


@failures_router.put("/{fail_id}", response_model=FailureOut)
def update_failure(fail_id: int, body: FailureUpdate, db: Session = Depends(get_db)):
    """Редактирование записи об отказе."""
    fail = db.query(FailureEvent).filter(FailureEvent.id == fail_id).first()
    if not fail:
        raise HTTPException(404, "Отказ не найден")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(fail, k, v)
    db.commit()
    db.refresh(fail)
    return fail


@failures_router.delete("/{fail_id}", status_code=204)
def delete_failure(fail_id: int, db: Session = Depends(get_db)):
    """Удаление записи об отказе."""
    fail = db.query(FailureEvent).filter(FailureEvent.id == fail_id).first()
    if not fail:
        raise HTTPException(404, "Отказ не найден")
    db.delete(fail)
    db.commit()
    return None


# ─── Риск и ML-модель ────────────────────────────────────────────────────────

risk_router = APIRouter(prefix="/api/risk", tags=["Risk & ML"])


def _build_asset_features(asset: Asset, db: Session) -> dict:
    """Собрать словарь признаков для ML-предиктора из БД.

    Включает:
    - возраст и критичность объекта
    - количество отказов и ремонтов (из таблиц)
    - дней без ТО и без осмотра
    - последние показания датчиков (нагрузка, температура)
    - текущий месяц (сезонный фактор)
    Производные признаки (failure_rate, age_ratio и др.) вычисляются
    внутри FailurePredictor._make_row().
    """
    age = asset_age(asset.installed_date)
    failures_count = db.query(func.count(FailureEvent.id)).filter(
        FailureEvent.asset_id == asset.id
    ).scalar() or 0
    repairs_count = db.query(func.count(Repair.id)).filter(
        Repair.asset_id == asset.id
    ).scalar() or 0

    dsm = days_since_last_maintenance(asset)

    # Берём последний сенсорный снимок для актуальных показаний
    latest_sensor = (
        db.query(SensorSnapshot)
        .filter(SensorSnapshot.asset_id == asset.id)
        .order_by(desc(SensorSnapshot.recorded_at))
        .first()
    )
    load = latest_sensor.load_percent if latest_sensor else 65.0
    temp = latest_sensor.temperature_c if latest_sensor else 10.0

    # Дней с последнего осмотра
    latest_insp = (
        db.query(Inspection)
        .filter(Inspection.asset_id == asset.id)
        .order_by(desc(Inspection.inspected_at))
        .first()
    )
    days_since_insp = (
        (datetime.utcnow() - latest_insp.inspected_at).days
        if latest_insp else 365
    )

    return {
        "category":               asset.asset_type.category if asset.asset_type else "line",
        "age_years":              round(age, 2),
        "failures_count":         failures_count,
        "repairs_count":          repairs_count,
        "criticality":            asset.criticality,
        "load_percent":           load,
        "days_since_maintenance": dsm,
        "days_since_inspection":  days_since_insp,
        "month":                  datetime.utcnow().month,
        "is_storm":               False,   # симулятор обновляет риски сам при шторме
        "humidity":               60.0,
        "temperature":            temp,
    }


@risk_router.post("/calculate/{asset_id}", response_model=RiskScoreOut)
def calculate_risk(asset_id: int, db: Session = Depends(get_db)):
    """Рассчитать риск отказа для одного объекта и сохранить в БД.

    Используется кнопкой «Пересчитать риск» на карточке объекта.
    """
    asset = (
        db.query(Asset)
        .options(joinedload(Asset.asset_type), joinedload(Asset.repairs))
        .filter(Asset.id == asset_id)
        .first()
    )
    if not asset:
        raise HTTPException(404, "Объект не найден")

    features = _build_asset_features(asset, db)
    prediction = predictor.predict(features)

    # Сохраняем риск-скор с полным снимком признаков для объяснимости
    score = RiskScore(
        asset_id=asset_id,
        risk_probability=prediction["risk_probability"],
        risk_level=prediction["risk_level"],
        forecast_horizon_days=prediction.get("forecast_horizon_days", 90),
        feature_snapshot={**features, **prediction},
        model_version=prediction["model_version"],
    )
    db.add(score)
    db.commit()
    db.refresh(score)
    return score


@risk_router.post("/calculate-all")
def calculate_all_risks(db: Session = Depends(get_db)):
    """Пакетный расчёт рисков для всех активных объектов.

    Используется кнопкой «Пересчитать риски всех объектов» на странице прогноза.
    """
    assets = (
        db.query(Asset)
        .options(joinedload(Asset.asset_type), joinedload(Asset.repairs))
        .filter(Asset.status == "active")
        .all()
    )
    results = []
    for asset in assets:
        features = _build_asset_features(asset, db)
        prediction = predictor.predict(features)
        score = RiskScore(
            asset_id=asset.id,
            risk_probability=prediction["risk_probability"],
            risk_level=prediction["risk_level"],
            forecast_horizon_days=prediction.get("forecast_horizon_days", 90),
            feature_snapshot=features,
            model_version=prediction["model_version"],
        )
        db.add(score)
        results.append({"asset_id": asset.id, "risk_level": prediction["risk_level"]})
    db.commit()
    return {"calculated": len(results), "results": results}


@risk_router.get("/scores", response_model=List[RiskScoreOut])
def list_risk_scores(limit: int = 200, db: Session = Depends(get_db)):
    """Последний риск-скор для каждого объекта.

    Используется subquery для выборки только последней записи по каждому asset_id.
    """
    subq = (
        db.query(RiskScore.asset_id, func.max(RiskScore.calculated_at).label("max_dt"))
        .group_by(RiskScore.asset_id)
        .subquery()
    )
    scores = (
        db.query(RiskScore)
        .join(subq, (RiskScore.asset_id == subq.c.asset_id) &
                    (RiskScore.calculated_at == subq.c.max_dt))
        .limit(limit)
        .all()
    )
    return scores


@risk_router.post("/retrain")
def retrain_model():
    """Переобучить ML-модель на свежесгенерированных данных.

    Запускает полный цикл: генерация датасета (10 000 примеров) →
    GridSearchCV → обучение ансамбля → сохранение pickle.
    Сбрасывает кэш предиктора, чтобы следующий predict загрузил новую модель.
    Занимает 1–3 минуты в зависимости от железа.
    """
    metrics = train_model(settings.ml_model_path)
    predictor._bundle = None  # сброс кэша: следующий predict перечитает pickle
    return {"ok": True, "metrics": metrics}


@risk_router.get("/model-metrics")
def model_metrics():
    """Метрики текущей ML-модели (AUC, F1, версия, дата обучения и т.д.)."""
    return predictor.get_metrics()


# ─── Планирование ТОиР ───────────────────────────────────────────────────────

maintenance_router = APIRouter(prefix="/api/maintenance", tags=["Maintenance"])


@maintenance_router.post("/generate")
def generate_maintenance_plan(horizon_days: int = 180, db: Session = Depends(get_db)):
    """Автоматически сформировать план ТОиР на заданный горизонт.

    Алгоритм:
    1. Удаляет старые автоматически сгенерированные «scheduled» планы.
    2. Для каждого активного объекта вычисляет приоритет:
       0.5 × риск + 0.3 × критичность + 0.2 × (дней_без_ТО / 365).
    3. Распределяет работы по календарю с лимитом 5 работ/день.
    """
    plan = generate_plan(db, horizon_days)
    return {"generated": len(plan), "plan": plan}


@maintenance_router.get("/plans", response_model=List[MaintenancePlanOut])
def get_plans(
    status: Optional[str] = None,
    asset_id: Optional[int] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    db: Session = Depends(get_db),
):
    """Список планов ТО с фильтрами по статусу, объекту и диапазону дат."""
    q = db.query(MaintenancePlan).options(joinedload(MaintenancePlan.asset))
    if status:
        q = q.filter(MaintenancePlan.status == status)
    if asset_id:
        q = q.filter(MaintenancePlan.asset_id == asset_id)
    if from_date:
        q = q.filter(MaintenancePlan.plan_date >= from_date)
    if to_date:
        q = q.filter(MaintenancePlan.plan_date <= to_date)
    plans = q.order_by(MaintenancePlan.plan_date).all()

    # Подставляем имя объекта из связанного Asset
    result = []
    for p in plans:
        out = MaintenancePlanOut.model_validate(p)
        out.asset_name = p.asset.name if p.asset else None
        result.append(out)
    return result


@maintenance_router.put("/plans/{plan_id}/status")
def update_plan_status(plan_id: int, status: str, db: Session = Depends(get_db)):
    """Обновить статус записи плана (например, отметить как выполненную)."""
    plan = db.query(MaintenancePlan).filter(MaintenancePlan.id == plan_id).first()
    if not plan:
        raise HTTPException(404, "План не найден")
    plan.status = status
    db.commit()
    return {"ok": True}


# ─── Цифровая копия (Digital Twin) ───────────────────────────────────────────

twin_router = APIRouter(prefix="/api/twin", tags=["Digital Twin"])


@twin_router.post("/rebuild")
def rebuild_twin(db: Session = Depends(get_db)):
    """Перестроить граф цифровой копии из актуальных данных БД.

    Используется кнопкой «Пересобрать цифровую копию» на странице прогноза.
    После пересборки обновляет health и risk для каждого узла.
    """
    assets = db.query(Asset).options(joinedload(Asset.asset_type)).all()
    twin = get_twin()
    twin.build_from_assets(assets)

    # Обновляем состояния всех узлов: подтягиваем данные из БД
    for asset in assets:
        failures_count = db.query(func.count(FailureEvent.id)).filter(
            FailureEvent.asset_id == asset.id
        ).scalar() or 0
        repairs_count = db.query(func.count(Repair.id)).filter(
            Repair.asset_id == asset.id
        ).scalar() or 0
        dsm = days_since_last_maintenance(asset)
        latest_sensor = (
            db.query(SensorSnapshot)
            .filter(SensorSnapshot.asset_id == asset.id)
            .order_by(desc(SensorSnapshot.recorded_at))
            .first()
        )
        twin.update_node_state(
            asset_id=asset.id,
            failures_count=failures_count,
            repairs_count=repairs_count,
            days_since_maintenance=dsm,
            load_percent=latest_sensor.load_percent if latest_sensor else 65.0,
            temperature=latest_sensor.temperature_c if latest_sensor else 10.0,
        )
    return {"ok": True, "nodes": twin.graph.number_of_nodes(), "edges": twin.graph.number_of_edges()}


@twin_router.get("/graph")
def get_graph():
    """Полный граф сети: узлы с health/risk + рёбра + критические цепочки."""
    twin = get_twin()
    if not twin._built:
        return {"nodes": [], "edges": [], "message": "Граф не построен. POST /api/twin/rebuild"}
    return twin.get_graph_data()


@twin_router.get("/node/{asset_id}")
def get_node(asset_id: int):
    """Состояние одного узла графа + список downstream-объектов (зависимых).

    downstream_ids — объекты, которые пострадают при отказе данного узла.
    """
    twin = get_twin()
    state = twin.get_node_state(asset_id)
    if state is None:
        raise HTTPException(404, "Узел не найден в графе")
    downstream = twin.get_downstream_impact(asset_id)
    return {**state, "downstream_count": len(downstream), "downstream_ids": downstream[:10]}


# ─── Аналитика ───────────────────────────────────────────────────────────────

analytics_router = APIRouter(prefix="/api/analytics", tags=["Analytics"])


@analytics_router.get("/summary", response_model=AnalyticsSummary)
def get_summary(db: Session = Depends(get_db)):
    """Сводные KPI для дашборда (статусы, риски, отказы, ТО, health).

    Использует subquery для получения последнего риск-скора по каждому объекту.
    avg_health_score берётся из in-memory графа digital twin.
    """
    one_year_ago = datetime.utcnow() - timedelta(days=365)
    today = date.today()
    in_30_days = today + timedelta(days=30)

    # Счётчики по статусам
    total        = db.query(func.count(Asset.id)).scalar()
    active       = db.query(func.count(Asset.id)).filter(Asset.status == "active").scalar()
    maint        = db.query(func.count(Asset.id)).filter(Asset.status == "maintenance").scalar()
    failed_count = db.query(func.count(Asset.id)).filter(Asset.status == "failed").scalar()

    # Последние риски по каждому объекту (subquery)
    subq = (
        db.query(RiskScore.asset_id, func.max(RiskScore.calculated_at).label("max_dt"))
        .group_by(RiskScore.asset_id).subquery()
    )
    latest_scores = (
        db.query(RiskScore)
        .join(subq, (RiskScore.asset_id == subq.c.asset_id) &
                    (RiskScore.calculated_at == subq.c.max_dt))
        .all()
    )
    high_risk   = sum(1 for s in latest_scores if s.risk_level == "high")
    medium_risk = sum(1 for s in latest_scores if s.risk_level == "medium")
    low_risk    = sum(1 for s in latest_scores if s.risk_level == "low")

    # Отказы и ремонты за последний год
    failures_ly = db.query(func.count(FailureEvent.id)).filter(
        FailureEvent.failed_at >= one_year_ago
    ).scalar()
    repairs_ly = db.query(func.count(Repair.id)).filter(
        Repair.started_at >= one_year_ago
    ).scalar()

    # Запланированные работы на ближайшие 30 дней
    upcoming = db.query(func.count(MaintenancePlan.id)).filter(
        MaintenancePlan.status == "scheduled",
        MaintenancePlan.plan_date <= in_30_days,
    ).scalar()

    # Средний health из in-memory digital twin (не обращается к БД)
    twin = get_twin()
    health_vals = [
        data.get("health") for _, data in twin.graph.nodes(data=True)
        if data.get("health") is not None
    ]
    avg_health = round(sum(health_vals) / len(health_vals), 1) if health_vals else None

    return AnalyticsSummary(
        total_assets=total,
        active=active,
        in_maintenance=maint,
        failed=failed_count,
        high_risk_count=high_risk,
        medium_risk_count=medium_risk,
        low_risk_count=low_risk,
        total_failures_last_year=failures_ly,
        total_repairs_last_year=repairs_ly,
        avg_health_score=avg_health,
        upcoming_maintenance_count=upcoming,
    )


@analytics_router.get("/failures-by-month")
def failures_by_month(db: Session = Depends(get_db)):
    """Количество отказов по месяцам за последний год (для графика на дашборде)."""
    one_year_ago = datetime.utcnow() - timedelta(days=365)
    rows = (
        db.query(
            func.date_trunc("month", FailureEvent.failed_at).label("month"),
            func.count(FailureEvent.id).label("count"),
        )
        .filter(FailureEvent.failed_at >= one_year_ago)
        .group_by("month")
        .order_by("month")
        .all()
    )
    return [{"month": str(r.month)[:7], "count": r.count} for r in rows]


@analytics_router.get("/risk-distribution")
def risk_distribution(db: Session = Depends(get_db)):
    """Распределение объектов по уровням риска {low: N, medium: M, high: K}.

    Учитывает только последний риск-скор каждого объекта.
    """
    subq = (
        db.query(RiskScore.asset_id, func.max(RiskScore.calculated_at).label("max_dt"))
        .group_by(RiskScore.asset_id).subquery()
    )
    rows = (
        db.query(RiskScore.risk_level, func.count(RiskScore.id).label("count"))
        .join(subq, (RiskScore.asset_id == subq.c.asset_id) &
                    (RiskScore.calculated_at == subq.c.max_dt))
        .group_by(RiskScore.risk_level)
        .all()
    )
    return {r.risk_level: r.count for r in rows}


@analytics_router.get("/top-risk-assets")
def top_risk_assets(limit: int = 10, db: Session = Depends(get_db)):
    """Топ-N объектов с наибольшей вероятностью отказа (только high и medium).

    Используется на дашборде для таблицы приоритетов.
    """
    subq = (
        db.query(RiskScore.asset_id, func.max(RiskScore.calculated_at).label("max_dt"))
        .group_by(RiskScore.asset_id).subquery()
    )
    rows = (
        db.query(RiskScore, Asset)
        .join(subq, (RiskScore.asset_id == subq.c.asset_id) &
                    (RiskScore.calculated_at == subq.c.max_dt))
        .join(Asset, Asset.id == RiskScore.asset_id)
        .filter(RiskScore.risk_level.in_(["high", "medium"]))
        .order_by(desc(RiskScore.risk_probability))
        .limit(limit)
        .all()
    )
    return [
        {
            "asset_id":    r.Asset.id,
            "asset_name":  r.Asset.name,
            "region":      r.Asset.region,
            "risk_prob":   r.RiskScore.risk_probability,
            "risk_level":  r.RiskScore.risk_level,
            "criticality": r.Asset.criticality,
        }
        for r in rows
    ]


@analytics_router.get("/all-risk-assets")
def all_risk_assets(db: Session = Depends(get_db)):
    """Все объекты с последним рассчитанным риском (включая low и без риска).

    Используется на странице «Прогноз отказов» для полной таблицы.
    LEFT JOIN — объекты без риска тоже попадают в результат со значениями null.
    """
    subq = (
        db.query(RiskScore.asset_id, func.max(RiskScore.calculated_at).label("max_dt"))
        .group_by(RiskScore.asset_id).subquery()
    )
    rows = (
        db.query(Asset, RiskScore)
        .outerjoin(subq, Asset.id == subq.c.asset_id)
        .outerjoin(
            RiskScore,
            (RiskScore.asset_id == subq.c.asset_id) &
            (RiskScore.calculated_at == subq.c.max_dt),
        )
        .order_by(desc(func.coalesce(RiskScore.risk_probability, 0.0)))
        .all()
    )
    return [
        {
            "asset_id":    r.Asset.id,
            "asset_name":  r.Asset.name,
            "region":      r.Asset.region,
            "risk_prob":   r.RiskScore.risk_probability if r.RiskScore else None,
            "risk_level":  r.RiskScore.risk_level       if r.RiskScore else None,
            "criticality": r.Asset.criticality,
        }
        for r in rows
    ]


# ─── Управление симулятором ───────────────────────────────────────────────────

simulation_router = APIRouter(prefix="/api/simulation", tags=["Simulation"])


@simulation_router.get("/status")
def simulation_status():
    """Текущий статус симулятора: запущен/остановлен, тики, сценарий."""
    sim = get_simulator()
    if sim is None:
        return {"running": False, "message": "Simulator not initialized"}
    return sim.get_status()


@simulation_router.post("/start")
async def simulation_start():
    """Запустить симулятор, если он остановлен."""
    sim = get_simulator()
    if sim is None:
        raise HTTPException(503, "Simulator not initialized")
    if sim._running:
        return {"ok": True, "already_running": True, "status": sim.get_status()}
    await sim.start()
    return {"ok": True, "status": sim.get_status()}


@simulation_router.post("/stop")
async def simulation_stop():
    """Остановить симулятор."""
    sim = get_simulator()
    if sim is None or not sim._running:
        return {"ok": True, "was_running": False}
    await sim.stop()
    return {"ok": True, "was_running": True}


@simulation_router.post("/scenario/{scenario_name}")
async def set_scenario(scenario_name: str):
    """Переключить сценарий симуляции: normal | storm | overload | heatwave."""
    try:
        scenario = Scenario(scenario_name)
    except ValueError:
        raise HTTPException(400, f"Unknown scenario. Available: {[s.value for s in Scenario]}")
    sim = get_simulator()
    if sim is None:
        raise HTTPException(503, "Simulator not initialized")
    sim.set_scenario(scenario)
    return {"ok": True, "scenario": scenario}


@simulation_router.get("/live")
def simulation_live():
    """Мгновенный снимок состояний всех активов из памяти (без обращения к БД)."""
    sim = get_simulator()
    if sim is None or not sim._running:
        return {"running": False, "states": []}
    return {
        "running":   True,
        "sim_time":  sim.sim_time.isoformat(),
        "scenario":  sim.scenario,
        "states":    sim.get_live_states(),
    }


@simulation_router.get("/sensor-history/{asset_id}")
def sensor_history(asset_id: int, hours: int = 24, db: Session = Depends(get_db)):
    """История показаний датчиков объекта за последние N симулированных часов."""
    from models import SensorSnapshot
    from sqlalchemy import desc as sa_desc
    limit = min(hours * 4, 500)   # 4 снимка в час, не более 500 строк
    rows = (
        db.query(SensorSnapshot)
        .filter(SensorSnapshot.asset_id == asset_id)
        .order_by(sa_desc(SensorSnapshot.recorded_at))
        .limit(limit).all()
    )
    rows.reverse()   # хронологический порядок для графиков
    return [
        {
            "ts":          r.recorded_at.isoformat(),
            "load_pct":    r.load_percent,
            "temp_c":      r.temperature_c,
            "voltage_dev": r.voltage_deviation,
            "current_a":   r.current_a,
            "vibration":   r.vibration_level,
        }
        for r in rows
    ]


@simulation_router.post("/speed")
def set_speed(sim_speed: float, tick_interval_sec: float = None):
    """Изменить скорость симуляции на лету (без перезапуска).

    sim_speed — симулированных часов за один тик (0.1 .. 168).
    tick_interval_sec — интервал между тиками в реальных секундах (5 .. 3600).
    """
    sim = get_simulator()
    if sim is None:
        raise HTTPException(503, "Simulator not initialized")
    if not (0.1 <= sim_speed <= 168):
        raise HTTPException(400, "sim_speed must be 0.1..168")
    sim.sim_speed = sim_speed
    if tick_interval_sec is not None:
        if not (5 <= tick_interval_sec <= 3600):
            raise HTTPException(400, "tick_interval_sec must be 5..3600")
        sim.tick_interval_sec = tick_interval_sec
    return {"ok": True, "sim_speed": sim.sim_speed, "tick_interval_sec": sim.tick_interval_sec}


# ─── WebSocket — live-поток данных симулятора ─────────────────────────────────

ws_router = APIRouter(tags=["WebSocket"])


@ws_router.websocket("/ws/simulation")
async def ws_simulation(websocket: WebSocket):
    """
    WebSocket live-поток: сервер отправляет JSON на каждом тике симулятора.

    Формат сообщения от сервера:
      { "type":"tick", "sim_time":"...", "scenario":"normal",
        "tick":42, "ambient_temp":18.5, "states":[...] }

    Команды от клиента:
      {"cmd":"scenario", "value":"storm"}  — переключить сценарий
      {"cmd":"speed",    "value":2.0}      — изменить скорость
      {"cmd":"status"}                     — запросить статус

    Ping каждые 60 секунд для поддержания соединения.
    """
    await websocket.accept()
    sim = get_simulator()

    # Отправляем начальное состояние при подключении
    await websocket.send_json({
        "type":   "connected",
        "status": sim.get_status() if sim else {"running": False},
        "states": sim.get_live_states() if (sim and sim._running) else [],
    })

    # Регистрируем колбэк: симулятор будет вызывать push() на каждом тике
    async def push(payload: dict):
        await websocket.send_json(payload)

    if sim:
        sim.register_ws_callback(push)

    try:
        while True:
            try:
                # Ждём команды от клиента (с таймаутом для ping)
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=60.0)
                msg = json.loads(raw)
                cmd = msg.get("cmd")
                if cmd == "scenario" and sim:
                    try:
                        sim.set_scenario(Scenario(msg.get("value", "normal")))
                        await websocket.send_json({"type": "ack", "cmd": "scenario", "value": sim.scenario})
                    except ValueError:
                        await websocket.send_json({"type": "error", "msg": "Unknown scenario"})
                elif cmd == "speed" and sim:
                    sim.sim_speed = max(0.1, min(168, float(msg.get("value", 1.0))))
                    await websocket.send_json({"type": "ack", "cmd": "speed", "value": sim.sim_speed})
                elif cmd == "status":
                    await websocket.send_json({
                        "type":   "status",
                        "status": sim.get_status() if sim else {"running": False},
                    })
            except asyncio.TimeoutError:
                # Клиент молчит — отправляем ping чтобы не закрылось соединение
                await websocket.send_json({"type": "ping"})
    except WebSocketDisconnect:
        pass
    finally:
        # Убираем колбэк при отключении клиента
        if sim:
            sim.unregister_ws_callback(push)
