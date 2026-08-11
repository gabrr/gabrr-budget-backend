from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, contains_eager, joinedload

from app.db.models.categories import ExpenseCategory
from app.db.models.transaction import Transaction
from app.db.schemas.accounts import AccountSchema
from app.db.schemas.categories import CategorySchema
from app.db.schemas.transactions import TransactionSchema

USER_CORRECTED_REASON = "User corrected classification."
USER_CONFIDENCE = Decimal("1.0000")

REPORT_BUCKETS = {
    "income",
    "debt_installment",
    "fixed_cost",
    "living_cost",
    "excluded",
    "unknown",
}
TRANSACTION_NATURES = {"income", "expense", "transfer", "refund", "card_payment", "unknown"}
PROTECTED_PATCH_FIELDS = {
    "account_id",
    "classification_source",
    "import_job_id",
    "running_balance",
    "source_import_id",
    "statement_kind",
    "user_id",
}


def transaction_schema_to_model(
    stored_transaction_schema: TransactionSchema,
    *,
    category_key: str | None = None,
) -> Transaction:
    """Map ORM row to API Transaction; extra Pydantic-only fields stay unset."""
    resolved_category_key = category_key
    if (
        resolved_category_key is None
        and stored_transaction_schema.category_id
        and stored_transaction_schema.category is not None
    ):
        resolved_category_key = stored_transaction_schema.category.key

    category_enum = ExpenseCategory(resolved_category_key) if resolved_category_key else None

    return Transaction(
        id=stored_transaction_schema.id,
        user_id=stored_transaction_schema.user_id,
        account_id=stored_transaction_schema.account_id,
        category_id=stored_transaction_schema.category_id,
        category=category_enum,
        source_import_id=stored_transaction_schema.source_import_id,
        import_job_id=stored_transaction_schema.import_job_id,
        posted_at=stored_transaction_schema.posted_at,
        date=stored_transaction_schema.posted_at,
        description=stored_transaction_schema.description,
        merchant_name=stored_transaction_schema.merchant_name,
        amount=stored_transaction_schema.amount,
        currency=stored_transaction_schema.currency,
        payment_method=stored_transaction_schema.payment_method,
        installments=stored_transaction_schema.installments,
        installments_current=stored_transaction_schema.installments_current,
        reverted_at=stored_transaction_schema.reverted_at,
        is_draft=stored_transaction_schema.is_draft,
        statement_kind=stored_transaction_schema.statement_kind,
        transaction_nature=stored_transaction_schema.transaction_nature,
        report_bucket=stored_transaction_schema.report_bucket,
        classification_source=stored_transaction_schema.classification_source,
        classification_confidence=stored_transaction_schema.classification_confidence,
        classification_reason=stored_transaction_schema.classification_reason,
        running_balance=stored_transaction_schema.running_balance,
        created_at=stored_transaction_schema.created_at,
        updated_at=stored_transaction_schema.updated_at,
    )


class TransactionRepository:
    """Stateless persistence for TransactionSchema."""

    def list_filtered(
        self,
        session: Session,
        *,
        user_id: str,
        category: ExpenseCategory | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        import_job_id: str | None = None,
        is_draft: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[TransactionSchema], int]:

        transactions_listing_query = select(TransactionSchema).where(
            TransactionSchema.user_id == user_id
        )

        transaction_count_query = (
            select(func.count())
            .select_from(TransactionSchema)
            .where(
                TransactionSchema.user_id == user_id,
            )
        )

        if is_draft is None:
            transactions_listing_query = transactions_listing_query.where(
                TransactionSchema.is_draft.is_(False)
            )
            transaction_count_query = transaction_count_query.where(
                TransactionSchema.is_draft.is_(False)
            )
        else:
            transactions_listing_query = transactions_listing_query.where(
                TransactionSchema.is_draft.is_(is_draft)
            )
            transaction_count_query = transaction_count_query.where(
                TransactionSchema.is_draft.is_(is_draft)
            )

        if category is not None:
            transactions_listing_query = (
                select(TransactionSchema)
                .join(
                    CategorySchema,
                    TransactionSchema.category_id == CategorySchema.id,
                )
                .where(
                    TransactionSchema.user_id == user_id,
                    CategorySchema.key == category.value,
                )
                .options(contains_eager(TransactionSchema.category))
            )
            transaction_count_query = (
                select(func.count())
                .select_from(TransactionSchema)
                .join(
                    CategorySchema,
                    TransactionSchema.category_id == CategorySchema.id,
                )
                .where(
                    TransactionSchema.user_id == user_id,
                    CategorySchema.key == category.value,
                )
            )
            if is_draft is None:
                transactions_listing_query = transactions_listing_query.where(
                    TransactionSchema.is_draft.is_(False)
                )
                transaction_count_query = transaction_count_query.where(
                    TransactionSchema.is_draft.is_(False)
                )
            else:
                transactions_listing_query = transactions_listing_query.where(
                    TransactionSchema.is_draft.is_(is_draft)
                )
                transaction_count_query = transaction_count_query.where(
                    TransactionSchema.is_draft.is_(is_draft)
                )

        if date_from is not None:
            transactions_listing_query = transactions_listing_query.where(
                TransactionSchema.posted_at >= date_from
            )
            transaction_count_query = transaction_count_query.where(
                TransactionSchema.posted_at >= date_from
            )
        if date_to is not None:
            transactions_listing_query = transactions_listing_query.where(
                TransactionSchema.posted_at <= date_to
            )
            transaction_count_query = transaction_count_query.where(
                TransactionSchema.posted_at <= date_to
            )

        if import_job_id is not None:
            transactions_listing_query = transactions_listing_query.where(
                TransactionSchema.import_job_id == import_job_id
            )
            transaction_count_query = transaction_count_query.where(
                TransactionSchema.import_job_id == import_job_id
            )

        total = int(session.execute(transaction_count_query).scalar_one())

        if category is not None:
            ordered_transactions_query = (
                transactions_listing_query.order_by(TransactionSchema.posted_at.desc())
                .limit(limit)
                .offset(offset)
            )
        else:
            ordered_transactions_query = (
                transactions_listing_query.options(joinedload(TransactionSchema.category))
                .order_by(TransactionSchema.posted_at.desc())
                .limit(limit)
                .offset(offset)
            )
        transaction_schemas = list(session.scalars(ordered_transactions_query).unique().all())

        return transaction_schemas, total

    def get_by_id(
        self,
        session: Session,
        *,
        user_id: str,
        transaction_id: str,
    ) -> TransactionSchema | None:
        select_transaction_query = (
            select(TransactionSchema)
            .where(
                TransactionSchema.id == transaction_id,
                TransactionSchema.user_id == user_id,
            )
            .options(joinedload(TransactionSchema.category))
        )

        return session.scalars(select_transaction_query).first()

    def create(
        self,
        session: Session,
        payload: Transaction,
        *,
        user_id: str,
        default_account_id: str,
    ) -> TransactionSchema:
        posted_at = payload.posted_at or payload.date
        if posted_at is None:
            raise ValueError("posted_at or date is required")
        if payload.description is None or not str(payload.description).strip():
            raise ValueError("description is required")
        if payload.amount is None:
            raise ValueError("amount is required")

        account_id = default_account_id
        _validate_account_id(session, user_id=user_id, account_id=account_id)
        _validate_category_id(session, user_id=user_id, category_id=payload.category_id)

        new_transaction_schema = TransactionSchema(
            user_id=user_id,
            account_id=account_id,
            category_id=payload.category_id,
            source_import_id=payload.source_import_id,
            import_job_id=payload.import_job_id,
            posted_at=posted_at,
            description=payload.description.strip(),
            merchant_name=payload.merchant_name,
            amount=Decimal(str(payload.amount)),
            currency=(payload.currency or "BRL").upper()[:3],
            payment_method=payload.payment_method,
            installments=payload.installments,
            installments_current=payload.installments_current,
            reverted_at=payload.reverted_at,
            is_draft=bool(payload.is_draft),
            statement_kind=payload.statement_kind,
            transaction_nature=payload.transaction_nature,
            report_bucket=payload.report_bucket,
            classification_source=payload.classification_source,
            classification_confidence=(
                Decimal(str(payload.classification_confidence))
                if payload.classification_confidence is not None
                else None
            ),
            classification_reason=payload.classification_reason,
            running_balance=(
                Decimal(str(payload.running_balance)) if payload.running_balance is not None else None
            ),
        )
        session.add(new_transaction_schema)
        session.flush()
        session.refresh(new_transaction_schema, ["category"])

        return new_transaction_schema

    def create_many(
        self,
        session: Session,
        items: list[Transaction],
        *,
        user_id: str,
        default_account_id: str,
    ) -> list[TransactionSchema]:
        created_transaction_schemas: list[TransactionSchema] = []
        for payload in items:
            created_transaction_schemas.append(
                self.create(
                    session,
                    payload,
                    user_id=user_id,
                    default_account_id=default_account_id,
                )
            )

        return created_transaction_schemas

    def update(
        self,
        session: Session,
        *,
        user_id: str,
        transaction_id: str,
        payload: Transaction,
    ) -> TransactionSchema | None:
        stored_transaction_schema = self.get_by_id(
            session, user_id=user_id, transaction_id=transaction_id
        )
        if stored_transaction_schema is None:
            return None

        patch_fields = payload.model_dump(exclude_unset=True, exclude={"id", "category"})
        if "date" in patch_fields and "posted_at" not in patch_fields:
            patch_fields["posted_at"] = patch_fields.pop("date")
        elif "date" in patch_fields and "posted_at" in patch_fields:
            patch_fields.pop("date", None)

        patch_fields = _prepare_transaction_patch(
            session,
            user_id=user_id,
            patch_fields=patch_fields,
        )

        field_map = {
            "user_id": "user_id",
            "account_id": "account_id",
            "category_id": "category_id",
            "source_import_id": "source_import_id",
            "posted_at": "posted_at",
            "description": "description",
            "merchant_name": "merchant_name",
            "payment_method": "payment_method",
            "installments": "installments",
            "installments_current": "installments_current",
            "reverted_at": "reverted_at",
            "is_draft": "is_draft",
            "transaction_nature": "transaction_nature",
            "report_bucket": "report_bucket",
            "classification_source": "classification_source",
            "classification_reason": "classification_reason",
        }
        for pydantic_key, orm_key in field_map.items():
            if pydantic_key in patch_fields:
                setattr(stored_transaction_schema, orm_key, patch_fields[pydantic_key])
        if "amount" in patch_fields and patch_fields["amount"] is not None:
            stored_transaction_schema.amount = Decimal(str(patch_fields["amount"]))
        if "currency" in patch_fields and patch_fields["currency"] is not None:
            stored_transaction_schema.currency = str(patch_fields["currency"]).upper()[:3]
        if "description" in patch_fields and patch_fields["description"] is not None:
            stored_transaction_schema.description = str(patch_fields["description"]).strip()
        if "classification_confidence" in patch_fields:
            confidence = patch_fields["classification_confidence"]
            stored_transaction_schema.classification_confidence = (
                Decimal(str(confidence)) if confidence is not None else None
            )
        if "running_balance" in patch_fields:
            running_balance = patch_fields["running_balance"]
            stored_transaction_schema.running_balance = (
                Decimal(str(running_balance)) if running_balance is not None else None
            )

        session.flush()
        session.refresh(stored_transaction_schema, ["category"])

        return stored_transaction_schema

    def delete_by_id(
        self,
        session: Session,
        *,
        user_id: str,
        transaction_id: str,
    ) -> bool:
        stored_transaction_schema = self.get_by_id(
            session, user_id=user_id, transaction_id=transaction_id
        )
        if stored_transaction_schema is None:
            return False
        session.delete(stored_transaction_schema)

        return True

    def has_committed_for_import_job(
        self,
        session: Session,
        *,
        import_job_id: str,
    ) -> bool:
        statement = select(TransactionSchema.id).where(
            TransactionSchema.import_job_id == import_job_id,
            TransactionSchema.is_draft.is_(False),
        )

        return session.scalars(statement.limit(1)).first() is not None

    def delete_drafts_for_import_job(
        self,
        session: Session,
        *,
        import_job_id: str,
    ) -> int:
        result = session.execute(
            delete(TransactionSchema).where(
                TransactionSchema.import_job_id == import_job_id,
                TransactionSchema.is_draft.is_(True),
            )
        )

        return int(result.rowcount or 0)

    def delete_for_import_job(
        self,
        session: Session,
        *,
        user_id: str,
        import_job_id: str,
    ) -> int:
        result = session.execute(
            delete(TransactionSchema).where(
                TransactionSchema.user_id == user_id,
                TransactionSchema.import_job_id == import_job_id,
            )
        )

        return int(result.rowcount or 0)


def _prepare_transaction_patch(
    session: Session,
    *,
    user_id: str,
    patch_fields: dict,
) -> dict:
    forbidden = PROTECTED_PATCH_FIELDS & set(patch_fields)
    if forbidden:
        field_list = ", ".join(sorted(forbidden))
        raise ValueError(f"Cannot update protected fields: {field_list}")

    classification_changed = "report_bucket" in patch_fields or "transaction_nature" in patch_fields

    if "report_bucket" in patch_fields:
        patch_fields["report_bucket"] = _validate_enum(
            "report_bucket",
            patch_fields["report_bucket"],
            REPORT_BUCKETS,
        )

    if "transaction_nature" in patch_fields:
        patch_fields["transaction_nature"] = _validate_enum(
            "transaction_nature",
            patch_fields["transaction_nature"],
            TRANSACTION_NATURES,
        )

    if "classification_confidence" in patch_fields:
        patch_fields["classification_confidence"] = _validate_confidence(
            patch_fields["classification_confidence"]
        )

    if "classification_reason" in patch_fields:
        patch_fields["classification_reason"] = _validate_reason(
            patch_fields["classification_reason"]
        )

    if "is_draft" in patch_fields and not isinstance(patch_fields["is_draft"], bool):
        raise ValueError("is_draft must be a boolean")

    if "category_id" in patch_fields:
        _validate_category_id(
            session,
            user_id=user_id,
            category_id=patch_fields["category_id"],
        )

    if classification_changed:
        patch_fields["classification_source"] = "user"
        patch_fields.setdefault("classification_confidence", USER_CONFIDENCE)
        patch_fields.setdefault("classification_reason", USER_CORRECTED_REASON)

    return patch_fields


def _validate_enum(field_name: str, value: object, allowed_values: set[str]) -> str:
    if value is None:
        raise ValueError(f"{field_name} is required")

    normalized = str(value).strip()
    if normalized not in allowed_values:
        allowed = ", ".join(sorted(allowed_values))
        raise ValueError(f"Invalid {field_name}: {normalized!r} is not one of {allowed}")

    return normalized


def _validate_confidence(value: object) -> Decimal | None:
    if value is None:
        return None

    try:
        confidence = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError("classification_confidence must be a decimal") from error
    if confidence < Decimal("0") or confidence > Decimal("1"):
        raise ValueError("classification_confidence must be between 0 and 1")

    return confidence


def _validate_reason(value: object) -> str | None:
    if value is None:
        return None

    reason = str(value).strip()
    if not reason:
        raise ValueError("classification_reason cannot be blank")
    if len(reason) > 1000:
        raise ValueError("classification_reason cannot be longer than 1000 characters")

    return reason


def _validate_category_id(
    session: Session,
    *,
    user_id: str,
    category_id: str | None,
) -> None:
    if category_id is None:
        return

    category = session.get(CategorySchema, category_id)
    if category is None:
        raise ValueError("category_id does not exist")
    if category.user_id not in {None, user_id} and not category.is_system:
        raise ValueError("category_id is not available to this user")


def _validate_account_id(session: Session, *, user_id: str, account_id: str) -> None:
    account = session.get(AccountSchema, account_id)
    if account is None or account.user_id != user_id or not account.is_active:
        raise ValueError("Default account is not available to this user")
