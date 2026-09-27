"""Router aggregation for the whole API."""

from fastapi import APIRouter

from app.api.routes import admin, auth, bookings, catalog, payments

api_router = APIRouter()
api_router.include_router(auth.router, tags=["auth"])
api_router.include_router(catalog.router, tags=["centres & tests"])
api_router.include_router(bookings.router, tags=["bookings"])
api_router.include_router(payments.router, tags=["payments"])
api_router.include_router(admin.router, tags=["admin"])
