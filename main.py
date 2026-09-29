"""HTTP API for the bundled device-message sample.

``GET /summary`` reads ``sample_messages.json`` next to this module. The path
is fixed so a client cannot choose a file on the server. A missing or unreadable
file becomes an HTTP error payload, never an empty 200 response.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from processor import process_file

logger = logging.getLogger(__name__)

SAMPLE_FILE = Path(__file__).resolve().parent / "sample_messages.json"

app = FastAPI(
    title="Device Message Summary",
    version="1.0.0",
    summary="Aggregate the bundled JSON Lines sample of device messages.",
)


class RecordErrorModel(BaseModel):
    line: int = Field(..., ge=1, description="1-based line number in the source file.")
    code: Literal["BAD_JSON", "INVALID_RECORD"]
    message: str


class DeviceSummaryModel(BaseModel):
    device_id: str
    ok_count: int = Field(..., ge=0)
    error_count: int = Field(..., ge=0)
    last_sequence: int = Field(..., ge=0)
    last_status: Literal["ok", "error"]


class SummaryResponse(BaseModel):
    accepted: int = Field(..., ge=0)
    duplicates: int = Field(..., ge=0)
    errors: list[RecordErrorModel]
    devices: list[DeviceSummaryModel]


class ErrorBody(BaseModel):
    detail: str


def build_summary(path: Path) -> SummaryResponse:
    """Read ``path`` and return the summary, or raise ``HTTPException``.

    ``FileNotFoundError`` is handled before ``OSError`` because it is a
    subclass of ``OSError``. An empty file is a successful empty summary.
    """

    try:
        result = process_file(path)
    except FileNotFoundError:
        logger.info("Device message file not found: %s", path)
        raise HTTPException(
            status_code=404,
            detail=f"Could not find file: {path.name}",
        ) from None
    except UnicodeDecodeError:
        logger.info("Device message file is not UTF-8: %s", path)
        raise HTTPException(
            status_code=422,
            detail=f"File is not valid UTF-8: {path.name}",
        ) from None
    except OSError as exc:
        logger.warning("Could not read device message file %s", path, exc_info=exc)
        reason = exc.strerror or str(exc)
        raise HTTPException(
            status_code=500,
            detail=f"Could not read file {path.name}: {reason}",
        ) from None

    return SummaryResponse.model_validate(asdict(result))


@app.get(
    "/summary",
    response_model=SummaryResponse,
    responses={
        404: {"model": ErrorBody, "description": "The sample file does not exist."},
        422: {"model": ErrorBody, "description": "The sample file is not valid UTF-8."},
        500: {"model": ErrorBody, "description": "The sample file could not be read."},
    },
)
def get_summary() -> SummaryResponse:
    """Return totals, the ordered error list, and per-device summaries.

    Devices are ordered by ``device_id``. ``last_status`` belongs to the
    highest accepted sequence for that device.
    """

    return build_summary(SAMPLE_FILE)
