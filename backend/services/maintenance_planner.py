"""
services/maintenance_planner.py
Алгоритм автоматического формирования плана ТОиР.
"""
import logging
from datetime import date, timedelta
from typing import List

from sqlalchemy.orm import Session

from models import Asset, RiskScore, MaintenancePlan, Repair, Inspection

logger = logging.getLogger(__name__)

# Максимальное число объектов на обслуживание в один день
MAX_PER_DAY = 5


def compute_priority_score(
    risk_probability: float,
    criticality: float,
    days_since_maintenance: float,
) -> float:
    """
    Приоритет обслуживания: [0..1], выше = срочнее.
    """
    return (
        risk_probability * 0.50
        + criticality    * 0.30
        + min(days_since_maintenance / 365, 3) / 3 * 0.20
    )


def days_since_last_maintenance(asset: Asset) -> float:
    if not asset.repairs:
        # Если ремонтов не было — считаем от даты установки
        if asset.installed_date:
            return (date.today() - asset.installed_date).days
        return 730.0
    last_repair = max(asset.repairs, key=lambda r: r.completed_at or r.started_at)
    ts = last_repair.completed_at or last_repair.started_at
    return (date.today() - ts.date()).days


def generate_plan(db: Session, horizon_days: int = 180) -> List[dict]:
    """
    Генерирует план ТОиР на ближайшие horizon_days дней.
    Возвращает список словарей с деталями плана.
    """
    # Загрузить все активные активы с последним риском
    assets = db.query(Asset).filter(Asset.status == "active").all()

    # Удалить старые auto-generated планы со статусом 'scheduled'
    db.query(MaintenancePlan).filter(
        MaintenancePlan.auto_generated == True,
        MaintenancePlan.status == "scheduled",
    ).delete()
    db.flush()

    scored = []
    for asset in assets:
        # Последний риск-скор
        latest_risk = (
            db.query(RiskScore)
            .filter(RiskScore.asset_id == asset.id)
            .order_by(RiskScore.calculated_at.desc())
            .first()
        )
        risk_prob = latest_risk.risk_probability if latest_risk else 0.3

        dsm = days_since_last_maintenance(asset)
        priority = compute_priority_score(risk_prob, asset.criticality, dsm)

        scored.append({
            "asset": asset,
            "risk_prob": risk_prob,
            "priority": priority,
            "days_since_maint": dsm,
        })

    # Сортировка по приоритету
    scored.sort(key=lambda x: x["priority"], reverse=True)

    today = date.today()
    plan_records = []
    day_counter = {}  # date → count

    for rank, item in enumerate(scored, 1):
        risk = item["risk_prob"]
        priority = item["priority"]

        # Окно планирования по уровню риска
        if risk >= 0.60:
            window_start, window_end = 1, 30
        elif risk >= 0.30:
            window_start, window_end = 15, 90
        else:
            window_start, window_end = 60, 180

        # Найти первый доступный день
        plan_day = None
        for offset in range(window_start, min(window_end, horizon_days) + 1):
            candidate = today + timedelta(days=offset)
            if day_counter.get(candidate, 0) < MAX_PER_DAY:
                plan_day = candidate
                day_counter[candidate] = day_counter.get(candidate, 0) + 1
                break

        if plan_day is None:
            continue  # не удалось разместить

        maint_type = (
            "emergency_inspection" if risk >= 0.60
            else "planned_maintenance" if risk >= 0.30
            else "routine_inspection"
        )

        estimated_h = {"emergency_inspection": 8, "planned_maintenance": 16, "routine_inspection": 4}[maint_type]
        base_cost   = {"emergency_inspection": 50000, "planned_maintenance": 120000, "routine_inspection": 15000}[maint_type]
        cost = base_cost * (0.8 + item["asset"].criticality * 0.5)

        plan = MaintenancePlan(
            asset_id=item["asset"].id,
            plan_date=plan_day,
            priority=rank,
            maintenance_type=maint_type,
            estimated_duration_h=estimated_h,
            estimated_cost=round(cost, 2),
            status="scheduled",
            auto_generated=True,
            notes=(
                f"Риск: {risk * 100:.1f}%, "
                f"Приоритет: {priority:.3f}, "
                f"Без ТО {item['days_since_maint']:.0f} дней"
            ),
        )
        db.add(plan)
        plan_records.append({
            "asset_id": item["asset"].id,
            "asset_name": item["asset"].name,
            "plan_date": plan_day.isoformat(),
            "priority": rank,
            "maintenance_type": maint_type,
            "risk_percent": round(risk * 100, 1),
            "estimated_cost": round(cost, 2),
        })

    db.commit()
    logger.info(f"Maintenance plan generated: {len(plan_records)} items")
    return plan_records
