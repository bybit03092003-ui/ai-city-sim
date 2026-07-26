"""Shared prompt templates and per-role LLM turns.

Used by both main.py (quick disposable one-shot test run, everything in one
process) and advance_week.py (the persistent, state.json-backed daily tick).
"""
from __future__ import annotations

from agent import Agent
from economy import CityState
from llm_client import ask_json

BUSINESSMAN_SYSTEM_TMPL = """Ты играешь роль обычного человека без опыта в бизнесе, который открывает своё дело в городе Барнаул, начиная с {start_date}, в текущих экономических условиях (симуляция реальной ситуации в РФ 2026 года).
Персонаж: {persona}
Бизнес: "{business_name}", сектор: {sector}.

Стартовый капитал — единственные деньги, которые есть, терять их некуда. Нужно с нуля: найти подходящее помещение,
привести его в порядок под бизнес, оформить всё по закону (регистрация ИП/самозанятости, разрешения, договоры
с клиентами, требования пожарной безопасности и т.п.), найти первых клиентов и постепенно выйти на ПАССИВНУЮ
ежемесячную прибыль от {monthly_profit_goal:.0f} руб — и успеть за {weeks_left} недель (дедлайн на неделе {deadline_week}, это ~6 месяцев).
Каждую неделю принимай ОДНО конкретное действие (поиск/аренда помещения, переговоры, обустройство, реклама,
оформление документов, работа с клиентами и т.п.), учитывая макроэкономику и конкуренцию. Действуй по закону —
нарушения могут привлечь внимание гос. органов.
Отвечай СТРОГО одним JSON-объектом, без текста вокруг:
{{"action": "краткое действие", "reasoning": "почему именно это", "cash_delta": число, "revenue_change": число, "cost_change": число, "risk_flag": true/false, "notes": "что могли бы заметить гос. органы, если risk_flag true"}}"""

REGULATOR_SYSTEM_TMPL = """Ты — {persona}
Город Барнаул, 2026 год. Тебе передали факты о подозрительном/непроверенном моменте в бизнесе предпринимателя.
Оцени, насколько это серьёзное нарушение, и прими решение.
Отвечай строго JSON:
{{"verdict": "текст решения", "fine": число (штраф в руб., 0 если нарушение не подтверждено или не существенно), "reasoning": "почему"}}"""


def businessman_prompt(
    agent: Agent, city: CityState, monthly_profit_goal: float, deadline_week: int, start_date: str
) -> tuple[str, str]:
    weeks_left = max(0, deadline_week - city.week)
    system = BUSINESSMAN_SYSTEM_TMPL.format(
        persona=agent.persona,
        business_name=agent.business_name,
        sector=agent.sector,
        monthly_profit_goal=monthly_profit_goal,
        deadline_week=deadline_week,
        weeks_left=weeks_left,
        start_date=start_date,
    )
    history_text = "\n".join(agent.history) if agent.history else "(пока ничего не происходило)"
    user = (
        f"{city.describe()}\n\n"
        f"Твоё текущее состояние: капитал {agent.cash:.0f} руб, недельная выручка {agent.weekly_revenue:.0f}, "
        f"недельные издержки {agent.weekly_costs:.0f}, недель подряд в плюсе: {agent.consecutive_profitable_weeks}.\n"
        f"Недавняя история:\n{history_text}\n\n"
        f"Прими решение на эту неделю."
    )
    return system, user


def businessman_turn(
    agent: Agent, city: CityState, monthly_profit_goal: float, deadline_week: int, start_date: str
) -> dict:
    system, user = businessman_prompt(agent, city, monthly_profit_goal, deadline_week, start_date)
    result = ask_json(agent.provider, system, user)
    agent.state["last_risk_flag"] = bool(result.get("risk_flag", False))
    return result


def regulator_turn(regulator: Agent, target: Agent, case_facts: str) -> dict:
    system = REGULATOR_SYSTEM_TMPL.format(persona=regulator.persona)
    user = f"Дело: {target.name} ({target.business_name}).\nФакты: {case_facts}"
    return ask_json(regulator.provider, system, user, max_tokens=350)


def apply_business_result(biz: Agent, result: dict, city_week: int, history_keep: int) -> float:
    """Apply a decision dict to a businessman agent. Returns the weekly profit."""
    cash_delta = float(result.get("cash_delta", 0) or 0)
    revenue_change = float(result.get("revenue_change", 0) or 0)
    cost_change = float(result.get("cost_change", 0) or 0)

    biz.weekly_revenue = max(0.0, biz.weekly_revenue + revenue_change)
    biz.weekly_costs = max(0.0, biz.weekly_costs + cost_change)
    weekly_profit = biz.weekly_revenue - biz.weekly_costs
    biz.cash += cash_delta + weekly_profit

    biz.consecutive_profitable_weeks = (
        biz.consecutive_profitable_weeks + 1 if weekly_profit > 0 else 0
    )

    line = (
        f"Нед.{city_week}: {result.get('action', '?')} "
        f"(касса {biz.cash:.0f}, выручка {biz.weekly_revenue:.0f}, издержки {biz.weekly_costs:.0f})"
    )
    biz.add_history(line, history_keep)
    return weekly_profit
