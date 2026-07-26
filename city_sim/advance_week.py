"""Advance the persistent city-sim by exactly one week.

Meant to be run once a day by a Windows Scheduled Task. Reads/writes
state.json so it can cooperate with claude_turn.py, which supplies
Claude-driven decisions out-of-band (both the businessman AND the
regulator can be Claude-driven -- both are, in the current config).

If no pending decision exists yet for a Claude-driven agent when this runs,
that agent simply holds for the week -- it does not block anyone else.

At meta["deadline_week"] this prints/logs a final report: did the
businessman reach a passive monthly profit >= meta["monthly_profit_goal"]
for at least meta["profit_stable_weeks_required"] consecutive weeks? That's
a one-time report -- after it fires, further runs are a no-op.
"""
from __future__ import annotations

import json
from pathlib import Path

from economy import CityState, roll_audit_target
from sim_logic import apply_business_result, businessman_turn, regulator_turn
from state_store import agents_from_state, city_from_state, load_state, save_state, sync_state

LOG_DIR = Path(__file__).parent / "logs"
DIARY_DIR = Path.home() / "Desktop" / "Дневник_ИИ_города"
DIARY_PATH = DIARY_DIR / "diary.md"
LOG_PATH = LOG_DIR / "history.jsonl"
PENDING_BUSINESS_PATH = Path(__file__).parent / "pending_claude_action.json"
PENDING_REGULATOR_CASE_PATH = Path(__file__).parent / "pending_regulator_case.json"
PENDING_REGULATOR_VERDICT_PATH = Path(__file__).parent / "pending_regulator_verdict.json"

HOLD_RESULT = {
    "action": "нет хода (ожидание решения игрока)",
    "reasoning": "",
    "cash_delta": 0,
    "revenue_change": 0,
    "cost_change": 0,
    "risk_flag": False,
    "notes": "",
}


def log(event: dict) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def diary(text: str) -> None:
    DIARY_DIR.mkdir(exist_ok=True)
    with DIARY_PATH.open("a", encoding="utf-8") as f:
        f.write(text + "\n")


def take_pending(path: Path) -> dict | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    path.unlink()
    return data


def write_pending_case(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def run_final_report(businessmen: list, monthly_profit_goal: float, stable_weeks_required: int, week: int) -> None:
    weekly_target = monthly_profit_goal / 4.345
    lines = [f"\n# 📋 ИТОГОВЫЙ ОТЧЁТ — неделя {week} (дедлайн)\n",
              f"Цель: пассивная прибыль от {monthly_profit_goal:.0f} руб/мес "
              f"(~{weekly_target:.0f} руб/нед) не менее {stable_weeks_required} недель подряд.\n"]

    for b in businessmen:
        weekly_profit = b.weekly_revenue - b.weekly_costs
        monthly_profit = weekly_profit * 4.345
        reached = b.consecutive_profitable_weeks >= stable_weeks_required and weekly_profit >= weekly_target
        b.state["goal_reached"] = reached
        status = "✅ ЦЕЛЬ ДОСТИГНУТА" if reached else "❌ цель не достигнута"
        lines.append(
            f"- **{b.name} ({b.business_name})** — {status}\n"
            f"  Капитал: {b.cash:.0f} руб. Текущая недельная прибыль: {weekly_profit:.0f} руб "
            f"(≈{monthly_profit:.0f} руб/мес). Недель подряд в плюсе: {b.consecutive_profitable_weeks}."
        )

    diary("\n".join(lines) + "\n")
    for line in lines:
        print(line)

    log({"week": week, "type": "final_report", "monthly_profit_goal": monthly_profit_goal,
         "results": [{"agent": b.name, "cash": b.cash, "weekly_profit": b.weekly_revenue - b.weekly_costs,
                       "goal_reached": b.state.get("goal_reached")} for b in businessmen]})


def main() -> None:
    state = load_state()
    monthly_profit_goal = state["meta"]["monthly_profit_goal"]
    stable_weeks_required = state["meta"]["profit_stable_weeks_required"]
    deadline_week = state["meta"]["deadline_week"]
    history_keep = state["meta"]["history_keep"]
    start_date = state["meta"]["start_date"]

    if state["meta"].get("concluded"):
        print(f"Эксперимент уже завершён (итоговый отчёт на неделе {deadline_week}). "
              f"Удалите state.json и дневник, чтобы начать заново.")
        return

    city = city_from_state(state)
    all_agents = agents_from_state(state)
    agents = [a for a in all_agents if a.active]
    businessmen = [a for a in agents if a.role == "businessman"]
    regulator = next((a for a in agents if a.role == "regulator"), None)

    if not DIARY_PATH.exists():
        diary(f"# Летопись города Барнаул, {start_date} и далее\n")
        diary(
            f"Цель: пассивная ежемесячная прибыль от {monthly_profit_goal:.0f} руб за {deadline_week} недель. "
            f"Участники: "
            + ", ".join(f"{b.name} ({b.business_name})" for b in businessmen)
            + f"; гос. органы: {regulator.name if regulator else '-'}.\n"
        )

    city.tick()
    print(f"=== {city.describe()} ===")
    diary(f"\n## Неделя {city.week}\n\n*{city.describe()}*\n")
    if city.notes and city.notes[-1].startswith(f"[Неделя {city.week}]"):
        print(city.notes[-1])
        diary(f"> {city.notes[-1]}\n")

    pending_business = take_pending(PENDING_BUSINESS_PATH)

    for biz in businessmen:
        if biz.provider == "claude":
            if pending_business and pending_business.get("agent") == biz.name:
                result = {k: pending_business[k] for k in
                          ("action", "reasoning", "cash_delta", "revenue_change", "cost_change",
                           "risk_flag", "notes")}
                biz.state["last_risk_flag"] = bool(result.get("risk_flag", False))
            else:
                result = HOLD_RESULT
        else:
            result = businessman_turn(biz, city, monthly_profit_goal, deadline_week, start_date)

        apply_business_result(biz, result, city.week, history_keep)

        print(f"[{biz.name} | {biz.provider}] {result.get('action', '?')} -- {result.get('reasoning', '')}")
        print(f"    -> касса: {biz.cash:.0f} руб, выручка/нед: {biz.weekly_revenue:.0f}, издержки/нед: {biz.weekly_costs:.0f}")

        log({"week": city.week, "agent": biz.name, "type": "business_action", **result,
             "cash_after": biz.cash, "weekly_revenue": biz.weekly_revenue, "weekly_costs": biz.weekly_costs})

        diary(
            f"**{biz.name} ({biz.business_name}) [{biz.provider}]** — {result.get('action', '?')}\n"
            f"  Причина: {result.get('reasoning', '')}\n"
            f"  Итог: касса {biz.cash:.0f} руб, выручка/нед {biz.weekly_revenue:.0f}, "
            f"издержки/нед {biz.weekly_costs:.0f}, недель подряд в плюсе: {biz.consecutive_profitable_weeks}."
            + (f"\n  ⚠ риск/нарушение: {result.get('notes', '')}" if result.get("risk_flag") else "")
            + "\n"
        )

    target_name = roll_audit_target(businessmen)
    if target_name and regulator:
        target = next(b for b in businessmen if b.name == target_name)
        last_note = target.history[-1] if target.history else "нет данных"
        case_facts = f"Гос. органы обратили внимание на бизнес по подозрению в нарушениях. Последнее действие: {last_note}"

        if regulator.provider == "claude":
            pending_verdict = take_pending(PENDING_REGULATOR_VERDICT_PATH)
            if pending_verdict and pending_verdict.get("target") == target.name:
                fine = float(pending_verdict.get("fine", 0) or 0)
                verdict_text = pending_verdict.get("verdict", "")
                target.cash -= fine
                print(f"[ПРОВЕРКА] {target.name}: решение гос. органов -- {verdict_text} (штраф {fine:.0f} руб)")
                target.add_history(
                    f"Нед.{city.week}: решение гос. органов, штраф {fine:.0f} руб.", history_keep,
                )
                log({"week": city.week, "type": "regulator_verdict", "target": target.name, "fine": fine,
                     "verdict": verdict_text})
                diary(f"**⚖ Гос. органы по делу {target.name}:** {verdict_text} (штраф {fine:.0f} руб)\n")
            else:
                write_pending_case(PENDING_REGULATOR_CASE_PATH, {
                    "target": target.name, "case_facts": case_facts, "week": city.week,
                })
                print(f"[ПРОВЕРКА] Дело {target.name} передано на рассмотрение гос. органам, решения пока нет.")
                diary(f"**⚖ Дело {target.name} на рассмотрении у гос. органов** (решение будет позже)\n")
        else:
            verdict = regulator_turn(regulator, target, case_facts)
            fine = float(verdict.get("fine", 0) or 0)
            target.cash -= fine
            print(f"[ПРОВЕРКА] {target.name}: решение -- {verdict.get('verdict', '')} (штраф {fine:.0f} руб)")
            target.add_history(
                f"Нед.{city.week}: решение гос. органов, штраф {fine:.0f} руб.", history_keep,
            )
            log({"week": city.week, "type": "regulator_verdict", "target": target.name, "fine": fine,
                 "verdict": verdict})
            diary(f"**⚖ Гос. органы по делу {target.name}:** {verdict.get('verdict', '')} (штраф {fine:.0f} руб)\n")

    if city.week >= deadline_week:
        run_final_report(businessmen, monthly_profit_goal, stable_weeks_required, city.week)
        state["meta"]["concluded"] = True

    sync_state(state, city, all_agents)
    save_state(state)
    print(f"\nСостояние сохранено. Неделя {city.week} завершена.")
    print(f"Дневник: {DIARY_PATH}")


if __name__ == "__main__":
    main()
