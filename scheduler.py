#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path

from imagination_day import (
    ConfigError,
    GoogleSheetsClient,
    OUTPUT_TABS,
    TAB_CATALOG,
    TAB_DRAFT,
    TAB_FINAL,
    TAB_GAPS,
    TAB_INSTRUCTIONS,
    TAB_ROSTERS,
    TAB_RUN_STATUS,
    TAB_TEACHER,
    TAB_VALIDATION,
    TAB_WAITLIST,
    build_catalog_snapshot_rows,
    build_gap_rows,
    build_generated_schedule_rows,
    build_instruction_rows,
    build_run_summary_rows,
    build_session_roster_rows,
    build_teacher_view_rows,
    build_validation_rows,
    build_waitlist_rows,
    ensure_output_workbook,
    generate_pdf_outputs,
    load_config,
    parse_attendees,
    parse_catalog,
    parse_schedule_rows,
    save_config,
    validate_data,
    ValidationIssue,
    assign_attendees,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Imagination Day scheduler")
    parser.add_argument(
        "--config",
        default="config.json",
        help="Path to the scheduler config file (default: config.json)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate", help="Validate the source sheets and refresh validation tabs")
    subparsers.add_parser("run", help="Generate a draft schedule into the output workbook")

    printables = subparsers.add_parser(
        "printables",
        help="Generate PDFs from the Final Schedule tab and refresh final roster tabs",
    )
    printables.add_argument(
        "--output-dir",
        default=None,
        help="Directory for generated PDFs (defaults to config pdf_output_dir)",
    )

    init_config = subparsers.add_parser(
        "init-config",
        help="Write a starter config file if one does not already exist",
    )
    init_config.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the target config file if it already exists",
    )
    return parser


def init_config_file(config_path: Path, *, force: bool) -> None:
    from imagination_day import DEFAULT_CONFIG

    if config_path.exists() and not force:
        raise ConfigError(
            f"{config_path} already exists. Use --force to overwrite it."
        )
    save_config(config_path, DEFAULT_CONFIG)
    print(f"Wrote starter config to {config_path}")


def load_source_data(client: GoogleSheetsClient, config: dict) -> tuple:
    student_rows = client.read_range(
        config["student_responses_url"],
        config["student_tab"],
        "A:ZZ",
    )
    catalog_rows = client.read_range(
        config["catalog_url"],
        config["catalog_tab"],
        "A:ZZ",
    )

    attendees, attendee_issues = parse_attendees(student_rows, config)
    sessions, time_slots, catalog_issues = parse_catalog(catalog_rows)
    issues = validate_data(attendees, sessions, attendee_issues + catalog_issues)

    student_meta = client.get_metadata(config["student_responses_url"])
    catalog_meta = client.get_metadata(config["catalog_url"])
    return attendees, sessions, time_slots, issues, student_meta, catalog_meta


def write_validation_outputs(
    client: GoogleSheetsClient,
    output_workbook_url: str,
    sessions: dict,
    time_slots: list[str],
    issues: list[ValidationIssue],
    summary_rows: list[list[str]],
) -> None:
    client.clear_and_write_tab(output_workbook_url, TAB_INSTRUCTIONS, build_instruction_rows())
    client.clear_and_write_tab(output_workbook_url, TAB_VALIDATION, build_validation_rows(issues))
    if sessions and time_slots:
        client.clear_and_write_tab(
            output_workbook_url,
            TAB_CATALOG,
            build_catalog_snapshot_rows(sessions, time_slots),
        )
    client.clear_and_write_tab(output_workbook_url, TAB_RUN_STATUS, summary_rows)


def fatal_issue_count(issues: list[ValidationIssue]) -> int:
    return sum(1 for issue in issues if issue.is_fatal)


def command_validate(config_path: Path) -> int:
    config = load_config(config_path)
    client = GoogleSheetsClient(config["credentials_file"], config["token_file"])
    output_workbook_url = ensure_output_workbook(client, config, config_path)

    attendees, sessions, time_slots, issues, student_meta, catalog_meta = load_source_data(client, config)
    fatal_count = fatal_issue_count(issues)

    summary_rows = build_run_summary_rows(
        student_source_title=student_meta["properties"]["title"],
        catalog_source_title=catalog_meta["properties"]["title"],
        output_workbook_url=output_workbook_url,
        attendee_count=len(attendees),
        issue_count=len(issues),
        fatal_issue_count=fatal_count,
        command_name="validate",
    )
    write_validation_outputs(client, output_workbook_url, sessions, time_slots, issues, summary_rows)

    print(f"Validation refreshed in {output_workbook_url}")
    print(f"Issues: {len(issues)} total, {fatal_count} fatal")
    return 1 if fatal_count else 0


def command_run(config_path: Path) -> int:
    config = load_config(config_path)
    client = GoogleSheetsClient(config["credentials_file"], config["token_file"])
    output_workbook_url = ensure_output_workbook(client, config, config_path)
    client.ensure_tabs(output_workbook_url, OUTPUT_TABS)

    attendees, sessions, time_slots, issues, student_meta, catalog_meta = load_source_data(client, config)
    fatal_count = fatal_issue_count(issues)

    if fatal_count:
        summary_rows = build_run_summary_rows(
            student_source_title=student_meta["properties"]["title"],
            catalog_source_title=catalog_meta["properties"]["title"],
            output_workbook_url=output_workbook_url,
            attendee_count=len(attendees),
            issue_count=len(issues),
            fatal_issue_count=fatal_count,
            command_name="run",
        )
        write_validation_outputs(client, output_workbook_url, sessions, time_slots, issues, summary_rows)
        print(f"Run stopped because validation found {fatal_count} fatal issue(s).")
        print(f"See {TAB_VALIDATION} in {output_workbook_url}")
        return 1

    assignments, wait_lists = assign_attendees(attendees, sessions, time_slots)
    generated_rows = build_generated_schedule_rows(attendees, assignments, time_slots)
    waitlist_rows = build_waitlist_rows(wait_lists, attendees)
    gap_rows = build_gap_rows(attendees, assignments, time_slots)
    roster_rows = build_session_roster_rows(attendees, assignments, sessions, time_slots)
    teacher_rows = build_teacher_view_rows(attendees, assignments, time_slots)

    final_schedule_seeded = False
    if not client.tab_has_data(output_workbook_url, TAB_FINAL):
        client.clear_and_write_tab(output_workbook_url, TAB_FINAL, generated_rows)
        final_schedule_seeded = True

    summary_rows = build_run_summary_rows(
        student_source_title=student_meta["properties"]["title"],
        catalog_source_title=catalog_meta["properties"]["title"],
        output_workbook_url=output_workbook_url,
        attendee_count=len(attendees),
        issue_count=len(issues),
        fatal_issue_count=fatal_count,
        gap_count=max(len(gap_rows) - 1, 0),
        waitlist_count=max(len(waitlist_rows) - 1, 0),
        seeded_final_schedule=final_schedule_seeded,
        command_name="run",
    )

    client.clear_and_write_tab(output_workbook_url, TAB_INSTRUCTIONS, build_instruction_rows())
    client.clear_and_write_tab(output_workbook_url, TAB_VALIDATION, build_validation_rows(issues))
    client.clear_and_write_tab(output_workbook_url, TAB_DRAFT, generated_rows)
    client.clear_and_write_tab(output_workbook_url, TAB_WAITLIST, waitlist_rows)
    client.clear_and_write_tab(output_workbook_url, TAB_GAPS, gap_rows)
    client.clear_and_write_tab(output_workbook_url, TAB_ROSTERS, roster_rows)
    client.clear_and_write_tab(output_workbook_url, TAB_TEACHER, teacher_rows)
    client.clear_and_write_tab(output_workbook_url, TAB_CATALOG, build_catalog_snapshot_rows(sessions, time_slots))
    client.clear_and_write_tab(output_workbook_url, TAB_RUN_STATUS, summary_rows)

    print(f"Draft schedule written to {output_workbook_url}")
    if final_schedule_seeded:
        print(f"{TAB_FINAL} was empty, so it was seeded automatically from {TAB_DRAFT}.")
    else:
        print(f"{TAB_FINAL} already contained data and was left unchanged.")
    return 0


def validate_final_schedule(
    attendees,
    assignments,
    sessions,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    known_sessions = set(sessions)
    attendee_map = {attendee.attendee_id: attendee for attendee in attendees}

    for attendee_id, schedule in assignments.items():
        for period, session_name in schedule.items():
            if session_name and session_name not in known_sessions:
                issues.append(
                    ValidationIssue(
                        "ERROR",
                        "final_schedule_session",
                        attendee_map[attendee_id].name,
                        f"{period} references '{session_name}', which is not in the catalog.",
                    )
                )
    return issues


def command_printables(config_path: Path, output_dir_override: str | None) -> int:
    config = load_config(config_path)
    client = GoogleSheetsClient(config["credentials_file"], config["token_file"])
    output_workbook_url = ensure_output_workbook(client, config, config_path)
    client.ensure_tabs(output_workbook_url, OUTPUT_TABS)

    catalog_rows = client.read_range(config["catalog_url"], config["catalog_tab"], "A:ZZ")
    sessions, time_slots, catalog_issues = parse_catalog(catalog_rows)
    final_rows = client.read_range(output_workbook_url, TAB_FINAL, "A:ZZ")
    if len(final_rows) <= 1:
        print(f"{TAB_FINAL} is empty. Run `python scheduler.py run` and edit that tab first.")
        return 1

    attendees, assignments, final_time_slots = parse_schedule_rows(final_rows)
    issues = catalog_issues + validate_final_schedule(attendees, assignments, sessions)
    fatal_count = fatal_issue_count(issues)

    student_meta = client.get_metadata(config["student_responses_url"])
    catalog_meta = client.get_metadata(config["catalog_url"])
    summary_rows = build_run_summary_rows(
        student_source_title=student_meta["properties"]["title"],
        catalog_source_title=catalog_meta["properties"]["title"],
        output_workbook_url=output_workbook_url,
        attendee_count=len(attendees),
        issue_count=len(issues),
        fatal_issue_count=fatal_count,
        command_name="printables",
    )
    write_validation_outputs(client, output_workbook_url, sessions, time_slots, issues, summary_rows)

    if fatal_count:
        print(f"Printable generation stopped because validation found {fatal_count} fatal issue(s).")
        print(f"See {TAB_VALIDATION} in {output_workbook_url}")
        return 1

    roster_rows = build_session_roster_rows(attendees, assignments, sessions, final_time_slots)
    teacher_rows = build_teacher_view_rows(attendees, assignments, final_time_slots)
    client.clear_and_write_tab(output_workbook_url, TAB_INSTRUCTIONS, build_instruction_rows())
    client.clear_and_write_tab(output_workbook_url, TAB_ROSTERS, roster_rows)
    client.clear_and_write_tab(output_workbook_url, TAB_TEACHER, teacher_rows)

    output_dir = Path(output_dir_override or config["pdf_output_dir"]).expanduser()
    cards_pdf, rosters_pdf = generate_pdf_outputs(
        attendees,
        assignments,
        sessions,
        final_time_slots,
        config["time_blocks"],
        output_dir,
    )

    print(f"Generated PDFs:\n- {cards_pdf}\n- {rosters_pdf}")
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    config_path = Path(args.config).expanduser()

    try:
        if args.command == "init-config":
            init_config_file(config_path, force=args.force)
            return 0
        if args.command == "validate":
            return command_validate(config_path)
        if args.command == "run":
            return command_run(config_path)
        if args.command == "printables":
            return command_printables(config_path, args.output_dir)
        parser.error(f"Unknown command: {args.command}")
    except ConfigError as exc:
        print(f"Configuration error: {exc}")
        return 1
    except Exception as exc:  # pragma: no cover - CLI safety net
        print(f"Error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
