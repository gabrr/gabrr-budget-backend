from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models.transaction import Transaction
from app.db.repositories.import_jobs import ImportJobRepository
from app.db.repositories.transactions import TransactionRepository


def save_parsed_import_result(
    session: Session,
    *,
    job_id: str,
    user_id: str,
    default_account_id: str,
    statement_metadata: dict,
    transactions: list[Transaction],
    import_job_repository: ImportJobRepository,
    transaction_repository: TransactionRepository,
) -> None:
    if transaction_repository.has_committed_for_import_job(
        session,
        import_job_id=job_id,
    ):
        raise ValueError("Import job already has committed transactions; retry cannot replace them.")

    import_job_repository.save_statement_metadata(
        session,
        job_id,
        metadata=statement_metadata,
    )
    transaction_repository.delete_drafts_for_import_job(
        session,
        import_job_id=job_id,
    )
    transaction_repository.create_many(
        session,
        transactions,
        user_id=user_id,
        default_account_id=default_account_id,
    )
    import_job_repository.mark_step(
        session,
        job_id,
        current_step="Draft transactions saved",
    )
    import_job_repository.mark_done(session, job_id)
