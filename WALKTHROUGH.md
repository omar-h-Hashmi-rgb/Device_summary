# Walkthrough

This is the written walkthrough in place of a recording. It covers the successful summary, a file-read failure, the required tests, one design choice, and one defect that was fixed.

## Main flow

From this directory, with dependencies installed:

```bash
uvicorn main:app --reload
```

Open http://127.0.0.1:8000/summary.

The live server returned HTTP 200 and this body:

```json
{"accepted":3,"duplicates":1,"errors":[{"line":4,"code":"BAD_JSON","message":"Malformed JSON."}],"devices":[{"device_id":"D01","ok_count":1,"error_count":1,"last_sequence":3,"last_status":"error"},{"device_id":"D02","ok_count":0,"error_count":1,"last_sequence":2,"last_status":"error"}]}
```

That is the required sample result. Three records are accepted: D01 sequence 1 `ok`, D02 sequence 2 `error`, and D01 sequence 3 `error`. The repeated D01 sequence 1 is the one duplicate. Line 4 is the malformed line. D01's latest status stays `error` because sequence 3 is higher than sequence 1. D02 is listed after D01.

## Failure case

The sample file was renamed so `GET /summary` could not read it. The server responded with HTTP 404 and this JSON body, not an empty success:

```json
{"detail":"Could not find file: sample_messages.json"}
```

The file was renamed back. The next request to `/summary` returned HTTP 200 again. An empty file is a different case: it is valid input and returns zero totals with empty `errors` and `devices` lists.

## Tests

The three required tests:

```text
test_processor.py::test_sample_file_matches_expected_totals PASSED
test_processor.py::test_lower_sequence_arriving_later_keeps_latest_status PASSED
test_processor.py::test_empty_input_returns_zero_totals_and_empty_lists PASSED
============================== 3 passed in 0.98s ==============================
```

The full suite, including boolean sequences, extra fields, blank lines, duplicates whose status differs, and the missing-file response, reported `29 passed`.

## Design choice

A line is validated before it is added to the set of seen `(device_id, sequence)` pairs. An invalid line is an `INVALID_RECORD` and does not occupy that pair. The first valid copy is the only accepted one. `last_status` changes only when a later accepted sequence is strictly greater, so a lower sequence that arrives afterwards still increments the ok or error count but does not replace the latest status.

## Defect found and fixed

JSON `true` and `false` become Python booleans, and `bool` is a subclass of `int`, so `isinstance(True, int)` is true. A sequence check that only used `isinstance(value, int)` would accept `"sequence": true` as the integer 1. The validator now rejects a boolean before the integer check and records `INVALID_RECORD` with the message `sequence must be an integer greater than or equal to 0, not a boolean`. The rejected line is not counted as accepted or as a duplicate. `test_invalid_schema_and_types_are_rejected` covers both `true` and `false`.
