"""
services/digital_twin.py
Цифровая копия электросети — граф NetworkX с расчётом здоровья узлов.

Расчёт индекса состояния (health) выполняется ПО-РАЗНОМУ для каждой категории
оборудования, поскольку физические факторы старения у них принципиально разные:

  • трансформатор   — определяется тепловым старением масла/изоляции;
                      ключевые факторы — нагрузка, температура, отказы, давность диагностики.
  • подстанция      — определяется состоянием коммутационного оборудования и
                      числом операций; нагрузка как таковая вторична.
  • воздушная линия — определяется внешними воздействиями: ветер, гололёд,
                      грозы; нагрузка влияет слабо.
  • кабель          — определяется состоянием изоляции и тепловыми режимами;
                      шторм не влияет (закопан), нагрузка критична через нагрев.

Каждая категория имеет свою формулу и свой нормативный срок службы.
"""
import math
import random
import logging
from datetime import datetime, date
from typing import Optional, Tuple

import networkx as nx

logger = logging.getLogger(__name__)


# Нормативный срок службы по категории (для нормировки возраста), лет
CATEGORY_LIFETIME = {
    "transformer": 30.0,
    "substation":  45.0,
    "line":        35.0,
    "cable":       25.0,
}


def asset_age(installed_date: Optional[date]) -> float:
    if not installed_date:
        return 10.0
    return (date.today() - installed_date).days / 365.25


# ─── Per-category формулы расчёта индекса состояния ──────────────────────────

def _health_transformer(
    age_years: float, failures_count: int, repairs_count: int,
    load_percent: float, days_since_maintenance: float,
    is_storm: bool, temperature: float,
) -> Tuple[float, dict]:
    """
    Трансформатор: тепловое старение масла и витковой изоляции.
    Главный фактор — нагрузка и температура, ускоряющие деградацию изоляции
    (правило Монтсингера: удвоение скорости старения на каждые +6 °C).
    """
    b = {}
    score = 100.0
    b["age"]              = -age_years * 1.0                                # быстрое старение из-за масла
    b["failures"]         = -failures_count * 8.0                          # каждый отказ масла/обмоток дорогой
    b["repairs"]          = +min(repairs_count, 6) * 2.0                   # капремонт частично восстанавливает
    b["load"]             = -max(0.0, load_percent - 70) * 0.30            # нагрев изоляции
    b["overload_spike"]   = -5.0 if load_percent > 90 else 0.0             # острая перегрузка > 90 %
    b["maintenance_lag"]  = -min(days_since_maintenance / 365, 3) * 10.0   # ХАРГ и диагностика масла раз в год
    b["temperature"]      = -5.0 if (temperature < -25 or temperature > 45) else 0.0
    b["storm"]            = -2.0 if is_storm else 0.0                      # умеренный эффект (защищён зданием)
    for v in b.values():
        score += v
    return score, b


def _health_substation(
    age_years: float, failures_count: int, repairs_count: int,
    load_percent: float, days_since_maintenance: float,
    is_storm: bool, temperature: float,
) -> Tuple[float, dict]:
    """
    Подстанция: износ коммутационного оборудования и контактных систем,
    ресурс выключателей по числу операций; конструкция здания старится медленно.
    """
    b = {}
    score = 100.0
    b["age"]              = -age_years * 0.7                               # бетон и металл стареют медленнее
    b["failures"]         = -failures_count * 6.0
    b["repairs"]          = +min(repairs_count, 8) * 1.5
    b["switch_cycles"]    = -max(0.0, load_percent - 80) * 0.20            # выше 80 % — больше коммутаций
    b["maintenance_lag"]  = -min(days_since_maintenance / 365, 3) * 7.0
    b["storm"]            = -4.0 if is_storm else 0.0                      # риск молнии для ОРУ
    b["temperature"]      = -3.0 if (temperature < -30 or temperature > 40) else 0.0
    for v in b.values():
        score += v
    return score, b


def _health_line(
    age_years: float, failures_count: int, repairs_count: int,
    load_percent: float, days_since_maintenance: float,
    is_storm: bool, temperature: float,
) -> Tuple[float, dict]:
    """
    Воздушная линия (ВЛ): провода и изоляторы под открытым небом.
    Главные факторы — погода и механические нагрузки (ветер, гололёд, грозы);
    нагрузка по току влияет слабо, так как ВЛ обычно имеет запас по сечению.
    """
    b = {}
    score = 100.0
    b["age"]              = -age_years * 1.3                               # быстрое старение из-за погоды
    b["failures"]         = -failures_count * 10.0                         # часто погодные, видимые
    b["repairs"]          = +min(repairs_count, 6) * 2.0
    b["weather_storm"]    = -10.0 if is_storm else 0.0                     # ВЛ — главная жертва погоды
    b["temperature"]      = -3.0 if (temperature < -25 or temperature > 35) else 0.0
    b["load_marginal"]    = -max(0.0, load_percent - 85) * 0.15            # очень слабый вклад
    b["maintenance_lag"]  = -min(days_since_maintenance / 365, 3) * 6.0    # обходы и инструментальные осмотры
    for v in b.values():
        score += v
    return score, b


def _health_cable(
    age_years: float, failures_count: int, repairs_count: int,
    load_percent: float, days_since_maintenance: float,
    is_storm: bool, temperature: float,
) -> Tuple[float, dict]:
    """
    Кабель: главный механизм отказа — деградация изоляции, ускоряемая
    тепловым режимом (нагрев в грунте). Шторм не действует (закопан);
    нагрузка действует косвенно через нагрев.
    """
    b = {}
    score = 100.0
    b["age"]              = -age_years * 1.7                               # самое быстрое старение изоляции
    b["failures"]         = -failures_count * 12.0                         # отказ кабеля = земляные работы
    b["repairs"]          = +min(repairs_count, 4) * 1.0                   # ремонт ограничен муфтами
    b["thermal_load"]     = -max(0.0, load_percent - 60) * 0.25            # перегрев в грунте
    b["maintenance_lag"]  = -min(days_since_maintenance / 365, 3) * 5.0    # мегомметр, частичные разряды
    b["soil_cold"]        = -2.0 if temperature < -25 else 0.0             # промерзание грунта
    # b["storm"] = 0  — заземлён, шторм не влияет
    for v in b.values():
        score += v
    return score, b


# Диспетчер по категории
_CATEGORY_FORMULA = {
    "transformer": _health_transformer,
    "substation":  _health_substation,
    "line":        _health_line,
    "cable":       _health_cable,
}


def compute_health_score(
    age_years: float,
    failures_count: int,
    repairs_count: int,
    criticality: float,
    load_percent: float,
    days_since_maintenance: float,
    is_storm: bool = False,
    temperature: float = 10.0,
    category: str = "transformer",
    return_breakdown: bool = False,
):
    """
    Вычислить балл здоровья объекта [0..100] с учётом категории оборудования.
    100 = новый объект в идеальном состоянии. 0 = требует вывода из эксплуатации.

    Каждая категория использует собственную формулу с учётом её физических
    факторов старения. См. _health_transformer / _substation / _line / _cable.

    Параметр return_breakdown=True вернёт кортеж (health, breakdown), где
    breakdown — словарь {фактор → вклад в балл (отрицательный = ухудшает)}.
    Это нужно для объяснимости результата на UI.
    """
    formula = _CATEGORY_FORMULA.get(category, _health_transformer)
    score, breakdown = formula(
        age_years=age_years,
        failures_count=failures_count,
        repairs_count=repairs_count,
        load_percent=load_percent,
        days_since_maintenance=days_since_maintenance,
        is_storm=is_storm,
        temperature=temperature,
    )

    # Критичность влияет на ускорение деградации (общий множитель для всех категорий)
    crit_penalty = (1 - score / 100) * criticality * 5
    score -= crit_penalty
    breakdown["criticality_amp"] = -round(crit_penalty, 2)

    # Ограничиваем диапазон [0..100]
    score = max(0.0, min(100.0, score))
    final = round(score, 2)

    # Округляем вклады для отображения
    breakdown = {k: round(v, 2) for k, v in breakdown.items()}

    if return_breakdown:
        return final, breakdown
    return final


def health_to_risk(health: float) -> float:
    """Перевести health → вероятность отказа (0..1)."""
    # Логистическая функция: health=50 → risk≈0.5
    x = (50 - health) / 15
    return round(1 / (1 + math.exp(-x)), 4)


class DigitalTwin:
    """
    Граф электросети.
    Узлы: объекты (assets).
    Рёбра: физические связи (линия соединяет две подстанции и т.д.)
    """

    def __init__(self):
        self.graph: nx.DiGraph = nx.DiGraph()
        self._built = False

    def build_from_assets(self, assets: list) -> None:
        """
        Построить граф из списка объектов.
        Логика связей: подстанции → трансформаторы → линии → кабели.
        """
        self.graph.clear()

        substations = [a for a in assets if a.asset_type and a.asset_type.category == "substation"]
        transformers = [a for a in assets if a.asset_type and a.asset_type.category == "transformer"]
        lines        = [a for a in assets if a.asset_type and a.asset_type.category == "line"]
        cables       = [a for a in assets if a.asset_type and a.asset_type.category == "cable"]

        # Добавить все узлы
        for asset in assets:
            age = asset_age(asset.installed_date)
            self.graph.add_node(asset.id, **{
                "name":       asset.name,
                "category":   asset.asset_type.category if asset.asset_type else "unknown",
                "age":        round(age, 2),
                "criticality": asset.criticality,
                "status":     asset.status,
                "region":     asset.region,
                "lat":        asset.location_lat,
                "lon":        asset.location_lon,
                "health":     None,  # заполняется при update_node_state
                "risk":       None,
            })

        random.seed(1)  # детерминированные связи для воспроизводимости

        # Подстанции → трансформаторы
        for tr in transformers:
            if substations:
                ss = random.choice(substations)
                self.graph.add_edge(ss.id, tr.id, relation="feeds", voltage=tr.voltage_class)

        # Трансформаторы → линии
        for line in lines:
            src_pool = transformers + substations
            if src_pool:
                src = random.choice(src_pool)
                self.graph.add_edge(src.id, line.id, relation="connects", voltage=line.voltage_class)

        # Линии/трансформаторы → кабели
        for cable in cables:
            src_pool = transformers + lines
            if src_pool:
                src = random.choice(src_pool)
                self.graph.add_edge(src.id, cable.id, relation="connects", voltage=cable.voltage_class)

        self._built = True
        logger.info(f"Digital twin built: {self.graph.number_of_nodes()} nodes, "
                    f"{self.graph.number_of_edges()} edges")

    def update_node_state(
        self,
        asset_id: int,
        failures_count: int,
        repairs_count: int,
        days_since_maintenance: float,
        load_percent: float = 65.0,
        is_storm: bool = False,
        temperature: float = 10.0,
    ) -> dict:
        """Пересчитать health и risk для одного узла.

        Использует категорийную формулу: берёт категорию узла из графа
        и направляет расчёт в формулу, специфичную для трансформатора,
        подстанции, ВЛ или кабеля. Сохраняет в узле подробный breakdown —
        вклад каждого фактора в индекс состояния (для объяснимости в UI).
        """
        if asset_id not in self.graph:
            return {}

        node = self.graph.nodes[asset_id]
        age  = node.get("age", 10)
        crit = node.get("criticality", 0.5)
        category = node.get("category", "transformer")

        health, breakdown = compute_health_score(
            age_years=age,
            failures_count=failures_count,
            repairs_count=repairs_count,
            criticality=crit,
            load_percent=load_percent,
            days_since_maintenance=days_since_maintenance,
            is_storm=is_storm,
            temperature=temperature,
            category=category,
            return_breakdown=True,
        )
        risk = health_to_risk(health)

        self.graph.nodes[asset_id]["health"]    = health
        self.graph.nodes[asset_id]["risk"]      = risk
        self.graph.nodes[asset_id]["load"]      = load_percent
        self.graph.nodes[asset_id]["breakdown"] = breakdown
        self.graph.nodes[asset_id]["age_ratio"] = round(
            age / CATEGORY_LIFETIME.get(category, 30.0), 3
        )

        return {"health": health, "risk": risk, "breakdown": breakdown}

    def get_graph_data(self) -> dict:
        """Сериализация графа для фронтенда (vis.js / cytoscape / D3)."""
        nodes = []
        for nid, data in self.graph.nodes(data=True):
            nodes.append({
                "id":         nid,
                "label":      data.get("name", str(nid)),
                "category":   data.get("category"),
                "health":     data.get("health"),
                "risk":       data.get("risk"),
                "criticality": data.get("criticality"),
                "status":     data.get("status"),
                "lat":        data.get("lat"),
                "lon":        data.get("lon"),
                "region":     data.get("region"),
                "age":        data.get("age"),
            })

        edges = []
        for u, v, data in self.graph.edges(data=True):
            edges.append({
                "source":   u,
                "target":   v,
                "relation": data.get("relation", "connects"),
                "voltage":  data.get("voltage"),
            })

        # Критические пути: цепочки с суммарным риском > 0.7
        critical_chains = self._find_critical_chains()

        return {
            "nodes": nodes,
            "edges": edges,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "critical_chains": critical_chains,
        }

    def _find_critical_chains(self) -> list:
        chains = []
        for node in self.graph.nodes:
            risk = self.graph.nodes[node].get("risk") or 0
            if risk > 0.65:
                # найти «downstream» зависимые объекты
                descendants = list(nx.descendants(self.graph, node))[:5]
                chains.append({
                    "origin_id": node,
                    "risk":      risk,
                    "affected":  descendants,
                })
        return chains

    def get_node_state(self, asset_id: int) -> Optional[dict]:
        if asset_id not in self.graph:
            return None
        return dict(self.graph.nodes[asset_id])

    def get_downstream_impact(self, asset_id: int) -> list:
        """Сколько объектов пострадает при отказе данного узла."""
        if asset_id not in self.graph:
            return []
        return list(nx.descendants(self.graph, asset_id))


# Singleton — один граф на весь жизненный цикл приложения
_twin_instance: Optional[DigitalTwin] = None


def get_twin() -> DigitalTwin:
    global _twin_instance
    if _twin_instance is None:
        _twin_instance = DigitalTwin()
    return _twin_instance
