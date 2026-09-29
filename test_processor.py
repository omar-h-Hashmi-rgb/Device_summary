"""Tests for parsing, validation, deduplication, aggregation, and file errors."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from main import build_summary
from processor import (
    DeviceSummary,
    ProcessingResult,
    RecordError,
    process_file,
    process_text,
)

SAMPLE_FILE = Path(__file__).resolve().parent / "sample_messages.json"


def test_sample_file_matches_expected_totals() -> None:
    """D01 ok, the same row again, D02 error, one bad line, then D01 error."""

    result = process_file(SAMPLE_FILE)

    assert result == ProcessingResult(
        accepted=3,
        duplicates=1,
        errors=[RecordError(line=4, code="BAD_JSON", message="Malformed JSON.")],
        devices=[
            DeviceSummary(
                device_id="D01",
                ok_count=1,
                error_count=1,
                last_sequence=3,
                last_status="error",
            ),
            DeviceSummary(
                device_id="D02",
                ok_count=0,
                error_count=1,
                last_sequence=2,
                last_status="error",
            ),
        ],
    )


def test_lower_sequence_arriving_later_keeps_latest_status() -> None:
    """Sequence 1 arriving after sequence 3 counts, but does not become latest."""

    text = "\n".join(
        [
            '{"device_id": "D01", "sequence": 3, "status": "error"}',
            '{"device_id": "D01", "sequence": 1, "status": "ok"}',
        ]
    )

    result = process_text(text)

    assert result.accepted == 2
    assert result.duplicates == 0
    assert result.errors == []
    assert result.devices == [
        DeviceSummary(
            device_id="D01",
            ok_count=1,
            error_count=1,
            last_sequence=3,
            last_status="error",
        )
    ]


def test_empty_input_returns_zero_totals_and_empty_lists(tmp_path: Path) -> None:
    empty_file = tmp_path / "empty.json"
    empty_file.write_text("", encoding="utf-8")

    for result in (process_text(""), process_file(empty_file)):
        assert result.accepted == 0
        assert result.duplicates == 0
        assert result.errors == []
        assert result.devices == []


def test_blank_lines_and_malformed_json_continue_with_line_numbers() -> None:
    text = "\n".join(
        [
            "",
            "   \t",
            "{bad json",
            "null",
            '{"device_id": "D01", "sequence": 0, "status": "ok"}',
        ]
    )

    result = process_text(text)

    assert [(error.line, error.code) for error in result.errors] == [
        (1, "BAD_JSON"),
        (2, "BAD_JSON"),
        (3, "BAD_JSON"),
        (4, "INVALID_RECORD"),
    ]
    assert result.errors[0].message == "Blank line."
    assert result.errors[2].message == "Malformed JSON."
    assert result.accepted == 1
    assert result.devices[0].last_sequence == 0
    assert result.devices[0].last_status == "ok"


@pytest.mark.parametrize(
    ("line", "message"),
    [
        (
            '{"device_id": "D01", "sequence": 1}',
            "Object must contain exactly device_id, sequence, and status.",
        ),
        (
            '{"device_id": "D01", "sequence": 1, "status": "ok", "extra": true}',
            "Object must contain exactly device_id, sequence, and status.",
        ),
        (
            '{"device_id": "   ", "sequence": 1, "status": "ok"}',
            "device_id must be a non-empty string and must not be whitespace-only.",
        ),
        (
            '{"device_id": "", "sequence": 1, "status": "ok"}',
            "device_id must be a non-empty string and must not be whitespace-only.",
        ),
        (
            '{"device_id": 1, "sequence": 1, "status": "ok"}',
            "device_id must be a non-empty string and must not be whitespace-only.",
        ),
        (
            '{"device_id": "D01", "sequence": true, "status": "ok"}',
            "sequence must be an integer greater than or equal to 0, not a boolean.",
        ),
        (
            '{"device_id": "D01", "sequence": false, "status": "error"}',
            "sequence must be an integer greater than or equal to 0, not a boolean.",
        ),
        (
            '{"device_id": "D01", "sequence": -1, "status": "ok"}',
            "sequence must be an integer greater than or equal to 0.",
        ),
        (
            '{"device_id": "D01", "sequence": 1.0, "status": "ok"}',
            "sequence must be an integer greater than or equal to 0.",
        ),
        (
            '{"device_id": "D01", "sequence": "1", "status": "ok"}',
            "sequence must be an integer greater than or equal to 0.",
        ),
        (
            '{"device_id": "D01", "sequence": 1, "status": "OK"}',
            'status must be "ok" or "error".',
        ),
        (
            '{"device_id": "D01", "sequence": 1, "status": "warning"}',
            'status must be "ok" or "error".',
        ),
        ("null", "Value must be a JSON object."),
        ("[1]", "Value must be a JSON object."),
        ('"D01"', "Value must be a JSON object."),
    ],
)
def test_invalid_schema_and_types_are_rejected(line: str, message: str) -> None:
    result = process_text(line)

    assert result.accepted == 0
    assert result.duplicates == 0
    assert result.devices == []
    assert result.errors == [
        RecordError(line=1, code="INVALID_RECORD", message=message)
    ]


def test_invalid_record_is_not_counted_as_a_duplicate() -> None:
    text = "\n".join(
        [
            '{"device_id": "D01", "sequence": 1, "status": "ok"}',
            '{"device_id": "D01", "sequence": true, "status": "error"}',
            '{"device_id": "D01", "sequence": 1, "status": "error"}',
        ]
    )

    result = process_text(text)

    assert result.accepted == 1
    assert result.duplicates == 1
    assert len(result.errors) == 1
    assert result.errors[0].code == "INVALID_RECORD"
    assert result.devices[0].ok_count == 1
    assert result.devices[0].error_count == 0
    assert result.devices[0].last_status == "ok"


def test_later_duplicate_with_different_status_keeps_the_first() -> None:
    text = "\n".join(
        [
            '{"device_id": "D01", "sequence": 4, "status": "ok"}',
            '{"device_id": "D01", "sequence": 4, "status": "error"}',
        ]
    )

    result = process_text(text)

    assert result.accepted == 1
    assert result.duplicates == 1
    assert result.errors == []
    assert result.devices == [
        DeviceSummary(
            device_id="D01",
            ok_count=1,
            error_count=0,
            last_sequence=4,
            last_status="ok",
        )
    ]


def test_highest_sequence_wins_when_it_arrives_later() -> None:
    text = "\n".join(
        [
            '{"device_id": "D01", "sequence": 1, "status": "ok"}',
            '{"device_id": "D01", "sequence": 5, "status": "error"}',
        ]
    )

    result = process_text(text)

    assert result.devices[0].ok_count == 1
    assert result.devices[0].error_count == 1
    assert result.devices[0].last_sequence == 5
    assert result.devices[0].last_status == "error"


def test_device_ids_are_preserved_and_sorted_alphabetically() -> None:
    text = "\n".join(
        [
            '{"device_id": "D10", "sequence": 1, "status": "ok"}',
            '{"device_id": " D01", "sequence": 2, "status": "error"}',
            '{"device_id": "D01", "sequence": 2, "status": "ok"}',
        ]
    )

    result = process_text(text)

    assert result.accepted == 3
    assert result.duplicates == 0
    assert [device.device_id for device in result.devices] == [" D01", "D01", "D10"]
    preserved = result.devices[0]
    assert preserved.device_id == " D01"
    assert preserved.last_status == "error"


def test_nonstandard_json_numbers_are_bad_json() -> None:
    result = process_text('{"device_id": "D01", "sequence": NaN, "status": "ok"}')

    assert result.accepted == 0
    assert result.errors[0].code == "BAD_JSON"
    assert result.errors[0].line == 1


def test_summary_endpoint_serializes_the_sample() -> None:
    payload = build_summary(SAMPLE_FILE)

    assert payload.accepted == 3
    assert payload.duplicates == 1
    assert len(payload.errors) == 1
    assert payload.errors[0].line == 4
    assert payload.errors[0].code == "BAD_JSON"
    assert [device.device_id for device in payload.devices] == ["D01", "D02"]
    assert payload.devices[0].last_sequence == 3
    assert payload.devices[0].last_status == "error"


def test_missing_file_returns_404(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"

    with pytest.raises(HTTPException) as caught:
        build_summary(missing)

    assert caught.value.status_code == 404
    assert caught.value.detail == "Could not find file: missing.json"


def test_invalid_utf8_returns_422(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_bytes(b"\xff\xfe")

    with pytest.raises(HTTPException) as caught:
        build_summary(path)

    assert caught.value.status_code == 422
    assert caught.value.detail == "File is not valid UTF-8: bad.json"


def test_directory_path_returns_500(tmp_path: Path) -> None:
    with pytest.raises(HTTPException) as caught:
        build_summary(tmp_path)

    assert caught.value.status_code == 500
    assert str(caught.value.detail).startswith(f"Could not read file {tmp_path.name}:")


def test_empty_file_is_a_successful_summary(tmp_path: Path) -> None:
    path = tmp_path / "empty.json"
    path.write_text("", encoding="utf-8")

    payload = build_summary(path)

    assert payload.accepted == 0
    assert payload.duplicates == 0
    assert payload.errors == []
    assert payload.devices == []
