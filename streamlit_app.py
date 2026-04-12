#!/usr/bin/env python3

from __future__ import annotations

import copy
import io
import json
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

import streamlit as st

from imagination_day import ConfigError, DEFAULT_CONFIG, load_config, save_config
from scheduler import (
    command_printables,
    command_refresh_final,
    command_run,
    command_validate,
)


REPO_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = REPO_ROOT / "config.json"
EXAMPLE_CONFIG_PATH = REPO_ROOT / "config.example.json"
REQUIRED_CONFIG_KEYS = ("student_responses_url", "catalog_url")


def load_starter_config() -> dict[str, Any]:
    if EXAMPLE_CONFIG_PATH.exists():
        try:
            data = json.loads(EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return copy.deepcopy(DEFAULT_CONFIG)


def merge_config(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = merge_config(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_editable_config() -> dict[str, Any]:
    starter = load_starter_config()
    if not CONFIG_PATH.exists():
        return starter

    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return starter

    if not isinstance(raw, dict):
        return starter
    return merge_config(starter, raw)


def resolve_local_path(path_text: str | None) -> Path | None:
    if not path_text:
        return None
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def json_text(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True)


def required_config_gaps(config: dict[str, Any]) -> list[str]:
    return [key for key in REQUIRED_CONFIG_KEYS if not str(config.get(key) or "").strip()]


def config_health_message() -> tuple[str, str]:
    if not CONFIG_PATH.exists():
        return "warning", "No config file found yet. Fill in the form below and save it as `config.json`."
    try:
        load_config(CONFIG_PATH)
    except ConfigError as exc:
        return "warning", f"Config needs attention: {exc}"
    return "success", "Config looks valid enough for the scheduler to run."


def save_form_config(
    *,
    student_responses_url: str,
    student_tab: str,
    catalog_url: str,
    catalog_tab: str,
    output_workbook_url: str,
    output_workbook_title: str,
    credentials_file: str,
    token_file: str,
    pdf_output_dir: str,
    session_aliases_text: str,
    grade_lunch_assignments_text: str,
    time_blocks_text: str,
) -> None:
    def parse_mapping(label: str, raw_text: str) -> dict[str, Any]:
        try:
            value = json.loads(raw_text.strip() or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError(f"{label} must be valid JSON: {exc.msg}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{label} must be a JSON object.")
        return value

    config = {
        "student_responses_url": student_responses_url.strip(),
        "student_tab": student_tab.strip() or "Form Responses 1",
        "catalog_url": catalog_url.strip(),
        "catalog_tab": catalog_tab.strip() or "Sheet1",
        "output_workbook_url": output_workbook_url.strip() or None,
        "output_workbook_title": output_workbook_title.strip() or None,
        "credentials_file": credentials_file.strip() or "credentials.json",
        "token_file": token_file.strip() or "token.json",
        "pdf_output_dir": pdf_output_dir.strip() or ".",
        "session_aliases": parse_mapping("Session aliases", session_aliases_text),
        "grade_lunch_assignments": parse_mapping(
            "Grade lunch assignments",
            grade_lunch_assignments_text,
        ),
        "time_blocks": parse_mapping("Time blocks", time_blocks_text),
    }
    save_config(CONFIG_PATH, config)


def run_scheduler_action(label: str, callback, *args, **kwargs) -> dict[str, Any]:
    stream = io.StringIO()
    code = 1
    error = None

    try:
        with redirect_stdout(stream), redirect_stderr(stream):
            code = callback(*args, **kwargs)
    except Exception:
        error = traceback.format_exc()

    return {
        "label": label,
        "code": code,
        "log": stream.getvalue().strip(),
        "error": error,
    }


def status_line(label: str, ok: bool, detail: str) -> None:
    prefix = "OK" if ok else "Missing"
    st.write(f"- **{label}:** {prefix} ({detail})")


def show_flash_messages() -> None:
    flash = st.session_state.pop("flash_message", None)
    if not flash:
        return
    kind = flash["kind"]
    text = flash["text"]
    if kind == "success":
        st.success(text)
    elif kind == "error":
        st.error(text)
    else:
        st.info(text)


def show_last_action_result() -> None:
    result = st.session_state.get("last_action_result")
    if not result:
        return

    if result["error"]:
        st.error(f"{result['label']} failed with an unexpected exception.")
        st.code(result["error"], language="text")
        return

    if result["code"] == 0:
        st.success(f"{result['label']} finished successfully.")
    else:
        st.error(f"{result['label']} finished with errors.")

    if result["log"]:
        st.code(result["log"], language="text")


st.set_page_config(page_title="Imagination Day Wizard", layout="wide")

show_flash_messages()

st.title("Imagination Day Wizard")
st.caption("Local step-by-step runner for the yearly scheduling workflow.")

config = load_editable_config()
gaps = required_config_gaps(config)
health_kind, health_text = config_health_message()
if health_kind == "success":
    st.success(health_text)
else:
    st.warning(health_text)

st.subheader("Setup Status")
credentials_path = resolve_local_path(str(config.get("credentials_file") or ""))
token_path = resolve_local_path(str(config.get("token_file") or ""))
pdf_output_dir = resolve_local_path(str(config.get("pdf_output_dir") or "."))

status_line("`config.json`", CONFIG_PATH.exists(), str(CONFIG_PATH))
status_line(
    "`credentials.json`",
    bool(credentials_path and credentials_path.exists()),
    str(credentials_path or "not set"),
)
status_line(
    "`token.json`",
    bool(token_path and token_path.exists()),
    str(token_path or "not set"),
)
status_line(
    "Required URLs",
    not gaps,
    ", ".join(gaps) if gaps else "student and catalog URLs are present",
)
status_line(
    "PDF output folder",
    bool(pdf_output_dir and pdf_output_dir.exists()),
    str(pdf_output_dir or "not set"),
)

if not token_path or not token_path.exists():
    st.info(
        "The first successful scheduler run will open a Google sign-in flow in your browser "
        "and create `token.json`."
    )

st.subheader("Config")
with st.form("config_form"):
    left, right = st.columns(2)
    with left:
        student_responses_url = st.text_input(
            "Student responses sheet URL",
            value=str(config.get("student_responses_url") or ""),
        )
        student_tab = st.text_input(
            "Student responses tab",
            value=str(config.get("student_tab") or "Form Responses 1"),
        )
        catalog_url = st.text_input(
            "Catalog sheet URL",
            value=str(config.get("catalog_url") or ""),
        )
        catalog_tab = st.text_input(
            "Catalog tab",
            value=str(config.get("catalog_tab") or "Sheet1"),
        )
        output_workbook_url = st.text_input(
            "Output workbook URL",
            value=str(config.get("output_workbook_url") or ""),
            help="Leave blank on the first run. The scheduler will create it and save the URL.",
        )
        output_workbook_title = st.text_input(
            "Output workbook title",
            value=str(config.get("output_workbook_title") or ""),
        )

    with right:
        credentials_file = st.text_input(
            "Credentials file",
            value=str(config.get("credentials_file") or "credentials.json"),
        )
        token_file = st.text_input(
            "Token file",
            value=str(config.get("token_file") or "token.json"),
        )
        pdf_output_dir_text = st.text_input(
            "PDF output directory",
            value=str(config.get("pdf_output_dir") or "."),
        )
        session_aliases_text = st.text_area(
            "Session aliases (JSON object)",
            value=json_text(config.get("session_aliases") or {}),
            height=180,
        )
        grade_lunch_assignments_text = st.text_area(
            "Grade lunch assignments (JSON object)",
            value=json_text(config.get("grade_lunch_assignments") or {}),
            height=180,
        )
        time_blocks_text = st.text_area(
            "Time blocks (JSON object)",
            value=json_text(config.get("time_blocks") or {}),
            height=180,
        )

    save_pressed = st.form_submit_button("Save Config", type="primary")
    if save_pressed:
        try:
            save_form_config(
                student_responses_url=student_responses_url,
                student_tab=student_tab,
                catalog_url=catalog_url,
                catalog_tab=catalog_tab,
                output_workbook_url=output_workbook_url,
                output_workbook_title=output_workbook_title,
                credentials_file=credentials_file,
                token_file=token_file,
                pdf_output_dir=pdf_output_dir_text,
                session_aliases_text=session_aliases_text,
                grade_lunch_assignments_text=grade_lunch_assignments_text,
                time_blocks_text=time_blocks_text,
            )
            st.session_state["flash_message"] = {
                "kind": "success",
                "text": f"Saved config to {CONFIG_PATH.name}.",
            }
        except ValueError as exc:
            st.session_state["flash_message"] = {
                "kind": "error",
                "text": str(exc),
            }
        st.rerun()

st.subheader("Run Workflow")
st.write("Use the same order each year: validate, generate the draft, make manual edits in Google Sheets, refresh, then generate PDFs.")

run_algorithm = st.selectbox(
    "Draft scheduling algorithm",
    options=("cp-sat", "greedy"),
    index=0,
)
cp_sat_time_limit = st.number_input(
    "CP-SAT time limit (seconds)",
    min_value=1.0,
    max_value=300.0,
    value=10.0,
    step=1.0,
)

button_col1, button_col2 = st.columns(2)
with button_col1:
    if st.button("1. Validate Sources", use_container_width=True):
        with st.spinner("Validating source sheets..."):
            st.session_state["last_action_result"] = run_scheduler_action(
                "Validate Sources",
                command_validate,
                CONFIG_PATH,
            )
        st.rerun()

    if st.button("2. Generate Draft Schedule", use_container_width=True):
        with st.spinner("Generating draft schedule..."):
            st.session_state["last_action_result"] = run_scheduler_action(
                "Generate Draft Schedule",
                command_run,
                CONFIG_PATH,
                algorithm=run_algorithm,
                cp_sat_time_limit=float(cp_sat_time_limit),
            )
        st.rerun()

with button_col2:
    if st.button("4. Refresh Final Reports", use_container_width=True):
        with st.spinner("Refreshing final report tabs..."):
            st.session_state["last_action_result"] = run_scheduler_action(
                "Refresh Final Reports",
                command_refresh_final,
                CONFIG_PATH,
            )
        st.rerun()

    if st.button("5. Generate PDFs", use_container_width=True):
        with st.spinner("Refreshing reports and generating PDFs..."):
            st.session_state["last_action_result"] = run_scheduler_action(
                "Generate PDFs",
                command_printables,
                CONFIG_PATH,
                None,
            )
        st.rerun()

show_last_action_result()

config = load_editable_config()
output_workbook_url = str(config.get("output_workbook_url") or "").strip()

st.subheader("Manual Editing Step")
st.write("Step 3 happens in Google Sheets. After you generate the draft schedule, teachers should edit only `5 Final Schedule (Edit Here)`.")
if output_workbook_url:
    st.markdown(f"[Open output workbook]({output_workbook_url})")
else:
    st.info("The output workbook URL will appear here after the first successful validate or run.")

st.subheader("Generated PDFs")
pdf_output_dir = resolve_local_path(str(config.get("pdf_output_dir") or "."))
if pdf_output_dir and pdf_output_dir.exists():
    pdf_files = sorted(pdf_output_dir.glob("*.pdf"))
    if pdf_files:
        for pdf_file in pdf_files:
            st.write(f"- `{pdf_file.name}`")
    else:
        st.write(f"No PDFs found yet in `{pdf_output_dir}`.")
else:
    st.write("The configured PDF output folder does not exist yet.")
