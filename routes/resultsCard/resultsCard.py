# resultsCard.py - Fixed with Proper Data Sending using DB fields
# + Best-4-Subjects Rule (when >4 subjects)
# + SPECIAL CORE-4 Rule for P1 / P2 / P3 classes
#   (English, Mathematics, Literacy 2, Religious Education – must all exist)
import uuid
import re
from flask import Blueprint, render_template, request, jsonify, session, send_file
from supabase import create_client, Client
import os
from datetime import datetime
from functools import wraps
from dotenv import load_dotenv
import io
import requests
from routes.accounts.accounts import get_institute_id as get_institute_id_func
from routes.permissions.permissions import role_required

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Node.js API URL
REPORT_API_URL = os.getenv('REPORT_API_URL')
print(f"REPORT_API_URL: {REPORT_API_URL}")

# Create blueprint WITHOUT url_prefix - will be set when registering
results_bp = Blueprint('results', __name__)


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Please login'}), 401
        return f(*args, **kwargs)
    return decorated_function


# Grade-to-Points mapping
GRADE_POINTS = {
    'D1': 1, 'D2': 2, 'C3': 3, 'C4': 4,
    'C5': 5, 'C6': 6, 'P7': 7, 'P8': 8, 'F9': 9
}

# Number of best subjects to use when a student has more subjects than this
BEST_SUBJECTS_COUNT = 4

# ============================================================
#  P1 / P2 / P3 handling – CORE 4 SUBJECTS
# ============================================================

CORE_4_LABELS = ['English', 'Mathematics', 'Literacy 2', 'Religious Education']


def normalize_class_name(name):
    """Lowercase, strip dots/spaces/dashes/underscores – used for P1-P3 detection."""
    if not name:
        return ''
    return re.sub(r'[\.\s\-_]+', '', str(name)).lower()


def is_p1_p2_p3_class(class_name):
    """
    Return True for P1, P2, P3 (and common spellings: Primary 1, Pri 1,
    Primary One, P.1, P-1, P 1, PRIMARY ONE, etc.).
    Handles trailing suffixes like 'P1A', 'Primary 1 Blue'.
    """
    if not class_name:
        return False
    norm = normalize_class_name(class_name)

    patterns = [
        ('p', '1'), ('p', '2'), ('p', '3'),
        ('primary', '1'), ('primary', '2'), ('primary', '3'),
        ('pri', '1'), ('pri', '2'), ('pri', '3'),
        ('primary', 'one'), ('primary', 'two'), ('primary', 'three'),
        ('pri', 'one'), ('pri', 'two'), ('pri', 'three'),
    ]

    for prefix, number in patterns:
        key = prefix + number
        if norm.startswith(key):
            rest = norm[len(key):]
            # avoid P10, P11, Primary 10 etc.
            if not rest or not rest[0].isdigit():
                return True
    return False


def normalize_subject_name(name):
    """Lowercase, convert dots/dashes/parens/quotes to spaces, collapse spaces."""
    if not name:
        return ''
    norm = str(name).lower()
    norm = re.sub(r'[\.\-\_\'\(\)]', ' ', norm)
    norm = re.sub(r'\s+', ' ', norm).strip()
    return norm


def is_english_subject(name):
    if not name:
        return False
    norm = normalize_subject_name(name)
    first = norm.split(' ')[0]
    return first in ('english', 'eng') or norm.startswith('english')


def is_math_subject(name):
    if not name:
        return False
    norm = normalize_subject_name(name)
    first = norm.split(' ')[0]
    return first in ('mathematics', 'maths', 'math') or 'mathemat' in norm


def is_literacy2_subject(name):
    if not name:
        return False
    norm = normalize_subject_name(name)
    # Remove all spaces so "lit 2" == "lit2" == "literacy 2"
    compact = norm.replace(' ', '')
    patterns = {
        'literacy2', 'literacyii', 'literacytwo',
        'lit2', 'litii', 'littwo',
    }
    return compact in patterns or any(compact.startswith(p) for p in patterns)


def is_re_subject(name):
    if not name:
        return False
    norm = normalize_subject_name(name)  # lowercase, dots → spaces
    if norm in ('re', 'r e', 'religious education', 'religious ed',
                'religious educ', 'religious studies'):
        return True
    if norm.startswith('religious'):
        return True
    # word-boundary match on original e.g. "R.E.", "R.E", "R E"
    if re.search(r'\bR\s*\.?\s*E\s*\.?\b', str(name), re.IGNORECASE):
        return True
    return False


def find_core_4_in_subject_grades(subject_grades):
    """
    Given {subject_name: grade} for a student, find the 4 P1-P3 core subjects.

    Returns:
        (found_dict, missing_labels)
        - found_dict: {original_subject_name: grade} for the ones found
        - missing_labels: list of human-readable labels for missing subjects
    """
    eng = math = lit = re_sub = None

    for name, grade in subject_grades.items():
        if eng is None and is_english_subject(name):
            eng = (name, grade)
        elif math is None and is_math_subject(name):
            math = (name, grade)
        elif lit is None and is_literacy2_subject(name):
            lit = (name, grade)
        elif re_sub is None and is_re_subject(name):
            re_sub = (name, grade)

    found = {}
    missing = []

    if eng is not None:
        found[eng[0]] = eng[1]
    else:
        missing.append('English')

    if math is not None:
        found[math[0]] = math[1]
    else:
        missing.append('Mathematics')

    if lit is not None:
        found[lit[0]] = lit[1]
    else:
        missing.append('Literacy 2')

    if re_sub is not None:
        found[re_sub[0]] = re_sub[1]
    else:
        missing.append('Religious Education')

    return found, missing


def validate_p1_p3_class_subjects(class_id, institute_id):
    """
    Fetch the class_subjects list for a P1-P3 class and return the list of
    missing core subjects (empty list if all 4 are present).
    """
    try:
        resp = supabase.table('class_subjects')\
            .select('*, subjects(id, name)')\
            .eq('class_id', class_id)\
            .eq('institute_id', institute_id)\
            .execute()

        names = []
        for row in (resp.data or []):
            subj = row.get('subjects')
            if subj and isinstance(subj, dict) and subj.get('name'):
                names.append(subj['name'])

        missing = []
        if not any(is_english_subject(n) for n in names):
            missing.append('English')
        if not any(is_math_subject(n) for n in names):
            missing.append('Mathematics')
        if not any(is_literacy2_subject(n) for n in names):
            missing.append('Literacy 2')
        if not any(is_re_subject(n) for n in names):
            missing.append('Religious Education')
        return missing
    except Exception as e:
        print(f"Error validating P1-P3 class subjects: {e}")
        return ['Unknown error validating subjects']


# ============================================================
#  Grade / Aggregate helpers
# ============================================================

def get_grade_from_percentage(percentage, grading_settings):
    """Get grade based on percentage from database settings"""
    for grade in grading_settings:
        min_pct = float(grade['min_percentage'])
        max_pct = float(grade['max_percentage'])
        if min_pct <= percentage <= max_pct:
            return grade['grade_name'], grade.get('status', ''), grade
    return 'F9', 'Fail', None


def calculate_aggregate(subject_grades):
    """Calculate aggregate from subject grades"""
    total_points = 0
    for grade in subject_grades.values():
        total_points += GRADE_POINTS.get(grade, 9)
    return total_points


def get_best_subjects(subject_grades, count=BEST_SUBJECTS_COUNT):
    """
    Return the best N subjects (lowest grade points = best grades).
    - If the student has <= count subjects, return all of them unchanged.
    - Otherwise, return only the top `count` subjects ordered by grade points.
    """
    if len(subject_grades) <= count:
        return dict(subject_grades)

    sorted_items = sorted(
        subject_grades.items(),
        key=lambda item: GRADE_POINTS.get(item[1], 9)
    )
    return dict(sorted_items[:count])


def get_grade_data_from_db(grade_name, grading_settings):
    """
    Get ALL grade data from DB including status (remarks),
    class_teacher_comment, head_teacher_comment, and requirements
    """
    for grade in grading_settings:
        if grade['grade_name'] == grade_name:
            return {
                'grade_name': grade.get('grade_name', ''),
                'status': grade.get('status', ''),
                'class_teacher_comment': grade.get('class_teacher_comment', ''),
                'head_teacher_comment': grade.get('head_teacher_comment', ''),
                'requirements': grade.get('requirements', '')
            }
    return {
        'grade_name': grade_name,
        'status': 'No remarks',
        'class_teacher_comment': '',
        'head_teacher_comment': '',
        'requirements': ''
    }


def determine_division(aggregate, subject_grades):
    """
    Determine division based on aggregate and subject performance
    Returns: (division, requirements, explanation)
    """
    subject_names = list(subject_grades.keys())

    has_f9 = any(grade == 'F9' for grade in subject_grades.values())
    f9_subjects = [name for name, grade in subject_grades.items() if grade == 'F9']

    has_english = any('english' in name.lower() for name in subject_names)
    has_mathematics = any('math' in name.lower() or 'mathematics' in name.lower() for name in subject_names)

    english_passed = True
    math_passed = True

    if has_english:
        for name, grade in subject_grades.items():
            if 'english' in name.lower():
                if grade == 'F9':
                    english_passed = False
                break

    if has_mathematics:
        for name, grade in subject_grades.items():
            if 'math' in name.lower() or 'mathematics' in name.lower():
                if grade == 'F9':
                    math_passed = False
                break

    passed_subjects = sum(1 for grade in subject_grades.values() if grade != 'F9')
    total_subjects = len(subject_grades)

    division = None
    requirements = []
    explanation = []

    # Division 1: 4-12 points, all subjects credit (C6 or better), no F9
    if 4 <= aggregate <= 12:
        all_passed = all(grade not in ['F9', 'P7', 'P8'] for grade in subject_grades.values())
        if all_passed and not has_f9:
            division = 'Division 1'
            requirements.append('Passed all subjects with Credit (C6) or better')
            requirements.append('No F9 in any subject')
            explanation.append('Excellent performance across all subjects')
        else:
            division = 'Division 2'
            if has_f9:
                requirements.append(f'Failed subject(s): {", ".join(f9_subjects)}')
                explanation.append('A single F9 in any subject drops you from Division 1')
            else:
                requirements.append('Some subjects below C6 level')
                explanation.append('Not all subjects at Credit level')

    elif 13 <= aggregate <= 23:
        if has_english and has_mathematics:
            if english_passed and math_passed:
                division = 'Division 2'
                requirements.append('Passed English and Mathematics')
                explanation.append('Satisfactory performance in core subjects')
            else:
                division = 'Division 3'
                if not english_passed:
                    requirements.append('Failed English')
                if not math_passed:
                    requirements.append('Failed Mathematics')
                explanation.append('Failed one or more core subjects')
        else:
            division = 'Division 3'
            if not has_english:
                requirements.append('English not available in results')
            if not has_mathematics:
                requirements.append('Mathematics not available in results')
            explanation.append('Core subjects not available')

    elif 24 <= aggregate <= 29:
        division = 'Division 3'
        requirements.append('Basic pass levels in core subjects')
        explanation.append('Basic pass achievement')

    elif 30 <= aggregate <= 34:
        if passed_subjects >= 2:
            division = 'Division 4'
            requirements.append(f'Passed {passed_subjects} out of {total_subjects} subjects')
            explanation.append('Minimum pass level')
        else:
            division = 'Ungraded'
            requirements.append(f'Passed only {passed_subjects} subject(s) - need at least 2')
            explanation.append('Insufficient passes for certificate')

    else:
        division = 'Ungraded'
        if passed_subjects == 0:
            requirements.append('Failed all subjects')
            explanation.append('No subjects passed')
        else:
            requirements.append(f'Passed only {passed_subjects} subject(s)')
            explanation.append('Does not qualify for a certificate')

    return division, requirements, explanation


def generate_class_teacher_comment(division, aggregate, subject_grades):
    """Generate dynamic class teacher comment"""
    passed = sum(1 for grade in subject_grades.values() if grade != 'F9')
    failed = len(subject_grades) - passed
    f9_subjects = [name for name, grade in subject_grades.items() if grade == 'F9']

    comments = []

    if 'Division 1' in division:
        comments.append(" EXCEPTIONAL PERFORMANCE! ")
        comments.append("The student has demonstrated outstanding mastery across all subjects. ")
        if aggregate <= 6:
            comments.append("This is truly exceptional work - keep up the excellent standards!")
        elif aggregate <= 9:
            comments.append("Excellent work - maintain this high level of commitment.")
        else:
            comments.append("Very good performance - continue striving for excellence.")

    elif 'Division 2' in division:
        comments.append(" GOOD ACADEMIC PROGRESS. ")
        if failed > 0:
            comments.append(f"The student has shown strength in {passed} subjects but needs to improve in {failed} area(s). ")
        comments.append("Continue working hard to reach the next level.")
        if aggregate <= 18:
            comments.append("Close to Division 1 - keep pushing!")
        else:
            comments.append("Steady improvement will lead to better results.")

    elif 'Division 3' in division:
        comments.append(" SATISFACTORY PERFORMANCE. ")
        if failed > 2:
            comments.append(f"While {passed} subjects were passed, there are {failed} subjects requiring significant improvement. ")
        comments.append("Focus on strengthening weak areas.")
        if failed <= 2:
            comments.append("With more effort, can achieve Division 2.")

    elif 'Division 4' in division:
        comments.append(" MINIMUM PASS LEVEL ACHIEVED. ")
        if failed >= 2:
            comments.append(f"Passed only {passed} subject(s) - considerable improvement needed in {failed} subject(s). ")
        comments.append("Urgent attention required to improve performance.")

    else:
        comments.append(" PERFORMANCE BELOW MINIMUM REQUIREMENTS. ")
        comments.append("Requires immediate intervention and academic support. ")
        comments.append("Please ensure regular attendance and increased effort in all subjects.")

    if f9_subjects:
        comments.append(f"Needs focused support in: {', '.join(f9_subjects)}.")

    best_subjects = [name for name, grade in subject_grades.items()
                     if grade in ['D1', 'D2', 'C3']]
    if best_subjects and len(best_subjects) >= 2:
        comments.append(f"Shows particular strength in {', '.join(best_subjects[:2])}.")

    return ' '.join(comments)


def generate_head_teacher_comment(division, aggregate, subject_grades):
    """Generate dynamic head teacher comment"""
    comments = []
    f9_subjects = [name for name, grade in subject_grades.items() if grade == 'F9']
    passed = sum(1 for grade in subject_grades.values() if grade != 'F9')
    total = len(subject_grades)

    if 'Division 1' in division:
        comments.append(" EXCELLENT ACHIEVEMENT: ")
        if aggregate <= 6:
            comments.append("This is outstanding performance! The student has demonstrated exceptional academic ability and dedication. ")
            comments.append("Should be commended for this remarkable achievement.")
        elif aggregate <= 9:
            comments.append("Very impressive results. The student has shown consistent high performance across all subjects. ")
            comments.append("A role model for academic excellence.")
        else:
            comments.append("Good performance with strong subject mastery. ")
            comments.append("Encouraged to maintain this standard.")

    elif 'Division 2' in division:
        comments.append(" GOOD ACADEMIC STANDING: ")
        comments.append("The student has performed well and shown competence in core subjects. ")
        if aggregate <= 18:
            comments.append("With additional effort, can achieve Division 1 next term. ")
        else:
            comments.append("Steady progress is noted. Continue working hard.")

    elif 'Division 3' in division:
        comments.append(" SATISFACTORY: ")
        comments.append("Basic standards have been met. ")
        comments.append("Areas of weakness should be identified and addressed promptly.")

    elif 'Division 4' in division:
        comments.append(" ATTENTION REQUIRED: ")
        comments.append("Performance is at minimum pass level. ")
        comments.append("Structured support and intervention are recommended.")

    else:
        comments.append(" URGENT ACADEMIC INTERVENTION NEEDED: ")
        comments.append("The student has not met the minimum requirements. ")
        comments.append("A comprehensive academic support plan should be developed.")

    if f9_subjects:
        comments.append(f"Special attention needed in: {', '.join(f9_subjects)}.")

    if passed >= 2:
        comments.append(f"Passed {passed} out of {total} subjects.")

    comments.append("We believe in every student's potential for growth and excellence.")

    return ' '.join(comments)


def get_next_term_from_db(institute_id):
    """Get next term settings from database"""
    try:
        response = supabase.table('next_term_settings')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .execute()

        if response.data:
            return response.data[0]
        return None
    except Exception as e:
        print(f"Error fetching next term: {e}")
        return None


def format_next_term_date(date_str):
    """Format date string nicely"""
    if not date_str or date_str == 'To be announced':
        return 'To be announced'
    try:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
        return date_obj.strftime('%A, %d %B %Y')
    except:
        return date_str


@results_bp.route('/r', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def r():
    return render_template('results/index2.html')


@results_bp.route('/')
@role_required(['owner', 'teacher', 'accountant'])
def index():
    """Results page"""
    user = session.get('user')
    institute_id = get_institute_id_func(user['id'])

    if not institute_id:
        return render_template('results/index.html', exams=[], classes=[], students=[], institute=None)

    try:
        institute_response = supabase.table('institutes')\
            .select('*')\
            .eq('id', institute_id)\
            .execute()

        institute = institute_response.data[0] if institute_response.data else {}

        exams_response = supabase.table('exams')\
            .select('*, classes(name)')\
            .eq('institute_id', institute_id)\
            .order('created_at', desc=True)\
            .execute()
        exams = exams_response.data if exams_response.data else []

        classes_response = supabase.table('classes')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('name')\
            .execute()
        classes = classes_response.data if classes_response.data else []

        terms_response = supabase.table('exam_marksheets')\
            .select('term')\
            .eq('institute_id', institute_id)\
            .execute()
        terms = sorted(set([t['term'] for t in terms_response.data if t.get('term')])) if terms_response.data else []

        years_response = supabase.table('exam_marksheets')\
            .select('academic_year')\
            .eq('institute_id', institute_id)\
            .execute()
        years = sorted(set([y['academic_year'] for y in years_response.data if y.get('academic_year')])) if years_response.data else []

        students_response = supabase.table('students')\
            .select('id, name, student_id, class_id, classes(name), photo_url, gender, status')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')\
            .order('name')\
            .execute()
        students = students_response.data if students_response.data else []

        for student in students:
            if student.get('classes') and isinstance(student['classes'], dict):
                student['class_name'] = student['classes'].get('name', 'N/A')
            else:
                student['class_name'] = 'N/A'

        next_term = get_next_term_from_db(institute_id)

        return render_template('results/index.html',
                               exams=exams,
                               classes=classes,
                               students=students,
                               institute=institute,
                               terms=terms,
                               years=years,
                               next_term=next_term)

    except Exception as e:
        print(f"Error loading results page: {e}")
        import traceback
        traceback.print_exc()
        return render_template('results/index.html', exams=[], classes=[], students=[], institute=None)


def build_student_report_data_batch(student_ids, exam_ids, institute_id, grading_settings,
                                    term=None, year=None,
                                    include_position=True, include_comments=True):
    """Build student report data with division calculation and proper fields.

    Rules:
    ----------
    • P1 / P2 / P3 classes (any common spelling):
        Aggregate & Division are computed from EXACTLY 4 core subjects:
        English, Mathematics, Literacy 2, Religious Education.
        (Presence of all 4 is validated upstream in generate_class_results.)
    • Other classes:
        If the student has more than BEST_SUBJECTS_COUNT subjects, the
        aggregate & division use the BEST 4 subjects (lowest points).
        Otherwise all subjects are used.

    All subjects are still shown in the subject table regardless of rule.
    Comments use the FULL subject list so every weakness is mentioned.
    """
    try:
        students_response = supabase.table('students')\
            .select('*, classes(id, name)')\
            .in_('id', student_ids)\
            .eq('institute_id', institute_id)\
            .execute()

        students = {s['id']: s for s in (students_response.data or [])}
        if not students:
            return {}

        class_ids = list(set([s.get('class_id') for s in students.values() if s.get('class_id')]))

        subjects_response = supabase.table('class_subjects')\
            .select('*, subjects(id, name)')\
            .in_('class_id', class_ids)\
            .eq('institute_id', institute_id)\
            .execute()

        subjects_by_class = {}
        for subj in (subjects_response.data or []):
            class_id = subj['class_id']
            if class_id not in subjects_by_class:
                subjects_by_class[class_id] = []
            subjects_by_class[class_id].append(subj)

        marksheet_ids = []
        for exam_id in exam_ids:
            marksheet_response = supabase.table('exam_marksheets')\
                .select('id, exam_id')\
                .eq('exam_id', exam_id)\
                .eq('institute_id', institute_id)\
                .eq('academic_year', str(year))\
                .eq('term', term)\
                .order('generated_at', desc=True)\
                .limit(1)\
                .execute()

            if marksheet_response.data:
                marksheet_ids.append(marksheet_response.data[0]['id'])

        if not marksheet_ids:
            return {}

        marks_response = supabase.table('exam_marks')\
            .select('*')\
            .in_('student_id', student_ids)\
            .in_('exam_id', exam_ids)\
            .in_('marksheet_id', marksheet_ids)\
            .eq('institute_id', institute_id)\
            .execute()

        marks_lookup = {}
        for mark in (marks_response.data or []):
            key = (mark['student_id'], mark['exam_id'], mark['subject_id'])
            marks_lookup[key] = float(mark['obtained_marks'])

        exams_response = supabase.table('exams')\
            .select('*')\
            .in_('id', exam_ids)\
            .eq('institute_id', institute_id)\
            .execute()
        exams = exams_response.data if exams_response.data else []
        exam_names = [exam['exam_name'] for exam in exams]

        subject_max_marks = {}
        for class_id, subjects in subjects_by_class.items():
            for subj in subjects:
                subject_max_marks[(class_id, subj['subject_id'])] = float(subj['marks'])

        all_students_response = supabase.table('students')\
            .select('id, name, class_id')\
            .in_('class_id', class_ids)\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')\
            .execute()

        students_by_class = {}
        for s in (all_students_response.data or []):
            class_id = s['class_id']
            if class_id not in students_by_class:
                students_by_class[class_id] = []
            students_by_class[class_id].append(s)

        all_student_ids = [s['id'] for s in (all_students_response.data or [])]
        all_marks_response = supabase.table('exam_marks')\
            .select('student_id, subject_id, exam_id, obtained_marks')\
            .in_('student_id', all_student_ids)\
            .in_('exam_id', exam_ids)\
            .in_('marksheet_id', marksheet_ids)\
            .eq('institute_id', institute_id)\
            .execute()

        position_marks_lookup = {}
        for mark in (all_marks_response.data or []):
            key = (mark['student_id'], mark['exam_id'], mark['subject_id'])
            position_marks_lookup[key] = float(mark['obtained_marks'])

        result = {}

        for student_id, student in students.items():
            class_id = student.get('class_id')
            if not class_id:
                continue

            subjects = subjects_by_class.get(class_id, [])
            if not subjects:
                continue

            subject_results = []
            subject_grades = {}

            for subject in subjects:
                subject_name = subject['subjects']['name'] if subject.get('subjects') else 'N/A'
                subject_id = subject['subject_id']
                max_marks = float(subject['marks'])

                scores = {}
                total_obtained = 0
                total_possible = 0

                for exam in exams:
                    exam_id = exam['id']
                    exam_name = exam['exam_name']
                    key = (student_id, exam_id, subject_id)
                    obtained = marks_lookup.get(key)

                    if obtained is not None:
                        scores[exam_name] = obtained
                        total_obtained += obtained
                        total_possible += max_marks
                    else:
                        scores[exam_name] = 0

                if total_possible > 0:
                    subject_average = (total_obtained / total_possible) * 100
                    subject_grade, status, grade_data = get_grade_from_percentage(subject_average, grading_settings)
                else:
                    subject_average = 0
                    subject_grade = 'F9'
                    status = 'Fail'
                    grade_data = None

                subject_grades[subject_name] = subject_grade

                grade_data = get_grade_data_from_db(subject_grade, grading_settings)
                remarks = grade_data.get('status', 'No remarks')

                subject_results.append({
                    'name': subject_name,
                    'scores': scores,
                    'avg': round(subject_average, 1),
                    'grade': subject_grade,
                    'remarks': remarks
                })

            # ----- Decide which subjects feed aggregate / division -----
            class_name = student.get('classes', {}).get('name') if student.get('classes') else 'N/A'
            is_p1_p3 = is_p1_p2_p3_class(class_name)

            if is_p1_p3:
                # CORE 4 rule
                core_subjects, missing_core = find_core_4_in_subject_grades(subject_grades)
                if missing_core:
                    print(f"WARNING: Student '{student.get('name')}' in {class_name} "
                          f"is missing core subjects: {missing_core}")
                subjects_for_calc = core_subjects
                is_best_four = False
                aggregate_based_on = (
                    "Core 4 subjects: English, Mathematics, Literacy 2, Religious Education"
                    if not missing_core else
                    f"Core 4 subjects (missing: {', '.join(missing_core)})"
                )
            else:
                # Best-4 rule (or all if <= 4)
                subjects_for_calc = get_best_subjects(subject_grades, BEST_SUBJECTS_COUNT)
                is_best_four = len(subject_grades) > BEST_SUBJECTS_COUNT
                aggregate_based_on = (
                    f"Best {len(subjects_for_calc)} of {len(subject_grades)} subjects"
                    if is_best_four else
                    f"All {len(subject_grades)} subjects"
                )

            aggregate = calculate_aggregate(subjects_for_calc)

            division, requirements, explanation = determine_division(
                aggregate, subjects_for_calc
            )

            # Comments receive FULL subject_grades so all weak subjects are mentioned
            class_comment = generate_class_teacher_comment(division, aggregate, subject_grades)
            head_comment = generate_head_teacher_comment(division, aggregate, subject_grades)

            all_requirements = []
            for grade_name in set(subject_grades.values()):
                grade_data = get_grade_data_from_db(grade_name, grading_settings)
                if grade_data.get('requirements'):
                    all_requirements.append(grade_data.get('requirements'))

            db_requirements = ', '.join(set(all_requirements)) if all_requirements else ', '.join(requirements)

            # ---------------- Position calculation -----------------
            class_students = students_by_class.get(class_id, [])
            class_percentages = []

            for class_student in class_students:
                student_total = 0
                student_possible = 0

                for subject in subjects:
                    subject_id = subject['subject_id']
                    max_marks = float(subject['marks'])

                    for exam in exams:
                        exam_id = exam['id']
                        key = (class_student['id'], exam_id, subject_id)
                        obtained = position_marks_lookup.get(key)

                        if obtained is not None:
                            student_total += obtained
                            student_possible += max_marks

                percentage = (student_total / student_possible * 100) if student_possible > 0 else 0
                class_percentages.append({
                    'student_id': class_student['id'],
                    'name': class_student['name'],
                    'percentage': percentage
                })

            class_percentages.sort(key=lambda x: x['percentage'], reverse=True)

            position = 1
            for idx, cp in enumerate(class_percentages, 1):
                if cp['student_id'] == student_id:
                    position = idx
                    break

            total_students = len(class_percentages)

            exam_totals = {}
            for exam in exams:
                exam_name = exam['exam_name']
                exam_total = 0
                for subject in subject_results:
                    exam_total += subject['scores'].get(exam_name, 0)
                exam_totals[exam_name] = exam_total

            overall_avg = sum(exam_totals.values()) / (len(exams) * len(subjects)) if exams and subjects else 0

            entry = {
                'name': student.get('name', 'N/A'),
                'studentId': student.get('student_id', 'N/A'),
                'class': class_name,
                'gender': student.get('gender', 'N/A'),
                'division': division,
                'aggregates': aggregate,
                'photoUrl': student.get('photo_url', ''),
                'subjects': subject_results,
                'totals': {
                    **exam_totals,
                    'avg': round(overall_avg, 1),
                    'grade': division
                },
                'requirements': db_requirements,

                # Metadata for Node.js template (optional rendering)
                'aggregateBasedOn': aggregate_based_on,
                'bestSubjectsUsed': list(subjects_for_calc.keys())
                                    if (is_best_four or is_p1_p3) else None,
                'totalSubjects': len(subject_grades),
                'isPrimaryLowerClass': is_p1_p3,
                'coreSubjectsMissing': (
                    find_core_4_in_subject_grades(subject_grades)[1] if is_p1_p3 else []
                ),
            }

            if include_position:
                entry['position'] = position
                entry['outOf'] = total_students

            if include_comments:
                entry['classTeacherComment'] = class_comment
                entry['headTeacherComment'] = head_comment

            result[student_id] = entry

        return result

    except Exception as e:
        print(f"Error building batch student data: {e}")
        import traceback
        traceback.print_exc()
        return {}


@results_bp.route('/generate-class', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def generate_class_results():
    """Generate merged PDF for entire class"""
    user = session.get('user')
    institute_id = get_institute_id_func(user['id'])

    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400

    try:
        data = request.get_json()
        class_id = data.get('class_id')
        exam_ids = data.get('exam_ids', [])
        term = data.get('term', '').strip()
        year = data.get('year', datetime.now().year)

        include_position = bool(data.get('include_position', True))
        include_comments = bool(data.get('include_comments', True))

        next_term_data = get_next_term_from_db(institute_id)
        if next_term_data:
            next_term_date = next_term_data.get('next_term_date')
            next_term = format_next_term_date(next_term_date)
        else:
            next_term = data.get('next_term', 'To be announced')

        if not class_id:
            return jsonify({'success': False, 'message': 'Please select a class'}), 400

        if not exam_ids:
            return jsonify({'success': False, 'message': 'Please select at least one exam'}), 400

        if not term:
            return jsonify({'success': False, 'message': 'Please enter the term'}), 400

        # ---- Fetch class name EARLY (needed for P1-P3 validation) ----
        class_response = supabase.table('classes')\
            .select('name')\
            .eq('id', class_id)\
            .eq('institute_id', institute_id)\
            .execute()
        class_name = class_response.data[0]['name'] if class_response.data else 'Class'

        # ---- P1 / P2 / P3 CORE-4 SUBJECT PRE-VALIDATION ----
        if is_p1_p2_p3_class(class_name):
            missing_core = validate_p1_p3_class_subjects(class_id, institute_id)
            if missing_core:
                return jsonify({
                    'success': False,
                    'message': (
                        f"Cannot generate report for {class_name}. "
                        f"The following mandatory core subjects are missing from this class: "
                        f"{', '.join(missing_core)}. "
                        f"Please add them to the class subjects before generating results."
                    )
                }), 400

        print(f"Generate class request: class_id={class_id}, class_name={class_name}, "
              f"exam_ids={exam_ids}, term={term}, year={year}, next_term={next_term}")
        print(f"Toggles: include_position={include_position}, include_comments={include_comments}")

        # Students
        students_response = supabase.table('students')\
            .select('id, name, student_id')\
            .eq('class_id', class_id)\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')\
            .order('name')\
            .execute()

        students = students_response.data if students_response.data else []

        if not students:
            return jsonify({'success': False, 'message': 'No active students found in this class'}), 404

        student_ids = [s['id'] for s in students]

        grading_response = supabase.table('exam_grading')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('min_percentage', desc=True)\
            .execute()
        grading = grading_response.data if grading_response.data else []

        institute_response = supabase.table('institutes')\
            .select('*')\
            .eq('id', institute_id)\
            .execute()
        institute = institute_response.data[0] if institute_response.data else {}

        exams_response = supabase.table('exams')\
            .select('exam_name')\
            .in_('id', exam_ids)\
            .eq('institute_id', institute_id)\
            .execute()
        exam_names = [exam['exam_name'] for exam in (exams_response.data or [])]

        # Build per-student data
        students_data_dict = build_student_report_data_batch(
            student_ids, exam_ids, institute_id, grading, term, year,
            include_position=include_position,
            include_comments=include_comments
        )

        students_data = []
        failed_students = []

        for student in students:
            student_data = students_data_dict.get(student['id'])
            if student_data:
                students_data.append(student_data)
            else:
                failed_students.append(student['name'])

        if not students_data:
            return jsonify({
                'success': False,
                'message': f'No marks found for term "{term}" in year {year}. '
                           f'Please ensure marks have been entered for this term.'
            }), 500

        payload = {
            'school': {
                'name': institute.get('institute_name', 'Academic Institute'),
                'tagline': institute.get('target_line', 'Excellence in Education'),
                'address': institute.get('address', ''),
                'phone': institute.get('phone_number', ''),
                'motto': institute.get('target_line', 'Foundation for your digital ambitions'),
                'logoUrl': institute.get('logo_url', '')
            },
            'term': {
                'termYear': f'{term} {year}',
                'nextTermBegins': next_term,
                'reportTitle': 'Academic Report Card'
            },
            'exams': exam_names,
            'students': students_data
        }

        payload['options'] = {
            'includePosition': include_position,
            'includeComments': include_comments,
            'useBestFourRule': True,
            'bestSubjectsCount': BEST_SUBJECTS_COUNT,
            'useP1P3CoreRule': is_p1_p2_p3_class(class_name),
            'p1p3CoreSubjects': CORE_4_LABELS
        }

        print(f"Sending to API: {len(students_data)} students, {len(exam_names)} exams")
        print(f"Next term from DB: {next_term}")

        try:
            response = requests.post(
                f"{REPORT_API_URL}/generate-report-cards",
                json=payload,
                timeout=300,
                headers={'Content-Type': 'application/json'}
            )

            if response.status_code != 200:
                print(f"API error: {response.status_code}")
                print(f"Response: {response.text[:500]}")
                return jsonify({
                    'success': False,
                    'message': f'Report API error: {response.status_code} - {response.text[:200]}'
                }), 500

            pdf_buffer = io.BytesIO(response.content)
            pdf_buffer.seek(0)

            return send_file(
                pdf_buffer,
                as_attachment=True,
                download_name=f"report_cards_{class_name}_{term}_{year}.pdf",
                mimetype='application/pdf'
            )

        except requests.exceptions.ConnectionError:
            print(f"Connection error to {REPORT_API_URL}")
            return jsonify({
                'success': False,
                'message': 'Report API is not available. Please ensure the Node.js service is running.'
            }), 503
        except requests.exceptions.Timeout:
            print("Request timeout")
            return jsonify({
                'success': False,
                'message': 'Report generation timed out. Please try with fewer students or exams.'
            }), 504
        except Exception as e:
            print(f"API request error: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'message': f'Error generating report: {str(e)}'
            }), 500

    except Exception as e:
        print(f"Error generating class results: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


@results_bp.route('/api/next-term', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def save_next_term():
    """Save next term settings"""
    user = session.get('user')
    institute_id = get_institute_id_func(user['id'])

    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400

    try:
        data = request.get_json()
        next_term_date = data.get('next_term_date')
        next_term_text = data.get('next_term_text', 'To be announced')

        existing = supabase.table('next_term_settings')\
            .select('id')\
            .eq('institute_id', institute_id)\
            .execute()

        if existing.data:
            result = supabase.table('next_term_settings')\
                .update({
                    'next_term_date': next_term_date,
                    'next_term_text': next_term_text,
                    'updated_at': datetime.now().isoformat()
                })\
                .eq('institute_id', institute_id)\
                .execute()
        else:
            result = supabase.table('next_term_settings')\
                .insert({
                    'id': str(uuid.uuid4()),
                    'institute_id': institute_id,
                    'next_term_date': next_term_date,
                    'next_term_text': next_term_text,
                    'created_at': datetime.now().isoformat(),
                    'updated_at': datetime.now().isoformat()
                })\
                .execute()

        if result.data:
            return jsonify({'success': True, 'message': 'Next term settings saved successfully'})
        else:
            return jsonify({'success': False, 'message': 'Failed to save settings'}), 500

    except Exception as e:
        print(f"Error saving next term: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500