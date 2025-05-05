#!/usr/bin/env python3
# printables_from_schedule.py
#
# Build printable PDFs from a FINAL, manually-edited attendee_schedule.csv
# -------------------------------------------------------------------------

import re
from itertools import zip_longest
from pathlib import Path

import pandas as pd
from fpdf import FPDF
from fpdf.enums import XPos, YPos

# ───────────────────────────── File locations ─────────────────────────────
SCHEDULE_CSV = Path("attendee_schedule.csv")   # edited master schedule
ROOMS_CSV    = Path("rooms.csv")               # session → room mapping

OUT_CARDS_PDF  = Path("attendee_schedule.pdf")  # 8-up cards
OUT_ROSTER_PDF = Path("class_rosters.pdf")      # instructor rosters

# ─────────────────────── 1.  Load attendee schedule ───────────────────────
sched_df = pd.read_csv(SCHEDULE_CSV).rename(columns=lambda c: c.strip())

# Detect period columns (Period1 / Period 1 / period7 …)
period_regex = re.compile(r"period\s*(\d+)", flags=re.I)
period_col = {int(m.group(1)): c
              for c in sched_df.columns
              for m in [period_regex.match(c.replace(" ", ""))] if m}

if not period_col:
    raise ValueError("No Period* columns found in attendee_schedule.csv")

NUM_PERIODS = max(period_col)
TIME_SLOTS  = [f"period{i}" for i in range(1, NUM_PERIODS + 1)]

# Default bell schedule – adjust if the school uses different times
default_times = {
    1: "8:45-9:20", 2: "9:25-10:00", 3: "10:05-10:40",
    4: "10:45-11:20", 5: "11:25-12:00", 6: "12:05-12:40",
    7: "12:45-1:20",
}
TIME_BLOCKS = {f"period{i}": default_times.get(i, f"P{i}") for i in range(1, NUM_PERIODS + 1)}

# Build assignments + attendee info dictionaries
assignments = {
    row["Name"]: {
        f"period{i}": row[period_col[i]] if pd.notna(row[period_col[i]]) else ""
        for i in range(1, NUM_PERIODS + 1)
    }
    for _, row in sched_df.iterrows()
}
attendee_info = {
    row["Name"]: {"Grade": row["Grade"], "Teacher": row["Teacher"]}
    for _, row in sched_df.iterrows()
}

# ───────────────────────── 2.  Load room data ─────────────────────────────
rooms_df = pd.read_csv(ROOMS_CSV).rename(columns=lambda c: c.strip())
dry_col  = next(c for c in rooms_df if "room" in c.lower() and "rain" not in c.lower())
rain_col = next((c for c in rooms_df if "rain" in c.lower()), None)

ROOM      = dict(zip(rooms_df["Session"], rooms_df[dry_col].fillna("").astype(str)))
ROOM_RAIN = dict(zip(rooms_df["Session"], rooms_df[rain_col].fillna("").astype(str))) if rain_col else {}

# ───────────────────────── 3.  8-up index cards ───────────────────────────
CARD_W, CARD_H   = 100, 64           # mm (fits Avery 5388/5889 safe area)
LEFT_MARGIN      = 7
TOP_MARGIN       = 10
COL_GAP          = 6
COLS             = [("Time", 21), ("Session", 42), ("Room", 17), ("Rain", 17)]

class CardsPDF(FPDF):
    def card(self, *, x0, y0, name, grade, teacher, schedule):
        self.set_xy(x0, y0)
        # Header
        self.set_font("Helvetica", "B", 14)
        self.multi_cell(CARD_W, 7, name)
        self.set_x(x0)
        self.set_font("Helvetica", "", 11)
        self.cell(0, 5, f"Grade: {grade}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_x(x0)
        self.cell(0, 5, f"Teacher: {teacher}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(1); self.set_x(x0)

        # Table header
        self.set_font("Helvetica", "B", 8)
        for lbl, w in COLS:
            self.cell(w, 5, lbl, border=1, align="C")
        self.ln(5); self.set_x(x0)

        # Rows
        self.set_font("Helvetica", "", 8)
        for p in TIME_SLOTS:
            sess = schedule[p]
            self.cell(COLS[0][1], 5, TIME_BLOCKS[p], border=1)

            x_before, y_before = self.get_x(), self.get_y()
            self.multi_cell(COLS[1][1], 5, sess, border=1)
            self.set_xy(x_before + COLS[1][1], y_before)

            self.cell(COLS[2][1], 5, ROOM.get(sess, ""),      border=1)
            self.cell(COLS[3][1], 5, ROOM_RAIN.get(sess, ""), border=1)
            self.ln(5); self.set_x(x0)
        # Optional outline:
        # self.rect(x0, y0, CARD_W, CARD_H)

cards_pdf = CardsPDF(orientation="P", unit="mm", format="Letter")
cards_pdf.set_auto_page_break(False)

for idx, (name, sched) in enumerate(assignments.items()):
    if idx % 8 == 0:
        cards_pdf.add_page()
    row = idx % 4
    col = (idx // 4) % 2
    x = LEFT_MARGIN + col * (CARD_W + COL_GAP)
    y = TOP_MARGIN  + row * CARD_H
    cards_pdf.card(
        x0=x, y0=y,
        name=name,
        grade=attendee_info[name]["Grade"],
        teacher=attendee_info[name]["Teacher"],
        schedule=sched
    )

cards_pdf.output(str(OUT_CARDS_PDF))

# ─────────────────────── 4.  Instructor rosters PDF ───────────────────────
class RosterPDF(FPDF):
    def header(self):  # override default header
        pass

roster_pdf = RosterPDF(orientation="L", unit="mm", format="Letter")
col_w = 37 if NUM_PERIODS == 7 else 44  # 7×37=259mm ; 6×44=264mm (fits 279mm)

# Build {session: {period: [names]}}
session_roster = {}
for name, schedule in assignments.items():
    for p, sess in schedule.items():
        if not sess:
            continue
        session_roster.setdefault(sess, {ts: [] for ts in TIME_SLOTS})
        session_roster[sess][p].append(name)

for sess, p_dict in session_roster.items():
    roster_pdf.add_page()
    roster_pdf.set_font("Helvetica", "B", 18)
    roster_pdf.cell(0, 10, sess, align="C", ln=1)

    roster_pdf.set_font("Helvetica", "", 11)
    roster_pdf.cell(0, 6, f"Location: {ROOM.get(sess, '')}", ln=1)
    roster_pdf.cell(0, 6, f"Rain Location: {ROOM_RAIN.get(sess, '')}", ln=1)
    roster_pdf.ln(3)

    # Column headers
    roster_pdf.set_font("Helvetica", "B", 8)
    for p in TIME_SLOTS:
        roster_pdf.cell(col_w, 6, TIME_BLOCKS[p], border=1, align="C")
    roster_pdf.ln(6)

    # Data rows – zip_longest to pad uneven columns
    roster_pdf.set_font("Helvetica", "", 8)
    rows = zip_longest(*(p_dict[p] for p in TIME_SLOTS), fillvalue="")
    for row_vals in rows:
        for val in row_vals:
            roster_pdf.cell(col_w, 5, val, border=1)
        roster_pdf.ln(5)

roster_pdf.output(str(OUT_ROSTER_PDF))

print("Generated:")
print(f" • {OUT_CARDS_PDF}")
print(f" • {OUT_ROSTER_PDF}")
