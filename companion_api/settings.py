from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings


class CompanionSettings(BaseSettings):
    """Companion-only configuration. Supabase credentials come from delapan's
    own settings — this holds what delapan has no opinion about."""

    bucket: str = Field(default="hunter8-resumes", alias="HUNTER8_BUCKET")
    invite_ttl_days: int = Field(default=30, alias="HUNTER8_INVITE_TTL_DAYS")
    allowed_origins: str = Field(
        default="http://localhost:5173", alias="HUNTER8_ALLOWED_ORIGINS"
    )

    def origins(self) -> list[str]:
        values = [o.strip() for o in self.allowed_origins.split(",") if o.strip()]
        if "*" in values:
            raise ValueError(
                "HUNTER8_ALLOWED_ORIGINS must name explicit origins: '*' with "
                "credentialed CORS lets any site read an authenticated response"
            )
        return values


@lru_cache
def get_companion_settings() -> CompanionSettings:
    return CompanionSettings()
