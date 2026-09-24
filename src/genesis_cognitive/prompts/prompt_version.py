"""Immutable prompt version model."""

from pydantic import BaseModel, ConfigDict, Field


class PromptInstructions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    role: str = Field(min_length=1)
    objectives: tuple[str, ...] = ()
    rules: tuple[str, ...] = ()
    prohibitions: tuple[str, ...] = ()


class PromptContracts(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    input: str = Field(min_length=1)
    output_schema: str = Field(min_length=1)


class PromptCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    catalog_ref: str = Field(min_length=1)
    skills: tuple[str, ...] = ()


class PromptModelPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    model_alias: str = Field(min_length=1)
    structured_output: bool


class PromptEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    suite_id: str = Field(min_length=1)
    dataset_ref: str = Field(min_length=1)


class PromptFoundry(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    deployment_ready: bool
    agent_name: str = Field(min_length=1)


class PromptChange(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    reason: str = Field(min_length=1)


class PromptVersion(BaseModel):
    """Immutable, validated prompt asset."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: str
    prompt_id: str
    agent_id: str
    prompt_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    status: str
    language: str
    instructions: PromptInstructions
    contracts: PromptContracts
    capabilities: PromptCapabilities
    model_policy: PromptModelPolicy
    evaluation: PromptEvaluation
    foundry: PromptFoundry
    change: PromptChange

    @property
    def output_schema_ref(self) -> str:
        return self.contracts.output_schema

    @property
    def evaluation_suite_id(self) -> str:
        return self.evaluation.suite_id

    @property
    def evaluation_dataset_ref(self) -> str:
        return self.evaluation.dataset_ref
