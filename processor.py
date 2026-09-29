"""Parse, validate, deduplicate, and aggregate simulated device messages.

Input is JSON Lines: one JSON value per physical line. Each line is processed
on its own, so a blank line or a bad record never stops the rest of the file.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeGuard

ErrorCode = Literal["BAD_JSON", "INVALID_RECORD"]
Status = Literal["ok", "error"]

# A record is valid only when these are the sole keys.
_REQUIRED_KEYS = frozenset({"device_id", "sequence", "status"})

_MSG_BLANK = "Blank line."
_MSG_MALFORMED = "Malformed JSON."
_MSG_NOT_OBJECT = "Value must be a JSON object."
_MSG_KEYS = "Object must contain exactly device_id, sequence, and status."
_MSG_DEVICE_ID = "device_id must be a non-empty string and must not be whitespace-only."
_MSG_SEQUENCE_BOOL = "sequence must be an integer greater than or equal to 0, not a boolean."
_MSG_SEQUENCE = "sequence must be an integer greater than or equal to 0."
_MSG_STATUS = 'status must be "ok" or "error".'

__all__ = [
    "DeviceSummary",
    "ErrorCode",
    "ProcessingResult",
    "RecordError",
    "Status",
    "process_file",
    "process_lines",
    "process_text",
]


@dataclass(frozen=True)
class RecordError:
    """One rejected line, stored in the order the lines were read.

    ``line`` is 1-based. ``code`` is the stable category. ``message`` explains
    the category for that particular line.
    """

    line: int
    code: ErrorCode
    message: str


@dataclass(frozen=True)
class DeviceSummary:
    """Totals for one device, built only from accepted records."""

    device_id: str
    ok_count: int
    error_count: int
    last_sequence: int
    last_status: Status


@dataclass(frozen=True)
class ProcessingResult:
    """Aggregate result for a whole file.

    ``accepted`` counts the first valid copy of each ``(device_id, sequence)``.
    ``duplicates`` counts later valid copies of a pair already accepted.
    ``errors`` keeps file order. ``devices`` is sorted by ``device_id``.
    """

    accepted: int
    duplicates: int
    errors: list[RecordError]
    devices: list[DeviceSummary]


@dataclass(frozen=True)
class _Failure:
    code: ErrorCode
    message: str


@dataclass(frozen=True)
class _ValidRecord:
    device_id: str
    sequence: int
    status: Status


@dataclass
class _DeviceAccum:
    """Running totals for one device while the file is being read."""

    ok_count: int
    error_count: int
    last_sequence: int
    last_status: Status

    @classmethod
    def from_first(cls, sequence: int, status: Status) -> _DeviceAccum:
        return cls(
            ok_count=1 if status == "ok" else 0,
            error_count=1 if status == "error" else 0,
            last_sequence=sequence,
            last_status=status,
        )

    def add(self, sequence: int, status: Status) -> None:
        if status == "ok":
            self.ok_count += 1
        else:
            self.error_count += 1
        # Highest accepted sequence wins, including when a smaller sequence
        # is read later. An equal sequence never reaches this method.
        if sequence > self.last_sequence:
            self.last_sequence = sequence
            self.last_status = status

    def finish(self, device_id: str) -> DeviceSummary:
        return DeviceSummary(
            device_id=device_id,
            ok_count=self.ok_count,
            error_count=self.error_count,
            last_sequence=self.last_sequence,
            last_status=self.last_status,
        )


def _is_device_id(value: object) -> TypeGuard[str]:
    """True when ``value`` is a string with a non-whitespace character.

    A valid id is not stripped. ``" D01"`` and ``"D01"`` stay different ids.
    """

    return isinstance(value, str) and value.strip() != ""


def _is_sequence(value: object) -> TypeGuard[int]:
    """True for an integer >= 0.

    ``bool`` is a subclass of ``int``. JSON ``true`` and ``false`` must fail
    this check, and a fractional JSON number (decoded as ``float``) must too.
    """

    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _as_status(value: object) -> Status | None:
    if value == "ok":
        return "ok"
    if value == "error":
        return "error"
    return None


def _reject_nonstandard_constant(constant: str) -> None:
    """Reject ``NaN`` and ``Infinity``, which are not strict JSON."""

    raise json.JSONDecodeError(f"Non-standard JSON number {constant}", constant, 0)


def _decode_line(raw_line: str) -> object | _Failure:
    """Parse one physical line into JSON, or a ``BAD_JSON`` failure."""

    if raw_line.strip() == "":
        return _Failure("BAD_JSON", _MSG_BLANK)
    try:
        return json.loads(raw_line, parse_constant=_reject_nonstandard_constant)
    except json.JSONDecodeError:
        return _Failure("BAD_JSON", _MSG_MALFORMED)


def _validate(payload: object) -> _ValidRecord | _Failure:
    """Check schema and types. Invalid payloads are not eligible for dedupe."""

    if not isinstance(payload, dict):
        return _Failure("INVALID_RECORD", _MSG_NOT_OBJECT)
    if set(payload) != _REQUIRED_KEYS:
        return _Failure("INVALID_RECORD", _MSG_KEYS)

    device_id = payload["device_id"]
    sequence = payload["sequence"]
    if not _is_device_id(device_id):
        return _Failure("INVALID_RECORD", _MSG_DEVICE_ID)
    if isinstance(sequence, bool):
        return _Failure("INVALID_RECORD", _MSG_SEQUENCE_BOOL)
    if not _is_sequence(sequence):
        return _Failure("INVALID_RECORD", _MSG_SEQUENCE)
    status = _as_status(payload["status"])
    if status is None:
        return _Failure("INVALID_RECORD", _MSG_STATUS)
    return _ValidRecord(device_id=device_id, sequence=sequence, status=status)


def _accept(
    record: _ValidRecord,
    devices: dict[str, _DeviceAccum],
) -> None:
    current = devices.get(record.device_id)
    if current is None:
        devices[record.device_id] = _DeviceAccum.from_first(
            record.sequence, record.status
        )
    else:
        current.add(record.sequence, record.status)


def process_lines(lines: Iterable[str]) -> ProcessingResult:
    """Aggregate JSON Lines from an iterable.

    Line numbers start at 1. A trailing newline on an item is ignored.
    Whitespace-only lines are ``BAD_JSON``. Validation runs before the
    duplicate check, so an invalid line is never a duplicate.
    """

    errors: list[RecordError] = []
    seen: set[tuple[str, int]] = set()
    devices: dict[str, _DeviceAccum] = {}
    accepted = 0
    duplicates = 0

    for line_number, raw_line in enumerate(lines, start=1):
        decoded = _decode_line(raw_line)
        if isinstance(decoded, _Failure):
            errors.append(
                RecordError(line=line_number, code=decoded.code, message=decoded.message)
            )
            continue

        validated = _validate(decoded)
        if isinstance(validated, _Failure):
            errors.append(
                RecordError(
                    line=line_number,
                    code=validated.code,
                    message=validated.message,
                )
            )
            continue

        identity = (validated.device_id, validated.sequence)
        if identity in seen:
            # The later copy is a duplicate even when its status differs.
            duplicates += 1
            continue

        seen.add(identity)
        accepted += 1
        _accept(validated, devices)

    summaries = [
        devices[device_id].finish(device_id) for device_id in sorted(devices)
    ]
    return ProcessingResult(
        accepted=accepted,
        duplicates=duplicates,
        errors=errors,
        devices=summaries,
    )


def process_text(text: str) -> ProcessingResult:
    """Aggregate a complete JSON Lines document.

    An empty string has no lines. A single trailing newline does not create an
    extra blank line. A leading UTF-8 BOM is removed so it matches file reads.
    """

    if text.startswith("\ufeff"):
        text = text.removeprefix("\ufeff")
    return process_lines(text.splitlines())


def process_file(path: str | Path) -> ProcessingResult:
    """Aggregate the JSON Lines file at ``path`` one line at a time.

    Missing files, permission errors, and decoding errors propagate to the
    caller. The HTTP layer turns those into error responses.
    """

    with Path(path).open(encoding="utf-8-sig") as handle:
        return process_lines(handle)
