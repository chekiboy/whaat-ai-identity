"""The waiting session's side: `whaat wait <kind>` asks here in short calls with the identity's token and gets the
next call the page handed over, or nothing yet."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from whaat.handoff.store import HandoffStore, Kind
from whaat.reports.types.base import Strict
from whaat.security import require_identity

router = APIRouter(prefix="/api/v1/handoff", tags=["handoff"])
IdentityDep = Annotated[str, Depends(require_identity)]


class NextCall(Strict):
    kind: Kind


class Handed(BaseModel):
    call: str | None = Field(
        description="The call to run now, composed by whaat from the user's click; null: none yet."
    )


@router.post("/next", response_model=Handed)
def next_call(body: NextCall, request: Request, identity: IdentityDep) -> Handed:
    """The next call for this identity's session of this kind, taken as it is given; also marks the session as
    listening, so the page hands its next click over instead of showing the call to paste."""
    store: HandoffStore = request.app.state.handoff
    return Handed(call=store.take(identity, body.kind))
