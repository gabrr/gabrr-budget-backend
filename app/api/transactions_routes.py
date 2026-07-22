"""Transaction CRUD and listing."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import CurrentUser
from app.config import settings
from app.db.models import ExpenseCategory, Transaction
from app.db.repositories.transactions import (
    TransactionRepository,
    transaction_schema_to_model,
)
from app.db.session import get_session

transactions_router = APIRouter(prefix="/transactions")

_transaction_repository = TransactionRepository()
PROTECTED_CREATE_FIELDS = {"account_id", "import_job_id", "source_import_id", "user_id"}


class TransactionsBulkCreatePayload(BaseModel):
    transactions: list[Transaction] = Field(min_length=1)


def _reject_internal_create_fields(payload: Transaction) -> None:
    forbidden = PROTECTED_CREATE_FIELDS & payload.model_fields_set
    if forbidden:
        field_list = ", ".join(sorted(forbidden))
        raise HTTPException(
            status_code=422,
            detail=f"Cannot set protected fields: {field_list}",
        )


@transactions_router.get("")
async def list_transactions(
    current_user: CurrentUser,
    session: Session = Depends(get_session),
    category: ExpenseCategory | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    import_job_id: str | None = None,
    is_draft: bool | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    transaction_schemas, total = _transaction_repository.list_filtered(
        session,
        user_id=current_user.id,
        category=category,
        date_from=date_from,
        date_to=date_to,
        import_job_id=import_job_id,
        is_draft=is_draft,
        limit=limit,
        offset=offset,
    )
    items = [
        transaction_schema_to_model(stored_transaction_schema)
        for stored_transaction_schema in transaction_schemas
    ]

    return {"items": items, "total": total, "limit": limit, "offset": offset}


@transactions_router.post("", response_model=Transaction, status_code=201)
async def create_transaction(
    current_user: CurrentUser,
    payload: Transaction,
    session: Session = Depends(get_session),
) -> Transaction:
    _reject_internal_create_fields(payload)
    try:
        stored_transaction_schema = _transaction_repository.create(
            session,
            payload,
            user_id=current_user.id,
            default_account_id=settings.default_account_id,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    return transaction_schema_to_model(stored_transaction_schema)


@transactions_router.post("/bulk", response_model=list[Transaction], status_code=201)
async def bulk_create_transactions(
    current_user: CurrentUser,
    payload: TransactionsBulkCreatePayload,
    session: Session = Depends(get_session),
) -> list[Transaction]:
    for transaction in payload.transactions:
        _reject_internal_create_fields(transaction)
    try:
        created_transaction_schemas = _transaction_repository.create_many(
            session,
            payload.transactions,
            user_id=current_user.id,
            default_account_id=settings.default_account_id,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    return [
        transaction_schema_to_model(stored_transaction_schema)
        for stored_transaction_schema in created_transaction_schemas
    ]


@transactions_router.get("/{transaction_id}", response_model=Transaction)
async def get_transaction(
    transaction_id: str,
    current_user: CurrentUser,
    session: Session = Depends(get_session),
) -> Transaction:
    stored_transaction_schema = _transaction_repository.get_by_id(
        session,
        user_id=current_user.id,
        transaction_id=transaction_id,
    )
    if stored_transaction_schema is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    return transaction_schema_to_model(stored_transaction_schema)


@transactions_router.patch("/{transaction_id}", response_model=Transaction)
async def update_transaction(
    transaction_id: str,
    current_user: CurrentUser,
    payload: Transaction,
    session: Session = Depends(get_session),
) -> Transaction:
    try:
        stored_transaction_schema = _transaction_repository.update(
            session,
            user_id=current_user.id,
            transaction_id=transaction_id,
            payload=payload,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if stored_transaction_schema is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    return transaction_schema_to_model(stored_transaction_schema)


@transactions_router.delete("/{transaction_id}")
async def delete_transaction(
    transaction_id: str,
    current_user: CurrentUser,
    session: Session = Depends(get_session),
) -> dict[str, str]:
    deleted = _transaction_repository.delete_by_id(
        session,
        user_id=current_user.id,
        transaction_id=transaction_id,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Transaction not found")

    return {"status": "deleted", "id": transaction_id}
