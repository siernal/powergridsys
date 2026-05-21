"""
services/transformer_simulator.py

Динамический симулятор состояния активов электросети.
Реализует:
  - Тепловую модель трансформатора (упрощённая IEEE C57.91)
  - Суточный/сезонный профиль нагрузки
  - Накопление деградации изоляции (модель Монтзингера)
  - Генерацию SensorSnapshot в БД на каждом тике
  - Обновление Digital Twin
  - Генерацию FailureEvent при превышении порогов
  - Сценарии: NORMAL / STORM / OVERLOAD / HEATWAVE
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════════════
#  Сценарии
# ════════════════════════════════════════════════════════════════════════════

class Scenario(str, Enum):
    NORMAL   = "normal"
    STORM    = "storm"
    OVERLOAD = "overload"
    HEATWAVE = "heatwave"


# ════════════════════════════════════════════════════════════════════════════
#  Профиль нагрузки
# ════════════════════════════════════════════════════════════════════════════

def daily_load_factor(hour: float, scenario: Scenario) -> float:
    """
    Суточный коэффициент нагрузки [0..1].
    Реалистичный двухпиковый профиль (утренний + вечерний пик).
    """
    # Базовый профиль через сумму синусоид
    base = (
        0.50
        + 0.18 * math.sin(math.pi * (hour - 6) / 12)   # дневной подъём
        + 0.12 * math.sin(math.pi * (hour - 18) / 6)   # вечерний пик
        - 0.10 * math.cos(2 * math.pi * hour / 24)     # ночная депрессия
    )
    base = max(0.25, min(1.0, base))

    if scenario == Scenario.OVERLOAD:
        base = min(1.0, base * 1.35 + 0.10)
    elif scenario == Scenario.STORM:
        base = max(0.30, base - 0.15 + random.gauss(0, 0.08))
    elif scenario == Scenario.HEATWAVE:
        # кондиционеры ночью тоже работают
        base = min(1.0, base * 1.20 + 0.08)

    return round(max(0.20, min(1.0, base)), 4)


def seasonal_factor(month: int) -> float:
    """Сезонный коэффициент нагрузки."""
    # Пики зимой (отопление) и летом (кондиционирование)
    return 1.0 + 0.12 * math.cos(math.pi * (month - 1) / 6)


# ════════════════════════════════════════════════════════════════════════════
#  Тепловая модель (IEEE C57.91 упрощённая)
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class ThermalState:
    """Тепловое состояние масляного трансформатора."""
    # Температура верхнего масла, °C
    oil_temp: float = 40.0
    # Горячая точка (hot-spot), °C
    hotspot_temp: float = 50.0
    # Накопленный индекс деградации изоляции (0..∞, 1 = нормальная скорость)
    aging_index: float = 0.0
    # Счётчик тепловых циклов
    thermal_cycles: int = 0
    # Предыдущая нагрузка (для подсчёта циклов)
    _prev_load: float = 0.65

    # Постоянные времени
    TAU_OIL_H: float = 3.0       # часы
    TAU_HOTSPOT_H: float = 0.5   # часы
    THETA_AMBIENT_BASE: float = 20.0
    DELTA_THETA_OIL_RATED: float = 35.0   # °C при номинале
    DELTA_THETA_HS_RATED: float  = 23.0   # °C добавка от hot-spot
    N_EXPONENT: float = 0.8              # ONAN трансформатор

    # Пороги
    HOTSPOT_ALARM: float  = 110.0   # °C — тревога
    HOTSPOT_TRIP:  float  = 130.0   # °C — аварийное отключение
    AGING_LIMIT:   float  = 500.0   # условные единицы деградации

    def step(
        self,
        load_factor: float,
        ambient_temp: float,
        dt_hours: float,
    ) -> dict:
        """
        Сделать шаг симуляции dt_hours часов.
        Возвращает словарь с текущими параметрами.
        """
        # Установившаяся температура масла при данной нагрузке
        oil_steady = (
            ambient_temp
            + self.DELTA_THETA_OIL_RATED * (load_factor ** (2 * self.N_EXPONENT))
        )
        # Экспоненциальный переходной процесс (первый порядок)
        alpha_oil = dt_hours / self.TAU_OIL_H
        self.oil_temp += (oil_steady - self.oil_temp) * min(alpha_oil, 1.0)

        # Hot-spot: масло + добавка от тока
        hs_steady = self.oil_temp + self.DELTA_THETA_HS_RATED * (load_factor ** 1.6)
        alpha_hs = dt_hours / self.TAU_HOTSPOT_H
        self.hotspot_temp += (hs_steady - self.hotspot_temp) * min(alpha_hs, 1.0)

        # Деградация изоляции (Монтзингер/Arrhenius):
        # Скорость деградации удваивается на каждые 6°C выше 98°C
        theta_ref = 98.0
        aging_rate = 2 ** ((self.hotspot_temp - theta_ref) / 6.0)
        self.aging_index += aging_rate * dt_hours

        # Тепловые циклы: переход нагрузка ↑/↓ через порог 0.80
        if self._prev_load < 0.80 <= load_factor:
            self.thermal_cycles += 1
        self._prev_load = load_factor

        return {
            "oil_temp":      round(self.oil_temp, 2),
            "hotspot_temp":  round(self.hotspot_temp, 2),
            "aging_index":   round(self.aging_index, 3),
            "thermal_cycles": self.thermal_cycles,
            "aging_rate":    round(aging_rate, 4),
            "alarm":         self.hotspot_temp >= self.HOTSPOT_ALARM,
            "trip":          self.hotspot_temp >= self.HOTSPOT_TRIP,
        }


# ════════════════════════════════════════════════════════════════════════════
#  Состояние одного актива в симуляторе
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class AssetSimState:
    asset_id: int
    category: str
    nominal_load_pct: float = 65.0   # базовая нагрузка в %
    thermal: ThermalState = field(default_factory=ThermalState)
    # Текущая нагрузка %
    load_pct: float = 65.0
    # Текущее напряжение (отклонение от номинала, %)
    voltage_dev: float = 0.0
    # Ток (А) — условный
    current_a: float = 100.0
    # Вибрация (мм/с) — для подстанций/трансформаторов
    vibration: float = 0.5
    # Счётчик малых дефектов (не записывается в БД как Failure напрямую)
    micro_fault_accumulator: float = 0.0
    # Запущено ли аварийное отключение
    tripped: bool = False
    # Счётчик записанных отказов
    failures_logged: int = 0


# ════════════════════════════════════════════════════════════════════════════
#  Главный класс симулятора
# ════════════════════════════════════════════════════════════════════════════

class TransformerSimulator:
    """
    Фоновый симулятор состояния активов.

    Запуск:
        sim = TransformerSimulator(db_session_factory, get_twin)
        await sim.start()

    Остановка:
        await sim.stop()
    """

    def __init__(
        self,
        db_session_factory: Callable,
        twin_getter: Callable,
        tick_interval_sec: float = 30.0,
        sim_speed: float = 1.0,
    ):
        """
        db_session_factory — фабрика SQLAlchemy-сессий (contextmanager или callable).
        twin_getter        — функция, возвращающая DigitalTwin.
        tick_interval_sec  — как часто (в реальных секундах) делается тик.
        sim_speed          — сколько симулированных часов проходит за один тик.
                             По умолчанию 1.0 → каждые 30 сек = 1 час симвремени.
        """
        self._db_factory = db_session_factory
        self._twin_getter = twin_getter
        self.tick_interval_sec = tick_interval_sec
        self.sim_speed = sim_speed  # sim-часов / реальный тик

        self.scenario: Scenario = Scenario.NORMAL
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # Симулированное время (стартует с текущего)
        self.sim_time: datetime = datetime.utcnow()

        # Состояния активов: {asset_id: AssetSimState}
        self._states: Dict[int, AssetSimState] = {}

        # Список WebSocket-колбэков для push-уведомлений
        self._ws_callbacks: List[Callable] = []

        # Статистика тиков
        self.ticks_done: int = 0
        self.snapshots_written: int = 0
        self.failures_generated: int = 0

        logger.info("TransformerSimulator created (tick=%.1fs, speed=%.1f sim-h/tick)",
                    tick_interval_sec, sim_speed)

    # ── Управление ─────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._running:
            logger.warning("Simulator already running")
            return
        self._running = True
        await self._load_assets()
        self._task = asyncio.create_task(self._loop())
        logger.info("Simulator started, %d assets loaded", len(self._states))

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Simulator stopped after %d ticks", self.ticks_done)

    def set_scenario(self, scenario: Scenario) -> None:
        self.scenario = scenario
        logger.info("Scenario changed to: %s", scenario)

    def register_ws_callback(self, cb: Callable) -> None:
        """Зарегистрировать колбэк для отправки обновлений через WebSocket."""
        self._ws_callbacks.append(cb)

    def unregister_ws_callback(self, cb: Callable) -> None:
        self._ws_callbacks = [c for c in self._ws_callbacks if c is not cb]

    def get_status(self) -> dict:
        return {
            "running":             self._running,
            "scenario":            self.scenario,
            "sim_time":            self.sim_time.isoformat(),
            "ticks_done":          self.ticks_done,
            "snapshots_written":   self.snapshots_written,
            "failures_generated":  self.failures_generated,
            "assets_tracked":      len(self._states),
            "tick_interval_sec":   self.tick_interval_sec,
            "sim_speed_h_per_tick": self.sim_speed,
        }

    def get_live_states(self) -> list:
        """Текущие live-состояния всех активов (без обращения к БД)."""
        result = []
        for aid, st in self._states.items():
            result.append({
                "asset_id":     aid,
                "category":     st.category,
                "load_pct":     round(st.load_pct, 1),
                "oil_temp":     round(st.thermal.oil_temp, 1),
                "hotspot_temp": round(st.thermal.hotspot_temp, 1),
                "voltage_dev":  round(st.voltage_dev, 2),
                "current_a":    round(st.current_a, 1),
                "vibration":    round(st.vibration, 3),
                "aging_index":  round(st.thermal.aging_index, 2),
                "tripped":      st.tripped,
            })
        return result

    # ── Внутренняя логика ──────────────────────────────────────────────────

    async def _load_assets(self) -> None:
        """Загрузить активы из БД и создать начальные состояния."""
        from models import Asset, AssetType, SensorSnapshot
        from sqlalchemy import desc

        db = self._db_factory()
        try:
            assets = db.query(Asset).join(AssetType).all()
            for asset in assets:
                # Берём последний сенсорный снимок как начальное состояние
                last_snap = (
                    db.query(SensorSnapshot)
                    .filter(SensorSnapshot.asset_id == asset.id)
                    .order_by(desc(SensorSnapshot.recorded_at))
                    .first()
                )
                init_load = last_snap.load_percent if last_snap else 60.0 + random.gauss(0, 8)
                init_temp = last_snap.temperature_c if last_snap else 40.0 + random.gauss(0, 5)

                thermal = ThermalState(
                    oil_temp=init_temp,
                    hotspot_temp=init_temp + 10,
                )
                self._states[asset.id] = AssetSimState(
                    asset_id=asset.id,
                    category=asset.asset_type.category if asset.asset_type else "line",
                    nominal_load_pct=init_load,
                    thermal=thermal,
                    load_pct=init_load,
                )
        finally:
            db.close()

    async def _loop(self) -> None:
        """Основной цикл симуляции."""
        while self._running:
            try:
                await self._tick()
            except Exception as exc:
                logger.exception("Simulator tick error: %s", exc)
            await asyncio.sleep(self.tick_interval_sec)

    async def _tick(self) -> None:
        """Один тик симуляции."""
        from models import Asset, SensorSnapshot, FailureEvent, RiskScore
        from services.digital_twin import get_twin, asset_age
        from services.maintenance_planner import days_since_last_maintenance
        from sqlalchemy import func, desc

        dt_hours = self.sim_speed
        self.sim_time += timedelta(hours=dt_hours)
        hour  = self.sim_time.hour + self.sim_time.minute / 60.0
        month = self.sim_time.month

        # Ambient temperature: суточный цикл + сезон
        ambient_temp = (
            5.0
            + 15.0 * math.sin(math.pi * (month - 3) / 6)
            + 8.0  * math.sin(math.pi * (hour - 6) / 12)
            + random.gauss(0, 1.5)
        )
        if self.scenario == Scenario.HEATWAVE:
            ambient_temp += 15.0
        elif self.scenario == Scenario.STORM:
            ambient_temp -= 3.0 + random.uniform(0, 4)

        lf_base = daily_load_factor(hour, self.scenario) * seasonal_factor(month)

        db = self._db_factory()
        twin = self._twin_getter()
        snapshots_batch = []
        failures_batch  = []
        risk_batch      = []

        try:
            # Подгружаем необходимые данные одним запросом
            from models import Repair
            from sqlalchemy import func as sqlfunc

            asset_failures = dict(
                db.query(FailureEvent.asset_id, sqlfunc.count(FailureEvent.id))
                .group_by(FailureEvent.asset_id).all()
            )
            asset_repairs = dict(
                db.query(Repair.asset_id, sqlfunc.count(Repair.id))
                .group_by(Repair.asset_id).all()
            )

            for asset_id, st in self._states.items():
                if st.tripped:
                    # Авария: постепенно остывает, нагрузка = 0
                    st.load_pct = 0.0
                    st.thermal.oil_temp = max(ambient_temp + 5, st.thermal.oil_temp - 2 * dt_hours)
                    continue

                # ── Нагрузка ──────────────────────────────────────────────
                # Каждый актив имеет небольшое индивидуальное смещение
                rng_seed = asset_id % 17
                load_jitter = math.sin(asset_id * 1.37 + hour) * 0.06
                category_factor = {
                    "transformer": 1.00,
                    "substation":  0.95,
                    "line":        1.05,
                    "cable":       0.92,
                }.get(st.category, 1.0)

                load_pct = (
                    st.nominal_load_pct
                    * lf_base
                    * category_factor
                    * (1.0 + load_jitter)
                    + random.gauss(0, 2.0)
                )
                load_pct = max(5.0, min(115.0, load_pct))
                st.load_pct = load_pct
                load_factor = load_pct / 100.0

                # ── Тепловая модель ───────────────────────────────────────
                thermal_result = st.thermal.step(
                    load_factor=load_factor,
                    ambient_temp=ambient_temp,
                    dt_hours=dt_hours,
                )

                # ── Электрические параметры ───────────────────────────────
                # Отклонение напряжения (при перегрузке падает)
                v_drop = -0.8 * max(0, load_factor - 0.75) + random.gauss(0, 0.3)
                st.voltage_dev = round(max(-8.0, min(5.0, v_drop)), 2)

                # Ток (условный, пропорционален нагрузке)
                st.current_a = round(load_factor * 200.0 + random.gauss(0, 5), 1)

                # Вибрация (растёт при деградации и перегрузке)
                aging_factor = 1.0 + st.thermal.aging_index / 300.0
                vib_base = 0.3 + 0.4 * load_factor
                st.vibration = round(
                    max(0.1, min(5.0, vib_base * aging_factor + random.gauss(0, 0.05))),
                    3
                )

                # ── Микро-дефекты → вероятность отказа ───────────────────
                # Накапливаем "стресс" при перегрузке и высокой температуре
                stress = 0.0
                if load_pct > 90:
                    stress += (load_pct - 90) * 0.005
                if thermal_result["hotspot_temp"] > 105:
                    stress += (thermal_result["hotspot_temp"] - 105) * 0.004
                if self.scenario == Scenario.STORM:
                    stress += 0.02 * random.random()
                st.micro_fault_accumulator += stress * dt_hours

                # ── Генерация отказа ──────────────────────────────────────
                failure_event = None
                if thermal_result["trip"]:
                    # Тепловое отключение
                    st.tripped = True
                    failure_event = self._build_failure(
                        asset_id, "thermal_trip",
                        "critical", 8.0 + random.uniform(0, 16),
                        f"Аварийное отключение: горячая точка {thermal_result['hotspot_temp']:.1f}°C"
                    )
                elif st.micro_fault_accumulator > 1.5 and random.random() < 0.15:
                    # Накопленный стресс → вероятностный отказ
                    st.micro_fault_accumulator *= 0.3
                    sev = "major" if st.micro_fault_accumulator > 1.0 else "minor"
                    failure_event = self._build_failure(
                        asset_id, "stress_failure", sev,
                        2.0 + random.uniform(0, 6),
                        f"Отказ вследствие накопленного стресса (нагрузка {load_pct:.0f}%)"
                    )
                    st.failures_logged += 1

                if failure_event:
                    failures_batch.append(failure_event)
                    self.failures_generated += 1

                # ── Запись SensorSnapshot ─────────────────────────────────
                snap = SensorSnapshot(
                    asset_id=asset_id,
                    recorded_at=self.sim_time,
                    load_percent=round(load_pct, 1),
                    temperature_c=round(thermal_result["oil_temp"], 1),
                    voltage_deviation=st.voltage_dev,
                    current_a=st.current_a,
                    vibration_level=st.vibration,
                )
                snapshots_batch.append(snap)

                # ── Обновление Digital Twin ───────────────────────────────
                failures_cnt = asset_failures.get(asset_id, 0) + st.failures_logged
                repairs_cnt  = asset_repairs.get(asset_id, 0)

                from models import Asset as AssetModel
                asset_obj = db.query(AssetModel).filter(AssetModel.id == asset_id).first()
                if asset_obj:
                    dsm = days_since_last_maintenance(asset_obj)
                    age = asset_age(asset_obj.installed_date)
                    node_state = twin.update_node_state(
                        asset_id=asset_id,
                        failures_count=failures_cnt,
                        repairs_count=repairs_cnt,
                        days_since_maintenance=dsm,
                        load_percent=load_pct,
                        is_storm=(self.scenario == Scenario.STORM),
                        temperature=ambient_temp,
                    )

                    # ── RiskScore ─────────────────────────────────────────
                    # Пишем в БД каждые ~6 тиков (не захламляем таблицу)
                    if self.ticks_done % 6 == 0 and node_state:
                        risk_level = (
                            "high"   if node_state["risk"] >= 0.60 else
                            "medium" if node_state["risk"] >= 0.30 else
                            "low"
                        )
                        risk_batch.append(RiskScore(
                            asset_id=asset_id,
                            calculated_at=self.sim_time,
                            risk_probability=node_state["risk"],
                            risk_level=risk_level,
                            feature_snapshot={
                                "load_pct":    round(load_pct, 1),
                                "oil_temp":    round(thermal_result["oil_temp"], 1),
                                "hotspot":     round(thermal_result["hotspot_temp"], 1),
                                "aging_index": round(st.thermal.aging_index, 2),
                                "scenario":    self.scenario,
                            },
                            model_version="sim-1.0",
                        ))

            # ── Батч-запись в БД ──────────────────────────────────────────
            if snapshots_batch:
                db.bulk_save_objects(snapshots_batch)
                self.snapshots_written += len(snapshots_batch)
            if failures_batch:
                db.bulk_save_objects(failures_batch)
            if risk_batch:
                db.bulk_save_objects(risk_batch)
            db.commit()

        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

        self.ticks_done += 1

        # ── Push WS-обновления ────────────────────────────────────────────
        if self._ws_callbacks:
            payload = {
                "type":     "tick",
                "sim_time": self.sim_time.isoformat(),
                "scenario": self.scenario,
                "tick":     self.ticks_done,
                "states":   self.get_live_states()[:20],  # первые 20 для скорости
                "ambient_temp": round(ambient_temp, 1),
            }
            dead = []
            for cb in self._ws_callbacks:
                try:
                    await cb(payload)
                except Exception:
                    dead.append(cb)
            for cb in dead:
                self.unregister_ws_callback(cb)

        logger.debug(
            "Tick #%d | sim_time=%s | load_base=%.0f%% | snaps=%d | fails=%d",
            self.ticks_done,
            self.sim_time.strftime("%Y-%m-%d %H:%M"),
            lf_base * 100,
            len(snapshots_batch),
            len(failures_batch),
        )

    @staticmethod
    def _build_failure(
        asset_id: int,
        failure_type: str,
        severity: str,
        downtime_h: float,
        root_cause: str,
    ):
        from models import FailureEvent
        return FailureEvent(
            asset_id=asset_id,
            failed_at=datetime.utcnow(),
            failure_type=failure_type,
            severity=severity,
            downtime_hours=round(downtime_h, 1),
            root_cause=root_cause,
        )


# ════════════════════════════════════════════════════════════════════════════
#  Singleton
# ════════════════════════════════════════════════════════════════════════════

_simulator_instance: Optional[TransformerSimulator] = None


def get_simulator() -> Optional[TransformerSimulator]:
    return _simulator_instance


def create_simulator(db_factory: Callable, twin_getter: Callable, **kwargs) -> TransformerSimulator:
    global _simulator_instance
    _simulator_instance = TransformerSimulator(db_factory, twin_getter, **kwargs)
    return _simulator_instance
