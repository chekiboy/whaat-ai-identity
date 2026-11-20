"""Memory curation from the UI: the page shows the line that starts the curation run in a terminal of the user's own,
and hands the user's word to that session: apply-rows with the rows chosen, revert-applied-rows for an applied row,
and Done, which ends the curation with session-end. The session takes each call through `whaat wait curation`, which it
runs in the background; when none waits, the page shows the call to paste instead. The decisions, notes and sent
stamps live in the report's JSON, not in side files."""

from datetime import date, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from whaat.curation import view as curation_view
from whaat.curation.schemas import (
    CurationStarted,
    DecisionsSent,
    Discarded,
    DoneCall,
    RevertRow,
    SendDecisions,
    StartCuration,
)
from whaat.handoff.command import start_line
from whaat.handoff.store import HandoffStore
from whaat.identities.registry import IdentityRegistry, Principal
from whaat.journal.exceptions import CurationReportNotFoundError, InvalidStoredDocumentError, UnknownRowsError
from whaat.journal.schemas import CurationReportDocument
from whaat.journal.service import JournalService
from whaat.journal.store import CURATION_DIR
from whaat.memory.service import MEMORY_DIR
from whaat.memory.validity import commit_dates
from whaat.reports.store import PRIVATE_ROOT_PREFIX
from whaat.security import require_admin, require_identity
from whaat.terminal.agent import AgentTokenMissingError

router = APIRouter(prefix="/api/v1/curation", tags=["curation"])
AdminDep = Annotated[Principal, Depends(require_admin)]
IdentityDep = Annotated[str, Depends(require_identity)]
REPORT_CALL = "/whaat:memory-curation report"
# confirmed=report-page: the rows were chosen on the page, which lists the risky ones before sending;
# without it delete, merge and move rows would wait for a yes in the session
APPLY_CALL = "/whaat:memory-curation apply-rows report={report_id} confirmed=report-page"
REVERT_CALL = "/whaat:memory-curation revert-applied-rows report={report_id} rows={n} confirmed=report-page"
DONE_CALL = "/whaat:session-end steps=none confirmed=report-page"
NOBODY_WAITS = "no curation session of this identity waits for the page"


def _journal(request: Request) -> JournalService:
    journal: JournalService = request.app.state.journal_service
    return journal


def _handoff(request: Request) -> HandoffStore:
    store: HandoffStore = request.app.state.handoff
    return store


JournalDep = Annotated[JournalService, Depends(_journal)]
HandoffDep = Annotated[HandoffStore, Depends(_handoff)]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _document(journal: JournalService, report_id: str) -> tuple[str, CurationReportDocument]:
    try:
        return journal.curation_document(report_id)
    except CurationReportNotFoundError as err:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(err)) from err
    except InvalidStoredDocumentError as err:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(err)) from err


def _hand(handoff: HandoffStore, identity: str, call: str) -> str | None:
    """Hand the call to the identity's waiting curation session; the reason it was not handed, or None."""
    if not handoff.listening(identity, "curation"):
        return NOBODY_WAITS
    handoff.put(identity, "curation", call)
    return None


@router.post("/start", response_model=CurationStarted)
def start_curation(body: StartCuration, request: Request, _: AdminDep) -> CurationStarted:
    """The line that starts memory-curation's report as this identity, with its own agent config, for the user to
    paste into a terminal."""
    registry: IdentityRegistry = request.app.state.registry
    if body.identity not in registry.folders():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"no identity {body.identity!r}")
    try:
        launch = request.app.state.launch(body.identity)
    except AgentTokenMissingError as err:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(err)) from err
    if launch is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{body.identity} has no agent config: set its Claude config folder in Settings first",
        )
    cwd = Path(body.cwd).expanduser() if body.cwd else None
    command = start_line(launch, request.app.state.preferences.command(), REPORT_CALL, cwd)
    return CurationStarted(command=command, waiting=request.app.state.handoff.listening(body.identity, "curation"))


@router.get("/view", response_model=curation_view.CurationView)
def curation_page(report_id: str, request: Request, _: AdminDep, journal: JournalDep) -> curation_view.CurationView:
    """What the report page draws beside the report: the memory map and each row's diagram data, from the identity's
    memory as it is now."""
    identity, document = _document(journal, report_id)
    registry: IdentityRegistry = request.app.state.registry
    return curation_view.view(str(registry.folder_of(identity) / MEMORY_DIR), document.body.rows)


@router.post("/decisions", response_model=DecisionsSent)
def send_decisions(body: SendDecisions, _: AdminDep, handoff: HandoffDep, journal: JournalDep) -> DecisionsSent:
    """Save the user's word per row into the report, then hand the apply call to the identity's waiting curation
    session and stamp the applied rows as sent; a row already sent (and not reverted since) is refused. When no
    session waits, the answer carries the call to paste."""
    _owner, document = _document(journal, body.report_id)
    sent = {row.n for row in document.body.rows if row.sent_at}
    again = sorted(row.n for row in body.rows if row.decision == "apply" and row.n in sent)
    if again:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"already sent: rows {', '.join(map(str, again))}"
        )
    try:
        identity, commit, warnings = journal.save_curation_decisions(body.report_id, body.rows)
    except CurationReportNotFoundError as err:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(err)) from err
    except UnknownRowsError as err:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(err)) from err
    except InvalidStoredDocumentError as err:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(err)) from err
    command = APPLY_CALL.format(report_id=body.report_id)
    applying = [row.n for row in body.rows if row.decision == "apply"]
    if not applying:
        detail: str | None = "only discarded rows: nothing to apply, the decisions are saved"
    else:
        detail = _hand(handoff, identity, command)
    at = None
    if detail is None:
        at = _now()
        journal.mark_curation_sent(body.report_id, applying, at)
    return DecisionsSent(commit=commit, warnings=warnings, command=command, handed=detail is None, detail=detail, at=at)


@router.post("/revert", response_model=DecisionsSent)
def send_revert(body: RevertRow, _: AdminDep, handoff: HandoffDep, journal: JournalDep) -> DecisionsSent:
    """Hand revert-applied-rows for one applied row to the waiting curation session; the row counts as unsent again."""
    identity, document = _document(journal, body.report_id)
    row = next((r for r in document.body.rows if r.n == body.n), None)
    if row is None or not (row.applied or "").strip(" —"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="rows must be applied rows of this report")
    command = REVERT_CALL.format(report_id=body.report_id, n=body.n)
    detail = _hand(handoff, identity, command)
    if detail is None:
        journal.mark_curation_sent(body.report_id, [body.n], None)
    return DecisionsSent(
        commit=None,
        warnings=[],
        command=command,
        handed=detail is None,
        detail=detail,
        at=_now() if detail is None else None,
    )


@router.post("/done", response_model=DecisionsSent)
def send_done(body: DoneCall, _: AdminDep, handoff: HandoffDep) -> DecisionsSent:
    """Done on the page: hand the session-end call with no steps to the waiting curation session, which ends the
    curation; its terminal is the user's to close."""
    detail = _hand(handoff, body.identity, DONE_CALL)
    return DecisionsSent(
        commit=None,
        warnings=[],
        command=DONE_CALL,
        handed=detail is None,
        detail=detail,
        at=_now() if detail is None else None,
    )


@router.get("/discarded", response_model=list[Discarded])
def discarded_proposals(request: Request, identity: IdentityDep) -> list[Discarded]:
    """Every proposal the user discarded in this identity's curation reports, newest report first, with whether its
    memory file changed since: a discarded proposal is not made again unless the file changed."""
    registry: IdentityRegistry = request.app.state.registry
    home = registry.folder_of(identity)
    _, last_change = commit_dates(str(home / MEMORY_DIR))
    found: list[Discarded] = []
    for path in sorted((home / CURATION_DIR).rglob("*_memory-curation.json"), reverse=True):
        try:
            document = CurationReportDocument.model_validate_json(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        day = (document.envelope.created_date or date.min).isoformat()
        report_id = f"{PRIVATE_ROOT_PREFIX}{identity}:{path.relative_to(home).as_posix()}"
        for row in document.body.rows:
            if row.decision != "reject":
                continue
            changed = last_change.get(row.file, "")
            found.append(
                Discarded(
                    file=row.file,
                    actions=list(row.actions),
                    target=row.target,
                    reason=row.reason,
                    note=row.note,
                    report_id=report_id,
                    report_date=day,
                    changed_since=bool(changed) and changed > day,
                )
            )
    return found
