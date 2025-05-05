#!/usr/bin/env python3
# imagination_day_scheduler.py
#
# • Gives 4th-graders first pick
# • Seats “scarce-choice” students earlier
# • Exports a wait-list when a class fills up
# • Generates CSVs + 8-up PDF index cards
#
# ---------------------------------------------------------------------------

import pandas as pd
from fpdf import FPDF
from pathlib import Path
from collections import defaultdict

# ---------------------------------------------------------------------------
# 0 .  File locations (edit if you like)
ATTENDEES_CSV   = Path("attendees1.csv")
SESSIONS_CSV    = Path("sessions.csv")
ROOMS_CSV       = Path("rooms.csv")

OUT_ATTENDEE_CSV       = Path("attendee_schedule.csv")
OUT_ATTENDEE_LONG_CSV  = Path("attendee_schedule_long.csv")
OUT_SESSION_CSV        = Path("session_attendees.csv")
OUT_WAITLIST_CSV       = Path("wait_lists.csv")
OUT_PDF                = Path("attendee_schedule.pdf")

# ---------------------------------------------------------------------------
# 1 .  Load data

attendees_df = pd.read_csv(ATTENDEES_CSV)
sessions_df  = pd.read_csv(SESSIONS_CSV)

# sessions:  {session: {period1: cap, …}}
sessions = sessions_df.set_index("Session").to_dict(orient="index")

# 1b.  Load room assignments -----------------------------------------------

rooms_df = pd.read_csv(ROOMS_CSV)

# Try to guess the column names once, so the file can be re-used next year
dry_col  = next(c for c in rooms_df.columns if "rain"   not in c.lower() and "room" in c.lower())
rain_col = next((c for c in rooms_df.columns if "rain"  in c.lower()), None)   # optional

ROOM      : dict[str, str] = {}
ROOM_RAIN : dict[str, str] = {}

for _, row in rooms_df.iterrows():
    sess = str(row["Session"]).strip()
    ROOM[sess]      = str(row[dry_col]).strip()  if pd.notna(row[dry_col])  else ""
    ROOM_RAIN[sess] = str(row[rain_col]).strip() if rain_col and pd.notna(row[rain_col]) else ""


# attendee_info:  {name: {"Grade": …, "Teacher": …, "Choices": [s1, …]}}
attendee_info = {}
for _, row in attendees_df.iterrows():
    choices = [
        row[f"Choice{i}"] for i in range(1, 11)
        if pd.notna(row[f"Choice{i}"])
    ]
    # de-duplicate while keeping order
    choices = list(dict.fromkeys(choices))
    attendee_info[row["Name"]] = {
        "Grade"  : row["Grade"],
        "Teacher": row["Teacher"],
        "Choices": choices,
    }

# ---------------------------------------------------------------------------
# 2 .  Settings and helpers

TIME_SLOTS  = ["period1", "period2", "period3",
               "period4", "period5", "period6", "period7"]

TIME_BLOCKS = {
    "period1": "8:45-9:20",  "period2": "9:25-10:00",
    "period3": "10:05-10:40","period4": "10:45-11:20",
    "period5": "11:25-12:00","period6": "12:05-12:40", "period7": "12:45-1:20",
}

GRADE_ORDER = {"4th": 0, "3rd": 1, "2nd": 2, "1st": 3, "K": 4}

# total seats per session (all periods)
SESSION_CAPACITY = {s: sum(p.values()) for s, p in sessions.items()}

def grade_rank(name: str) -> int:
    return GRADE_ORDER.get(attendee_info[name]["Grade"], 99)

def scarcity_score(name: str) -> int:
    """Lower = scarcer wish list (seat count min)."""
    caps = [SESSION_CAPACITY.get(c, 0) for c in attendee_info[name]["Choices"]]
    return min(caps) if caps else 0

# ---------------------------------------------------------------------------
# 3 .  Sort attendees ➀ grade, ➁ scarcity

sorted_attendees = sorted(
    attendee_info.keys(),
    key=lambda n: (grade_rank(n), scarcity_score(n))
)


# ---------------------------------------------------------------------------
# 4 .  Greedy assignment loop + wait-list capture

assignments = {n: {p: None for p in TIME_SLOTS} for n in attendee_info}

wait_lists  = defaultdict(list)      # {session: [(student, pref_rank), …]}

for student in sorted_attendees:
    taken_periods = set()
    prefs = attendee_info[student]["Choices"]

    for rank, session in enumerate(prefs, start=1):
        if session not in sessions:
            continue  # bad session name in CSV; skip silently

        # periods still open for this session AND this student
        open_periods = {
            ts: cap for ts, cap in sessions[session].items()
            if cap > 0 and ts not in taken_periods
        }

        if not open_periods:
            wait_lists[session].append((student, rank))
            continue

        # choose the period with **most** seats left (keeps options for others)
        best_period = max(open_periods, key=open_periods.get)

        # book it
        assignments[student][best_period] = session
        sessions[session][best_period]  -= 1
        taken_periods.add(best_period)

# ---------------------------------------------------------------------------
# 4a.  Diagnostics – gaps & top-3 miss --------------------------------------

gaps = []            # list of (name, empty_periods)
top3_miss = []       # list of names

for name, sched in assignments.items():
    blanks = [p for p, sess in sched.items() if sess is None]
    if blanks:
        gaps.append((name, blanks))

    # Did the student land at least one of their first three choices?
    got_top3 = any(
        (sched[p] in attendee_info[name]["Choices"][:2])
        for p in TIME_SLOTS
        if sched[p]                          # ignore blanks
    )
    if not got_top3:
        top3_miss.append(name)

# Write the two reports
with open("gaps_in_schedule.csv", "w", newline="") as f:
    f.write("Student,Grade,Teacher,BlankPeriods\n")
    for name, blanks in gaps:
        info = attendee_info[name]
        f.write(f"{name},{info['Grade']},{info['Teacher']},"
                f"\"{', '.join(blanks)}\"\n")

with open("top3_miss.csv", "w", newline="") as f:
    f.write("Student,Grade,Teacher\n")
    for name in top3_miss:
        info = attendee_info[name]
        f.write(f"{name},{info['Grade']},{info['Teacher']}\n")

# ---------------------------------------------------------------------------
# 5 .  CSV exports

# 5a.  Per-student compact schedule
with OUT_ATTENDEE_CSV.open("w", newline="") as f:
    header = "Name,Grade,Teacher," + ",".join([f.capitalize() for f in TIME_SLOTS])
    f.write(header + "\n")
    for name, sched in assignments.items():
        row = [
            name,
            attendee_info[name]["Grade"],
            attendee_info[name]["Teacher"],
            *[sched[p] or "" for p in TIME_SLOTS],
        ]
        f.write(",".join(row) + "\n")

# 5b.  Per-student long form
with OUT_ATTENDEE_LONG_CSV.open("w", newline="") as f:
    for name, sched in assignments.items():
        f.write(f"{name}\n{attendee_info[name]['Grade']},"
                f"{attendee_info[name]['Teacher']}\n\n")
        f.write("Period,Session\n")
        for p in TIME_SLOTS:
            f.write(f"{p},{sched[p] or ''}\n")
        f.write("\n")

# 5c.  Per-session rosters
with OUT_SESSION_CSV.open("w", newline="") as f:
    f.write("Session,Period,Students\n")
    for session in sessions_df["Session"]:
        for p in TIME_SLOTS:
            kids = [s for s, sc in assignments.items() if sc[p] == session]
            f.write(f"{session},{p},\"{'; '.join(kids)}\"\n")

# 5d.  Wait-lists
with OUT_WAITLIST_CSV.open("w", newline="") as f:
    f.write("Session,Student,PreferenceRank\n")
    for session, ppl in wait_lists.items():
        for name, rank in ppl:
            f.write(f"{session},{name},{rank}\n")

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 6 .  Avery 5388 / 5889 index cards  (2 × 4 grid on US-Letter)  -------------

from fpdf.enums import XPos, YPos

# -- Card / sheet geometry (in mm) -----------------------------------------
CARD_W      = 100          # 3.94"  safe printable width
CARD_H      = 64           # 2.52"  safe printable height
LEFT_MARGIN = 7            # left edge to first card
TOP_MARGIN  = 10           # top edge to first card
COL_GAP     = 6            # gutter between the two columns

# -- Column layout inside the table ----------------------------------------
COLS = [("Time", 21), ("Session", 42), ("Room", 17), ("Rain", 17)]

class AveryIndexCard(FPDF):
    def draw_card(self, *, name, grade, teacher, sched, x, y):
        x0, y0 = x, y          # remember left edge

        # ------------------------------------------------ Header ----------
        self.set_xy(x0, y0)
        self.set_font("Helvetica", "B", 14)
        self.multi_cell(CARD_W, 7, name)   # auto line-feed
        self.set_x(x0)

        self.set_font("Helvetica", "", 11)
        self.cell(0, 5, f"Grade: {grade}", ln=1)
        self.set_x(x0)
        self.cell(0, 5, f"Teacher: {teacher}", ln=1)
        self.ln(1)                       # tiny spacer
        self.set_x(x0)

        # ---------------------------------------------- Table header ------
        self.set_font("Helvetica", "B", 8)
        for label, w in COLS:
            self.cell(w, 5, label, border=1, align="C")
        self.ln(5)
        self.set_x(x0)

        # ---------------------------------------------- Table rows --------
        self.set_font("Helvetica", "", 8)
        for p in TIME_SLOTS:
            session = sched[p] or ""

            # Time
            self.cell(COLS[0][1], 5, TIME_BLOCKS[p], border=1)

            # Session (may wrap)
            x_before, y_before = self.get_x(), self.get_y()
            self.multi_cell(
                COLS[1][1], 5, session,
                border=1, align="L"
            )
            # multi_cell moved cursor — realign for Room/Rain
            self.set_xy(x_before + COLS[1][1], y_before)

            # Room / Rain
            self.cell(COLS[2][1], 5, ROOM.get(session, ""),      border=1)
            self.cell(COLS[3][1], 5, ROOM_RAIN.get(session, ""), border=1)

            self.ln(5)            # move to next row
            self.set_x(x0)        # …but keep inside this card

        # Optional outline for test prints
        # self.rect(x0, y0, CARD_W, CARD_H)

# -- Build the sheet --------------------------------------------------------
pdf = AveryIndexCard(orientation="P", unit="mm", format="Letter")
pdf.set_auto_page_break(False)   # manual grid; don’t let FPDF break pages

for idx, (name, sched) in enumerate(assignments.items()):
    # new sheet every 8 cards
    if idx % 8 == 0:
        pdf.add_page()

    row = idx % 4                      # 0-3 in the current sheet
    col = (idx // 4) % 2               # 0 or 1

    x = LEFT_MARGIN + col * (CARD_W + COL_GAP)
    y = TOP_MARGIN  + row * CARD_H

    pdf.draw_card(
        name=name,
        grade=attendee_info[name]["Grade"],
        teacher=attendee_info[name]["Teacher"],
        sched=sched,
        x=x,
        y=y
    )

pdf.output(str(OUT_PDF))



print("✔ Scheduling complete:")
print(f"  • {OUT_ATTENDEE_CSV.name}")
print(f"  • {OUT_ATTENDEE_LONG_CSV.name}")
print(f"  • {OUT_SESSION_CSV.name}")
print(f"  • {OUT_WAITLIST_CSV.name}")
print(f"  • {OUT_PDF.name}")
