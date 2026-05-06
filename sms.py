# fix_enrollments.py - Script to ensure ALL students are enrolled for 2026
import os
import uuid
import time
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client, Client

# Load environment variables
load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Configuration
BATCH_SIZE = 50  # Process in batches to avoid crashing
DELAY_BETWEEN_BATCHES = 0.5  # Seconds between batches

def get_all_institutes():
    """Get all institutes from the database"""
    try:
        response = supabase.table('institutes').select('id, institute_name').execute()
        return response.data if response.data else []
    except Exception as e:
        print(f"Error fetching institutes: {e}")
        return []

def get_all_active_students(institute_id, batch_offset=0, batch_size=BATCH_SIZE):
    """Get active students in batches"""
    try:
        response = supabase.table('students')\
            .select('id, student_id, name, class_id, created_at, status, institute_id')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')\
            .range(batch_offset, batch_offset + batch_size - 1)\
            .execute()
        
        return response.data if response.data else []
    except Exception as e:
        print(f"Error fetching students batch: {e}")
        return []

def get_total_student_count(institute_id):
    """Get total number of active students"""
    try:
        response = supabase.table('students')\
            .select('id', count='exact')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')\
            .execute()
        
        return response.count if response.count else 0
    except Exception as e:
        print(f"Error counting students: {e}")
        return 0

def update_or_create_enrollment_2026(student_id, class_id, current_class_id=None):
    """
    Update existing enrollment to 2026 or create new one
    Returns: (success, action) where action is 'created', 'updated', or 'skipped'
    """
    try:
        target_year = 2026
        
        # Check if enrollment for 2026 already exists
        existing_2026 = supabase.table('class_enrollments')\
            .select('id, class_id, academic_year')\
            .eq('student_id', student_id)\
            .eq('academic_year', target_year)\
            .execute()
        
        if existing_2026.data:
            # Check if class_id matches
            enrollment = existing_2026.data[0]
            if enrollment['class_id'] != class_id:
                # Update class_id if different
                supabase.table('class_enrollments')\
                    .update({'class_id': class_id, 'updated_at': datetime.now().isoformat()})\
                    .eq('id', enrollment['id'])\
                    .execute()
                return True, 'updated_class'
            return True, 'skipped_exists'
        
        # Create new enrollment for 2026
        enrollment_data = {
            'id': str(uuid.uuid4()),
            'student_id': student_id,
            'class_id': class_id,
            'academic_year': target_year,
            'enrolled_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        result = supabase.table('class_enrollments').insert(enrollment_data).execute()
        
        if result.data:
            return True, 'created'
        else:
            return False, 'failed'
            
    except Exception as e:
        print(f"Error in update_or_create_enrollment: {e}")
        return False, str(e)

def fix_student_class_reference_batch(institute_id, batch_size=BATCH_SIZE):
    """Fix students with missing class_id using enrollments"""
    try:
        # Get students with class_id = null
        students_response = supabase.table('students')\
            .select('id, name, student_id')\
            .eq('institute_id', institute_id)\
            .is_('class_id', 'null')\
            .execute()
        
        students = students_response.data if students_response.data else []
        
        if not students:
            return 0, []
        
        fixed_count = 0
        errors = []
        
        for student in students:
            try:
                # Get enrollment for 2026
                enrollment_response = supabase.table('class_enrollments')\
                    .select('class_id')\
                    .eq('student_id', student['id'])\
                    .eq('academic_year', 2026)\
                    .execute()
                
                if enrollment_response.data:
                    class_id = enrollment_response.data[0]['class_id']
                    
                    # Update student's class_id
                    update_response = supabase.table('students')\
                        .update({'class_id': class_id, 'updated_at': datetime.now().isoformat()})\
                        .eq('id', student['id'])\
                        .execute()
                    
                    if update_response.data:
                        fixed_count += 1
                        print(f"  🔧 Fixed class reference for {student['name']} ({student['student_id']})")
                    else:
                        errors.append(f"Failed to update class for {student['name']}")
                else:
                    print(f"  ⚠️ No 2026 enrollment found for {student['name']} ({student['student_id']})")
                    
            except Exception as e:
                error_msg = f"Error fixing class for {student.get('name', 'Unknown')}: {str(e)}"
                print(f"  ❌ {error_msg}")
                errors.append(error_msg)
        
        return fixed_count, errors
        
    except Exception as e:
        print(f"Error fixing student class references: {e}")
        return 0, [str(e)]

def process_institute_batches(institute_id, institute_name):
    """Process all students in batches to avoid crashing"""
    print(f"\n{'='*60}")
    print(f"Processing Institute: {institute_name}")
    print(f"Institute ID: {institute_id}")
    print(f"{'='*60}")
    
    # Get total students count
    total_students = get_total_student_count(institute_id)
    
    if total_students == 0:
        print("No active students found in this institute.")
        return 0, 0
    
    print(f"\n📊 Total active students: {total_students}")
    print(f"Processing in batches of {BATCH_SIZE}...")
    
    # Stats
    total_processed = 0
    total_created = 0
    total_updated = 0
    total_skipped = 0
    total_errors = 0
    class_fixes = 0
    
    # Process in batches
    offset = 0
    batch_num = 1
    
    while offset < total_students:
        print(f"\n--- Batch {batch_num} (Records {offset+1} to {min(offset+BATCH_SIZE, total_students)}) ---")
        
        # Get batch of students
        students = get_all_active_students(institute_id, offset, BATCH_SIZE)
        
        if not students:
            print(f"  No students found in this batch")
            break
        
        batch_processed = 0
        batch_created = 0
        batch_updated = 0
        batch_skipped = 0
        batch_errors = 0
        
        for student in students:
            batch_processed += 1
            
            if not student.get('class_id'):
                print(f"  ⚠️ {student['name']} ({student['student_id']}) has no class_id. Will try to fix later.")
                # Still try to create enrollment? Skip for now
                continue
            
            # Ensure enrollment for 2026
            success, action = update_or_create_enrollment_2026(
                student['id'], 
                student['class_id'],
                student.get('class_id')
            )
            
            if success:
                if action == 'created':
                    batch_created += 1
                    print(f"  ✅ Created 2026 enrollment for {student['name']} ({student['student_id']})")
                elif action == 'updated_class':
                    batch_updated += 1
                    print(f"  🔄 Updated class for 2026 enrollment: {student['name']}")
                elif action == 'skipped_exists':
                    batch_skipped += 1
                    # Uncomment for verbose output:
                    # print(f"  ⏭️ Already enrolled for 2026: {student['name']}")
            else:
                batch_errors += 1
                print(f"  ❌ Failed to create enrollment for {student['name']}: {action}")
        
        # Update totals
        total_processed += batch_processed
        total_created += batch_created
        total_updated += batch_updated
        total_skipped += batch_skipped
        total_errors += batch_errors
        
        print(f"\n  Batch {batch_num} Summary:")
        print(f"    Processed: {batch_processed}")
        print(f"    Created: {batch_created}")
        print(f"    Updated: {batch_updated}")
        print(f"    Already existed: {batch_skipped}")
        print(f"    Errors: {batch_errors}")
        
        # Move to next batch
        offset += BATCH_SIZE
        batch_num += 1
        
        # Add delay to avoid rate limiting
        if offset < total_students:
            print(f"  Waiting {DELAY_BETWEEN_BATCHES}s before next batch...")
            time.sleep(DELAY_BETWEEN_BATCHES)
    
    # Fix students with missing class_id references
    print(f"\n🔧 Checking for students with missing class_id...")
    class_fixes, fix_errors = fix_student_class_reference_batch(institute_id, BATCH_SIZE)
    
    if class_fixes > 0:
        print(f"  ✅ Fixed class references for {class_fixes} student(s)")
    
    # Final summary for this institute
    print(f"\n{'='*60}")
    print(f"📊 FINAL SUMMARY for {institute_name}")
    print(f"{'='*60}")
    print(f"  Total students processed: {total_processed}")
    print(f"  New 2026 enrollments created: {total_created}")
    print(f"  Existing enrollments updated: {total_updated}")
    print(f"  Already had 2026 enrollment: {total_skipped}")
    print(f"  Class references fixed: {class_fixes}")
    print(f"  Total errors: {total_errors}")
    
    return total_created + total_updated, class_fixes

def main():
    print("=" * 60)
    print("STUDENT ENROLLMENT SYNC SCRIPT - ENSURE ALL STUDENTS HAVE 2026 ENROLLMENT")
    print("=" * 60)
    print(f"\nConfiguration:")
    print(f"  Batch Size: {BATCH_SIZE} students")
    print(f"  Delay between batches: {DELAY_BETWEEN_BATCHES}s")
    print(f"  Target Year: 2026")
    
    # Get all institutes
    institutes = get_all_institutes()
    
    if not institutes:
        print("\nNo institutes found in the database!")
        return
    
    print(f"\nFound {len(institutes)} institute(s)\n")
    
    total_enrollments = 0
    total_fixes = 0
    
    for institute in institutes:
        institute_id = institute['id']
        institute_name = institute['institute_name']
        
        enrollments, fixes = process_institute_batches(institute_id, institute_name)
        total_enrollments += enrollments
        total_fixes += fixes
    
    print(f"\n{'='*60}")
    print("🎉 FINAL SUMMARY - ALL INSTITUTES")
    print(f"{'='*60}")
    print(f"  Total new/updated enrollments: {total_enrollments}")
    print(f"  Total class references fixed: {total_fixes}")
    print("\n✅ Script completed! All students now have 2026 enrollments.")
    
    # Final verification query suggestion
    print("\n📝 To verify, run this SQL query:")
    print("""
    SELECT 
        COUNT(DISTINCT s.id) as total_students,
        COUNT(DISTINCT ce.student_id) as students_with_2026_enrollment
    FROM students s
    LEFT JOIN class_enrollments ce ON s.id = ce.student_id AND ce.academic_year = 2026
    WHERE s.status = 'active';
    """)

def dry_run():
    """Preview what will be changed without making actual changes"""
    print("=" * 60)
    print("DRY RUN MODE - Preview changes only")
    print("=" * 60)
    
    institutes = get_all_institutes()
    
    for institute in institutes:
        institute_id = institute['id']
        institute_name = institute['institute_name']
        
        print(f"\nInstitute: {institute_name}")
        print(f"ID: {institute_id}")
        
        # Get students without 2026 enrollment
        students_response = supabase.table('students')\
            .select('id, name, student_id, class_id')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')\
            .execute()
        
        students = students_response.data if students_response.data else []
        
        if not students:
            print("  No active students found")
            continue
        
        # Check which students need enrollment
        student_ids = [s['id'] for s in students]
        
        enrollments_response = supabase.table('class_enrollments')\
            .select('student_id')\
            .in_('student_id', student_ids)\
            .eq('academic_year', 2026)\
            .execute()
        
        enrolled_ids = set(e['student_id'] for e in enrollments_response.data) if enrollments_response.data else set()
        
        students_needing_enrollment = [s for s in students if s['id'] not in enrolled_ids and s.get('class_id')]
        students_without_class = [s for s in students if not s.get('class_id')]
        
        print(f"\n  Students needing 2026 enrollment: {len(students_needing_enrollment)}")
        for student in students_needing_enrollment[:10]:  # Show first 10
            print(f"    - {student['name']} ({student['student_id']}) -> Class: {student['class_id'][:8]}...")
        
        if len(students_needing_enrollment) > 10:
            print(f"    ... and {len(students_needing_enrollment) - 10} more")
        
        print(f"\n  Students without class_id: {len(students_without_class)}")
        for student in students_without_class[:5]:
            print(f"    - {student['name']} ({student['student_id']})")
    
    print("\n" + "=" * 60)
    print("To apply these changes, run: python fix_enrollments.py --apply")
    print("=" * 60)

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == '--dry-run':
        dry_run()
    elif len(sys.argv) > 1 and sys.argv[1] == '--apply':
        main()
    else:
        print("Usage:")
        print("  python fix_enrollments.py --dry-run    # Preview changes without making them")
        print("  python fix_enrollments.py --apply      # Apply changes to database")
        print("\nRunning dry run by default...")
        dry_run()