"""AI City Sim -- quick disposable test run.

Runs entirely in one process/memory, for trying out N weeks fast and
checking API keys/costs before relying on the persistent daily pipeline
(advance_week.py + claude_turn.py + Windows Task Scheduler).

Note: any agent with provider == "claude" has no real turn here -- it just
holds each week, since taking its turn requires a human (see claude_turn.py
and the persistent state.json pipeline instead).

Run:
    python main.py [weeks]
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from agent import Agent
from economy import CityState, roll_audit_target
from sim_logic import apply_business_result, businessman_turn, lawyer_turn, regulator_turn

CONFIG_PATH = Path(__file__).parent / "agents_config.json"
LOG_DIR = Path(__file__).parent / "logs"
DIARY_DIR = Path.home() / "Desktop" / "Дневник_ИИ_города"


def load_agents(config: dict) -> tuple[list[Agent], list[Agent], Agent | None, Agent | None]:
    agents = [Agent(**{k: v for k, v in a.items() if k != "role"}, role=a["role"]) for a in config["agents"]]
    businessmen = [a for a in agents if a.role == "businessman"]
    lawyer = next((a for a in agents if a.role == "lawyer"), None)
    regulator = next((a for a in agents if a.role == "regulator"), None)
    return agents, businessmen, lawyer, regulator


def run(max_weeks_override: int | None = None) -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    goal_cash = config["goal_cash"]
    stable_weeks_required = config["stable_weeks_required"]
    deadline_week = config["deadline_week"]
    max_weeks = max_weeks_override or config["max_weeks"]
    history_keep = config["history_keep"]

    agents, businessmen, lawyer, regulator = load_agents(config)
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

    diary(f"# Тестовый прогон города Барнаул, 2026 (запуск {run_id})\n")
    diary(
        f"Цель бизнесменов: капитал {goal_cash:.0f} руб при {stable_weeks_required} "
        f"неделях подряд в плюсе. Участники: "
        + ", ".join(f"{b.name} ({b.business_name})" for b in businessmen)
        + f"; юрист: {lawyer.name if lawyer else '-'}; регулятор: {regulator.name if regulator else '-'}.\n"
    )

    achieved: set[str] = set()

    for _ in range(max_weeks):
        city.tick()
        print(f"\n=== {city.describe()} ===")
        diary(f"\n## Неделя {city.week}\n\n*{city.describe()}*\n")
        if city.notes and city.notes[-1].startswith(f"[Неделя {city.week}]"):
            print(city.notes[-1])
            diary(f"> {city.notes[-1]}\n")

        for biz in businessmen:
            if biz.provider == "claude":
                result = {"action": "нет хода (Claude-агент требует человека, см. claude_turn.py)",
                          "reasoning": "", "cash_delta": 0, "revenue_change": 0, "cost_change": 0,
                          "risk_flag": False, "notes": ""}
            else:
                result = businessman_turn(biz, city, goal_cash, deadline_week)
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

            if (
                biz.name not in achieved
                and biz.cash >= goal_cash
                and biz.consecutive_profitable_weeks >= stable_weeks_required
            ):
                achieved.add(biz.name)
                biz.state["achieved_week"] = city.week
                msg = (
                    f"*** {biz.name} ({biz.business_name}) [{biz.provider}] достиг цели на неделе {city.week}: "
                    f"капитал {biz.cash:.0f} руб, {biz.consecutive_profitable_weeks} недель подряд в плюсе. ***"
                )
                print(msg)
                log({"week": city.week, "agent": biz.name, "type": "goal_achieved", "cash": biz.cash})
                diary(f"### 🏆 {msg}\n")

        target_name = roll_audit_target(businessmen)
        if target_name and lawyer and regulator:
            target = next(b for b in businessmen if b.name == target_name)
            last_note = target.history[-1] if target.history else "нет данных"
            case_facts = f"Регулятор проверяет бизнес по подозрению в нарушениях. Последнее действие: {last_note}"

            defense = lawyer_turn(lawyer, target, case_facts)
            fee = float(defense.get("fee", 0) or 0)
            target.cash -= fee

            verdict = regulator_turn(regulator, target, case_facts, defense.get("defense", ""))
            fine = float(verdict.get("fine", 0) or 0)
            target.cash -= fine

            print(f"[ПРОВЕРКА] {target.name}: юрист гонорар {fee:.0f} руб -- {defense.get('defense', '')}")
            print(f"    Решение регулятора: штраф {fine:.0f} руб -- {verdict.get('verdict', '')}")

            target.add_history(
                f"Нед.{city.week}: проверка регулятора, штраф {fine:.0f} руб, гонорар юриста {fee:.0f} руб.",
                history_keep,
            )
            log({"week": city.week, "type": "audit", "target": target.name, "fee": fee, "fine": fine,
                 "defense": defense, "verdict": verdict})

            diary(
                f"**⚖ Проверка: {target.name}**\n"
                f"  Юрист ({lawyer.name}): {defense.get('defense', '')} (гонорар {fee:.0f} руб)\n"
                f"  Регулятор ({regulator.name}): {verdict.get('verdict', '')} (штраф {fine:.0f} руб)\n"
            )

        if len(achieved) == len(businessmen):
            print("\nВсе бизнесмены достигли цели. Останавливаем симуляцию.")
            diary("\n## Все бизнесмены достигли цели. Симуляция остановлена.\n")
            break

    ranked = sorted(businessmen, key=lambda b: b.cash, reverse=True)
    summary_lines = ["\n## Итог по провайдерам\n", "| Персонаж | Провайдер | Капитал | Недель подряд в плюсе | Цель достигнута |",
                      "|---|---|---|---|---|"]
    for b in ranked:
        achieved_week = b.state.get("achieved_week")
        summary_lines.append(
            f"| {b.name} | {b.provider} | {b.cash:.0f} руб | {b.consecutive_profitable_weeks} | "
            f"{'неделя ' + str(achieved_week) if achieved_week else 'нет'} |"
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
