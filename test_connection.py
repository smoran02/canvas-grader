import os
from canvasapi import Canvas
from dotenv import load_dotenv

load_dotenv()

API_URL = os.getenv("CANVAS_API_URL")
API_KEY = os.getenv("CANVAS_API_KEY")

canvas = Canvas(API_URL, API_KEY)

print("Connecting to CSUF Canvas...")
user = canvas.get_current_user()
print(f"Logged in as: {user.name}")

print("\n--- My Courses ---")
courses = user.get_courses(enrollment_status="active")

for course in courses:
    try:
        print(f"ID: {course.id} | Name: {course.name}")
    except AttributeError:
        continue

