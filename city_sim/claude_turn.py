"""CLI for the human-supplied (Claude) businessman turn.

    python claude_turn.py show "Игорь Соколов (Claude)"
    python claude_turn.py apply "Игорь Соколов (Claude)" \
        --action "..." --reasoning "..." \
        --cash_delta 0 --revenue_change 5000 --cost_change 0 --notes ""

`show` prints the current city + agent state so a person (here, Claude
reasoning in chat) can decide the week's action. `apply` writes that
decision to pending_claude_action.json, where advance_week.py will pick it
up on its next run and clear the file.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from state_store import city_from_state, load_state

PENDING_PATH = Path(__file__).parent / "pending_claude_action.json"


def cmd_show(args: argparse.Namespace) -> None:
    state = load_state()
    city = city_from_state(state)
    agent = state["agents"].get(args.agent)
    if agent is None:
        raise SystemExit(f"Unknown agent: {args.agent}")

    goal_cash = state["meta"]["goal_cash"]
    deadline_week = state["meta"]["deadline_week"]
    weeks_left = max(0, deadline_week - city.week)

    print(city.describe())
    if city.notes and city.notes[-1].startswith(f"[Неделя {city.week}]"):
        print(city.notes[-1])
    print(
        f"\nКорабль прибывает на неделе {deadline_week} (осталось {weeks_left} нед.). "
        f"Билет стоит {goal_cash:.0f} руб. У кого не хватит -- останется в городе."
    )

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
    if PENDING_PATH.exists():
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
    PENDING_PATH.write_text(json.dumps(pending, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Ход для {args.agent} записан, применится на следующем тике advance_week.py.")


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

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
