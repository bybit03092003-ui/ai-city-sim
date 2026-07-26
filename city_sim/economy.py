"""City-level economic state for the Barnaul-2026 simulation.

Keeps things intentionally simple: a handful of sectors with demand
multipliers that drift week to week, plus a small chance of a
regulatory-check event landing on a random business each tick.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

SECTORS = [
    "кофейня/фудкорт",
    "интернет-магазин",
    "ремонт техники",
    "услуги для бизнеса",
    "производство/handmade",
]


@dataclass
class CityState:
    week: int = 0
    inflation_pct_annual: float = 9.5  # ориентир на текущую РФ-инфляцию
    key_rate_pct: float = 18.0
    sector_demand: dict = field(default_factory=lambda: {s: 1.0 for s in SECTORS})
    notes: list[str] = field(default_factory=list)

    def describe(self) -> str:
        demand_lines = ", ".join(
            f"{s}: спрос x{v:.2f}" for s, v in self.sector_demand.items()
        )
        return (
            f"Неделя {self.week}. Инфляция ~{self.inflation_pct_annual:.1f}%/год, "
            f"ключевая ставка {self.key_rate_pct:.1f}%. Спрос по секторам: {demand_lines}."
        )

    def tick(self) -> None:
        self.week += 1
        # small random walk on demand and macro numbers
        for s in self.sector_demand:
            self.sector_demand[s] = max(
                0.4, min(1.8, self.sector_demand[s] + random.uniform(-0.08, 0.08))
            )
        self.inflation_pct_annual = max(
            4.0, self.inflation_pct_annual + random.uniform(-0.3, 0.3)
        )
        self.key_rate_pct = max(8.0, self.key_rate_pct + random.uniform(-0.2, 0.2))

        if random.random() < 0.1:
            event = random.choice(
                [
                    "Городская администрация ввела упрощённую регистрацию для малого бизнеса.",
                    "Рост цен на аренду коммерческих помещений в центре города.",
                    "Локальный всплеск спроса из-за городского фестиваля.",
                    "Перебои с поставками из-за ремонта дорог/логистики.",
                    "Налоговая объявила выборочные проверки малого бизнеса в этом квартале.",
                ]
            )
            self.notes.append(f"[Неделя {self.week}] {event}")


def roll_audit_target(business_agents: list) -> str | None:
    """Return the name of a business agent flagged for an audit this week, if any."""
    candidates = [a for a in business_agents if a.state.get("last_risk_flag")]
    base_pool = candidates if candidates else business_agents
    if not base_pool:
        return None
    chance = 0.35 if candidates else 0.05
    if random.random() < chance:
        return random.choice(base_pool).name
    return None
