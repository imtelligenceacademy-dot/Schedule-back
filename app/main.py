from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError, TimeoutError as PoolTimeoutError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from .config import get_settings
from .database import get_db
from .routers import admin, auth, catalog, schedules, transfer

settings = get_settings()
app = FastAPI(
    title="IM-Telligence Robotics Schedule Manager",
    version="1.0.0",
    docs_url=None if settings.production else "/api/docs",
    redoc_url=None,
    openapi_url=None if settings.production else "/api/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "X-CSRF-Token", "Authorization"],
)


@app.middleware("http")
async def security_headers(request, call_next):
    origin = request.headers.get("origin")
    if request.method not in {"GET", "HEAD", "OPTIONS"} and origin and origin.rstrip("/") not in settings.origins:
        return JSONResponse(status_code=403, content={"detail": "This origin is not allowed."})
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store"
    if settings.production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
    return response


@app.exception_handler(IntegrityError)
async def integrity_error(_, exc):
    return JSONResponse(
        status_code=409,
        content={
            "detail": "This change conflicts with existing data. Check names, duplicates and teacher assignments."
        },
    )


@app.exception_handler(StaleDataError)
async def stale_error(_, exc):
    return JSONResponse(
        status_code=409, content={"detail": "This schedule entry was modified by another user. Refresh before saving."}
    )


@app.exception_handler(OperationalError)
@app.exception_handler(PoolTimeoutError)
async def database_unavailable(_, exc):
    return JSONResponse(
        status_code=503,
        content={"detail": "The schedule database is temporarily unavailable. Please try again shortly."},
    )


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    db.execute(select(1))
    return {"status": "ok"}


for module in (auth, catalog, schedules, admin, transfer):
    app.include_router(module.router)

# Optional local bundled preview. Production serves only the API; Vercel serves React.
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if not settings.production and DIST.exists():

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "API route not found.")
        target = (DIST / path).resolve()
        if target.is_relative_to(DIST.resolve()) and target.is_file():
            return FileResponse(target)
        return FileResponse(DIST / "index.html")
