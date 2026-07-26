"""AI City Sim -- quick disposable test run.

Runs entirely in one process/memory, for trying out N weeks fast and
checking API keys/costs before relying on the persistent daily pipeline
(advance_week.py + claude_turn.py + Windows Task Scheduler).

Note: any agent with provider == "claude" has no real turn here -- it just
holds each week, since taking its turn requires a human (see claude_turn.py
and the persistent state.json pipeline instead). Only active agents
(agents_config.json "active": true) are simulated.

Run:
    python main.py [weeks]
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from agent import Agent
from economy import CityState, roll_audit_target
from sim_logic import apply_business_result, businessman_turn, regulator_turn

CONFIG_PATH = Path(__file__).parent / "agents_config.json"
LOG_DIR = Path(__file__).parent / "logs"
DIARY_DIR = Path.home() / "Desktop" / "Дневник_ИИ_города"


def load_agents(config: dict) -> tuple[list[Agent], Agent | None]:
    agents = [
        Agent(**{k: v for k, v in a.items() if k != "role"}, role=a["role"])
        for a in config["agents"]
        if a.get("active", True)
    ]
    businessmen = [a for a in agents if a.role == "businessman"]
    regulator = next((a for a in agents if a.role == "regulator"), None)
    return businessmen, regulator


def run(max_weeks_override: int | None = None) -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    monthly_profit_goal = config["monthly_profit_goal"]
    stable_weeks_required = config["profit_stable_weeks_required"]
    deadline_week = config["deadline_week"]
    start_date = config["start_date"]
    max_weeks = max_weeks_override or config["max_weeks"]
    history_keep = config["history_keep"]
    personal_weekly_expenses = config["personal_monthly_expenses"] / 3

    businessmen, regulator = load_agents(config)
    city = CityState()

    LOG_DIR.mkdir(exist_ok=True)
    DIARY_DIR.mkdir(exist_ok=True)
    run_id = int(time.time())
    log_path = LOG_DIR / f"run_{run_id}.jsonl"
    diary_path = DIARY_DIR / f"run_{run_id}_test_diary.md"

    def log(event: dict) -> None:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    def diary(text: str) -> None:
        with diary_path.open("a", encoding="utf-8") as f:
            f.write(text + "\n")

    period_target = monthly_profit_goal / 3
    diary(f"# Тестовый прогон города Барнаул, {start_date} (запуск {run_id})\n")
    diary(
        f"Цель: пассивная прибыль от {monthly_profit_goal:.0f} руб/мес (~{period_target:.0f} руб/период) "
        f"не менее {stable_weeks_required} периодов подряд, за {deadline_week} периодов по 10 дней. Участники: "
        + ", ".join(f"{b.name} ({b.business_name})" for b in businessmen)
        + f"; гос. органы: {regulator.name if regulator else '-'}.\n"
    )

    for _ in range(max_weeks):
        city.tick()
        print(f"\n=== {city.describe()} ===")
        diary(f"\n## День {city.week * 10} (период {city.week})\n\n*{city.describe()}*\n")
        if city.notes and city.notes[-1].startswith(f"[День {city.week * 10}]"):
            print(city.notes[-1])
            diary(f"> {city.notes[-1]}\n")

        for biz in businessmen:
            if biz.provider == "claude":
                result = {"action": "нет хода (Claude-агент требует человека, см. claude_turn.py)",
                          "reasoning": "", "cash_delta": 0, "revenue_change": 0, "cost_change": 0,
                          "risk_flag": False, "notes": ""}
            else:
                result = businessman_turn(biz, city, monthly_profit_goal, deadline_week, start_date, personal_weekly_expenses)
            apply_business_result(biz, result, city.week, history_keep)
            biz.cash -= personal_weekly_expenses

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
        if target_name and regulator and regulator.provider != "claude":
            target = next(b for b in businessmen if b.name == target_name)
            last_note = target.history[-1] if target.history else "нет данных"
            case_facts = f"Гос. органы обратили внимание на бизнес по подозрению в нарушениях. Последнее действие: {last_note}"

            verdict = regulator_turn(regulator, target, case_facts)
            fine = float(verdict.get("fine", 0) or 0)
            target.cash -= fine

            print(f"[ПРОВЕРКА] {target.name}: решение -- {verdict.get('verdict', '')} (штраф {fine:.0f} руб)")

            target.add_history(
                f"Нед.{city.week}: решение гос. органов, штраф {fine:.0f} руб.",
                history_keep,
            )
            log({"week": city.week, "type": "regulator_verdict", "target": target.name, "fine": fine,
                 "verdict": verdict})

            diary(
                f"**⚖ Гос. органы по делу {target.name}:** {verdict.get('verdict', '')} (штраф {fine:.0f} руб)\n"
            )

    ranked = sorted(businessmen, key=lambda b: b.cash, reverse=True)
    summary_lines = ["\n## Итог\n", "| Персонаж | Провайдер | Капитал | Недельная прибыль | Недель подряд в плюсе |",
                      "|---|---|---|---|---|"]
    for b in ranked:
        weekly_profit = b.weekly_revenue - b.weekly_costs
        summary_lines.append(
            f"| {b.name} | {b.provider} | {b.cash:.0f} руб | {weekly_profit:.0f} руб | {b.consecutive_profitable_weeks} |"
        )
    summary_text = "\n".join(summary_lines)
    print(summary_text)
    diary(f"\n---\nСимуляция завершена на неделе {city.week}.\n{summary_text}\n")
    print(f"\nЛог сохранён в {log_path}")
    print(f"Читаемая летопись: {diary_path}")


if __name__ == "__main__":
    import sys

    weeks = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    run(max_weeks_override=weeks)
