"""Transaction CRUD and listing."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import ExpenseCategory, Transaction
from app.db.repositories.transactions import (
    TransactionRepository,
    transaction_schema_to_model,
)
from app.db.session import get_session

transactions_router = APIRouter(prefix="/transactions")

_transaction_repository = TransactionRepository()


class TransactionsBulkCreatePayload(BaseModel):
    transactions: list[Transaction] = Field(min_length=1)


@transactions_router.get("")
async def list_transactions(
    session: Session = Depends(get_session),
    category: ExpenseCategory | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    is_draft: bool | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    transaction_schemas, total = _transaction_repository.list_filtered(
        session,
        user_id=settings.default_user_id,
        category=category,
        date_from=date_from,
        date_to=date_to,
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
    payload: Transaction,
    session: Session = Depends(get_session),
) -> Transaction:
    try:
        stored_transaction_schema = _transaction_repository.create(
            session,
            payload,
            default_user_id=settings.default_user_id,
            default_account_id=settings.default_account_id,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    return transaction_schema_to_model(stored_transaction_schema)


@transactions_router.post("/bulk", response_model=list[Transaction], status_code=201)
async def bulk_create_transactions(
    payload: TransactionsBulkCreatePayload,
    session: Session = Depends(get_session),
) -> list[Transaction]:
    try:
        created_transaction_schemas = _transaction_repository.create_many(
            session,
            payload.transactions,
            default_user_id=settings.default_user_id,
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
    session: Session = Depends(get_session),
) -> Transaction:
    stored_transaction_schema = _transaction_repository.get_by_id(
        session,
        user_id=settings.default_user_id,
        transaction_id=transaction_id,
    )
    if stored_transaction_schema is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    return transaction_schema_to_model(stored_transaction_schema)


@transactions_router.patch("/{transaction_id}", response_model=Transaction)
async def update_transaction(
    transaction_id: str,
    payload: Transaction,
    session: Session = Depends(get_session),
) -> Transaction:
    try:
        stored_transaction_schema = _transaction_repository.update(
            session,
            user_id=settings.default_user_id,
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
    session: Session = Depends(get_session),
) -> dict[str, str]:
    deleted = _transaction_repository.delete_by_id(
        session,
        user_id=settings.default_user_id,
        transaction_id=transaction_id,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Transaction not found")

    return {"status": "deleted", "id": transaction_id}
