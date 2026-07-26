from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Agent:
    name: str
    role: str  # "businessman" | "lawyer" | "regulator"
    persona: str
    provider: str = "gemini"  # "gemini" | "groq" | "openrouter" | "ollama" | "github" | "claude"
    sector: str | None = None
    business_name: str | None = None
    cash: float = 0
    weekly_revenue: float = 0
    weekly_costs: float = 0
    consecutive_profitable_weeks: int = 0
    history: list[str] = field(default_factory=list)
    state: dict = field(default_factory=dict)  # scratch space, e.g. last_risk_flag

    def add_history(self, line: str, keep: int) -> None:
        self.history.append(line)
        if len(self.history) > keep:
            self.history = self.history[-keep:]

    def net_worth(self) -> float:
        return self.cash
