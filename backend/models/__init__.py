"""
models/__init__.py — все ORM-модели приложения (SQLAlchemy).

Каждый класс соответствует таблице в PostgreSQL.
Схема создаётся автоматически через Base.metadata.create_all() при старте.
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, Text,
    DateTime, Date, Numeric, ForeignKey, JSON
)
from sqlalchemy.orm import relationship
from core.database import Base


# ─── Пользователи ────────────────────────────────────────────────────────────

class User(Base):
    """Учётная запись пользователя системы.

    Роли:
      admin     — полный доступ
      engineer  — просмотр + расчёт рисков + планирование
      inspector — добавление осмотров
      viewer    — только чтение
    """
    __tablename__ = "users"

    id            = Column(Integer, primary_key=True)
    username      = Column(String(100), unique=True, nullable=False)
    full_name     = Column(String(200))
    role          = Column(String(30), default="viewer")   # admin/engineer/inspector/viewer
    email         = Column(String(200))
    hashed_password = Column(Text)                         # bcrypt-хэш
    is_active     = Column(Boolean, default=True)          # False = заблокирован
    created_at    = Column(DateTime, default=datetime.utcnow)


# ─── Типы объектов ────────────────────────────────────────────────────────────

class AssetType(Base):
    """Справочник типов оборудования (нормативные характеристики).

    Используется как шаблон при создании нового объекта:
    нормативный срок службы и базовый коэффициент критичности берутся отсюда.
    """
    __tablename__ = "asset_types"

    id                   = Column(Integer, primary_key=True)
    name                 = Column(String(100), nullable=False)   # «Трансформатор 110кВ»
    category             = Column(String(50), nullable=False)    # transformer/line/substation/cable
    base_lifetime_years  = Column(Integer, default=30)           # нормативный срок службы, лет
    criticality_default  = Column(Float, default=0.5)            # базовая критичность 0..1

    assets = relationship("Asset", back_populates="asset_type")


# ─── Объекты электросети ──────────────────────────────────────────────────────

class Asset(Base):
    """Физический объект электросети (трансформатор, линия, подстанция, кабель).

    Центральная сущность системы — к ней привязаны осмотры, ремонты,
    отказы, датчики, риски и планы ТО.
    """
    __tablename__ = "assets"

    id              = Column(Integer, primary_key=True)
    name            = Column(String(200), nullable=False)        # «Трансформатор 110кВ №001»
    asset_type_id   = Column(Integer, ForeignKey("asset_types.id"))
    location_lat    = Column(Float)                              # широта (WGS-84)
    location_lon    = Column(Float)                              # долгота (WGS-84)
    region          = Column(String(100))                        # Северный / Южный / …
    installed_date  = Column(Date)                               # дата ввода в эксплуатацию
    voltage_class   = Column(String(20))                         # 0.4кВ / 10кВ / 35кВ / 110кВ
    criticality     = Column(Float, default=0.5)                 # итоговая критичность 0..1
    status          = Column(String(30), default="active")       # active/maintenance/failed/decommissioned
    parent_asset_id = Column(Integer, ForeignKey("assets.id"), nullable=True)  # иерархия
    created_at      = Column(DateTime, default=datetime.utcnow)

    asset_type        = relationship("AssetType", back_populates="assets")
    inspections       = relationship("Inspection", back_populates="asset")
    repairs           = relationship("Repair", back_populates="asset")
    failures          = relationship("FailureEvent", back_populates="asset")
    risk_scores       = relationship("RiskScore", back_populates="asset")
    maintenance_plans = relationship("MaintenancePlan", back_populates="asset")
    sensor_snapshots  = relationship("SensorSnapshot", back_populates="asset")


# ─── Осмотры ─────────────────────────────────────────────────────────────────

class Inspection(Base):
    """Запись о плановом или внеплановом осмотре объекта.

    condition_score 1..5: 1=аварийное состояние, 5=отличное.
    """
    __tablename__ = "inspections"

    id              = Column(Integer, primary_key=True)
    asset_id        = Column(Integer, ForeignKey("assets.id"))
    inspector_id    = Column(Integer, ForeignKey("users.id"), nullable=True)  # кто проводил
    inspected_at    = Column(DateTime, nullable=False)
    condition_score = Column(Integer)   # балл состояния 1..5
    defects_found   = Column(Text)      # описание выявленных дефектов
    notes           = Column(Text)      # произвольные заметки
    created_at      = Column(DateTime, default=datetime.utcnow)

    asset = relationship("Asset", back_populates="inspections")


# ─── Ремонты ─────────────────────────────────────────────────────────────────

class Repair(Base):
    """Запись о выполненном ремонте или техническом обслуживании.

    repair_type: planned = плановый ТО, emergency = аварийный, capital = капитальный.
    """
    __tablename__ = "repairs"

    id               = Column(Integer, primary_key=True)
    asset_id         = Column(Integer, ForeignKey("assets.id"))
    repair_type      = Column(String(50))      # planned/emergency/capital
    started_at       = Column(DateTime)
    completed_at     = Column(DateTime)        # None если ещё в процессе
    cost             = Column(Numeric(12, 2))  # стоимость, руб.
    work_description = Column(Text)
    performed_by     = Column(String(200))     # «Бригада №3»
    created_at       = Column(DateTime, default=datetime.utcnow)

    asset = relationship("Asset", back_populates="repairs")


# ─── Отказы ──────────────────────────────────────────────────────────────────

class FailureEvent(Base):
    """Факт отказа (аварии) оборудования.

    severity: minor = незначительный, major = серьёзный, critical = критический.
    downtime_hours — продолжительность простоя.
    """
    __tablename__ = "failure_events"

    id             = Column(Integer, primary_key=True)
    asset_id       = Column(Integer, ForeignKey("assets.id"))
    failed_at      = Column(DateTime, nullable=False)
    failure_type   = Column(String(100))    # «Пробой изоляции», «КЗ» и т.п.
    severity       = Column(String(20))     # minor/major/critical
    downtime_hours = Column(Float)          # часов простоя
    root_cause     = Column(Text)           # корневая причина
    resolved_at    = Column(DateTime)       # время устранения

    asset = relationship("Asset", back_populates="failures")


# ─── Риск-скоры ──────────────────────────────────────────────────────────────

class RiskScore(Base):
    """Результат расчёта риска отказа ML-моделью для одного объекта.

    feature_snapshot — снимок признаков, которые были использованы при расчёте
    (сохраняется для объяснимости прогноза).
    """
    __tablename__ = "risk_scores"

    id                = Column(Integer, primary_key=True)
    asset_id          = Column(Integer, ForeignKey("assets.id"))
    calculated_at     = Column(DateTime, default=datetime.utcnow)
    risk_probability  = Column(Float)          # вероятность отказа 0..1
    risk_level        = Column(String(10))     # low / medium / high
    feature_snapshot  = Column(JSON)           # признаки на момент расчёта
    model_version     = Column(String(20), default="1.0")

    asset = relationship("Asset", back_populates="risk_scores")


# ─── Планы ТО ────────────────────────────────────────────────────────────────

class MaintenancePlan(Base):
    """Запись в плане технического обслуживания и ремонта (ТОиР).

    auto_generated=True означает, что запись создана автоматически алгоритмом
    (а не добавлена вручную диспетчером).
    status: scheduled = запланировано, completed = выполнено, cancelled = отменено.
    """
    __tablename__ = "maintenance_plans"

    id                   = Column(Integer, primary_key=True)
    asset_id             = Column(Integer, ForeignKey("assets.id"))
    plan_date            = Column(Date, nullable=False)         # дата проведения
    priority             = Column(Integer)                      # порядковый номер приоритета
    maintenance_type     = Column(String(50))                   # emergency_inspection / planned_maintenance / routine_inspection
    estimated_duration_h = Column(Float)                        # оценочная длительность, ч
    estimated_cost       = Column(Numeric(10, 2))               # оценочная стоимость, руб.
    status               = Column(String(20), default="scheduled")
    auto_generated       = Column(Boolean, default=True)
    notes                = Column(Text)                         # автоматически заполняется деталями расчёта
    created_at           = Column(DateTime, default=datetime.utcnow)

    asset = relationship("Asset", back_populates="maintenance_plans")


# ─── Телеметрия датчиков ──────────────────────────────────────────────────────

class SensorSnapshot(Base):
    """Снимок показаний датчиков объекта в момент времени.

    Генерируется симулятором (TransformerSimulator) каждые 30 секунд
    реального времени (= 1 час симулированного времени).
    Используется ML-моделью как актуальная нагрузка и температура.
    """
    __tablename__ = "sensor_snapshots"

    id                = Column(Integer, primary_key=True)
    asset_id          = Column(Integer, ForeignKey("assets.id"))
    recorded_at       = Column(DateTime, default=datetime.utcnow)
    load_percent      = Column(Float)      # нагрузка, % от номинала
    temperature_c     = Column(Float)      # температура масла, °C
    voltage_deviation = Column(Float)      # отклонение напряжения от номинала, %
    current_a         = Column(Float)      # ток, А (условный)
    vibration_level   = Column(Float)      # вибрация, мм/с

    asset = relationship("Asset", back_populates="sensor_snapshots")


# ─── Погода ──────────────────────────────────────────────────────────────────

class WeatherSnapshot(Base):
    """Снимок погодных условий по региону за сутки.

    is_storm=True при wind_speed_ms > 15 и precipitation_mm > 10.
    Используется ML-моделью как внешний фактор риска.
    """
    __tablename__ = "weather_snapshots"

    id                = Column(Integer, primary_key=True)
    region            = Column(String(100))
    recorded_at       = Column(DateTime, default=datetime.utcnow)
    temperature_c     = Column(Float)
    humidity_percent  = Column(Float)
    wind_speed_ms     = Column(Float)
    precipitation_mm  = Column(Float)
    is_storm          = Column(Boolean, default=False)
