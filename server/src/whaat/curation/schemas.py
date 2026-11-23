from pydantic import BaseModel, Field

from whaat.journal.schemas import CurationDecision
from whaat.reports.types.base import Strict


class StartCuration(Strict):
    identity: str = Field(description="Whose memory to curate; its own agent config runs the session.")
    cwd: str | None = Field(default=None, description="The folder the line starts in; the terminal's own if none.")


class CurationStarted(BaseModel):
    command: str = Field(
        description="The line to paste into a terminal: it starts the curation report as the identity."
    )
    waiting: bool = Field(description="A curation session of this identity already waits for the page.")


class Discarded(BaseModel):
    file: str
    actions: list[str] = Field(
        description="The rejected row's actions, in order; a new row repeats it only with the same list."
    )
    target: str | None
    reason: str
    note: str | None = Field(description="The user's note on the discarded row.")
    report_id: str
    report_date: str
    changed_since: bool = Field(
        description="The memory file changed after that report's day: the proposal may be made again, saying so."
    )


class SendDecisions(Strict):
    report_id: str
    rows: list[CurationDecision]


class DecisionsSent(BaseModel):
    commit: str | None
    warnings: list[str]
    command: str = Field(description="The call; handed to the waiting curation session, else shown to paste.")
    handed: bool = Field(description="The waiting session takes the call; false: the user pastes it.")
    detail: str | None = Field(description="Why it was not handed: no session waits, or nothing to apply.")
    at: str | None = Field(default=None, description="When it was handed (YYYY-MM-DD HH:MM); null when it was not.")


class RevertRow(Strict):
    report_id: str
    n: int = Field(ge=1)


class DoneCall(Strict):
    report_id: str
