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
- set `grade_lunch_assignments` so each grade is assigned the correct lunch session automatically
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

Generate the final PDFs from the `5 Final Schedule (Edit Here)` tab:

```bash
python scheduler.py printables
```

You can also call the printable step directly:

```bash
python printables.py
```

## Workflow

1. Run `python scheduler.py validate`.
2. Fix every `ERROR` listed in `3 Validation Issues`.
3. Run `python scheduler.py run`.
4. Review `4 Draft Schedule (Do Not Edit)`.
5. Open `5 Final Schedule (Edit Here)`.
6. If that tab was empty, the script already copied the draft into it for you. No copy/paste step is required.
7. Lunch is assigned automatically by grade from config and should already be present in the draft.
8. Teachers edit only `5 Final Schedule (Edit Here)`.
9. Run `python scheduler.py printables`.

## Output Workbook Tabs

- `1 Instructions`
- `2 Run Status`
- `3 Validation Issues`
- `4 Draft Schedule (Do Not Edit)`
- `5 Final Schedule (Edit Here)`
- `6 Waitlist`
- `7 Students With Gaps`
- `8 Session Rosters`
- `9 Teacher View`
- `10 Catalog Snapshot`

## Notes

- `5 Final Schedule (Edit Here)` is not overwritten once it already contains data.
- PDFs are generated from `5 Final Schedule (Edit Here)`, not from `4 Draft Schedule (Do Not Edit)`.
- Lunch is assigned automatically from `grade_lunch_assignments` in config before other class preferences are scheduled.
- The script stores Google OAuth tokens in `token.json` after the first successful login.
