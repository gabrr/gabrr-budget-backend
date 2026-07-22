from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import CurrentUser
from app.db.models.wealth import MonthlyCapacityReport
from app.db.session import get_session
from app.services.monthly_capacity_report import MonthlyCapacityReportService

reports_router = APIRouter(prefix="/reports", tags=["reports"])
_monthly_capacity_report_service = MonthlyCapacityReportService()


@reports_router.get("/monthly-capacity", response_model=MonthlyCapacityReport)
async def get_monthly_capacity_report(
    current_user: CurrentUser,
    session: Session = Depends(get_session),
    months: int = Query(default=60, ge=1, le=120),
    anchor_month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    currency: str = Query(default="BRL", min_length=3, max_length=3),
    include_drafts: bool = Query(default=False),
) -> MonthlyCapacityReport:
    try:
        return _monthly_capacity_report_service.build_report(
            session,
            user_id=current_user.id,
            anchor_month=anchor_month,
            months=months,
            currency=currency.upper(),
            include_drafts=include_drafts,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
