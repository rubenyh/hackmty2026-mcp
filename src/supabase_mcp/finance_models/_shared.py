"""Shared strict contracts for financial domains."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator
from pydantic_core import PydanticCustomError

from supabase_mcp.models import StrictModel, UserScope


class TimePeriod(StrEnum):
    TODAY = "today"
    CURRENT_WEEK = "current_week"
    CURRENT_MONTH = "current_month"
    PREVIOUS_MONTH = "previous_month"
    LAST_30_DAYS = "last_30_days"
    LAST_90_DAYS = "last_90_days"
    LAST_3_MONTHS = "last_3_months"
    LAST_6_MONTHS = "last_6_months"
    LAST_12_MONTHS = "last_12_months"
    CURRENT_YEAR = "current_year"
    CUSTOM = "custom"


class ResolvedDateRange(StrictModel):
    start_date: date
    end_date: date
    end_inclusive: Literal[True] = True
    timezone: str


class Pagination(StrictModel):
    limit: int = Field(default=50, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=256)


class MoneyAmount(StrictModel):
    currency: str = Field(min_length=3, max_length=3)
    amount: Decimal


class CurrencyTotal(StrictModel):
    currency: str = Field(min_length=3, max_length=3)
    total: Decimal


class AppliedFilters(StrictModel):
    period: ResolvedDateRange | None = None
    account_ids: list[UUID] = Field(default_factory=list, max_length=50)


class DataQuality(StrictModel):
    complete: bool = True
    warnings: list[str] = Field(default_factory=list, max_length=20)


AccountIds = Annotated[list[UUID], Field(max_length=50)]
ResourceIds = Annotated[list[UUID], Field(max_length=100)]


class _ScopedRequest(StrictModel):
    scope: UserScope = Field(description="Trusted user scope / Ámbito de usuario confiable")


class _PeriodRequest(_ScopedRequest):
    period: TimePeriod = TimePeriod.CURRENT_MONTH
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def validate_custom_dates(self) -> Self:
        # Subclasses intentionally narrow ``period`` with Literal values, so
        # Pydantic may store the public string rather than a TimePeriod member.
        # Normalizing to the public value accepts both representations; identity does not.
        if str(self.period) == TimePeriod.CUSTOM.value:
            if self.start_date is None or self.end_date is None:
                raise PydanticCustomError(
                    "invalid_date_range",
                    "custom / personalizado requires start_date and end_date",
                )
            if self.end_date < self.start_date:
                raise PydanticCustomError(
                    "invalid_date_range", "end_date must be on or after start_date"
                )
        elif self.start_date is not None or self.end_date is not None:
            raise PydanticCustomError(
                "invalid_date_range",
                "start_date and end_date are only valid for custom / personalizado",
            )
        return self
