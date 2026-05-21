"""
services/digital_twin.py
Цифровая копия электросети — граф NetworkX с расчётом здоровья узлов.
"""
import math
import random
import logging
from datetime import datetime, date
from typing import Optional

import networkx as nx

logger = logging.getLogger(__name__)


def asset_age(installed_date: Optional[date]) -> float:
    if not installed_date:
        return 10.0
    return (date.today() - installed_date).days / 365.25


def compute_health_score(
    age_years: float,
    failures_count: int,
    repairs_count: int,
    criticality: float,
    load_percent: float,
    days_since_maintenance: float,
    is_storm: bool = False,
    temperature: float = 10.0,
) -> float:
    """
    Вычислить балл здоровья объекта [0..100].
    100 = новый объект в идеальном состоянии.
    0   = требует немедленного вывода из эксплуатации.
    """
    score = 100.0

    # Деградация по возрасту
    score -= age_years * 0.9

    # Каждый отказ — -6 баллов
    score -= failures_count * 6.0

    # Ремонты немного восстанавливают
    score += min(repairs_count, 8) * 1.5

    # Перегрузка
    if load_percent > 70:
        score -= (load_percent - 70) * 0.25

    # Давность ТО: через год без обслуживания -8
    score -= min(days_since_maintenance / 365, 3) * 8

    # Шторм: кратковременный стресс
    if is_storm:
        score -= 5

    # Экстремальная температура
    if temperature < -20 or temperature > 40:
        score -= 4

    # Критичность влияет на вес ухудшений (высококритичные деградируют быстрее)
    score = score - (1 - score / 100) * criticality * 5

    return round(max(0.0, min(100.0, score)), 2)


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
        """Пересчитать health и risk для одного узла."""
        if asset_id not in self.graph:
            return {}

        node = self.graph.nodes[asset_id]
        age  = node.get("age", 10)
        crit = node.get("criticality", 0.5)

        health = compute_health_score(
            age_years=age,
            failures_count=failures_count,
            repairs_count=repairs_count,
            criticality=crit,
            load_percent=load_percent,
            days_since_maintenance=days_since_maintenance,
            is_storm=is_storm,
            temperature=temperature,
        )
        risk = health_to_risk(health)

        self.graph.nodes[asset_id]["health"] = health
        self.graph.nodes[asset_id]["risk"]   = risk
        self.graph.nodes[asset_id]["load"]   = load_percent

        return {"health": health, "risk": risk}

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
