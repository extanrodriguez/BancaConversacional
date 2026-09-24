"""Capability manifest and query types — all schema-required fields are mandatory."""

from pydantic import BaseModel, ConfigDict, Field

from genesis_cognitive.enums import LifecycleStatus, SelectedRoute, SupportLevel
from genesis_cognitive.types.constraints import CapabilityName, EntityName, IntentName


class OrchestratorRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    required_capabilities: tuple[str, ...]
    requires_confirmation: bool
    requires_idempotency: bool
    max_execution_time_seconds: int | None = Field(ge=1)


class AppRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    allowed_channels: tuple[str, ...]
    required_capabilities: tuple[str, ...]
    show_confirmation_ui: bool
    show_cancellation_ui: bool
    show_timer: bool


class AuthenticationRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    requires_authenticated: bool
    minimum_authentication_level: str | None
    requires_elevated: bool


class CapabilityValidationRules(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    min_required_entities: int = Field(ge=0)
    all_required_entities_present: bool


class CapabilityManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    capability_id: str = Field(min_length=1, max_length=128)
    intent_ids: tuple[IntentName, ...] = Field(min_length=1)
    capability_candidate: CapabilityName | None
    domain: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")
    description: str = Field(min_length=1, max_length=1024)
    required_entities: tuple[EntityName, ...]
    optional_entities: tuple[EntityName, ...]
    skill_or_specialist: str | None
    output_contract: str = Field(min_length=1)
    orchestrator_requirements: OrchestratorRequirements
    app_requirements: AppRequirements
    auth_requirements: AuthenticationRequirements
    support_level: SupportLevel
    lifecycle_status: LifecycleStatus
    feature_flag: str | None
    selected_route: SelectedRoute
    validation_rules: CapabilityValidationRules
    enabled: bool


class CapabilityQueryContext(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    channel: str
    authenticated: bool
    authentication_level: str | None
    customer_segment: str | None
    app_capabilities: tuple[str, ...]
    orchestrator_capabilities: tuple[str, ...]
