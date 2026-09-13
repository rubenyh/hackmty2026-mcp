"""Packaged form requirements and strict business contexts; never executable JSON."""

import json
from datetime import date
from importlib.resources import files
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field, StrictFloat, StrictInt, field_validator, model_validator

from supabase_mcp.models import StrictModel

CONTRACT = json.loads(files(__package__).joinpath("actions.json").read_text())
ACTIONS = {entry["name"]: entry for entry in CONTRACT["actions"]}
Amount = Annotated[StrictFloat | StrictInt, Field(ge=0, le=1_000_000)]


class NamedContext(StrictModel):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Escribe un nombre.")
        return value.strip()


class BudgetContext(NamedContext):
    category: str = Field(min_length=1, max_length=80)
    limit_amount: Amount = Field(gt=0, le=100_000)
    start_date: str
    end_date: str

    @field_validator("category")
    @classmethod
    def category_key(cls, value: str) -> str:
        import unicodedata

        normalized = "".join(
            c
            for c in unicodedata.normalize("NFKD", value.lower().strip())
            if not unicodedata.combining(c)
        )
        aliases = {
            "alimentos": "groceries",
            "supermercado": "groceries",
            "restaurantes": "dining",
            "comida": "dining",
            "transporte": "transport",
            "servicios": "utilities",
            "salud": "health",
            "vivienda": "housing",
            "entretenimiento": "entertainment",
            "compras": "shopping",
            "otros": "other",
        }
        result = aliases.get(normalized, normalized)
        if result not in {*aliases.values(), "credit_card", "education", "travel"}:
            raise ValueError(
                "Elige una categoría disponible: alimentos, restaurantes, transporte, "
                "servicios, salud o vivienda."
            )
        return result

    @model_validator(mode="after")
    def dates(self) -> "BudgetContext":
        if date.fromisoformat(self.start_date) > date.fromisoformat(self.end_date):
            raise ValueError("La fecha final debe ser posterior o igual al inicio.")
        if not self.category.strip():
            raise ValueError("Escribe una categoría.")
        return self


class BudgetUpdate(BudgetContext):
    id: UUID


class GoalContext(NamedContext):
    target_amount: Amount = Field(gt=0)
    target_date: str
    suggested_monthly_contribution: Amount = Field(le=100_000)

    @field_validator("target_date")
    @classmethod
    def real_date(cls, value: str) -> str:
        date.fromisoformat(value)
        return value


class GoalUpdate(GoalContext):
    id: UUID


CONTEXTS: dict[str, type[BaseModel]] = {
    "budget.create": BudgetContext,
    "budget.update": BudgetUpdate,
    "savings_goal.create": GoalContext,
    "savings_goal.update": GoalUpdate,
    "budget.load": NamedContext,
    "savings_goal.load": NamedContext,
}
