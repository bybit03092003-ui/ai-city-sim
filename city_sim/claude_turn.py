"""CLI for the human/Claude-supplied turns: the businessman AND the
regulator ("gov bodies") -- both are Claude-driven in the current config.

    python claude_turn.py show "Игорь Соколов"
        Prints city + this agent's state, and (if it's the regulator) any
        pending case awaiting a ruling.

    python claude_turn.py apply "Игорь Соколов" \
        --action "..." --reasoning "..." \
        --cash_delta 0 --revenue_change 5000 --cost_change 0 --notes ""
        Records a businessman's weekly decision.

    python claude_turn.py apply_regulator "Городская комиссия (гос. органы)" \
        --target "Игорь Соколов" --fine 0 --verdict "..."
        Records the regulator's ruling on whatever case is currently pending.

Both writes go to pending_*.json files; advance_week.py picks them up on
its next run and clears them.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from state_store import city_from_state, load_state

PENDING_BUSINESS_PATH = Path(__file__).parent / "pending_claude_action.json"
PENDING_REGULATOR_CASE_PATH = Path(__file__).parent / "pending_regulator_case.json"
PENDING_REGULATOR_VERDICT_PATH = Path(__file__).parent / "pending_regulator_verdict.json"


def cmd_show(args: argparse.Namespace) -> None:
    state = load_state()
    city = city_from_state(state)
    agent = state["agents"].get(args.agent)
    if agent is None:
        raise SystemExit(f"Unknown agent: {args.agent}")

    monthly_profit_goal = state["meta"]["monthly_profit_goal"]
    deadline_week = state["meta"]["deadline_week"]
    weeks_left = max(0, deadline_week - city.week)

    print(city.describe())
    if city.notes and city.notes[-1].startswith(f"[Неделя {city.week}]"):
        print(city.notes[-1])
    print(
        f"\nДедлайн на неделе {deadline_week} (осталось {weeks_left} нед.). "
        f"Цель -- пассивная прибыль от {monthly_profit_goal:.0f} руб/мес."
    )

    if agent["role"] == "regulator":
        print(f"\n{args.agent} (гос. органы)")
        print(f"Персонаж: {agent['persona']}")
        if PENDING_REGULATOR_CASE_PATH.exists():
            case = json.loads(PENDING_REGULATOR_CASE_PATH.read_text(encoding="utf-8"))
            print(f"\n(!) Есть дело на рассмотрении (неделя {case['week']}):")
            print(f"    Цель проверки: {case['target']}")
            print(f"    Факты: {case['case_facts']}")
        else:
            print("\nНет дел на рассмотрении.")
        if PENDING_REGULATOR_VERDICT_PATH.exists():
            print("\n(!) Уже есть неприменённое решение в очереди -- оно будет перезаписано.")
        return

    print(f"\n{args.agent} ({agent['business_name']}), сектор: {agent['sector']}")
    print(f"Персонаж: {agent['persona']}")
    print(
        f"Капитал: {agent['cash']:.0f} руб, выручка/нед {agent['weekly_revenue']:.0f}, "
        f"издержки/нед {agent['weekly_costs']:.0f}, недель подряд в плюсе: {agent['consecutive_profitable_weeks']}"
    )
    if agent["history"]:
        print("История:")
        for line in agent["history"]:
            print(" ", line)
    if PENDING_BUSINESS_PATH.exists():
        print("\n(!) Уже есть неприменённый ход в очереди -- он будет перезаписан.")


def cmd_apply(args: argparse.Namespace) -> None:
    pending = {
        "agent": args.agent,
        "action": args.action,
        "reasoning": args.reasoning,
        "cash_delta": args.cash_delta,
        "revenue_change": args.revenue_change,
        "cost_change": args.cost_change,
        "risk_flag": args.risk_flag,
        "notes": args.notes or "",
    }
    PENDING_BUSINESS_PATH.write_text(json.dumps(pending, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Ход для {args.agent} записан, применится на следующем тике advance_week.py.")


def cmd_apply_regulator(args: argparse.Namespace) -> None:
    if not PENDING_REGULATOR_CASE_PATH.exists():
        raise SystemExit("Нет дела на рассмотрении -- сначала проверьте `show`, дождитесь появления дела.")
    case = json.loads(PENDING_REGULATOR_CASE_PATH.read_text(encoding="utf-8"))
    if case["target"] != args.target:
        raise SystemExit(f"Дело на рассмотрении сейчас против {case['target']}, а не {args.target}.")

    verdict = {"target": args.target, "fine": args.fine, "verdict": args.verdict}
    PENDING_REGULATOR_VERDICT_PATH.write_text(json.dumps(verdict, ensure_ascii=False, indent=2), encoding="utf-8")
    PENDING_REGULATOR_CASE_PATH.unlink()
    print(f"Решение по делу {args.target} записано, применится на следующем тике advance_week.py.")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_show = sub.add_parser("show")
    p_show.add_argument("agent")
    p_show.set_defaults(func=cmd_show)

    p_apply = sub.add_parser("apply")
    p_apply.add_argument("agent")
    p_apply.add_argument("--action", required=True)
    p_apply.add_argument("--reasoning", required=True)
    p_apply.add_argument("--cash_delta", type=float, default=0)
    p_apply.add_argument("--revenue_change", type=float, default=0)
    p_apply.add_argument("--cost_change", type=float, default=0)
    p_apply.add_argument("--risk_flag", action="store_true")
    p_apply.add_argument("--notes", default="")
    p_apply.set_defaults(func=cmd_apply)

    p_apply_reg = sub.add_parser("apply_regulator")
    p_apply_reg.add_argument("agent")
    p_apply_reg.add_argument("--target", required=True)
    p_apply_reg.add_argument("--fine", type=float, default=0)
    p_apply_reg.add_argument("--verdict", required=True)
    p_apply_reg.set_defaults(func=cmd_apply_regulator)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
