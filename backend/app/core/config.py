"""Конфигурация приложения. Все значения — из окружения (.env)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Общее
    tz: str = Field("Asia/Tashkent", alias="TZ")
    default_operating_mode: str = Field("RESEARCH", alias="DEFAULT_OPERATING_MODE")
    log_level: str = Field("INFO", alias="LOG_LEVEL")
    backend_secret_key: str = Field("dev-secret", alias="BACKEND_SECRET_KEY")
    cors_origins: str = Field("http://localhost:3000", alias="BACKEND_CORS_ORIGINS")

    # PostgreSQL (доверенный контур)
    postgres_host: str = Field("postgres", alias="POSTGRES_HOST")
    postgres_port: int = Field(5432, alias="POSTGRES_PORT")
    postgres_db: str = Field("medviz", alias="POSTGRES_DB")
    postgres_user: str = Field("medviz", alias="POSTGRES_USER")
    postgres_password: str = Field("medviz", alias="POSTGRES_PASSWORD")
    postgres_audit_user: str = Field("medviz_audit", alias="POSTGRES_AUDIT_USER")
    postgres_audit_password: str = Field("medviz_audit", alias="POSTGRES_AUDIT_PASSWORD")

    # Идентифицирующий контур (таблица ID↔UUID, SR-9)
    idmap_db: str = Field("medviz_idmap", alias="IDMAP_POSTGRES_DB")
    idmap_user: str = Field("medviz_idmap", alias="IDMAP_POSTGRES_USER")
    idmap_password: str = Field("medviz_idmap", alias="IDMAP_POSTGRES_PASSWORD")

    # MinIO
    minio_endpoint: str = Field("minio:9000", alias="MINIO_ENDPOINT")
    minio_access_key: str = Field("medviz", alias="MINIO_ROOT_USER")
    minio_secret_key: str = Field("medviz", alias="MINIO_ROOT_PASSWORD")
    minio_secure: bool = Field(False, alias="MINIO_SECURE")
    bucket_images: str = Field("images", alias="MINIO_BUCKET_IMAGES")
    bucket_masks: str = Field("masks", alias="MINIO_BUCKET_MASKS")
    bucket_meshes: str = Field("meshes", alias="MINIO_BUCKET_MESHES")

    # Orthanc
    orthanc_raw_url: str = Field("http://orthanc-raw:8042", alias="ORTHANC_RAW_URL")
    orthanc_clean_url: str = Field("http://orthanc-clean:8042", alias="ORTHANC_CLEAN_URL")
    orthanc_username: str = Field("medviz", alias="ORTHANC_USERNAME")
    orthanc_password: str = Field("medviz", alias="ORTHANC_PASSWORD")

    # Celery / Redis
    celery_broker_url: str = Field("redis://redis:6379/1", alias="CELERY_BROKER_URL")
    celery_result_backend: str = Field("redis://redis:6379/2", alias="CELERY_RESULT_BACKEND")

    # Приём
    ingest_watch_dir: str = Field("/data/ingest", alias="INGEST_WATCH_DIR")

    # Аутентификация OIDC (Keycloak)
    keycloak_url: str = Field("http://keycloak:8080", alias="KEYCLOAK_URL")
    keycloak_realm: str = Field("medviz", alias="KEYCLOAK_REALM")
    keycloak_client_id: str = Field("medviz-backend", alias="KEYCLOAK_CLIENT_ID")
    # Разрешить dev-заголовки X-Debug-* (ТОЛЬКО на изолированных стендах).
    allow_debug_auth: bool = Field(False, alias="ALLOW_DEBUG_AUTH")

    @property
    def oidc_issuer(self) -> str:
        return f"{self.keycloak_url}/realms/{self.keycloak_realm}"

    @property
    def oidc_jwks_url(self) -> str:
        return f"{self.oidc_issuer}/protocol/openid-connect/certs"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def idmap_database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.idmap_user}:{self.idmap_password}"
            f"@postgres-idmap:5432/{self.idmap_db}"
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
