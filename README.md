# Device message summary

A Python service that reads simulated device messages from a JSON Lines file, rejects bad lines, keeps the first copy of each device and sequence, and returns per-device totals. `GET /summary` serves the bundled `sample_messages.json` next to `main.py`.

Python 3.10 or newer is required.

## Setup

From this directory:

```bash
pip install -r requirements.txt
```

## Run

```bash
uvicorn main:app --reload
```

Open http://127.0.0.1:8000/summary for the JSON summary. Interactive docs are at http://127.0.0.1:8000/docs.

## Test

From this directory:

```bash
pytest
```

## Time spent

About 1 hour.

## Assumptions

A line is valid only when it is a JSON object whose keys are exactly `device_id`, `sequence`, and `status`. The key set is checked before field types, and each line produces at most one error. `device_id` must be a string that is not empty and not whitespace-only; a valid id is stored exactly as supplied, so surrounding spaces are preserved and compared literally. `sequence` must be a JSON integer greater than or equal to 0. JSON booleans are rejected because `bool` is a subclass of `int` in Python. A JSON number with a fractional part is rejected because it decodes as `float`. `NaN` and `Infinity` are rejected as malformed JSON. `status` must be the string `ok` or `error`. Blank lines and lines that do not parse are `BAD_JSON`, including whitespace-only lines. Any other parsed JSON value is `INVALID_RECORD`. Both error kinds include the 1-based line number and a short message, and the error list stays in file order. Duplicate detection runs only after validation: the first valid `(device_id, sequence)` is accepted, and every later valid pair is a duplicate even when its status differs. `ok_count` and `error_count` include only accepted rows. `last_status` comes from the accepted row with the greatest sequence, whether that row appears before or after a smaller sequence. Devices are ordered with Python's default string sort on the preserved `device_id`, so `D10` sorts before `D2`. The sample file is JSON Lines even though its name ends in `.json`. A leading UTF-8 BOM is ignored. An empty file is a successful summary with zero totals. The endpoint reads only the bundled sample and does not take a path from the client. The React notes below assume the page is served from the same origin as the API, or that a dev proxy forwards `/summary`.

## Unfinished work

There is no upload endpoint, no device filter, and no authentication. The live server is not started inside the automated tests; file-read failures are checked by calling the same function the route uses.

## Known limitation

Every accepted `(device_id, sequence)` pair is stored in memory until the request finishes, so a very large file of unique pairs can exhaust RAM.

## AI and reuse note

I used Cursor's AI coding assistant to draft this project. It produced the JSON Lines parser, the FastAPI `GET /summary` route, `sample_messages.json`, the pytest suite, and the first version of this README. I did not copy code from an employer repository or from another project. After the draft, I kept the validation order explicit (schema before duplicates), added a short message on each error, and made a missing or unreadable sample file return an HTTP error instead of an empty successful summary. I verified the result with `pytest` (29 passed), by opening http://127.0.0.1:8000/summary, and by temporarily removing the sample file, which returned HTTP 404 and `{"detail":"Could not find file: sample_messages.json"}`. The sample file was then restored. A step-by-step record of that check is in `WALKTHROUGH.md`.

## Fetching the summary from React

- Track a loading flag with `useState`, and start `fetch("/summary")` inside `useEffect` when the page mounts. Set loading to true before the request and back to false in a `finally` block, and render a pending indicator while that flag is true so a slow response is not shown as empty data.
- Treat a response with `response.ok` and zero totals (`accepted` is 0, `duplicates` is 0, and `devices` is empty) as empty data, and render an empty-state message instead of a table.
- Wrap the request in `try/catch`. If `fetch` throws a network error, or `response.ok` is false, read the JSON `detail` string when the body has one and store it as an API failure with different copy from the empty state.
- After a successful response that contains devices, render a table of `device_id`, `ok_count`, `error_count`, `last_sequence`, and `last_status` in the order returned by the API, which is already sorted alphabetically by `device_id`.
- Render the `errors` array in response order, showing each 1-based `line` with its `code` and `message`, so `BAD_JSON` and `INVALID_RECORD` stay tied to the source line.
