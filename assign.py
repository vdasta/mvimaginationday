import pandas as pd
from fpdf import FPDF

def lt(s):
    return bytes(s, 'utf-8')
    
# Load the attendees and sessions data from CSV files
attendees_df = pd.read_csv("attendees.csv")
sessions_df = pd.read_csv("sessions.csv")

# Convert the attendees and sessions data to dictionaries
#attendees = attendees_df.set_index("Name").to_dict(orient="index")
#attendee_info = {}
#for attendee in attendees:
#    attendee_info[attendee]["Grade"] = attendees_df.loc[attendees_df["Name"] == attendee, "Grade"].iloc[0]
#    attendee_info[attendee]["Teacher"] = attendees_df.loc[attendees_df["Name"] == attendee, "Teacher"].iloc[0]
#    attendee_info[attendee]["Choices"] = [        attendees_df.loc[attendees_df["Name"] == attendee, f"Choice{i}"].iloc[0]
#        for i in range(1, 11)
#    ]

# Convert the attendees data to a dictionary
attendee_info = {}
for index, row in attendees_df.iterrows():
    attendee_name = row["Name"]
    attendee_info[attendee_name] = {
        "Grade": row["Grade"],
        "Teacher": row["Teacher"],
        "Choices": [row["Choice1"], row["Choice2"], row["Choice3"], row["Choice4"], row["Choice5"], row["Choice6"], row["Choice7"], row["Choice8"], row["Choice9"], row["Choice10"], row["Choice11"]]
    }

#    HACK ALERT!!!!!!
room_assignment = {
    "Basketball (1st/2nd)":"Gym",
    "Basketball (3rd/4th)":"Gym",
    "Be a Nurse":"Room 109",
    "Bootcamp":"Back Door",
    "Chalk the Walk":"Back Door",
    "Cheerleading":"Back Door",
    "Circus Fun":"Art Room",
    "Crochet Coasters":"Room 110",
    "Doodle Bots":"Room 203",
    "Fancy Fingers":"Room 105",
    "Fantastic Flight":"MPR",
    "Football":"Back Door",
    "Garden":"Outdoor Classroom",
    "Golf":"Back Door",
    "Kindness Rocks":"Room 106",
    "Lunch1":"Homeroom",
    "Lunch2":"Homeroom",
    "Martial Arts":"Room 206",
    "Milk Fireworks (1st/2nd)":"Room 505",
    "Pawsitive Pals":"Room 102",
    "Photography":"Room 103",
    "Photos by the Sun":"Back Door",
    "Playing with the Band":"Music Room",
    "Police Officer":"Room 109",
    "Re-Imagining Merch":"Room 107",
    "Right on the Button":"Room 104",
    "Rocket Science":"Room 505",
    "Sew Creative":"Room 101",
    "Shrinky Dinks":"Room 205",
    "Soccer":"Back Door",
    "Spanish":"Room 208",
    "Stand Up Comedy":"Room 201",
    "Strawberry DNA":"Room 202",
    "SweatKids Fitness":"Room 110",
    "The Voice":"Room 108",
    "Tie Dye":"Yellow Pod",
    "Traveling World of Reptiles":"Art Room",
    "Water Relay Races":"Back Door",
    "Woodworking":"Room 207",
    "None":"None",
    "Catapult":""
    }

room_alt_assignment = {
    "Basketball (1st/2nd)":"Gym",
    "Basketball (3rd/4th)":"Gym",
    "Be a Nurse":"",
    "Bootcamp":"Blue Pod",
    "Chalk the Walk":"Hall near MPR",
    "Cheerleading":"Stage",
    "Circus Fun":"",
    "Crochet Coasters":"209",
    "Doodle Bots":"",
    "Fancy Fingers":"111",
    "Fantastic Flight":"",
    "Football":"110",
    "Garden":"Under awning in O.C.",
    "Golf":"201",
    "Kindness Rocks":"",
    "Lunch1":"",
    "Lunch2":"",
    "Martial Arts":"",
    "Milk Fireworks (1st/2nd)":"",
    "Pawsitive Pals":"",
    "Photography":"",
    "Photos by the Sun":"110",
    "Playing with the Band":"",
    "Police Officer":"",
    "Re-Imagining Merch":"112",
    "Right on the Button":"",
    "Rocket Science":"",
    "Sew Creative":"",
    "Shrinky Dinks":"",
    "Soccer":"Green Pod",
    "Spanish":"",
    "Stand Up Comedy":"301",
    "Strawberry DNA":"",
    "SweatKids Fitness":"",
    "The Voice":"",
    "Tie Dye":"",
    "Traveling World of Reptiles":"",
    "Water Relay Races":"107",
    "Woodworking":"",
    "None":"None",
    "Catapult":""
    }


sessions = sessions_df.set_index("Session").to_dict(orient="index")

# Define a list of the 6 time slots
time_slots = ["period1", "period2", "period3", "period4", "period5", "period6"]
time_blocks = {"period1":"9:05-9:40", "period2":"9:50-10:25", "period3":"10:35-11:10", "period4":"11:20-11:55", "period5":"12:05-12:40", "period6":"12:50-1:25"}

# Initialize a dictionary to keep track of which sessions each attendee is assigned to
assignments = {attendee: {slot: None for slot in time_slots} for attendee in attendee_info}

# Sort the attendees in ascending order based on the number of available spots for their preferred sessions
#sorted_attendees = sorted(attendees.keys(), key=lambda attendee: sum([min([sessions.get(s, {}).get(slot, 0) for slot in attendees[attendee][t]]) for t in attendees[attendee] for s in sessions]))
#sorted_attendees = sorted(attendee_info.keys(), key=lambda attendee: (attendee_info[attendee]["Grade"] == "4th", sum([min([sessions.get(s, {}).get(slot, 0) for slot in attendee_info[attendee][t]["Choices"]]) for t in attendee_info[attendee] for s in sessions])))
sorted_attendees = sorted(
    attendee_info.keys(),
    key=lambda attendee: (
        attendee_info[attendee]["Grade"] == "4th",
        sum([
            min([sessions.get(s, {}).get(slot, 0) for slot in attendee_info[attendee][t]]) 
            for s in sessions for t in attendee_info[attendee] if t == "Choices"
        ])
    )
)

#print(sessions)
# Assign each attendee to their highest-ranked available time slot for each session
for attendee in sorted_attendees:
    print(f"Processing attendee: {attendee}")
    preferred_sessions = attendee_info[attendee]["Choices"]
#    print(f"Preferred Sessions: {preferred_sessions}")
    assigned_slots = []
    for session in preferred_sessions:
 #       print(f"  Processing session: {session}")
        time_slot_availabilities = {}
        for time in sessions[session]:
  #          print(f"    Processing time: {time}")
            if time not in assigned_slots and sessions[session][time] > 0:
                time_slot_availabilities[time] = sessions[session][time]
        if time_slot_availabilities:
            time_slot = max(time_slot_availabilities, key=time_slot_availabilities.get)
            assignments[attendee][time_slot] = session
            sessions[session][time_slot] -= 1
 #           print(f"      Assigned {attendee} to {time_slot} for session {session}")
            assigned_slots.append(time_slot)



# Verify that each session has the correct number of attendees for each time slot
session_attendees = {session: {time_slot: [] for time_slot in time_slots} for session in sessions}
for attendee in assignments:
    for time_slot, session in assignments[attendee].items():
        if session is not None:
            session_attendees[session][time_slot].append(attendee)

#print(sessions)
# Write the attendee schedules to a CSV file
with open("attendee_schedule.csv", "w") as f:
   f.write("Name,Grade,Teacher,Period 1,Period 2,Period 3,Period 4,Period 5,Period 6\n")
   for attendee, schedule in   assignments.items():
        print(attendee)
        f.write(f"{attendee},{attendee_info[attendee]['Grade']},{attendee_info[attendee]['Teacher']},")
        f.write(f"{','.join([schedule[time_slot] or '' for time_slot in time_slots])}\n")

with open("attendee_schedule_long.csv", "w") as f: 
 for attendee, schedule in assignments.items():
        f.write(f"{attendee}\n{attendee_info[attendee]['Grade']},{attendee_info[attendee]['Teacher']}\n")
        f.write(f"\n")
        f.write(f"Period,Session,Room,Rain Location\n")
        for time_slot in time_slots:
            f.write(f"{time_slot},{schedule[time_slot] or ''}\n")
        f.write(f"\n")


# Write the session attendee lists to a CSV file
with open("session_attendees.csv", "w") as f:
    for session, schedule in session_attendees.items():
        f.write(f"{session}\n")
        for time_slot, attendees in schedule.items():
            f.write(f"{time_slot}, {', '.join(attendees)}\n")
        f.write("\n")

# NOTE CARDS PDF:
from fpdf import FPDF

class AveryIndexCard(FPDF):
    
    def __init__(self, orientation='P', unit='mm', format='Letter', doc_encoding='UTF-8'):
        super().__init__(orientation, unit, format)
        self.encoding = doc_encoding
        self.core_fonts_encoding = doc_encoding
    
    def card(self, name, grade, teacher, schedule, x_pos):
        self.set_xy(x_pos, self.y)
        self.set_font('Arial', 'B', 16)
        self.cell(60, 10, name)
        self.ln(5)
        self.set_x(x_pos)
        self.set_font('Arial', 'B', 12)
        self.cell(60, 10, f"Grade: {grade}")
        self.ln(5)
        self.set_x(x_pos)
        self.cell(60, 10, f"Teacher: {teacher}")
        self.ln(10)
        self.set_x(x_pos)
        self.set_font('Arial', 'B', 8)
        self.cell(20, 5, f"Time", align="C")
        self.cell(30, 5, f"Session", align="C")
        self.cell(15, 5, f"Room", align="C")
        self.cell(15, 5, f"Rain Room", align="C")
        self.ln(5)
        self.set_x(x_pos)
        self.set_font('Arial', '', 8)
        for time_slot in schedule:
            self.cell(20, 5, f"{time_blocks[time_slot]}", border = 1)
            self.cell(30, 5, f"{schedule[time_slot]}", border = 1)
            self.cell(15, 5, f"{room_assignment.get(schedule[time_slot],0)}", border = 1)
            self.cell(15, 5, f"{room_alt_assignment.get(schedule[time_slot],0)}", border = 1)
            self.ln(5)
            self.set_x(x_pos)


pdf = AveryIndexCard('P', 'mm', 'Letter', doc_encoding='UTF-8')

# Set margins and column width for 8 cards per page
left_margin = 10
right_margin = 216 - 10 - 108 # Page width - left margin - card width
column_width = 100

for i, (attendee, schedule) in enumerate(assignments.items()):
    # Calculate x position for current card based on current column
    col = (i // 4) % 2
    x_pos = left_margin + col * column_width
    
    # Add a new page if necessary (every 8th card)
    if i % 8 == 0:
        pdf.add_page()
    
    # Calculate y position based on current row
    row = i % 4
    y_pos = 10 + row * 60
    pdf.set_y(y_pos)
    
    # Print current card
    pdf.card(attendee, attendee_info[attendee]['Grade'], attendee_info[attendee]['Teacher'], schedule, x_pos)
    
    # Set position for next card
 #   pdf.set_xy(left_margin, y_pos)

pdf.output('attendee_schedule.pdf', 'F')
