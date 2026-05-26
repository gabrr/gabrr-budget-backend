from __future__ import annotations

from typing import Any

from app.db.models.transaction import Transaction
from app.workers.import_worker.helpers import (
    _normalize_currency,
    _optional_date,
    _optional_decimal,
    _optional_int,
    _optional_string,
    _required_confidence,
    _required_date,
    _required_decimal,
    _required_enum,
    _required_string,
)

STATEMENT_KINDS = {"checking_account", "credit_card", "unknown"}
TRANSACTION_NATURES = {"income", "expense", "transfer", "refund", "card_payment", "unknown"}
REPORT_BUCKETS = {"income", "debt_installment", "fixed_cost", "living_cost", "excluded", "unknown"}


def parse_agent_result_for_persistence(
    agent_result: dict[str, Any],
    *,
    import_job_id: str,
) -> tuple[dict[str, Any], list[Transaction]]:
    statement = agent_result.get("statement")
    if not isinstance(statement, dict):
        raise ValueError("Agent result must include a statement object.")

    statement_kind = _required_enum(
        statement.get("kind"),
        path="statement.kind",
        allowed_values=STATEMENT_KINDS,
    )
    statement_metadata = {
        "statement_kind": statement_kind,
        "statement_kind_confidence": _required_confidence(
            statement.get("kind_confidence"),
            path="statement.kind_confidence",
        ),
        "statement_kind_reason": _required_string(
            statement.get("kind_reason"),
            path="statement.kind_reason",
            max_length=1000,
        ),
        "statement_period_start": _optional_date(
            statement.get("period_start"),
            path="statement.period_start",
        ),
        "statement_period_end": _optional_date(
            statement.get("period_end"),
            path="statement.period_end",
        ),
        "institution_name": _optional_string(
            statement.get("institution_name"),
            path="statement.institution_name",
            max_length=255,
        ),
        "account_hint": _optional_string(
            statement.get("account_hint"),
            path="statement.account_hint",
            max_length=255,
        ),
        "statement_kind_source": "agent",
    }
    period_start = statement_metadata["statement_period_start"]
    period_end = statement_metadata["statement_period_end"]
    if period_start is not None and period_end is not None and period_start > period_end:
        raise ValueError(
            "Invalid statement period: statement.period_start must be <= statement.period_end"
        )

    return statement_metadata, map_agent_result_to_transactions(
        agent_result,
        import_job_id=import_job_id,
        statement_kind=statement_kind,
    )


def map_agent_result_to_transactions(
    agent_result: dict[str, Any],
    *,
    import_job_id: str,
    statement_kind: str,
) -> list[Transaction]:
    rows = agent_result.get("transactions")
    if not isinstance(rows, list):
        raise ValueError("Agent result must include a transactions list.")

    transactions: list[Transaction] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"Invalid transaction at index {index}: row must be an object")

        missing = {
            "date",
            "description",
            "amount",
            "transaction_nature",
            "report_bucket",
            "classification_confidence",
            "classification_reason",
        } - set(row)
        if missing:
            missing_fields = ", ".join(sorted(missing))
            raise ValueError(f"Invalid transaction at index {index}: missing {missing_fields}")

        path_prefix = f"transactions[{index}]"
        posted_at = _required_date(row["date"], path=f"{path_prefix}.date")
        amount = _required_decimal(row["amount"], path=f"{path_prefix}.amount")
        description = _required_string(
            row["description"],
            path=f"{path_prefix}.description",
            max_length=500,
        )

        transactions.append(
            Transaction(
                import_job_id=import_job_id,
                posted_at=posted_at,
                date=posted_at,
                description=description,
                merchant_name=_optional_string(
                    row.get("merchant_name"),
                    path=f"{path_prefix}.merchant_name",
                    max_length=255,
                ),
                amount=amount,
                currency=_normalize_currency(row.get("currency"), path=f"{path_prefix}.currency"),
                payment_method=_optional_string(
                    row.get("payment_method"),
                    path=f"{path_prefix}.payment_method",
                    max_length=40,
                ),
                installments=_optional_int(row.get("installments")),
                installments_current=_optional_int(row.get("installments_current")),
                is_draft=True,
                statement_kind=statement_kind,
                transaction_nature=_required_enum(
                    row.get("transaction_nature"),
                    path=f"{path_prefix}.transaction_nature",
                    allowed_values=TRANSACTION_NATURES,
                ),
                report_bucket=_required_enum(
                    row.get("report_bucket"),
                    path=f"{path_prefix}.report_bucket",
                    allowed_values=REPORT_BUCKETS,
                ),
                classification_source="agent",
                classification_confidence=_required_confidence(
                    row.get("classification_confidence"),
                    path=f"{path_prefix}.classification_confidence",
                ),
                classification_reason=_required_string(
                    row.get("classification_reason"),
                    path=f"{path_prefix}.classification_reason",
                    max_length=1000,
                ),
                running_balance=_optional_decimal(
                    row.get("running_balance"),
                    path=f"{path_prefix}.running_balance",
                ),
            )
        )

    return transactions
