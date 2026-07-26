"""Persistent JSON state shared between advance_week.py (auto providers,
run daily via Windows Task Scheduler) and claude_turn.py (the human-supplied
Claude businessman turn). This lets two separate processes cooperate on one
ongoing simulation instead of everything living in one Python run.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from agent import Agent
from economy import CityState

STATE_PATH = Path(__file__).parent / "state.json"
CONFIG_PATH = Path(__file__).parent / "agents_config.json"


def init_state() -> dict:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    agents = [
        Agent(**{k: v for k, v in a.items() if k != "role"}, role=a["role"])
        for a in config["agents"]
    ]
    return {
        "meta": {
            "start_date": config["start_date"],
            "monthly_profit_goal": config["monthly_profit_goal"],
            "profit_stable_weeks_required": config["profit_stable_weeks_required"],
            "personal_monthly_expenses": config["personal_monthly_expenses"],
            "deadline_week": config["deadline_week"],
            "history_keep": config["history_keep"],
            "concluded": False,
        },
        "city": asdict(CityState()),
        "agents": {a.name: asdict(a) for a in agents},
    }


def load_state() -> dict:
    if not STATE_PATH.exists():
        state = init_state()
        save_state(state)
        return state
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def city_from_state(state: dict) -> CityState:
    c = state["city"]
    city = CityState()
    city.week = c["week"]
    city.inflation_pct_annual = c["inflation_pct_annual"]
    city.key_rate_pct = c["key_rate_pct"]
    city.sector_demand = c["sector_demand"]
    city.notes = c["notes"]
    return city


def agents_from_state(state: dict) -> list[Agent]:
    return [Agent(**d) for d in state["agents"].values()]


def sync_state(state: dict, city: CityState, agents: list[Agent]) -> None:
    state["city"] = asdict(city)
    state["agents"] = {a.name: asdict(a) for a in agents}
