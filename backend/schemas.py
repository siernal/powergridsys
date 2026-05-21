"""
schemas.py — Pydantic-схемы для валидации запросов и формирования ответов API.

Соглашение:
  *Create  — тело POST-запроса (входные данные от клиента)
  *Out     — тело ответа API (исходящие данные)
  *Detail  — расширенная версия *Out с агрегированными полями
"""
from datetime import datetime, date
from typing import Optional, List, Any
from pydantic import BaseModel, Field


# ─── Аутентификация ───────────────────────────────────────────────────────────

class Token(BaseModel):
    """JWT-токен, возвращаемый при успешном логине."""
    access_token: str
    token_type: str   # всегда "bearer"


class UserOut(BaseModel):
    """Данные текущего пользователя (без пароля)."""
    id: int
    username: str
    full_name: Optional[str]
    role: str         # admin/engineer/inspector/viewer
    email: Optional[str]

    class Config:
        from_attributes = True


# ─── Тип объекта ─────────────────────────────────────────────────────────────

class AssetTypeOut(BaseModel):
    """Запись справочника типов оборудования."""
    id: int
    name: str
    category: str               # transformer/line/substation/cable
    base_lifetime_years: int    # нормативный срок службы, лет
    criticality_default: float  # базовая критичность 0..1

    class Config:
        from_attributes = True


# ─── Объект электросети ───────────────────────────────────────────────────────

class AssetCreate(BaseModel):
    """Тело запроса при создании нового объекта через POST /api/assets."""
    name: str
    asset_type_id: int
    location_lat: Optional[float] = None
    location_lon: Optional[float] = None
    region: Optional[str] = None
    installed_date: date
    voltage_class: Optional[str] = None
    criticality: float = Field(default=0.5, ge=0, le=1)  # ge/le = ограничения диапазона
    status: str = "active"


class AssetUpdate(BaseModel):
    """Тело PATCH-подобного запроса при изменении объекта через PUT /api/assets/{id}.

    Все поля опциональны: передаются только те, которые надо обновить.
    """
    name: Optional[str] = None
    asset_type_id: Optional[int] = None
    location_lat: Optional[float] = None
    location_lon: Optional[float] = None
    region: Optional[str] = None
    installed_date: Optional[date] = None
    voltage_class: Optional[str] = None
    criticality: Optional[float] = Field(default=None, ge=0, le=1)
    status: Optional[str] = None


class AssetOut(BaseModel):
    """Базовое представление объекта в списках и ответах API."""
    id: int
    name: str
    asset_type_id: int
    asset_type: Optional[AssetTypeOut]      # вложенный тип (JOIN)
    location_lat: Optional[float]
    location_lon: Optional[float]
    region: Optional[str]
    installed_date: Optional[date]
    voltage_class: Optional[str]
    criticality: float
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class AssetDetail(AssetOut):
    """Расширенная карточка объекта — используется на странице AssetDetail.

    Поля вычисляются в роутере на основе связанных записей
    (отказов, ремонтов, риск-скоров, digital twin).
    """
    age_years: Optional[float] = None                  # лет в эксплуатации
    failures_count: Optional[int] = 0                  # всего отказов
    repairs_count: Optional[int] = 0                   # всего ремонтов
    latest_inspection_score: Optional[int] = None      # последняя оценка осмотра 1..5
    days_since_maintenance: Optional[float] = None     # дней с последнего ТО
    latest_risk_probability: Optional[float] = None    # текущая вероятность отказа
    latest_risk_level: Optional[str] = None            # low/medium/high
    health_score: Optional[float] = None               # балл здоровья из digital twin 0..100


# ─── Осмотры ─────────────────────────────────────────────────────────────────

class InspectionCreate(BaseModel):
    """Тело запроса при добавлении записи об осмотре."""
    asset_id: int
    inspected_at: datetime
    condition_score: int = Field(ge=1, le=5)       # оценка состояния 1..5
    defects_found: Optional[str] = None
    notes: Optional[str] = None


class InspectionUpdate(BaseModel):
    """Тело запроса при редактировании записи об осмотре."""
    inspected_at: Optional[datetime] = None
    condition_score: Optional[int] = Field(default=None, ge=1, le=5)
    defects_found: Optional[str] = None
    notes: Optional[str] = None


class InspectionOut(BaseModel):
    """Запись осмотра в ответе API."""
    id: int
    asset_id: int
    inspected_at: datetime
    condition_score: int
    defects_found: Optional[str]
    notes: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# ─── Ремонты ─────────────────────────────────────────────────────────────────

class RepairCreate(BaseModel):
    """Тело запроса при фиксации факта ремонта."""
    asset_id: int
    repair_type: str           # planned/emergency/capital
    started_at: datetime
    completed_at: Optional[datetime] = None   # None если ремонт ещё не завершён
    cost: Optional[float] = None
    work_description: Optional[str] = None
    performed_by: Optional[str] = None


class RepairUpdate(BaseModel):
    """Тело запроса при редактировании записи о ремонте."""
    repair_type: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    cost: Optional[float] = None
    work_description: Optional[str] = None
    performed_by: Optional[str] = None


class RepairOut(BaseModel):
    """Запись ремонта в ответе API."""
    id: int
    asset_id: int
    repair_type: str
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    cost: Optional[float]
    work_description: Optional[str]
    performed_by: Optional[str]

    class Config:
        from_attributes = True


# ─── Отказы ──────────────────────────────────────────────────────────────────

class FailureCreate(BaseModel):
    """Тело запроса при регистрации отказа оборудования."""
    asset_id: int
    failed_at: datetime
    failure_type: Optional[str] = None
    severity: str = "minor"              # minor/major/critical
    downtime_hours: Optional[float] = None
    root_cause: Optional[str] = None


class FailureUpdate(BaseModel):
    """Тело запроса при редактировании записи об отказе."""
    failed_at: Optional[datetime] = None
    failure_type: Optional[str] = None
    severity: Optional[str] = None
    downtime_hours: Optional[float] = None
    root_cause: Optional[str] = None
    resolved_at: Optional[datetime] = None


class FailureOut(BaseModel):
    """Запись об отказе в ответе API."""
    id: int
    asset_id: int
    failed_at: datetime
    failure_type: Optional[str]
    severity: str
    downtime_hours: Optional[float]
    root_cause: Optional[str]
    resolved_at: Optional[datetime]    # время устранения

    class Config:
        from_attributes = True


# ─── Риск-скор ───────────────────────────────────────────────────────────────

class RiskScoreOut(BaseModel):
    """Результат расчёта риска ML-моделью для одного объекта."""
    id: int
    asset_id: int
    calculated_at: datetime
    risk_probability: float      # 0..1
    risk_level: str              # low/medium/high
    feature_snapshot: Optional[Any]   # JSON с признаками на момент расчёта
    model_version: Optional[str]

    class Config:
        from_attributes = True


# ─── Планы ТОиР ──────────────────────────────────────────────────────────────

class MaintenancePlanOut(BaseModel):
    """Запись плана ТО в ответе API.

    asset_name вычисляется в роутере через JOIN и не хранится в таблице.
    """
    id: int
    asset_id: int
    asset_name: Optional[str] = None          # имя объекта (вычисляется через JOIN)
    plan_date: date
    priority: Optional[int]                   # порядковый номер в плане
    maintenance_type: Optional[str]           # emergency_inspection/planned_maintenance/routine_inspection
    estimated_duration_h: Optional[float]     # оценочная длительность, ч
    estimated_cost: Optional[float]           # оценочная стоимость, руб.
    status: str                               # scheduled/completed/cancelled
    notes: Optional[str]
    auto_generated: bool                      # True = создано алгоритмом

    class Config:
        from_attributes = True


# ─── Аналитика ───────────────────────────────────────────────────────────────

class AnalyticsSummary(BaseModel):
    """Сводные KPI для главного дашборда.

    Все счётчики рассчитываются в роутере /api/analytics/summary
    за один запрос к БД с несколькими агрегатами.
    """
    total_assets: int                  # всего объектов на балансе
    active: int                        # статус active
    in_maintenance: int                # статус maintenance
    failed: int                        # статус failed
    high_risk_count: int               # последний риск-скор = high
    medium_risk_count: int
    low_risk_count: int
    total_failures_last_year: int      # отказов за последние 365 дней
    total_repairs_last_year: int       # ремонтов за последние 365 дней
    avg_health_score: Optional[float]  # средний health из digital twin (None если граф не построен)
    upcoming_maintenance_count: int    # запланированных работ на ближайшие 30 дней
