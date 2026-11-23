from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

Language = Literal["en", "hu"]
# "last", or an identity's id (the same pattern as whaat.config.IDENTITY_ID)
OpenWith = Annotated[str, StringConstraints(pattern=r"^(last|[A-Za-z][A-Za-z0-9-]{0,31})$")]
IdentityId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9-]{0,31}$")]


class IdentityPreferences(BaseModel):
    open_with: OpenWith = Field(
        default="last", description='The identity the app opens with: "last", the one used last, or a fixed one.'
    )
    last: str | None = Field(default=None, description="The identity chosen last in the app; null before the first.")
    agents: dict[str, str] = Field(
        default_factory=dict,
        description="An identity's own Claude Code config dir: a session of that identity starts claude with it,"
        " whaat's plugin and the identity's token.",
    )


class Preferences(BaseModel):
    """What the UI remembers, in one file per instance."""

    language: Language = "en"
    identity: IdentityPreferences = Field(default_factory=IdentityPreferences)


class IdentityPatch(BaseModel):
    open_with: OpenWith | None = None
    last: IdentityId | None = None
    agents: dict[IdentityId, str] | None = Field(default=None, description="An empty path takes an agent config off.")


class PreferencesPatch(BaseModel):
    language: Language | None = None
    identity: IdentityPatch | None = None
