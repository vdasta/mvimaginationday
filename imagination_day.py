#!/usr/bin/env python3

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any


SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

DEFAULT_CONFIG: dict[str, Any] = {
    "student_responses_url": "",
    "student_tab": "Form Responses 1",
    "catalog_url": "",
    "catalog_tab": "Sheet1",
    "output_workbook_url": None,
    "output_workbook_title": None,
    "credentials_file": "credentials.json",
    "token_file": "token.json",
    "pdf_output_dir": ".",
    "session_aliases": {},
    "time_blocks": {
        "period1": "8:45-9:20",
        "period2": "9:25-10:00",
        "period3": "10:05-10:40",
        "period4": "10:45-11:20",
        "period5": "11:25-12:00",
        "period6": "12:05-12:40",
        "period7": "12:45-1:20",
    },
}

OUTPUT_TABS = [
    "Run Summary",
    "Validation Errors",
    "Generated Schedule",
    "Final Schedule",
    "Wait List",
    "Gaps",
    "Session Rosters",
    "Teacher View",
    "Catalog Snapshot",
]

GRADE_ORDER = {"4th": 0, "3rd": 1, "2nd": 2, "1st": 3, "K": 4}
PERIOD_RE = re.compile(r"period\s*(\d+)", flags=re.I)
CHOICE_RE = re.compile(r"(\d+)(?:st|nd|rd|th)\s+choice", flags=re.I)
SPREADSHEET_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")


@dataclass(frozen=True)
class Attendee:
    attendee_id: str
    name: str
    grade: str
    teacher: str
    choices: list[str]
    source_row: int


@dataclass(frozen=True)
class SessionOffering:
    name: str
    room: str
    rain_room: str
    capacities: dict[str, int]


@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    category: str
    subject: str
    details: str

    @property
    def is_fatal(self) -> bool:
        return self.severity.upper() == "ERROR"


class ConfigError(RuntimeError):
    pass


def load_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        raise ConfigError(
            f"Missing config file: {config_path}. "
            "Create one from config.example.json."
        )

    data = json.loads(config_path.read_text(encoding="utf-8"))
    config = dict(DEFAULT_CONFIG)
    config.update(data)
    config["time_blocks"] = dict(DEFAULT_CONFIG["time_blocks"]) | dict(data.get("time_blocks", {}))
    config["session_aliases"] = dict(data.get("session_aliases", {}))

    for key in ("student_responses_url", "catalog_url"):
        if not config.get(key):
            raise ConfigError(f"Config key '{key}' must be set in {config_path}.")

    return config


def save_config(config_path: Path, config: dict[str, Any]) -> None:
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\ufeff", " ")
    return " ".join(text.split()).strip()


def normalize_key(value: Any) -> str:
    return normalize_text(value).casefold()


def quote_sheet_title(title: str) -> str:
    escaped = title.replace("'", "''")
    return f"'{escaped}'"


def spreadsheet_id_from_ref(url_or_id: str) -> str:
    text = normalize_text(url_or_id)
    match = SPREADSHEET_ID_RE.search(text)
    if match:
        return match.group(1)
    if text:
        return text
    raise ConfigError("Expected a Google Sheets URL or spreadsheet ID.")


def period_sort_key(period_name: str) -> int:
    match = PERIOD_RE.search(period_name)
    if not match:
        return 999
    return int(match.group(1))


def display_period(period_name: str) -> str:
    return f"Period {period_sort_key(period_name)}"


def build_alias_lookup(config: dict[str, Any]) -> dict[str, str]:
    aliases = {}
    for raw_name, canonical_name in config.get("session_aliases", {}).items():
        aliases[normalize_key(raw_name)] = normalize_text(canonical_name)
    return aliases


def canonical_session_name(raw_name: Any, alias_lookup: dict[str, str]) -> str:
    cleaned = normalize_text(raw_name)
    if not cleaned:
        return ""
    return alias_lookup.get(normalize_key(cleaned), cleaned)


class GoogleSheetsClient:
    def __init__(self, credentials_file: str, token_file: str) -> None:
        self.credentials_file = credentials_file
        self.token_file = token_file
        self._service = None

    @property
    def service(self):
        if self._service is None:
            self._service = self._build_service()
        return self._service

    def _build_service(self):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        creds = None
        token_path = Path(self.token_file)
        credentials_path = Path(self.credentials_file)

        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not credentials_path.exists():
                    raise ConfigError(
                        f"Missing Google API credentials file: {credentials_path}"
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(credentials_path), SCOPES
                )
                creds = flow.run_local_server(port=0)

            token_path.write_text(creds.to_json(), encoding="utf-8")

        return build("sheets", "v4", credentials=creds, cache_discovery=False)

    def get_metadata(self, spreadsheet_ref: str) -> dict[str, Any]:
        spreadsheet_id = spreadsheet_id_from_ref(spreadsheet_ref)
        return (
            self.service.spreadsheets()
            .get(spreadsheetId=spreadsheet_id)
            .execute()
        )

    def read_range(self, spreadsheet_ref: str, sheet_title: str, cell_range: str) -> list[list[str]]:
        spreadsheet_id = spreadsheet_id_from_ref(spreadsheet_ref)
        read_range = f"{quote_sheet_title(sheet_title)}!{cell_range}"
        response = (
            self.service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=read_range)
            .execute()
        )
        return response.get("values", [])

    def create_spreadsheet(self, title: str, first_sheet_title: str) -> dict[str, Any]:
        body = {
            "properties": {"title": title},
            "sheets": [{"properties": {"title": first_sheet_title}}],
        }
        return self.service.spreadsheets().create(body=body).execute()

    def ensure_tabs(self, spreadsheet_ref: str, tab_titles: list[str]) -> None:
        spreadsheet_id = spreadsheet_id_from_ref(spreadsheet_ref)
        metadata = self.get_metadata(spreadsheet_id)
        existing = {
            sheet["properties"]["title"]
            for sheet in metadata.get("sheets", [])
        }
        missing = [title for title in tab_titles if title not in existing]
        if not missing:
            return

        requests = [{"addSheet": {"properties": {"title": title}}} for title in missing]
        (
            self.service.spreadsheets()
            .batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": requests})
            .execute()
        )

    def tab_has_data(self, spreadsheet_ref: str, tab_title: str) -> bool:
        values = self.read_range(spreadsheet_ref, tab_title, "A1:Z5")
        for row in values:
            if any(normalize_text(cell) for cell in row):
                return True
        return False

    def clear_and_write_tab(self, spreadsheet_ref: str, tab_title: str, rows: list[list[Any]]) -> None:
        spreadsheet_id = spreadsheet_id_from_ref(spreadsheet_ref)
        clear_range = quote_sheet_title(tab_title)
        (
            self.service.spreadsheets()
            .values()
            .clear(spreadsheetId=spreadsheet_id, range=clear_range, body={})
            .execute()
        )

        if rows:
            payload = {"values": [[str(cell) if cell is not None else "" for cell in row] for row in rows]}
            (
                self.service.spreadsheets()
                .values()
                .update(
                    spreadsheetId=spreadsheet_id,
                    range=f"{quote_sheet_title(tab_title)}!A1",
                    valueInputOption="RAW",
                    body=payload,
                )
                .execute()
            )
            self._format_written_tab(spreadsheet_id, tab_title, len(rows[0]))

    def _format_written_tab(self, spreadsheet_id: str, tab_title: str, column_count: int) -> None:
        metadata = self.get_metadata(spreadsheet_id)
        sheet_map = {
            sheet["properties"]["title"]: sheet["properties"]["sheetId"]
            for sheet in metadata.get("sheets", [])
        }
        sheet_id = sheet_map.get(tab_title)
        if sheet_id is None:
            return

        requests = [
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": sheet_id,
                        "gridProperties": {"frozenRowCount": 1},
                    },
                    "fields": "gridProperties.frozenRowCount",
                }
            },
            {
                "autoResizeDimensions": {
                    "dimensions": {
                        "sheetId": sheet_id,
                        "dimension": "COLUMNS",
                        "startIndex": 0,
                        "endIndex": column_count,
                    }
                }
            },
        ]
        (
            self.service.spreadsheets()
            .batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": requests})
            .execute()
        )


def ensure_output_workbook(
    client: GoogleSheetsClient,
    config: dict[str, Any],
    config_path: Path,
) -> str:
    if config.get("output_workbook_url"):
        client.ensure_tabs(config["output_workbook_url"], OUTPUT_TABS)
        return config["output_workbook_url"]

    title = config.get("output_workbook_title") or f"Imagination Day Output {date.today().year}"
    created = client.create_spreadsheet(title, OUTPUT_TABS[0])
    output_url = created["spreadsheetUrl"]
    config["output_workbook_url"] = output_url
    save_config(config_path, config)
    client.ensure_tabs(output_url, OUTPUT_TABS)
    return output_url


def header_index(headers: list[str]) -> dict[str, int]:
    return {normalize_key(header): idx for idx, header in enumerate(headers)}


def cell(row: list[str], idx: int | None) -> str:
    if idx is None or idx >= len(row):
        return ""
    return normalize_text(row[idx])


def choice_columns(headers: list[str]) -> list[tuple[int, int, str]]:
    found = []
    for idx, header in enumerate(headers):
        match = CHOICE_RE.fullmatch(normalize_text(header))
        if match:
            found.append((int(match.group(1)), idx, header))
    return sorted(found)


def parse_attendees(rows: list[list[str]], config: dict[str, Any]) -> tuple[list[Attendee], list[ValidationIssue]]:
    if not rows:
        return [], [ValidationIssue("ERROR", "student_responses", "sheet", "Student Responses sheet is empty.")]

    headers = rows[0]
    idx = header_index(headers)
    alias_lookup = build_alias_lookup(config)
    issues: list[ValidationIssue] = []

    required_headers = [
        "first name",
        "last name",
        "grade",
        "teacher's last name",
    ]
    missing = [header for header in required_headers if header not in idx]
    if missing:
        issues.append(
            ValidationIssue(
                "ERROR",
                "student_responses",
                "headers",
                f"Missing required columns: {', '.join(missing)}",
            )
        )
        return [], issues

    choices = choice_columns(headers)
    if not choices:
        issues.append(
            ValidationIssue(
                "ERROR",
                "student_responses",
                "headers",
                "No '* Choice' columns were found in Student Responses.",
            )
        )
        return [], issues

    attendees: list[Attendee] = []
    name_counter: Counter[str] = Counter()

    for row_number, row in enumerate(rows[1:], start=2):
        first_name = cell(row, idx.get("first name"))
        last_name = cell(row, idx.get("last name"))
        grade = cell(row, idx.get("grade"))
        teacher = cell(row, idx.get("teacher's last name"))
        display_name = normalize_text(f"{first_name} {last_name}")

        if not display_name and not grade and not teacher:
            continue

        if not display_name:
            issues.append(
                ValidationIssue(
                    "ERROR",
                    "student_responses",
                    f"row {row_number}",
                    "Missing first/last name.",
                )
            )
            continue

        raw_choices = [cell(row, choice_idx) for _, choice_idx, _ in choices]
        seen_choices: set[str] = set()
        deduped_choices: list[str] = []
        duplicate_choices: list[str] = []

        for raw_choice in raw_choices:
            canonical = canonical_session_name(raw_choice, alias_lookup)
            if not canonical:
                continue
            normalized = normalize_key(canonical)
            if normalized in seen_choices:
                duplicate_choices.append(canonical)
                continue
            seen_choices.add(normalized)
            deduped_choices.append(canonical)

        if duplicate_choices:
            issues.append(
                ValidationIssue(
                    "WARNING",
                    "duplicate_choices",
                    display_name,
                    f"Repeated ranked choices were ignored: {', '.join(sorted(set(duplicate_choices)))}",
                )
            )

        if not deduped_choices:
            issues.append(
                ValidationIssue(
                    "ERROR",
                    "student_responses",
                    display_name,
                    "Student has no valid ranked choices.",
                )
            )

        attendee = Attendee(
            attendee_id=f"row-{row_number}",
            name=display_name,
            grade=grade,
            teacher=teacher,
            choices=deduped_choices,
            source_row=row_number,
        )
        attendees.append(attendee)
        name_counter[display_name] += 1

    for display_name, count in sorted(name_counter.items()):
        if count > 1:
            issues.append(
                ValidationIssue(
                    "WARNING",
                    "duplicate_name",
                    display_name,
                    f"{count} students share this display name. Internal row IDs will be used.",
                )
            )

    return attendees, issues


def parse_catalog(rows: list[list[str]]) -> tuple[dict[str, SessionOffering], list[str], list[ValidationIssue]]:
    if not rows:
        return {}, [], [ValidationIssue("ERROR", "catalog", "sheet", "Catalog sheet is empty.")]

    headers = rows[0]
    idx = header_index(headers)
    issues: list[ValidationIssue] = []

    required_headers = ["session", "room"]
    missing = [header for header in required_headers if header not in idx]
    if missing:
        issues.append(
            ValidationIssue(
                "ERROR",
                "catalog",
                "headers",
                f"Missing required columns: {', '.join(missing)}",
            )
        )
        return {}, [], issues

    rain_idx = idx.get("rainroom")
    periods = [
        header
        for header in headers
        if PERIOD_RE.fullmatch(normalize_text(header))
    ]
    time_slots = sorted(
        [normalize_text(period).replace(" ", "") for period in periods],
        key=period_sort_key,
    )

    if not time_slots:
        issues.append(
            ValidationIssue(
                "ERROR",
                "catalog",
                "headers",
                "Catalog must contain period1..periodN columns.",
            )
        )
        return {}, [], issues

    period_idx = {slot: idx[normalize_key(slot)] for slot in time_slots}
    sessions: dict[str, SessionOffering] = {}
    duplicate_sessions: list[str] = []

    for row_number, row in enumerate(rows[1:], start=2):
        session_name = normalize_text(cell(row, idx.get("session")))
        if not session_name:
            continue

        if normalize_key(session_name) in {normalize_key(name) for name in sessions}:
            duplicate_sessions.append(session_name)
            continue

        capacities: dict[str, int] = {}
        for period_name, period_column_idx in period_idx.items():
            raw_value = cell(row, period_column_idx)
            if not raw_value:
                capacities[period_name] = 0
                continue
            try:
                capacities[period_name] = int(raw_value)
            except ValueError:
                issues.append(
                    ValidationIssue(
                        "ERROR",
                        "catalog_capacity",
                        f"{session_name} / {period_name}",
                        f"Invalid capacity '{raw_value}' in row {row_number}.",
                    )
                )
                capacities[period_name] = 0

        room = cell(row, idx.get("room"))
        rain_room = cell(row, rain_idx)

        if not room:
            issues.append(
                ValidationIssue(
                    "WARNING",
                    "catalog_room",
                    session_name,
                    "Room is blank.",
                )
            )

        sessions[session_name] = SessionOffering(
            name=session_name,
            room=room,
            rain_room=rain_room,
            capacities=capacities,
        )

    for session_name in sorted(set(duplicate_sessions)):
        issues.append(
            ValidationIssue(
                "ERROR",
                "duplicate_session",
                session_name,
                "Session appears more than once in the catalog.",
            )
        )

    return sessions, time_slots, issues


def validate_data(
    attendees: list[Attendee],
    sessions: dict[str, SessionOffering],
    prior_issues: list[ValidationIssue],
) -> list[ValidationIssue]:
    issues = list(prior_issues)
    known_sessions = {normalize_key(name): name for name in sessions}

    for attendee in attendees:
        for choice in attendee.choices:
            if normalize_key(choice) not in known_sessions:
                issues.append(
                    ValidationIssue(
                        "ERROR",
                        "unknown_session",
                        attendee.name,
                        f"Choice '{choice}' does not exist in the catalog.",
                    )
                )

    return sorted(
        issues,
        key=lambda issue: (
            0 if issue.severity == "ERROR" else 1,
            issue.category,
            issue.subject,
        ),
    )


def session_capacity_totals(sessions: dict[str, SessionOffering]) -> dict[str, int]:
    return {
        session_name: sum(session.capacities.values())
        for session_name, session in sessions.items()
    }


def grade_rank(grade: str) -> int:
    return GRADE_ORDER.get(normalize_text(grade), 99)


def scarcity_score(attendee: Attendee, totals: dict[str, int]) -> int:
    capacities = [totals.get(choice, 0) for choice in attendee.choices]
    return min(capacities) if capacities else 0


def assign_attendees(
    attendees: list[Attendee],
    sessions: dict[str, SessionOffering],
    time_slots: list[str],
) -> tuple[dict[str, dict[str, str]], dict[str, list[tuple[str, int]]]]:
    capacities = {
        name: dict(session.capacities)
        for name, session in sessions.items()
    }
    totals = session_capacity_totals(sessions)
    attendee_map = {attendee.attendee_id: attendee for attendee in attendees}

    sorted_attendees = sorted(
        attendees,
        key=lambda attendee: (
            grade_rank(attendee.grade),
            scarcity_score(attendee, totals),
            attendee.teacher,
            attendee.name,
        ),
    )

    assignments = {
        attendee.attendee_id: {period: "" for period in time_slots}
        for attendee in attendees
    }
    wait_lists: dict[str, list[tuple[str, int]]] = defaultdict(list)

    for attendee in sorted_attendees:
        taken_periods: set[str] = set()
        for rank, session_name in enumerate(attendee.choices, start=1):
            open_periods = {
                period: remaining
                for period, remaining in capacities[session_name].items()
                if remaining > 0 and period not in taken_periods
            }
            if not open_periods:
                wait_lists[session_name].append((attendee.attendee_id, rank))
                continue

            best_period = max(open_periods, key=open_periods.get)
            assignments[attendee.attendee_id][best_period] = session_name
            capacities[session_name][best_period] -= 1
            taken_periods.add(best_period)

    return assignments, wait_lists


def build_generated_schedule_rows(
    attendees: list[Attendee],
    assignments: dict[str, dict[str, str]],
    time_slots: list[str],
) -> list[list[str]]:
    attendee_map = {attendee.attendee_id: attendee for attendee in attendees}
    rows = [["Name", "Grade", "Teacher", *[display_period(period) for period in time_slots]]]
    for attendee in sorted(attendees, key=lambda item: (item.teacher, item.grade, item.name)):
        schedule = assignments[attendee.attendee_id]
        rows.append([
            attendee.name,
            attendee.grade,
            attendee.teacher,
            *[schedule[period] for period in time_slots],
        ])
    return rows


def build_waitlist_rows(
    wait_lists: dict[str, list[tuple[str, int]]],
    attendees: list[Attendee],
) -> list[list[str]]:
    attendee_map = {attendee.attendee_id: attendee for attendee in attendees}
    rows = [["Session", "Student", "Grade", "Teacher", "Preference Rank"]]
    for session_name in sorted(wait_lists):
        for attendee_id, rank in wait_lists[session_name]:
            attendee = attendee_map[attendee_id]
            rows.append([session_name, attendee.name, attendee.grade, attendee.teacher, str(rank)])
    return rows


def build_gap_rows(
    attendees: list[Attendee],
    assignments: dict[str, dict[str, str]],
    time_slots: list[str],
) -> list[list[str]]:
    rows = [["Student", "Grade", "Teacher", "Blank Periods"]]
    for attendee in sorted(attendees, key=lambda item: (item.teacher, item.grade, item.name)):
        schedule = assignments[attendee.attendee_id]
        blanks = [display_period(period) for period in time_slots if not schedule[period]]
        if blanks:
            rows.append([attendee.name, attendee.grade, attendee.teacher, ", ".join(blanks)])
    return rows


def build_validation_rows(issues: list[ValidationIssue]) -> list[list[str]]:
    rows = [["Severity", "Category", "Subject", "Details"]]
    for issue in issues:
        rows.append([issue.severity, issue.category, issue.subject, issue.details])
    return rows


def build_catalog_snapshot_rows(
    sessions: dict[str, SessionOffering],
    time_slots: list[str],
) -> list[list[str]]:
    rows = [["Session", "Room", "Rain Room", *[display_period(period) for period in time_slots]]]
    for session_name in sorted(sessions):
        session = sessions[session_name]
        rows.append([
            session.name,
            session.room,
            session.rain_room,
            *[str(session.capacities[period]) for period in time_slots],
        ])
    return rows


def build_run_summary_rows(
    *,
    student_source_title: str,
    catalog_source_title: str,
    output_workbook_url: str,
    attendee_count: int,
    issue_count: int,
    fatal_issue_count: int,
    gap_count: int | None = None,
    waitlist_count: int | None = None,
    seeded_final_schedule: bool | None = None,
    command_name: str,
) -> list[list[str]]:
    rows = [["Metric", "Value"]]
    rows.extend(
        [
            ["Last Run", datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
            ["Command", command_name],
            ["Student Source", student_source_title],
            ["Catalog Source", catalog_source_title],
            ["Output Workbook", output_workbook_url],
            ["Student Count", str(attendee_count)],
            ["Validation Issue Count", str(issue_count)],
            ["Fatal Issue Count", str(fatal_issue_count)],
        ]
    )
    if gap_count is not None:
        rows.append(["Students With Gaps", str(gap_count)])
    if waitlist_count is not None:
        rows.append(["Waitlist Entries", str(waitlist_count)])
    if seeded_final_schedule is not None:
        rows.append(["Final Schedule Seeded", "yes" if seeded_final_schedule else "no"])
    return rows


def parse_schedule_rows(rows: list[list[str]]) -> tuple[list[Attendee], dict[str, dict[str, str]], list[str]]:
    if not rows:
        raise ValueError("Schedule sheet is empty.")

    headers = rows[0]
    idx = header_index(headers)
    period_columns: list[tuple[str, int]] = []

    for col_idx, header in enumerate(headers):
        normalized = normalize_text(header).replace(" ", "")
        if PERIOD_RE.fullmatch(normalized):
            period_columns.append((normalized.lower(), col_idx))

    if not period_columns:
        raise ValueError("Final Schedule does not contain any Period columns.")

    time_slots = [period for period, _ in sorted(period_columns, key=lambda item: period_sort_key(item[0]))]
    attendees: list[Attendee] = []
    assignments: dict[str, dict[str, str]] = {}

    for row_number, row in enumerate(rows[1:], start=2):
        name = cell(row, idx.get("name"))
        grade = cell(row, idx.get("grade"))
        teacher = cell(row, idx.get("teacher"))
        if not name and not grade and not teacher:
            continue
        attendee_id = f"row-{row_number}"
        attendees.append(
            Attendee(
                attendee_id=attendee_id,
                name=name,
                grade=grade,
                teacher=teacher,
                choices=[],
                source_row=row_number,
            )
        )
        assignments[attendee_id] = {
            period: cell(row, col_idx)
            for period, col_idx in period_columns
        }

    return attendees, assignments, time_slots


def build_session_roster_rows(
    attendees: list[Attendee],
    assignments: dict[str, dict[str, str]],
    sessions: dict[str, SessionOffering],
    time_slots: list[str],
) -> list[list[str]]:
    attendee_map = {attendee.attendee_id: attendee for attendee in attendees}
    rows = [["Session", "Room", "Rain Room", "Period", "Student Count", "Students"]]

    for session_name in sorted(sessions):
        for period in time_slots:
            students = sorted(
                attendee_map[attendee_id].name
                for attendee_id, schedule in assignments.items()
                if schedule.get(period) == session_name
            )
            rows.append([
                session_name,
                sessions[session_name].room,
                sessions[session_name].rain_room,
                display_period(period),
                str(len(students)),
                "; ".join(students),
            ])
    return rows


def build_teacher_view_rows(
    attendees: list[Attendee],
    assignments: dict[str, dict[str, str]],
    time_slots: list[str],
) -> list[list[str]]:
    rows = [["Teacher", "Name", "Grade", *[display_period(period) for period in time_slots]]]
    for attendee in sorted(attendees, key=lambda item: (item.teacher, item.grade, item.name)):
        schedule = assignments[attendee.attendee_id]
        rows.append([
            attendee.teacher,
            attendee.name,
            attendee.grade,
            *[schedule.get(period, "") for period in time_slots],
        ])
    return rows


def generate_pdf_outputs(
    attendees: list[Attendee],
    assignments: dict[str, dict[str, str]],
    sessions: dict[str, SessionOffering],
    time_slots: list[str],
    time_blocks: dict[str, str],
    output_dir: Path,
) -> tuple[Path, Path]:
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos

    output_dir.mkdir(parents=True, exist_ok=True)
    cards_pdf_path = output_dir / "attendee_schedule.pdf"
    rosters_pdf_path = output_dir / "class_rosters.pdf"

    room_map = {name: session.room for name, session in sessions.items()}
    rain_map = {name: session.rain_room for name, session in sessions.items()}

    CARD_W, CARD_H = 100, 64
    LEFT_MARGIN, TOP_MARGIN, COL_GAP = 7, 10, 6
    COLS = [("Time", 21), ("Session", 42), ("Room", 17), ("Rain", 17)]

    class CardsPDF(FPDF):
        def card(self, *, x0: float, y0: float, attendee: Attendee, schedule: dict[str, str]) -> None:
            self.set_xy(x0, y0)
            self.set_font("Helvetica", "B", 14)
            self.multi_cell(CARD_W, 7, attendee.name)
            self.set_x(x0)
            self.set_font("Helvetica", "", 11)
            self.cell(0, 5, f"Grade: {attendee.grade}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.set_x(x0)
            self.cell(0, 5, f"Teacher: {attendee.teacher}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.ln(1)
            self.set_x(x0)

            self.set_font("Helvetica", "B", 8)
            for label, width in COLS:
                self.cell(width, 5, label, border=1, align="C")
            self.ln(5)
            self.set_x(x0)

            self.set_font("Helvetica", "", 8)
            for period in time_slots:
                session_name = schedule.get(period, "")
                self.cell(COLS[0][1], 5, time_blocks.get(period, display_period(period)), border=1)
                x_before, y_before = self.get_x(), self.get_y()
                self.multi_cell(COLS[1][1], 5, session_name, border=1, align="L")
                self.set_xy(x_before + COLS[1][1], y_before)
                self.cell(COLS[2][1], 5, room_map.get(session_name, ""), border=1)
                self.cell(COLS[3][1], 5, rain_map.get(session_name, ""), border=1)
                self.ln(5)
                self.set_x(x0)

    cards_pdf = CardsPDF(orientation="P", unit="mm", format="Letter")
    cards_pdf.set_auto_page_break(False)
    sorted_attendees = sorted(attendees, key=lambda item: (item.teacher, item.grade, item.name))
    for idx, attendee in enumerate(sorted_attendees):
        if idx % 8 == 0:
            cards_pdf.add_page()
        row = idx % 4
        col = (idx // 4) % 2
        x = LEFT_MARGIN + col * (CARD_W + COL_GAP)
        y = TOP_MARGIN + row * CARD_H
        cards_pdf.card(x0=x, y0=y, attendee=attendee, schedule=assignments[attendee.attendee_id])
    cards_pdf.output(str(cards_pdf_path))

    class RosterPDF(FPDF):
        def header(self):
            return None

    roster_pdf = RosterPDF(orientation="L", unit="mm", format="Letter")
    col_w = 37 if len(time_slots) == 7 else 44
    roster_rows = build_session_roster_rows(attendees, assignments, sessions, time_slots)
    by_session: dict[str, list[list[str]]] = defaultdict(list)
    for row in roster_rows[1:]:
        by_session[row[0]].append(row)

    for session_name in sorted(by_session):
        roster_pdf.add_page()
        roster_pdf.set_font("Helvetica", "B", 18)
        roster_pdf.cell(0, 10, session_name, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        roster_pdf.set_font("Helvetica", "", 11)
        roster_pdf.cell(0, 6, f"Location: {room_map.get(session_name, '')}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        roster_pdf.cell(0, 6, f"Rain Location: {rain_map.get(session_name, '')}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        roster_pdf.ln(3)

        roster_pdf.set_font("Helvetica", "B", 8)
        for period in time_slots:
            roster_pdf.cell(col_w, 6, time_blocks.get(period, display_period(period)), border=1, align="C")
        roster_pdf.ln(6)

        period_students = []
        for period in time_slots:
            matching = next((row for row in by_session[session_name] if row[3] == display_period(period)), None)
            students = matching[5].split("; ") if matching and matching[5] else []
            period_students.append(students)

        max_rows = max((len(students) for students in period_students), default=0)
        roster_pdf.set_font("Helvetica", "", 8)
        for row_idx in range(max_rows):
            for students in period_students:
                roster_pdf.cell(col_w, 5, students[row_idx] if row_idx < len(students) else "", border=1)
            roster_pdf.ln(5)
    roster_pdf.output(str(rosters_pdf_path))

    return cards_pdf_path, rosters_pdf_path
