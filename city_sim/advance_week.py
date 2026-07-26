"""Advance the persistent city-sim by exactly one week.

Meant to be run once a day by a Windows Scheduled Task. Reads/writes
state.json so it can cooperate with claude_turn.py, which supplies the
human (Claude Pro, via chat) businessman's decision out-of-band.

If no pending decision exists yet for the Claude-driven businessman when
this runs, that agent simply holds for the week -- it does not block
everyone else.

At meta["deadline_week"] (the "ship" arrives), everyone with cash >=
goal_cash (the ticket price) survives; everyone else does not. That's a
one-time judgment day -- after it fires, further runs are a no-op.
"""
from __future__ import annotations

import json
from pathlib import Path

from economy import CityState, roll_audit_target
from sim_logic import apply_business_result, businessman_turn, lawyer_turn, regulator_turn
from state_store import agents_from_state, city_from_state, load_state, save_state, sync_state

LOG_DIR = Path(__file__).parent / "logs"
DIARY_DIR = Path.home() / "Desktop" / "Дневник_ИИ_города"
DIARY_PATH = DIARY_DIR / "diary.md"
LOG_PATH = LOG_DIR / "history.jsonl"
PENDING_PATH = Path(__file__).parent / "pending_claude_action.json"

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


def take_pending_claude_action() -> dict | None:
    if not PENDING_PATH.exists():
        return None
    data = json.loads(PENDING_PATH.read_text(encoding="utf-8"))
    PENDING_PATH.unlink()
    return data


def run_judgment_day(businessmen: list, goal_cash: float, week: int) -> None:
    survivors = [b for b in businessmen if b.cash >= goal_cash]
    casualties = [b for b in businessmen if b.cash < goal_cash]

    lines = [f"\n# 🚀 СУДНЫЙ ДЕНЬ — неделя {week}\n",
              f"Корабль прибыл. Билет стоил {goal_cash:.0f} руб.\n"]

    if survivors:
        lines.append(f"## Выжили ({len(survivors)}):\n")
        for b in sorted(survivors, key=lambda x: x.cash, reverse=True):
            b.state["survived"] = True
            lines.append(f"- **{b.name} [{b.provider}]** — {b.cash:.0f} руб. Улетел на корабле.")
    else:
        lines.append("## Выжившие: никто.\n")

    lines.append(f"\n## Погибли ({len(casualties)}):\n")
    for b in sorted(casualties, key=lambda x: x.cash, reverse=True):
        b.state["survived"] = False
        lines.append(f"- {b.name} [{b.provider}] — {b.cash:.0f} руб (не хватило {goal_cash - b.cash:.0f} руб). Остался в городе.")

    diary("\n".join(lines) + "\n")
    for line in lines:
        print(line)

    log({"week": week, "type": "judgment_day", "goal_cash": goal_cash,
         "survivors": [b.name for b in survivors], "casualties": [b.name for b in casualties]})


def main() -> None:
    state = load_state()
    goal_cash = state["meta"]["goal_cash"]
    stable_weeks_required = state["meta"]["stable_weeks_required"]
    deadline_week = state["meta"]["deadline_week"]
    history_keep = state["meta"]["history_keep"]

    if state["meta"].get("concluded"):
        print(f"Эксперимент уже завершён (судный день на неделе {deadline_week}). "
              f"Удалите state.json и дневник, чтобы начать заново.")
        return

    city = city_from_state(state)
    agents = agents_from_state(state)
    businessmen = [a for a in agents if a.role == "businessman"]
    lawyer = next((a for a in agents if a.role == "lawyer"), None)
    regulator = next((a for a in agents if a.role == "regulator"), None)

    if not DIARY_PATH.exists():
        diary(f"# Летопись города Барнаул, 2026\n")
        diary(
            f"На неделе {deadline_week} прибудет корабль. Билет — {goal_cash:.0f} руб. "
            f"Кто не успеет накопить — останется в городе.\n\n"
            f"Участники: "
            + ", ".join(f"{b.name} ({b.business_name})" for b in businessmen)
            + f"; юрист: {lawyer.name if lawyer else '-'}; регулятор: {regulator.name if regulator else '-'}.\n"
        )

    city.tick()
    print(f"=== {city.describe()} ===")
    diary(f"\n## Неделя {city.week}\n\n*{city.describe()}*\n")
    if city.notes and city.notes[-1].startswith(f"[Неделя {city.week}]"):
        print(city.notes[-1])
        diary(f"> {city.notes[-1]}\n")

    pending = take_pending_claude_action()

    for biz in businessmen:
        if biz.provider == "claude":
            if pending and pending.get("agent") == biz.name:
                result = {k: pending[k] for k in
                          ("action", "reasoning", "cash_delta", "revenue_change", "cost_change",
                           "risk_flag", "notes")}
                biz.state["last_risk_flag"] = bool(result.get("risk_flag", False))
            else:
                result = HOLD_RESULT
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
            not biz.state.get("achieved_week")
            and biz.cash >= goal_cash
            and biz.consecutive_profitable_weeks >= stable_weeks_required
        ):
            biz.state["achieved_week"] = city.week
            msg = (
                f"*** {biz.name} ({biz.business_name}) [{biz.provider}] уже накопил на билет на неделе {city.week}: "
                f"капитал {biz.cash:.0f} руб. ***"
            )
            print(msg)
            log({"week": city.week, "agent": biz.name, "type": "goal_achieved", "cash": biz.cash})
            diary(f"### 🎫 {msg}\n")

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

    if city.week >= deadline_week:
        run_judgment_day(businessmen, goal_cash, city.week)
        state["meta"]["concluded"] = True

    sync_state(state, city, agents)
    save_state(state)
    print(f"\nСостояние сохранено. Неделя {city.week} завершена.")
    print(f"Дневник: {DIARY_PATH}")


if __name__ == "__main__":
    main()
