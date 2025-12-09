import os
from canvasapi import Canvas
from dotenv import load_dotenv

load_dotenv()

API_URL = os.getenv("CANVAS_API_URL")
API_KEY = os.getenv("CANVAS_TEST_KEY")
COURSE_ID = 3532173

canvas = Canvas(API_URL, API_KEY)
course = canvas.get_course(COURSE_ID)

print(f"--- Assignments for {course.name} ---\n")

assignments = course.get_assignments()

for assignment in assignments:
    if assignment.published:
        is_discussion = "discussion_topic" in assignment.submission_types
        type_label = "[DISCUSSION]" if is_discussion else "[ASSIGNMENT]"

        print(f"{type_label} ID: {assignment.id} | Name: {assignment.name}")