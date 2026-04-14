#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter

from imagination_day import (
    canonical_grade_lunch_assignments,
    ConfigError,
    compute_schedule_metrics,
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
    build_final_waitlist_rows,
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
    run_parser = subparsers.add_parser("run", help="Generate a draft schedule into the output workbook")
    run_parser.add_argument(
        "--algorithm",
        default="cp-sat",
        choices=("greedy", "cp-sat"),
        help="Scheduling algorithm to use for draft generation (default: cp-sat)",
    )
    run_parser.add_argument(
        "--cp-sat-time-limit",
        type=float,
        default=10.0,
        help="Maximum CP-SAT solve time in seconds when --algorithm=cp-sat (default: 10)",
    )
    subparsers.add_parser(
        "refresh-final",
        help="Revalidate the edited Final Schedule and refresh final waitlist/gaps/rosters without generating PDFs",
    )

    printables = subparsers.add_parser(
        "printables",
        help="Refresh final reports from the Final Schedule tab and generate PDFs",
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

    benchmark = subparsers.add_parser(
        "benchmark",
        help="Compare scheduling algorithms on the source sheets without writing workbook tabs",
    )
    benchmark.add_argument(
        "--algorithms",
        nargs="+",
        default=["greedy", "cp-sat"],
        choices=("greedy", "cp-sat"),
        help="Algorithms to compare (default: greedy cp-sat)",
    )
    benchmark.add_argument(
        "--cp-sat-time-limit",
        type=float,
        default=10.0,
        help="Maximum CP-SAT solve time in seconds when included in --algorithms (default: 10)",
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
    issues = validate_data(attendees, sessions, attendee_issues + catalog_issues, config)

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
    client.sync_output_tab_protections(output_workbook_url)


def fatal_issue_count(issues: list[ValidationIssue]) -> int:
    return sum(1 for issue in issues if issue.is_fatal)


def read_tab_rows(client: GoogleSheetsClient, workbook_url: str, tab_title: str) -> list[list[str]]:
    return client.read_range(workbook_url, tab_title, "A:ZZ")


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
        lunch_assignments_count=len(canonical_grade_lunch_assignments(config)),
        command_name="validate",
    )
    write_validation_outputs(client, output_workbook_url, sessions, time_slots, issues, summary_rows)

    print(f"Validation refreshed in {output_workbook_url}")
    print(f"Issues: {len(issues)} total, {fatal_count} fatal")
    return 1 if fatal_count else 0


def command_run(config_path: Path, *, algorithm: str, cp_sat_time_limit: float) -> int:
    config = load_config(config_path)
    client = GoogleSheetsClient(config["credentials_file"], config["token_file"])
    output_workbook_url = ensure_output_workbook(client, config, config_path)
    client.ensure_tabs(output_workbook_url, OUTPUT_TABS)
    existing_draft_rows = read_tab_rows(client, output_workbook_url, TAB_DRAFT)
    existing_final_rows = read_tab_rows(client, output_workbook_url, TAB_FINAL)

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
            lunch_assignments_count=len(canonical_grade_lunch_assignments(config)),
            command_name="run",
        )
        write_validation_outputs(client, output_workbook_url, sessions, time_slots, issues, summary_rows)
        print(f"Run stopped because validation found {fatal_count} fatal issue(s).")
        print(f"See {TAB_VALIDATION} in {output_workbook_url}")
        return 1

    assignments, wait_lists = assign_attendees(
        attendees,
        sessions,
        time_slots,
        config,
        algorithm=algorithm,
        time_limit_seconds=cp_sat_time_limit,
    )
    generated_rows = build_generated_schedule_rows(attendees, assignments, time_slots)
    waitlist_rows = build_waitlist_rows(wait_lists, attendees)
    gap_rows = build_gap_rows(attendees, assignments, time_slots)
    roster_rows = build_session_roster_rows(attendees, assignments, sessions, time_slots)
    teacher_rows = build_teacher_view_rows(attendees, assignments, time_slots)

    final_schedule_seeded = False
    final_schedule_refreshed = False
    if not existing_final_rows or len(existing_final_rows) <= 1:
        client.clear_and_write_tab(output_workbook_url, TAB_FINAL, generated_rows)
        final_schedule_seeded = True
    elif existing_draft_rows and existing_final_rows == existing_draft_rows:
        client.clear_and_write_tab(output_workbook_url, TAB_FINAL, generated_rows)
        final_schedule_refreshed = True

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
        lunch_assignments_count=len(canonical_grade_lunch_assignments(config)),
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
    client.sync_output_tab_protections(output_workbook_url)

    print(f"Draft schedule written to {output_workbook_url}")
    print(f"Algorithm: {algorithm}")
    if final_schedule_seeded:
        print(f"{TAB_FINAL} was empty, so it was seeded automatically from {TAB_DRAFT}.")
    elif final_schedule_refreshed:
        print(f"{TAB_FINAL} matched the previous draft, so it was refreshed automatically.")
    else:
        print(f"{TAB_FINAL} already contained data and was left unchanged.")
    return 0


def validate_final_schedule(
    attendees,
    assignments,
    sessions,
    config,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    known_sessions = set(sessions)
    attendee_map = {attendee.attendee_id: attendee for attendee in attendees}

    for attendee_id, schedule in assignments.items():
        attendee = attendee_map[attendee_id]
        for period, session_name in schedule.items():
            if session_name and session_name not in known_sessions:
                issues.append(
                    ValidationIssue(
                        "ERROR",
                        "final_schedule_session",
                        attendee.name,
                        f"{period} references '{session_name}', which is not in the catalog.",
                    )
                )
    return issues


def refresh_final_outputs(
    config_path: Path,
    *,
    output_dir_override: str | None,
    generate_pdfs: bool,
) -> int:
    config = load_config(config_path)
    client = GoogleSheetsClient(config["credentials_file"], config["token_file"])
    output_workbook_url = ensure_output_workbook(client, config, config_path)
    client.ensure_tabs(output_workbook_url, OUTPUT_TABS)

    catalog_rows = client.read_range(config["catalog_url"], config["catalog_tab"], "A:ZZ")
    sessions, time_slots, catalog_issues = parse_catalog(catalog_rows)
    student_rows = client.read_range(config["student_responses_url"], config["student_tab"], "A:ZZ")
    source_attendees, attendee_issues = parse_attendees(student_rows, config)
    final_rows = client.read_range(output_workbook_url, TAB_FINAL, "A:ZZ")
    if len(final_rows) <= 1:
        print(f"{TAB_FINAL} is empty. Run `python scheduler.py run` and edit that tab first.")
        return 1

    attendees, assignments, final_time_slots = parse_schedule_rows(final_rows)
    issues = catalog_issues + attendee_issues + validate_final_schedule(attendees, assignments, sessions, config)
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
        lunch_assignments_count=len(canonical_grade_lunch_assignments(config)),
        command_name="printables" if generate_pdfs else "refresh-final",
    )
    write_validation_outputs(client, output_workbook_url, sessions, time_slots, issues, summary_rows)

    if fatal_count:
        action = "Printable generation" if generate_pdfs else "Final report refresh"
        print(f"{action} stopped because validation found {fatal_count} fatal issue(s).")
        print(f"See {TAB_VALIDATION} in {output_workbook_url}")
        return 1

    roster_rows = build_session_roster_rows(attendees, assignments, sessions, final_time_slots)
    teacher_rows = build_teacher_view_rows(attendees, assignments, final_time_slots)
    gap_rows = build_gap_rows(attendees, assignments, final_time_slots)
    waitlist_rows = build_final_waitlist_rows(attendees, assignments, source_attendees)
    client.clear_and_write_tab(output_workbook_url, TAB_INSTRUCTIONS, build_instruction_rows())
    client.clear_and_write_tab(output_workbook_url, TAB_WAITLIST, waitlist_rows)
    client.clear_and_write_tab(output_workbook_url, TAB_GAPS, gap_rows)
    client.clear_and_write_tab(output_workbook_url, TAB_ROSTERS, roster_rows)
    client.clear_and_write_tab(output_workbook_url, TAB_TEACHER, teacher_rows)
    client.sync_output_tab_protections(output_workbook_url)

    if not generate_pdfs:
        print(f"Final reports refreshed in {output_workbook_url}")
        return 0

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


def command_refresh_final(config_path: Path) -> int:
    return refresh_final_outputs(
        config_path,
        output_dir_override=None,
        generate_pdfs=False,
    )


def command_printables(config_path: Path, output_dir_override: str | None) -> int:
    return refresh_final_outputs(
        config_path,
        output_dir_override=output_dir_override,
        generate_pdfs=True,
    )


def delta_or_none(left: int | float | None, right: int | float | None) -> int | float | None:
    if left is None or right is None:
        return None
    return left - right


def command_benchmark(
    config_path: Path,
    *,
    algorithms: list[str],
    cp_sat_time_limit: float,
) -> int:
    config = load_config(config_path)
    client = GoogleSheetsClient(config["credentials_file"], config["token_file"])
    attendees, sessions, time_slots, issues, student_meta, catalog_meta = load_source_data(client, config)
    fatal_count = fatal_issue_count(issues)
    if fatal_count:
        print(json.dumps({
            "validation": {
                "total_issues": len(issues),
                "fatal_issues": fatal_count,
            },
            "error": "Benchmark stopped because validation found fatal issues.",
        }, indent=2))
        return 1

    results = {}
    for algorithm in algorithms:
        started = perf_counter()
        assignments, wait_lists = assign_attendees(
            attendees,
            sessions,
            time_slots,
            config,
            algorithm=algorithm,
            time_limit_seconds=cp_sat_time_limit,
        )
        solve_time_seconds = perf_counter() - started
        metrics = compute_schedule_metrics(
            attendees,
            sessions,
            time_slots,
            assignments,
            config,
            algorithm=algorithm,
            solve_time_seconds=solve_time_seconds,
        )
        metrics["reported_waitlist_entries"] = sum(len(entries) for entries in wait_lists.values())
        results[algorithm] = metrics

    comparison = {}
    if "greedy" in results and "cp-sat" in results:
        greedy = results["greedy"]
        cp_sat = results["cp-sat"]
        comparison = {
            "candidate": "cp-sat",
            "baseline": "greedy",
            "deltas": {
                "assigned_non_lunch_total": (
                    cp_sat["preference_metrics"]["assigned_non_lunch_total"]
                    - greedy["preference_metrics"]["assigned_non_lunch_total"]
                ),
                "students_with_top1": (
                    cp_sat["preference_metrics"]["students_with_top1"]
                    - greedy["preference_metrics"]["students_with_top1"]
                ),
                "manual_gap_slots": (
                    cp_sat["gap_metrics"]["manual_gap_slots"]
                    - greedy["gap_metrics"]["manual_gap_slots"]
                ),
                "students_with_gaps": (
                    cp_sat["gap_metrics"]["students_with_gaps"]
                    - greedy["gap_metrics"]["students_with_gaps"]
                ),
                "normalized_rank_score": delta_or_none(
                    cp_sat["preference_metrics"]["normalized_rank_score"],
                    greedy["preference_metrics"]["normalized_rank_score"],
                ),
                "non_lunch_seat_utilization": delta_or_none(
                    cp_sat["capacity_metrics"]["non_lunch_seat_utilization"],
                    greedy["capacity_metrics"]["non_lunch_seat_utilization"],
                ),
                "solve_time_seconds": delta_or_none(
                    cp_sat["solve_time_seconds"],
                    greedy["solve_time_seconds"],
                ),
            },
        }

    print(json.dumps({
        "student_source": student_meta["properties"]["title"],
        "catalog_source": catalog_meta["properties"]["title"],
        "student_count": len(attendees),
        "session_count": len(sessions),
        "time_slot_count": len(time_slots),
        "validation": {
            "total_issues": len(issues),
            "fatal_issues": fatal_count,
            "warnings": len(issues) - fatal_count,
        },
        "algorithms": results,
        "comparison": comparison,
    }, indent=2))
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
            return command_run(
                config_path,
                algorithm=args.algorithm,
                cp_sat_time_limit=args.cp_sat_time_limit,
            )
        if args.command == "refresh-final":
            return command_refresh_final(config_path)
        if args.command == "printables":
            return command_printables(config_path, args.output_dir)
        if args.command == "benchmark":
            return command_benchmark(
                config_path,
                algorithms=args.algorithms,
                cp_sat_time_limit=args.cp_sat_time_limit,
            )
        parser.error(f"Unknown command: {args.command}")
    except ConfigError as exc:
        print(f"Configuration error: {exc}")
        return 1
    except Exception as exc:  # pragma: no cover - CLI safety net
        print(f"Error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
