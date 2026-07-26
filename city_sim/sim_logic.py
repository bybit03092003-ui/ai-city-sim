"""Shared prompt templates and per-role LLM turns.

Used by both main.py (quick disposable one-shot test run, everything in one
process) and advance_week.py (the persistent, state.json-backed daily tick).
"""
from __future__ import annotations

from agent import Agent
from economy import CityState
from llm_client import ask_json

BUSINESSMAN_SYSTEM_TMPL = """Ты играешь роль владельца малого бизнеса в городе Барнаул, 2026 год (симуляция реальной экономики РФ).
Персонаж: {persona}
Бизнес: "{business_name}", сектор: {sector}.

ЭТО ИГРА НА ВЫЖИВАНИЕ. Через {weeks_left} недель (на неделе {deadline_week}) к городу прибудет корабль.
Билет стоит {goal_cash:.0f} руб. У кого на счету хватит денег — улетит и выживет. У кого не хватит — останется
в городе и погибнет. Другого выхода нет: копить на билет нужно как можно быстрее, не обанкротившись раньше срока.
Каждую неделю принимай ОДНО конкретное решение о развитии бизнеса (маркетинг, наём, цены, экономия, риск/обход правил и т.п.), учитывая макроэкономику и конкуренцию.
Отвечай СТРОГО одним JSON-объектом, без текста вокруг:
{{"action": "краткое действие", "reasoning": "почему именно это", "cash_delta": число, "revenue_change": число, "cost_change": число, "risk_flag": true/false, "notes": "что мог бы заметить регулятор, если risk_flag true"}}"""

LAWYER_SYSTEM_TMPL = """Ты — юрист. Персонаж: {persona}
Город Барнаул, 2026 год. Клиента проверяет регулятор из-за подозрительных действий в бизнесе.
Дай защитную стратегию. Отвечай строго JSON:
{{"defense": "краткая стратегия аргументации", "mitigation_score": число от 0 до 1, "fee": число (гонорар в руб., спишется у клиента)}}"""

REGULATOR_SYSTEM_TMPL = """Ты — представитель городской администрации/налоговой/полиции (для прототипа все функции в одной роли). Персонаж: {persona}
Город Барнаул, 2026 год. Тебе передали факты по делу и аргументы защиты юриста клиента. Прими решение по делу.
Отвечай строго JSON:
{{"verdict": "текст решения", "fine": число (штраф в руб., 0 если нарушение не подтверждено), "reasoning": "почему"}}"""


def businessman_prompt(agent: Agent, city: CityState, goal_cash: float, deadline_week: int) -> tuple[str, str]:
    weeks_left = max(0, deadline_week - city.week)
    system = BUSINESSMAN_SYSTEM_TMPL.format(
        persona=agent.persona,
        business_name=agent.business_name,
        sector=agent.sector,
        goal_cash=goal_cash,
        deadline_week=deadline_week,
        weeks_left=weeks_left,
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


def businessman_turn(agent: Agent, city: CityState, goal_cash: float, deadline_week: int) -> dict:
    system, user = businessman_prompt(agent, city, goal_cash, deadline_week)
    result = ask_json(agent.provider, system, user)
    agent.state["last_risk_flag"] = bool(result.get("risk_flag", False))
    return result


def lawyer_turn(lawyer: Agent, target: Agent, case_facts: str) -> dict:
    system = LAWYER_SYSTEM_TMPL.format(persona=lawyer.persona)
    user = f"Дело клиента {target.name} ({target.business_name}):\n{case_facts}"
    return ask_json(lawyer.provider, system, user, max_tokens=350)


def regulator_turn(regulator: Agent, target: Agent, case_facts: str, defense: str) -> dict:
    system = REGULATOR_SYSTEM_TMPL.format(persona=regulator.persona)
    user = (
        f"Дело: {target.name} ({target.business_name}).\nФакты: {case_facts}\n"
        f"Аргументы защиты юриста: {defense}"
    )
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
