"""Validated environment configuration."""

from __future__ import annotations

import re
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
CsvTuple = Annotated[tuple[str, ...], NoDecode]


def _parse_csv(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split(",") if part.strip())
    if isinstance(value, (list, tuple)):
        return tuple(str(part).strip() for part in value if str(part).strip())
    raise ValueError("must be a comma-separated string")


def _valid_identifier(value: str) -> bool:
    return bool(IDENTIFIER_PATTERN.fullmatch(value))


class Settings(BaseSettings):
    """Application settings loaded from environment variables or a local .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    database_url: SecretStr = Field(validation_alias="SUPABASE_DATABASE_URL")
    actions_secret: SecretStr | None = Field(default=None, validation_alias="MCP_ACTIONS_SECRET")
    actions_database_url: SecretStr | None = Field(
        default=None, validation_alias="MCP_ACTIONS_DATABASE_URL"
    )
    allowed_schemas: CsvTuple = Field(default=("public",), validation_alias="MCP_ALLOWED_SCHEMAS")
    allowed_tables: CsvTuple = Field(default=(), validation_alias="MCP_ALLOWED_TABLES")
    default_limit: int = Field(default=50, ge=1, validation_alias="MCP_DEFAULT_LIMIT")
    max_limit: int = Field(default=200, ge=1, le=10_000, validation_alias="MCP_MAX_LIMIT")
    statement_timeout_ms: int = Field(
        default=5_000, ge=100, le=60_000, validation_alias="MCP_STATEMENT_TIMEOUT_MS"
    )
    timezone: str = Field(default="America/Monterrey", validation_alias="MCP_TIMEZONE")
    transport: Literal["stdio", "http"] = Field(default="stdio", validation_alias="MCP_TRANSPORT")
    host: str = Field(default="127.0.0.1", min_length=1, validation_alias="MCP_HOST")
    port: int = Field(default=8_000, ge=1, le=65_535, validation_alias="MCP_PORT")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", validation_alias="LOG_LEVEL"
    )

    @field_validator("allowed_schemas", "allowed_tables", mode="before")
    @classmethod
    def parse_csv_values(cls, value: object) -> tuple[str, ...]:
        """Accept readable comma-separated allowlists."""
        return _parse_csv(value)

    @field_validator("allowed_schemas")
    @classmethod
    def validate_schemas(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("MCP_ALLOWED_SCHEMAS must contain at least one schema")
        invalid = [schema for schema in value if not _valid_identifier(schema)]
        if invalid:
            raise ValueError("MCP_ALLOWED_SCHEMAS contains an invalid PostgreSQL identifier")
        if len(set(value)) != len(value):
            raise ValueError("MCP_ALLOWED_SCHEMAS must not contain duplicates")
        return value

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        try:
            url = make_url(raw)
        except ArgumentError as exc:
            raise ValueError("SUPABASE_DATABASE_URL must be a valid PostgreSQL URL") from exc
        if url.drivername not in {"postgres", "postgresql", "postgresql+psycopg"}:
            raise ValueError("SUPABASE_DATABASE_URL must use PostgreSQL with Psycopg")
        sslmode = url.query.get("sslmode")
        if sslmode is not None and sslmode not in {"require", "verify-ca", "verify-full"}:
            raise ValueError("SUPABASE_DATABASE_URL sslmode must require or verify TLS")
        return value

    @field_validator("actions_database_url")
    @classmethod
    def validate_actions_url(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None

        cls.validate_database_url(value)

        url = make_url(value.get_secret_value())
        username = url.username or ""

        # Supports:
        #   fluidbank_actions
        #   fluidbank_actions.<supabase-project-ref>
        role = username.split(".", maxsplit=1)[0]

        if role != "fluidbank_actions":
            raise ValueError("MCP_ACTIONS_DATABASE_URL requires the fluidbank_actions role")

        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("MCP_TIMEZONE must be a valid IANA timezone") from exc
        return value

    @model_validator(mode="after")
    def validate_related_values(self) -> Settings:
        if self.actions_database_url is not None and (
            self.actions_secret is None or len(self.actions_secret.get_secret_value()) < 32
        ):
            raise ValueError("Write actions require MCP_ACTIONS_SECRET with at least 32 characters")
        if self.default_limit > self.max_limit:
            raise ValueError("MCP_DEFAULT_LIMIT cannot exceed MCP_MAX_LIMIT")

        allowed_schema_set = set(self.allowed_schemas)
        for entry in self.allowed_tables:
            parts = entry.split(".")
            if len(parts) == 1:
                if len(self.allowed_schemas) != 1:
                    raise ValueError(
                        "unqualified MCP_ALLOWED_TABLES entries require exactly one allowed schema"
                    )
                if not _valid_identifier(parts[0]):
                    raise ValueError("MCP_ALLOWED_TABLES contains an invalid table identifier")
            elif len(parts) == 2:
                schema, table = parts
                if not _valid_identifier(schema) or not _valid_identifier(table):
                    raise ValueError("MCP_ALLOWED_TABLES contains an invalid qualified identifier")
                if schema not in allowed_schema_set:
                    raise ValueError(
                        "every qualified MCP_ALLOWED_TABLES schema must be in MCP_ALLOWED_SCHEMAS"
                    )
            else:
                raise ValueError("MCP_ALLOWED_TABLES entries must be table or schema.table")

        if len(set(self.allowed_table_pairs)) != len(self.allowed_table_pairs):
            raise ValueError("MCP_ALLOWED_TABLES must not contain duplicate objects")
        return self

    @property
    def allowed_table_pairs(self) -> tuple[tuple[str, str], ...]:
        """Return exact normalized (schema, table) pairs."""
        default_schema = self.allowed_schemas[0]
        pairs: list[tuple[str, str]] = []
        for entry in self.allowed_tables:
            if "." in entry:
                schema, table = entry.split(".", maxsplit=1)
            else:
                schema, table = default_schema, entry
            pairs.append((schema, table))
        return tuple(pairs)

    def sqlalchemy_url(self) -> str:
        """Return a Psycopg async URL with TLS enforced; callers must never log it."""
        url = make_url(self.database_url.get_secret_value())
        url = url.set(drivername="postgresql+psycopg")
        if "sslmode" not in url.query:
            url = url.update_query_dict({"sslmode": "require"})
        return url.render_as_string(hide_password=False)
