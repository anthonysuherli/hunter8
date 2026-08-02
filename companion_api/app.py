from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from companion_api.settings import get_companion_settings


def create_app() -> FastAPI:
    settings = get_companion_settings()
    app = FastAPI(
        title="hunter8 companion", docs_url=None, redoc_url=None, openapi_url=None
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["authorization", "content-type"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    from companion_api.routes import account, dossier, session

    app.include_router(session.router)
    app.include_router(dossier.router)
    app.include_router(account.router)

    return app


app = create_app()
