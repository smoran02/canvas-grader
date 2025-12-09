import os
import json
import pandas as pd
from canvasapi import Canvas
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

COURSE_ID = 3532173
ASSIGNMENT_ID = 38526540
DRY_RUN = False
MODEL = "gpt-4o-mini"

canvas = Canvas(os.getenv("CANVAS_API_URL"), os.getenv("CANVAS_TEST_KEY"))
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
course = canvas.get_course(COURSE_ID)
assignment = course.get_assignment(ASSIGNMENT_ID)

SYSTEM_PROMPT = """
You are a grader for CPSC120A, an intro programming class at Cal State Fullerton.
You are grading a discussion about "Computer Scientist of the Week".
Your goal primarily is to grade effort. IF THE WORK IS REASONABLY ATTEMPTED, GIVE IT FULL CREDIT.

### RUBRIC

**PART 1: The Message (Max 7 points)**
- **7 pts (Full):** Thoughtful, well-written, meets minimum length (90+ words).
- **2 pts (Partial):** Too short (< 90 words), or VERY poorly written.
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
    if DRY_RUN and count >= 15:
        print("\n[DRY RUN] Stopping early.")
        break

    real_name = sub.user['name'] if hasattr(sub, 'user') else f"User {sub.user_id}"
    user_id = sub.user_id
    
    sis_id = getattr(sub, 'user', {}).get('sis_user_id', None)
    if not sis_id:
        sis_id = getattr(sub, 'user', {}).get('login_id', f"CANVAS_{user_id}")

    if user_id not in student_work:
        print(f"   ❌ {real_name}: No submission found (0/10)")
        graded_data.append({
            "Student": real_name,
            "SIS ID": sis_id,
            "Total Score": 0,
            "Feedback": "No submission found."
        })
        if not DRY_RUN:
            try:
                sub.edit(submission={'posted_grade': 0}, comment={'text_comment': "No submission found."})
            except: pass
        count += 1
        continue
    
    work = student_work[user_id]
    if not work['post'] and not work['replies']:
        print(f"   ❌ {real_name}: Empty submission (0/10)")
        graded_data.append({
            "Student": real_name,
            "SIS ID": sis_id,
            "Total Score": 0,
            "Feedback": "No content found."
        })
        if not DRY_RUN:
            try:
                sub.edit(submission={'posted_grade': 0}, comment={'text_comment': "No content found."})
            except: pass
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
    WORD COUNT: {word_count} words (90+ required)
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

        graded_data.append({
            "Student": real_name,
            "SIS ID": sis_id,
            "Total Score": final_score,
            "Feedback": final_feedback,
            "Word Count": word_count
        })

        # DO NOT DO THIS
        # THIS ACTUALLY CHANGES THE GRADES   
        # if not DRY_RUN:
        #     sub.edit(
        #         submission={'posted_grade': final_score}, 
        #         comment={'text_comment': final_feedback}
        #     )

        count += 1

    except Exception as e:
        print(f"Error grading {user_id}: {e}")

if graded_data:
    df = pd.DataFrame(graded_data)
    
    df = df.sort_values(by="Total Score", ascending=False)
    
    if df['SIS ID'].astype(str).str.contains("CANVAS_").all() == False:
        print("\nDeduplicating by Student CWID...")
        df = df.drop_duplicates(subset=["SIS ID"], keep="first")
    else:
        print("\nDeduplicating by Student Name...")
        df = df.drop_duplicates(subset=["Student"], keep="first")

    df = df.sort_values(by="Student", ascending=True)
    filename = "grades_test.csv" if DRY_RUN else f"grades_{ASSIGNMENT_ID}.csv"
    df.to_csv(filename, index=False)
    print(f"\n✅ Success! Grades exported to: {filename}")
    print(df[['Student', 'Total Score', 'Feedback']])
else:
    print("No submissions found.")