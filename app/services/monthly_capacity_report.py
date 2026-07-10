from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.wealth import (
    MonthlyCapacityMonth,
    MonthlyCapacityReport,
    MonthlyReportCheckpoint,
)
from app.db.repositories.wealth import WealthRepository
from app.db.schemas.transactions import TransactionSchema

MONEY_QUANT = Decimal("0.01")


@dataclass(frozen=True)
class MonthWindow:
    key: str
    label: str
    start: date
    end: date


class MonthlyCapacityReportService:
    def __init__(self, wealth_repository: WealthRepository | None = None) -> None:
        self._wealth_repository = wealth_repository or WealthRepository()

    def build_report(
        self,
        session: Session,
        *,
        user_id: str,
        anchor_month: str | None,
        months: int,
        currency: str = "BRL",
        include_drafts: bool = False,
    ) -> MonthlyCapacityReport:
        bounded_months = max(1, min(months, 120))
        anchor = _parse_anchor_month(anchor_month)
        window = [_month_window(_add_months(anchor, index)) for index in range(bounded_months)]
        start_date = window[0].start
        end_date = window[-1].end

        totals = {
            month.key: {
                "income": Decimal("0.00"),
                "living_costs": Decimal("0.00"),
                "fixed_costs": Decimal("0.00"),
                "debt_installments": Decimal("0.00"),
            }
            for month in window
        }
        for tx in _load_report_transactions(
            session,
            user_id=user_id,
            start_date=start_date,
            end_date=end_date,
            currency=currency,
            include_drafts=include_drafts,
        ):
            month_key = tx.posted_at.strftime("%Y-%m")
            if tx.report_bucket == "income":
                totals[month_key]["income"] += tx.amount
            elif tx.report_bucket == "debt_installment":
                totals[month_key]["debt_installments"] += abs(tx.amount)
            elif tx.report_bucket == "fixed_cost":
                totals[month_key]["fixed_costs"] += abs(tx.amount)
            elif tx.report_bucket == "living_cost":
                totals[month_key]["living_costs"] += abs(tx.amount)

        settings = self._wealth_repository.get_projection_settings(session, user_id=user_id)
        monthly_return_multiplier = Decimal(
            str(float(settings.average_annual_return_multiplier) ** (1 / 12))
        )
        checkpoints_by_month = self._wealth_repository.latest_checkpoint_by_month(
            session,
            user_id=user_id,
            start_date=start_date,
            end_date=end_date,
            currency=currency,
        )
        all_checkpoints = self._wealth_repository.list_checkpoints(
            session,
            user_id=user_id,
            currency=currency,
        )

        fallback_ceiling = _fallback_capacity_ceiling(totals.values())
        previous_projected_wealth: Decimal | None = None
        report_months: list[MonthlyCapacityMonth] = []
        previous_debt: Decimal | None = None

        for month in window:
            month_totals = totals[month.key]
            income = _money(month_totals["income"])
            living_costs = _money(month_totals["living_costs"])
            fixed_costs = _money(month_totals["fixed_costs"])
            debt_installments = _money(month_totals["debt_installments"])
            investment_capacity = _money(income - living_costs - fixed_costs - debt_installments)
            unused_capacity = Decimal("0.00")
            capacity_ceiling = income if income > 0 else fallback_ceiling

            checkpoint = checkpoints_by_month.get(month.key)
            if checkpoint is not None:
                projected_wealth = _money(checkpoint.wealth_amount)
            elif previous_projected_wealth is None:
                projected_wealth = None
            else:
                projected_wealth = _money(
                    previous_projected_wealth * monthly_return_multiplier + investment_capacity
                )

            has_debt_drop = (
                previous_debt is not None
                and previous_debt > 0
                and (debt_installments == 0 or debt_installments <= previous_debt / 2)
            )
            previous_debt = debt_installments
            if projected_wealth is not None:
                previous_projected_wealth = projected_wealth

            report_months.append(
                MonthlyCapacityMonth(
                    month=month.key,
                    label=month.label,
                    income=income,
                    living_costs=living_costs,
                    fixed_costs=fixed_costs,
                    debt_installments=debt_installments,
                    investment_capacity=investment_capacity,
                    unused_capacity=unused_capacity,
                    capacity_ceiling=_money(capacity_ceiling),
                    projected_wealth=projected_wealth,
                    has_debt_pressure=debt_installments > 0,
                    has_debt_drop=has_debt_drop,
                    has_investment_capacity=investment_capacity > 0,
                )
            )

        return MonthlyCapacityReport(
            currency=currency,
            average_annual_return_multiplier=settings.average_annual_return_multiplier,
            wealth_checkpoints=[
                MonthlyReportCheckpoint(
                    date=checkpoint.checkpoint_date,
                    wealth_amount=checkpoint.wealth_amount,
                )
                for checkpoint in all_checkpoints
                if start_date <= checkpoint.checkpoint_date <= end_date
            ],
            months=report_months,
        )


def _load_report_transactions(
    session: Session,
    *,
    user_id: str,
    start_date: date,
    end_date: date,
    currency: str,
    include_drafts: bool,
) -> list[TransactionSchema]:
    statement = (
        select(TransactionSchema)
        .where(
            TransactionSchema.user_id == user_id,
            TransactionSchema.posted_at >= start_date,
            TransactionSchema.posted_at <= end_date,
            TransactionSchema.currency == currency,
            TransactionSchema.reverted_at.is_(None),
            TransactionSchema.report_bucket.in_(
                ["income", "debt_installment", "fixed_cost", "living_cost"]
            ),
        )
        .order_by(TransactionSchema.posted_at.asc())
    )
    if not include_drafts:
        statement = statement.where(TransactionSchema.is_draft.is_(False))

    return list(session.scalars(statement).all())


def _fallback_capacity_ceiling(values: object) -> Decimal:
    ceilings: list[Decimal] = []
    for month_totals in values:
        if not isinstance(month_totals, dict):
            continue
        income = month_totals["income"]
        total_costs = (
            month_totals["living_costs"]
            + month_totals["fixed_costs"]
            + month_totals["debt_installments"]
        )
        ceilings.append(max(income, total_costs, Decimal("0.00")))

    return _money(max(ceilings) if ceilings else Decimal("0.00"))


def _parse_anchor_month(value: str | None) -> date:
    if value is None:
        today = date.today()
        return date(today.year, today.month, 1)
    year, month = value.split("-", maxsplit=1)
    return date(int(year), int(month), 1)


def _month_window(month: date) -> MonthWindow:
    _, last_day = calendar.monthrange(month.year, month.month)
    return MonthWindow(
        key=month.strftime("%Y-%m"),
        label=month.strftime("%b %Y"),
        start=month,
        end=date(month.year, month.month, last_day),
    )


def _add_months(month: date, offset: int) -> date:
    absolute_month = month.year * 12 + month.month - 1 + offset
    year = absolute_month // 12
    month_number = absolute_month % 12 + 1
    return date(year, month_number, 1)


def _money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
