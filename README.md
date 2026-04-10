# Imagination Day Scheduler

Local Python workflow for generating an Imagination Day draft schedule from Google Sheets, handing off a teacher-editable final schedule in a separate workbook, and producing the final PDFs after manual edits.

## Setup

1. Install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Create a Google OAuth desktop app and download `credentials.json` into the repo root.

3. Create `config.json` from the example:

```bash
cp config.example.json config.json
```

Or generate a starter file:

```bash
python scheduler.py init-config
```

4. Fill in:
- `student_responses_url`
- `catalog_url`
- `output_workbook_url`
  - leave this as `null` on first run to auto-create the output workbook

5. Optional:
- update `session_aliases` if student choices do not exactly match catalog session names
- update `time_blocks` if the schedule changes

## Commands

Validate the live source sheets and refresh the validation tabs:

```bash
python scheduler.py validate
```

Generate the draft schedule into the output workbook:

```bash
python scheduler.py run
```

Generate the final PDFs from the `Final Schedule` tab:

```bash
python scheduler.py printables
```

You can also call the printable step directly:

```bash
python printables.py
```

## Workflow

1. Run `python scheduler.py validate`.
2. Fix any fatal issues shown in the `Validation Errors` tab.
3. Run `python scheduler.py run`.
4. Review `Generated Schedule`.
5. If `Final Schedule` was empty, the script will seed it once from `Generated Schedule`.
6. Teachers manually edit `Final Schedule`.
7. Run `python scheduler.py printables`.

## Output Workbook Tabs

- `Run Summary`
- `Validation Errors`
- `Generated Schedule`
- `Final Schedule`
- `Wait List`
- `Gaps`
- `Session Rosters`
- `Teacher View`
- `Catalog Snapshot`

## Notes

- `Final Schedule` is not overwritten once it already contains data.
- PDFs are generated from `Final Schedule`, not `Generated Schedule`.
- The script stores Google OAuth tokens in `token.json` after the first successful login.
