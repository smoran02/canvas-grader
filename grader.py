import os
import json
import pandas as pd
from canvasapi import Canvas
from openai import OpenAI
from dotenv import load_dotenv
import math

load_dotenv()

COURSE_ID = 3532173
# ASSIGNMENT_ID = 38526540
ASSIGNMENT_ID = 38526543
DRY_RUN = False
MODEL = "gpt-4o-mini"

try:
    canvas = Canvas(os.getenv("CANVAS_API_URL"), os.getenv("CANVAS_TEST_KEY"))
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    course = canvas.get_course(COURSE_ID)
    assignment = course.get_assignment(ASSIGNMENT_ID)
except Exception as e:
    print(f"Initial setup failed: {e}")
    exit()

SYSTEM_PROMPT = """
You are a grader for CPSC120A, an intro programming class at Cal State Fullerton.
You are grading a discussion about "Computer Scientist of the Week".
Your goal primarily is to grade effort. IF THE WORK IS REASONABLY ATTEMPTED, GIVE IT FULL CREDIT.

### RUBRIC

**PART 1: The Message (Max 7 points)**
- **7 pts (Full):** Thoughtful, well-written, meets minimum length (80+ words).
- **2 pts (Partial):** Too short (< 80 words), or VERY poorly written.
- **0 pts (None):** Missing, extremely short, or egregious errors.

**PART 2: The Responses (Max 3 points)**
- **3 pts (Full):** 2+ well-written replies to different students.
- **1 pts (Partial):** Only 1 reply, OR replies contain egregious errors.
- **0 pts (None):** No replies.

### OUTPUT FORMAT
Return strictly valid JSON:
{
    "message_score": <int>,
    "reply_score": <int>,
    "total_score": <int>,
    "feedback": "<string: ONLY IF total_score IS NOT 10, 1 sentence briefly explaining why points were lost.>"
}
"""

print("\nFetching active student enrollments...")
active_student_ids = set()
enrollments = course.get_users(enrollment_status='active', include=['enrollments'])

for user in enrollments:
    is_student = any(e['type'] == 'StudentEnrollment' and e['enrollment_state'] == 'active' for e in user.enrollments)
    if is_student:
        active_student_ids.add(user.id)

print(f"Found {len(active_student_ids)} active student IDs.")

print(f"\nScanning discussion thread for {assignment.name}...")
student_work = {}

try:
    discussion_topic = course.get_discussion_topic(assignment.discussion_topic['id'])
    top_entries = discussion_topic.get_topic_entries()
    
    print("Indexing posts and replies...")
    for entry in top_entries:
        uid = entry.user_id
        if uid not in student_work:
            student_work[uid] = {'post': None, 'replies': []}
        
        if hasattr(entry, 'message'):
            student_work[uid]['post'] = entry.message

        if hasattr(entry, 'recent_replies') and entry.recent_replies:
            for reply in entry.recent_replies:
                try:
                    r_uid = reply['user_id'] if isinstance(reply, dict) else reply.user_id
                    r_msg = reply['message'] if isinstance(reply, dict) else reply.message
                    
                    if r_uid not in student_work:
                        student_work[r_uid] = {'post': None, 'replies': []}
                    student_work[r_uid]['replies'].append(r_msg)
                except AttributeError:
                    continue
except Exception as e:
    print(f"Warning during harvesting: {e}")

print(f"Found work for {len(student_work)} students.")

print(f"\nStarting grading...")
submissions = assignment.get_submissions(include=['user'])

graded_data = []
count = 0

for sub in submissions:
    user_id = sub.user_id

    if user_id not in active_student_ids:
        continue

    if count >= 15:
        break

    if DRY_RUN and count >= 15:
        print("\n[DRY RUN] Stopping early.")
        break

    user_info = getattr(sub, "user", {})
    real_name = user_info.get('name', f"User {user_id}")
    sis_id = user_info.get('sis_user_id', user_info.get('login_id', f"CANVAS_{user_id}"))
    
    work = student_work.get(user_id)

    if not work or (not work['post'] and not work['replies']):
        reason = "No submission found." if not work else "No content found."
        print(f"   ❌ {real_name}: {reason} (0/10)")
        graded_data.append({
            "Student": real_name,
            "SIS ID": sis_id,
            "Total Score": 0,
            "Feedback": reason,
            "Word Count": 0,
            "Status": "Missing",
            "Days Late": 0
        })
        # GRADES POSTED HERE
        # DONT THINK I NEED THIS FOR MISSING SUBMISSIONS
        # if not DRY_RUN:
        #     try:
        #         sub.edit(submission={'late_policy_status': 'missing'},
        #                       comment={'text_comment': reason})
        #     except:
        #         print(f"Could not update Canvas: {e}")
        count += 1
        continue

    first_name = real_name.split()[0] if real_name else "Student"
    
    raw_post = work['post'] or ""
    anon_post = raw_post.replace(real_name, "[NAME]").replace(first_name, "[NAME]")
    
    raw_replies = work['replies']
    anon_replies = [r.replace(real_name, "[NAME]") for r in raw_replies]

    clean_text = raw_post.replace('<p>', ' ').replace('</p>', ' ').replace('<br>', ' ')
    word_count = len(clean_text.split())

    llm_input = f"""
    STUDENT: [ANONYMOUS]
    --- PART 1: MESSAGE ---
    WORD COUNT: {word_count} words (80+ required)
    CONTENT: {anon_post}
    --- PART 2: RESPONSES ---
    COUNT: {len(anon_replies)} replies found (2+ required)
    CONTENT: {json.dumps(anon_replies)}
    """

    print(f"   Grading {real_name}...")

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": llm_input}
            ],
            temperature=0.0,
            response_format={"type": "json_object"}
        )
        result = json.loads(response.choices[0].message.content)

        final_score = result.get("total_score")
        final_feedback = result.get("feedback")
        
        if final_score >= 10:
            final_feedback = ""

        
        is_late = sub.late if hasattr(sub, 'late') else False
        seconds_late = getattr(sub, 'seconds_late', 0)
        days_late = math.ceil(seconds_late / 86400) if seconds_late > 0 else 0
        
        status = "Late" if is_late else "On Time"
        policy_status = "late" if is_late else "none"

        graded_data.append({
            "Student": real_name,
            "SIS ID": sis_id,
            "Total Score": final_score,
            "Feedback": final_feedback,
            "Word Count": word_count,
            "Status": status,
            "Days Late": days_late
        })

        # GRADES POSTED HERE   
        if not DRY_RUN:
            sub.edit(
                submission={'posted_grade': final_score, 
                            'late_policy_status': policy_status,
                            'seconds_late_override': seconds_late
                },
                comment={'text_comment': final_feedback}
            )

        count += 1

    except Exception as e:
        print(f"Error grading {user_id}: {e}")

if graded_data:
    df = pd.DataFrame(graded_data)

    # df = df.sort_values(by="Student", ascending=True)
    filename = "grades_test.csv" if DRY_RUN else f"grades_{ASSIGNMENT_ID}.csv"
    df.to_csv(filename, index=False)
    print(f"\n✅ Success! Grades exported to: {filename}")
    print(df[['Student', 'Total Score', 'Status', 'Feedback']])
else:
    print("No submissions found.")