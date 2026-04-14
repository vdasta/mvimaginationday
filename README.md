# Imagination Day Scheduler

This project creates the Imagination Day schedule from two Google Sheets:

- the student form responses
- the course catalog

It writes the results into a separate output workbook, lets teachers make manual edits there, and then generates the final PDFs for student lanyards and class rosters.

This is meant to be run locally on one computer by one volunteer.

## What You Need

- Python 3.10 or newer
- access to the student response spreadsheet
- access to the course catalog spreadsheet
- a Google Cloud project with the Google Sheets API enabled
- an OAuth desktop app downloaded as `credentials.json`

## One-Time Setup

### 1. Set up Python

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Set up Google access

Create a Google Cloud project and do all of the following:

1. Enable the Google Sheets API.
2. Configure the OAuth consent screen.
3. Create an OAuth client of type `Desktop app`.
4. Download the client JSON file.
5. Save that file in this folder as `credentials.json`.

Notes:

- `credentials.json` should stay local. Do not commit it to git.
- On the first successful run, the script will also create `token.json`.
- `token.json` should also stay local. Do not commit it to git.

### 3. Create the config file

Copy the example:

```bash
cp config.example.json config.json
```

Or generate a starter file:

```bash
python scheduler.py init-config
```

### 4. Edit `config.json`

Fill in these required values:

- `student_responses_url`
- `catalog_url`

Leave `output_workbook_url` as `null` the first time you run the script. The script will create the output workbook for you and save that URL back into `config.json`.

## Streamlit Wizard

If you want a step-by-step local UI instead of raw commands, run:

```bash
streamlit run streamlit_app.py
```

What the wizard does:

- lets you edit and save `config.json`
- shows whether `credentials.json` and `token.json` are present
- runs the same workflow buttons in order:
  - validate
  - generate draft schedule
  - refresh final reports
  - generate PDFs
- shows the latest logs from each step
- links to the output workbook once it exists

Notes:

- the wizard still uses the same local files and Google Sheets access as the CLI
- on the first successful run, Google OAuth will open in your browser and create `token.json`
- teachers still make manual edits in `5 Final Schedule (Edit Here)` inside the output workbook

## Yearly Items To Review In `config.json`

These values may need to change each year:

- `student_responses_url`
- `catalog_url`
- `session_aliases`
- `grade_lunch_assignments`
- `time_blocks`
- `pdf_output_dir`

Important:

- `session_aliases` is only for cases where the student form name does not exactly match the catalog name.
- `grade_lunch_assignments` must match the real lunch plan for that year.
- The values in `config.example.json` are examples, not guaranteed yearly defaults.

## Normal Workflow

Use this exact order each year.

### Step 1. Validate the source sheets

```bash
python scheduler.py validate
```

What this does:

- reads the student response sheet
- reads the course catalog sheet
- creates the output workbook if needed
- writes validation results into the output workbook

What to check:

- open the output workbook
- read `3 Validation Issues`
- fix every row marked `ERROR` before continuing

If validation stops with fatal issues, do not run the scheduler yet.

### Step 2. Generate the draft schedule

```bash
python scheduler.py run
```

Or compare the current greedy scheduler against the CP-SAT solver before writing any tabs:

```bash
python scheduler.py benchmark
```

To generate the draft with the CP-SAT solver instead of the default greedy heuristic:

```bash
python scheduler.py run --algorithm cp-sat
```

What this does:

- assigns lunch first by grade
- assigns classes based on student rankings and session availability
- writes a draft schedule to the output workbook
- populates helper tabs teachers can use during manual cleanup

What `benchmark` does:

- reads the same student and catalog sheets used by `run`
- computes schedule quality metrics for one or more algorithms
- prints a JSON comparison so you can compare preference satisfaction, gaps, and seat utilization before switching algorithms

What to check:

- `4 Draft Schedule (Do Not Edit)`
- `5 Final Schedule (Edit Here)`
- `6 Waitlist`
- `7 Students With Gaps`
- `8 Session Rosters`
- `9 Teacher View`

Important:

- `5 Final Schedule (Edit Here)` is the only tab teachers should edit.
- If `5 Final Schedule (Edit Here)` was empty, the script will copy the draft into it automatically.
- There is no manual copy/paste step on the first run.

### Step 3. Teachers make manual edits

Teachers should work only in:

- `5 Final Schedule (Edit Here)`

They may use these tabs while making decisions:

- `6 Waitlist`
- `7 Students With Gaps`
- `8 Session Rosters`
- `9 Teacher View`

All other tabs are protected on purpose.

### Step 4. Refresh reports after manual edits

```bash
python scheduler.py refresh-final
```

What this does:

- rereads `5 Final Schedule (Edit Here)`
- rebuilds the waitlist, gaps, roster, and teacher tabs from the edited final schedule
- checks that final schedules still reference valid catalog sessions

Run this after teachers finish editing and any time you want the helper tabs to match the current final schedule.

### Step 5. Generate the PDFs

```bash
python scheduler.py printables
```

What this does:

- refreshes the final report tabs again
- generates the final PDFs from `5 Final Schedule (Edit Here)`

Files created:

- `attendee_schedule.pdf`
- `class_rosters.pdf`

These files are written to the folder set by `pdf_output_dir` in `config.json`.

## Output Workbook Tabs

The script creates and manages these tabs:

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

Meaning of the main tabs:

- `4 Draft Schedule (Do Not Edit)` is the machine-generated draft.
- `5 Final Schedule (Edit Here)` is the teacher-edited final version.
- `6 Waitlist` shows students who wanted a session but could not be placed.
- `7 Students With Gaps` shows students with one or more blank periods.
- `8 Session Rosters` shows who is assigned to each session.
- `9 Teacher View` gives a teacher-friendly schedule view.

## Files In This Folder

Files you edit:

- `config.json`

Files you provide and keep local:

- `credentials.json`

Files the script creates and keeps local:

- `token.json`
- `attendee_schedule.pdf`
- `class_rosters.pdf`

Do not commit `config.json`, `credentials.json`, or `token.json` to git.

## Practical Notes

- Run only one scheduler command at a time.
- Use the same Google account each time unless you intentionally want a different owner/editor for the output workbook.
- The script will not overwrite `5 Final Schedule (Edit Here)` if it already contains edited data.
- PDFs are always generated from `5 Final Schedule (Edit Here)`, not from the draft tab.
- Lunch is assigned automatically before other classes, based on `grade_lunch_assignments`.

## If Something Looks Wrong

If the schedule does not look right, check these first:

1. `3 Validation Issues`
2. `session_aliases` in `config.json`
3. `grade_lunch_assignments` in `config.json`
4. the session names and periods in the catalog sheet

Common causes:

- a session name in the student form does not exactly match the catalog
- lunch assignments are wrong for the current year
- the catalog does not mark the correct periods for a session
- the output workbook is from an older test run
