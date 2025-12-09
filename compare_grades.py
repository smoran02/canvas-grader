import pandas as pd
from canvasapi import Canvas
import os
from dotenv import load_dotenv

load_dotenv()
API_URL = os.getenv("CANVAS_API_URL")
API_KEY = os.getenv("CANVAS_TEST_KEY")

COURSE_ID = 3532173
ASSIGNMENT_ID = 38526540
LOCAL_CSV = "grades_38526540.csv"
OUTPUT_CSV = "final_comparison.csv"

def get_val(obj, key, default='MISSING'):
    """Helper to safely get values from either a dict or an object"""
    if isinstance(obj, dict):
        return obj.get(key, default)
    else:
        return getattr(obj, key, default)

def main():
    print(f"📂 Loading local grades from {LOCAL_CSV}...")
    try:
        local_df = pd.read_csv(LOCAL_CSV)
        local_df['SIS ID'] = local_df['SIS ID'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()

        local_data = local_df.set_index('SIS ID')[['Total Score']].to_dict('index')
        
        print(f"   Loaded {len(local_data)} rows from CSV.")
    except Exception as e:
        print(f"❌ Error loading local CSV: {e}")
        return

    print("Fetching grades from Canvas...")
    try:
        canvas = Canvas(API_URL, API_KEY)
        course = canvas.get_course(COURSE_ID)
        assignment = course.get_assignment(ASSIGNMENT_ID)
        submissions = assignment.get_submissions(include=['user'])
    except Exception as e:
        print(f"❌ Canvas Error: {e}")
        return

    # 3. Compare
    results = []
    matched_count = 0
    
    print("🔍 Comparing...")

    for sub in submissions:
        if not hasattr(sub, 'user'):
            continue
        
        user_data = sub.user
        
        canvas_sis_id = str(get_val(user_data, 'sis_user_id')).strip()
        student_name = get_val(user_data, 'name')
        
        if canvas_sis_id == 'MISSING' or canvas_sis_id == 'None':
            continue

        canvas_score = sub.score if sub.score is not None else 0.0
        
        if canvas_sis_id in local_data:
            matched_count += 1
            local_score = local_data[canvas_sis_id]['Total Score']
            
            try:
                diff = float(canvas_score) - float(local_score)
            except:
                diff = "Error"
                
            status = "MATCH" if diff == 0 else "MISMATCH"
            
            results.append({
                "Student Name": student_name,
                "SIS ID": canvas_sis_id,
                "Local Grade": local_score,
                "Canvas Grade": canvas_score,
                "Difference": diff,
                "Status": status
            })
        else:
             results.append({
                "Student Name": student_name,
                "SIS ID": canvas_sis_id,
                "Local Grade": "N/A",
                "Canvas Grade": canvas_score,
                "Difference": "N/A",
                "Status": "NOT IN CSV"
            })

    if results:
        final_df = pd.DataFrame(results)
        
        final_df.to_csv(OUTPUT_CSV, index=False)
        print(f"\n✅ Comparison complete.")
        print(f"   Matched {matched_count} students.")
        print(f"   Detailed report saved to: {OUTPUT_CSV}")
        
        mismatches = final_df[final_df['Status'] == 'MISMATCH']
        if not mismatches.empty:
            print(f"\n⚠️ Found {len(mismatches)} mismatches:")
            print(mismatches[['Student Name', 'Local Grade', 'Canvas Grade', 'Difference']].to_string(index=False))
        else:
            print("\n🎉 No grade mismatches found among matched students.")
            
    else:
        print("❌ No comparisons generated. Check if your CSV 'SIS ID' column matches Canvas SIS IDs.")

if __name__ == "__main__":
    main()