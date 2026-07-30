# examGradingSetting.py - Exam Grading Settings Blueprint with Grade-to-Points Mapping
from flask import Blueprint, render_template, request, jsonify, session
from supabase import create_client, Client
import os
import uuid
from datetime import datetime
from functools import wraps
from dotenv import load_dotenv
from routes.accounts.accounts import get_institute_id
from routes.permissions.permissions import role_required

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

grading_bp = Blueprint('grading', __name__, url_prefix='/exam-grading')

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Please login'}), 401
        return f(*args, **kwargs)
    return decorated_function

# Grade-to-Points mapping based on common Ugandan grading system
GRADE_POINTS = {
    'D1': 1,
    'D2': 2,
    'C3': 3,
    'C4': 4,
    'C5': 5,
    'C6': 6,
    'P7': 7,
    'P8': 8,
    'F9': 9
}

# Division rules
DIVISION_RULES = {
    'D1': {
        'min_aggregate': 4,
        'max_aggregate': 12,
        'requires': ['English', 'Mathematics'],
        'min_grade': 'C6',
        'fail_if_any_f9': True
    },
    'D2': {
        'min_aggregate': 13,
        'max_aggregate': 23,
        'requires': ['English', 'Mathematics'],
        'min_grade': 'P8'
    },
    'D3': {
        'min_aggregate': 24,
        'max_aggregate': 29
    },
    'D4': {
        'min_aggregate': 30,
        'max_aggregate': 34
    },
    'U': {
        'min_aggregate': 35,
        'max_aggregate': 36
    }
}

def get_grade_points(grade_name):
    """Get points for a grade"""
    return GRADE_POINTS.get(grade_name, 9)  # Default to F9 (9 points)

def get_grade_from_percentage(percentage, grading_settings):
    """Get grade based on percentage from database settings"""
    for grade in grading_settings:
        min_pct = float(grade['min_percentage'])
        max_pct = float(grade['max_percentage'])
        if min_pct <= percentage <= max_pct:
            return grade['grade_name'], grade['status']
    return 'F9', 'Fail'

def calculate_aggregate(subject_grades):
    """Calculate aggregate from subject grades"""
    total_points = 0
    for grade in subject_grades:
        total_points += get_grade_points(grade)
    return total_points

def determine_division(aggregate, subjects_data, grading_settings):
    """
    Determine division based on aggregate and subject performance
    Returns: (division, requirements, explanation)
    """
    # Check for F9 in any subject
    has_f9 = any(grade == 'F9' for grade in subjects_data.values())
    
    # Get subject names
    subject_names = list(subjects_data.keys())
    
    # Check if all required subjects exist
    has_english = 'English' in subject_names or any('english' in name.lower() for name in subject_names)
    has_mathematics = 'Mathematics' in subject_names or any('math' in name.lower() or 'mathematics' in name.lower() for name in subject_names)
    
    # Check if English and Math are passed (not F9)
    english_passed = True
    math_passed = True
    
    if has_english:
        for name, grade in subjects_data.items():
            if 'english' in name.lower():
                if grade == 'F9':
                    english_passed = False
                break
    
    if has_mathematics:
        for name, grade in subjects_data.items():
            if 'math' in name.lower() or 'mathematics' in name.lower():
                if grade == 'F9':
                    math_passed = False
                break
    
    # Determine division
    division = None
    requirements = []
    explanation = []
    
    # Check for Division 1
    if DIVISION_RULES['D1']['min_aggregate'] <= aggregate <= DIVISION_RULES['D1']['max_aggregate']:
        # Must pass all subjects with at least C6
        all_passed = True
        for grade in subjects_data.values():
            if grade in ['F9', 'P7', 'P8']:
                all_passed = False
                break
        
        if all_passed and not has_f9:
            division = 'Division 1'
            requirements.append('Passed all subjects with Credit (C6) or better')
            requirements.append('No F9 in any subject')
            explanation.append('Excellent performance across all subjects')
        else:
            # Demoted to Division 2 or lower
            if has_f9:
                division = 'Division 2'
                requirements.append('Failed a subject (F9) - automatic demotion from Division 1')
                explanation.append('A single F9 in any subject drops you from Division 1')
            else:
                division = 'Division 2'
                requirements.append('Some subjects below C6 level')
                explanation.append('Not all subjects at Credit level')
    else:
        # Check for Division 2
        if DIVISION_RULES['D2']['min_aggregate'] <= aggregate <= DIVISION_RULES['D2']['max_aggregate']:
            if has_english and has_mathematics:
                if english_passed and math_passed:
                    division = 'Division 2'
                    requirements.append('Passed English and Mathematics')
                    explanation.append('Satisfactory performance in core subjects')
                else:
                    # Fails in English or Math
                    division = 'Division 3' if aggregate <= 29 else 'Division 4'
                    requirements.append('Failed English or Mathematics')
                    explanation.append('Failed one or more core subjects')
            else:
                division = 'Division 3' if aggregate <= 29 else 'Division 4'
                requirements.append('Missing English or Mathematics from results')
                explanation.append('Core subjects not available')
        else:
            # Check for Division 3
            if DIVISION_RULES['D3']['min_aggregate'] <= aggregate <= DIVISION_RULES['D3']['max_aggregate']:
                division = 'Division 3'
                requirements.append('Basic pass levels in core subjects')
                explanation.append('Basic pass achievement')
            else:
                # Check for Division 4
                if DIVISION_RULES['D4']['min_aggregate'] <= aggregate <= DIVISION_RULES['D4']['max_aggregate']:
                    # Must pass at least two subjects
                    passed_subjects = sum(1 for grade in subjects_data.values() if grade not in ['F9'])
                    if passed_subjects >= 2:
                        division = 'Division 4'
                        requirements.append('Passed at least two subjects')
                        explanation.append('Minimum pass level')
                    else:
                        division = 'Ungraded'
                        requirements.append('Failed to pass at least two subjects')
                        explanation.append('Insufficient passes')
                else:
                    # Division U (Ungraded)
                    division = 'Ungraded'
                    requirements.append('Aggregate beyond Division 4 range')
                    explanation.append('Does not qualify for a certificate')
    
    return division, requirements, explanation

def generate_class_teacher_comment(division, aggregate, subject_grades, grading_settings):
    """Generate dynamic class teacher comment based on performance"""
    comments = []
    
    # Count passes and failures
    passed = sum(1 for grade in subject_grades if grade not in ['F9'])
    failed = len(subject_grades) - passed
    
    # Get subject performance summary
    subjects = list(subject_grades.keys())
    
    # Base comment on division
    if 'Division 1' in division:
        comments.append(" Exceptional academic performance! ")
        comments.append("The student has demonstrated outstanding mastery across all subjects. ")
        if aggregate <= 6:
            comments.append("This is truly exceptional work - keep up the excellent standards!")
        elif aggregate <= 9:
            comments.append("Excellent work - maintain this high level of commitment.")
        else:
            comments.append("Very good performance - continue striving for excellence.")
    
    elif 'Division 2' in division:
        comments.append(" Good academic progress. ")
        if failed > 0:
            comments.append(f"The student has shown strength in {passed} subjects but needs to improve in {failed} area(s). ")
        comments.append("Continue working hard to reach the next level.")
        if aggregate <= 18:
            comments.append("Close to Division 1 - keep pushing!")
        else:
            comments.append("Steady improvement will lead to better results.")
    
    elif 'Division 3' in division:
        comments.append(" Satisfactory performance. ")
        if failed > 2:
            comments.append(f"While {passed} subjects were passed, there are {failed} subjects requiring significant improvement. ")
        comments.append("Focus on strengthening weak areas.")
        if failed <= 2:
            comments.append("With more effort, can achieve Division 2.")
    
    elif 'Division 4' in division:
        comments.append(" Minimum pass level achieved. ")
        if failed >= 2:
            comments.append(f"Passed only {passed} subject(s) - considerable improvement needed in {failed} subject(s). ")
        comments.append("Urgent attention required to improve performance.")
    
    else:  # Ungraded
        comments.append(" Performance below minimum requirements. ")
        comments.append("Requires immediate intervention and academic support. ")
        comments.append("Please ensure regular attendance and increased effort in all subjects.")
    
    # Add specific subject notes
    if failed > 0:
        failing_subjects = [subj for subj, grade in subject_grades.items() if grade == 'F9']
        if failing_subjects:
            comments.append(f"Needs focused support in: {', '.join(failing_subjects)}.")
    
    # Add encouragement based on best subjects
    best_subjects = [subj for subj, grade in subject_grades.items() 
                    if grade in ['D1', 'D2', 'C3']]
    if best_subjects and len(best_subjects) >= 2:
        comments.append(f"Shows particular strength in {', '.join(best_subjects[:2])}.")
    
    return ' '.join(comments)

def generate_head_teacher_comment(division, aggregate, subject_grades, grading_settings):
    """Generate dynamic head teacher comment based on overall performance"""
    comments = []
    
    # Overall assessment based on division
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
    
    else:  # Ungraded
        comments.append(" URGENT ACADEMIC INTERVENTION NEEDED: ")
        comments.append("The student has not met the minimum requirements. ")
        comments.append("A comprehensive academic support plan should be developed.")
    
    # Add general encouragement
    comments.append("We believe in every student's potential for growth and excellence.")
    
    # Add specific advice based on subject count
    if len(subject_grades) >= 6:
        comments.append(f"With {len(subject_grades)} subjects taken, the student has shown ability to handle a full workload.")
    
    return ' '.join(comments)

@grading_bp.route('/')
@role_required(['owner', 'teacher', 'accountant'])
def index():
    """Exam Grading Settings Page"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return render_template('grading/index.html', grades=[], fail_criteria=None, grade_points=GRADE_POINTS, division_rules=DIVISION_RULES)
    
    try:
        # Get grading settings
        grades_response = supabase.table('exam_grading')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('min_percentage', desc=True)\
            .execute()
        
        grades = grades_response.data if grades_response.data else []
        
        # Get fail criteria
        fail_response = supabase.table('exam_fail_criteria')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .execute()
        
        fail_criteria = fail_response.data[0] if fail_response.data else {
            'overall_percentage': 30,
            'subject_percentage': 15
        }
        
        # Get grade requirements (for comments)
        requirements_response = supabase.table('exam_grading_requirements')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .execute()
        
        requirements = requirements_response.data[0] if requirements_response.data else {}
        
        return render_template('grading/index.html', 
                             grades=grades, 
                             fail_criteria=fail_criteria,
                             grade_points=GRADE_POINTS,
                             division_rules=DIVISION_RULES,
                             requirements=requirements)
        
    except Exception as e:
        print(f"Error loading grading page: {e}")
        return render_template('grading/index.html', grades=[], fail_criteria={'overall_percentage': 30, 'subject_percentage': 15}, grade_points=GRADE_POINTS, division_rules=DIVISION_RULES)

@grading_bp.route('/api/grades', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_grades():
    """Get all grade settings"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        response = supabase.table('exam_grading')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('min_percentage', desc=True)\
            .execute()
        
        grades = response.data if response.data else []
        
        return jsonify({'success': True, 'grades': grades})
        
    except Exception as e:
        print(f"Error getting grades: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@grading_bp.route('/api/grades/save', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def save_grades():
    """Save grade settings"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        grades = data.get('grades', [])
        
        # Validate grade ranges
        for grade in grades:
            min_pct = grade.get('min_percentage')
            max_pct = grade.get('max_percentage')
            grade_name = grade.get('grade_name', '').strip()
            status = grade.get('status', 'Pass')
            class_comment = grade.get('class_teacher_comment', '')
            head_comment = grade.get('head_teacher_comment', '')
            requirements = grade.get('requirements', '')
            
            if not grade_name:
                return jsonify({'success': False, 'message': 'Grade name is required'}), 400
            
            if min_pct is None or max_pct is None:
                return jsonify({'success': False, 'message': 'Percentage range is required'}), 400
            
            if min_pct > max_pct:
                return jsonify({'success': False, 'message': f'Invalid range for {grade_name}: Min cannot be greater than Max'}), 400
        
        # Check for overlapping ranges
        sorted_grades = sorted(grades, key=lambda x: x.get('min_percentage', 0))
        for i in range(len(sorted_grades) - 1):
            if sorted_grades[i].get('max_percentage', 0) >= sorted_grades[i + 1].get('min_percentage', 0):
                return jsonify({'success': False, 'message': 'Grade ranges cannot overlap'}), 400
        
        # Delete existing grades
        supabase.table('exam_grading')\
            .delete()\
            .eq('institute_id', institute_id)\
            .execute()
        
        # Insert new grades with comments and requirements
        saved_count = 0
        for grade in grades:
            grade_data = {
                'id': str(uuid.uuid4()),
                'institute_id': institute_id,
                'grade_name': grade.get('grade_name', '').strip().upper(),
                'min_percentage': float(grade.get('min_percentage')),
                'max_percentage': float(grade.get('max_percentage')),
                'status': grade.get('status', 'Pass'),
                'class_teacher_comment': grade.get('class_teacher_comment', ''),
                'head_teacher_comment': grade.get('head_teacher_comment', ''),
                'requirements': grade.get('requirements', ''),
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }
            
            result = supabase.table('exam_grading').insert(grade_data).execute()
            if result.data:
                saved_count += 1
        
        return jsonify({
            'success': True,
            'message': f'Saved {saved_count} grade setting(s) successfully'
        })
        
    except Exception as e:
        print(f"Error saving grades: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@grading_bp.route('/api/calculate-student-results', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def calculate_student_results():
    """
    Calculate student results including aggregate, division, and comments
    Based on grade-to-percentage mapping from database
    """
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        student_id = data.get('student_id')
        exam_ids = data.get('exam_ids', [])
        term = data.get('term', '')
        year = data.get('year', datetime.now().year)
        subject_scores = data.get('subject_scores', {})  # {subject_name: percentage}
        
        # Get grading settings
        grades_response = supabase.table('exam_grading')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('min_percentage', desc=True)\
            .execute()
        
        grading_settings = grades_response.data if grades_response.data else []
        
        # Convert percentages to grades
        subject_grades = {}
        for subject, percentage in subject_scores.items():
            grade, status = get_grade_from_percentage(percentage, grading_settings)
            subject_grades[subject] = grade
        
        # Calculate aggregate
        aggregate = calculate_aggregate(list(subject_grades.values()))
        
        # Determine division
        division, requirements, explanation = determine_division(aggregate, subject_grades, grading_settings)
        
        # Generate comments
        class_comment = generate_class_teacher_comment(division, aggregate, subject_grades, grading_settings)
        head_comment = generate_head_teacher_comment(division, aggregate, subject_grades, grading_settings)
        
        # Get grade-specific comments from database
        grade_comments = {}
        for subject, grade in subject_grades.items():
            for g in grading_settings:
                if g['grade_name'] == grade:
                    grade_comments[subject] = {
                        'grade': grade,
                        'status': g.get('status', ''),
                        'class_comment': g.get('class_teacher_comment', ''),
                        'head_comment': g.get('head_teacher_comment', ''),
                        'requirements': g.get('requirements', '')
                    }
                    break
        
        return jsonify({
            'success': True,
            'student_id': student_id,
            'subject_grades': subject_grades,
            'aggregate': aggregate,
            'division': division,
            'requirements': requirements,
            'explanation': explanation,
            'class_teacher_comment': class_comment,
            'head_teacher_comment': head_comment,
            'grade_comments': grade_comments,
            'next_term': data.get('next_term', 'To be announced')
        })
        
    except Exception as e:
        print(f"Error calculating student results: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@grading_bp.route('/api/update-comments', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def update_comments():
    """Update grade comments and requirements"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        grade_name = data.get('grade_name')
        class_comment = data.get('class_teacher_comment', '')
        head_comment = data.get('head_teacher_comment', '')
        requirements = data.get('requirements', '')
        
        if not grade_name:
            return jsonify({'success': False, 'message': 'Grade name is required'}), 400
        
        # Update the grade with new comments
        result = supabase.table('exam_grading')\
            .update({
                'class_teacher_comment': class_comment,
                'head_teacher_comment': head_comment,
                'requirements': requirements,
                'updated_at': datetime.now().isoformat()
            })\
            .eq('grade_name', grade_name)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if result.data:
            return jsonify({'success': True, 'message': 'Comments updated successfully'})
        else:
            return jsonify({'success': False, 'message': 'Grade not found'}), 404
            
    except Exception as e:
        print(f"Error updating comments: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@grading_bp.route('/api/division-rules', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_division_rules():
    """Get division rules"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        response = supabase.table('division_rules')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .execute()
        
        rules = response.data if response.data else DIVISION_RULES
        
        return jsonify({'success': True, 'rules': rules})
        
    except Exception as e:
        print(f"Error getting division rules: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@grading_bp.route('/api/division-rules/save', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def save_division_rules():
    """Save division rules"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        division = data.get('division')
        rules = data.get('rules', {})
        
        if not division:
            return jsonify({'success': False, 'message': 'Division name is required'}), 400
        
        # Check if rule exists
        existing = supabase.table('division_rules')\
            .select('id')\
            .eq('division', division)\
            .eq('institute_id', institute_id)\
            .execute()
        
        rule_data = {
            'division': division,
            'min_aggregate': rules.get('min_aggregate'),
            'max_aggregate': rules.get('max_aggregate'),
            'requires': rules.get('requires', []),
            'min_grade': rules.get('min_grade'),
            'fail_if_any_f9': rules.get('fail_if_any_f9', False),
            'updated_at': datetime.now().isoformat()
        }
        
        if existing.data:
            result = supabase.table('division_rules')\
                .update(rule_data)\
                .eq('id', existing.data[0]['id'])\
                .execute()
        else:
            rule_data['id'] = str(uuid.uuid4())
            rule_data['institute_id'] = institute_id
            rule_data['created_at'] = datetime.now().isoformat()
            result = supabase.table('division_rules').insert(rule_data).execute()
        
        if result.data:
            return jsonify({'success': True, 'message': 'Division rules saved successfully'})
        else:
            return jsonify({'success': False, 'message': 'Failed to save division rules'}), 500
            
    except Exception as e:
        print(f"Error saving division rules: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    
    
@grading_bp.route('/api/save-next-term', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def save_next_term():
    """Save next term settings"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        next_term_date = data.get('next_term_date', '')
        next_term_text = data.get('next_term_text', 'To be announced')
        
        # Check if settings exist
        existing = supabase.table('next_term_settings')\
            .select('id')\
            .eq('institute_id', institute_id)\
            .execute()
        
        if existing.data:
            # Update
            result = supabase.table('next_term_settings')\
                .update({
                    'next_term_date': next_term_date if next_term_date else None,
                    'next_term_text': next_term_text,
                    'updated_at': datetime.now().isoformat()
                })\
                .eq('institute_id', institute_id)\
                .execute()
        else:
            # Insert
            settings_data = {
                'id': str(uuid.uuid4()),
                'institute_id': institute_id,
                'next_term_date': next_term_date if next_term_date else None,
                'next_term_text': next_term_text,
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }
            result = supabase.table('next_term_settings').insert(settings_data).execute()
        
        if result.data:
            return jsonify({'success': True, 'message': 'Next term settings saved successfully'})
        else:
            return jsonify({'success': False, 'message': 'Failed to save next term settings'}), 500
            
    except Exception as e:
        print(f"Error saving next term settings: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@grading_bp.route('/api/get-next-term', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_next_term():
    """Get next term settings"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        response = supabase.table('next_term_settings')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .execute()
        
        if response.data:
            return jsonify({'success': True, 'settings': response.data[0]})
        else:
            return jsonify({
                'success': True, 
                'settings': {
                    'next_term_date': '',
                    'next_term_text': 'To be announced'
                }
            })
            
    except Exception as e:
        print(f"Error getting next term settings: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500