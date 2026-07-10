from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import Field, field_validator

from app.db.models.base import DbModel, TimestampModel


class WealthCheckpointCreate(DbModel):
    checkpoint_date: date
    wealth_amount: Decimal = Field(ge=0)
    currency: str = "BRL"

    @field_validator("wealth_amount", mode="before")
    @classmethod
    def _parse_amount(cls, value: object) -> Decimal:
        return _parse_decimal(value)

    @field_validator("currency")
    @classmethod
    def _normalize_currency(cls, value: str) -> str:
        normalized = value.strip().upper()
        if len(normalized) != 3:
            raise ValueError("currency must be a three-letter ISO code")
        return normalized


class WealthCheckpoint(TimestampModel):
    id: str
    checkpoint_date: date
    wealth_amount: Decimal
    currency: str = "BRL"


class WealthCheckpointList(DbModel):
    checkpoints: list[WealthCheckpoint]


class WealthProjectionSettingsUpdate(DbModel):
    average_annual_return_multiplier: Decimal = Field(ge=0)

    @field_validator("average_annual_return_multiplier", mode="before")
    @classmethod
    def _parse_multiplier(cls, value: object) -> Decimal:
        return _parse_decimal(value)


class WealthProjectionSettings(DbModel):
    average_annual_return_multiplier: Decimal
    is_default: bool


class MonthlyCapacityMonth(DbModel):
    month: str
    label: str
    income: Decimal
    living_costs: Decimal
    fixed_costs: Decimal
    debt_installments: Decimal
    investment_capacity: Decimal
    unused_capacity: Decimal
    capacity_ceiling: Decimal
    projected_wealth: Decimal | None
    has_debt_pressure: bool
    has_debt_drop: bool
    has_investment_capacity: bool


class MonthlyReportCheckpoint(DbModel):
    date: date
    wealth_amount: Decimal


class MonthlyCapacityReport(DbModel):
    currency: str
    average_annual_return_multiplier: Decimal
    wealth_checkpoints: list[MonthlyReportCheckpoint]
    months: list[MonthlyCapacityMonth]


def _parse_decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None or isinstance(value, bool):
        raise ValueError("value must be a decimal")
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        normalized = value.strip().replace(",", ".")
        if not normalized:
            raise ValueError("value must be a decimal")
        return Decimal(normalized)
    return Decimal(str(value))
