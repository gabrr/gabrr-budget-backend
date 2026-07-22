import logging

from fastapi import APIRouter, Depends

from app.api.agents_routes import agents_router
from app.api.categories_routes import categories_router
from app.api.import_jobs_routes import import_jobs_router
from app.api.reports_routes import reports_router
from app.api.transactions_routes import transactions_router
from app.api.wealth_routes import wealth_router
from app.auth import get_current_user

router = APIRouter(dependencies=[Depends(get_current_user)])
logger = logging.getLogger(__name__)

router.include_router(categories_router)
router.include_router(transactions_router)
router.include_router(agents_router)
router.include_router(import_jobs_router)
router.include_router(wealth_router)
router.include_router(reports_router)
