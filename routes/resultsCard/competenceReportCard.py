# competenceReportCard.py - Optimized Competence-Based Report Card with Marksheet Support

from flask import Blueprint, render_template, request, jsonify, session, send_file
from supabase import create_client, Client
import os
import re
from datetime import datetime
from functools import wraps
from dotenv import load_dotenv
import io
import requests
from routes.permissions.permissions import role_required
from routes.accounts.accounts import get_institute_id as get_institute_id_func

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Node.js API URL
REPORT_API_URL = os.getenv('REPORT_API_URL', 'http://d44cgg048cgckw4kwo4osw4k.195.200.15.127.sslip.io')

competence_bp = Blueprint('competence', __name__, url_prefix='/competence-report')

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Please login'}), 401
        return f(*args, **kwargs)
    return decorated_function

def parse_exam_name(exam_name):
    patterns = {
        'A': re.compile(r'^A\d+$', re.IGNORECASE),
        'BOT': re.compile(r'^BOT$', re.IGNORECASE),
        'EOT': re.compile(r'^EOT$', re.IGNORECASE),
        'MT': re.compile(r'^MT$', re.IGNORECASE),
    }
    for pattern_type, pattern in patterns.items():
        if pattern.match(exam_name.strip().upper()):
            return pattern_type
    return 'OTHER'

def get_cdc_settings(institute_id):
    """Get CDC settings for an institute from the database"""
    try:
        response = supabase.table('cdc_report_settings')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .execute()
        
        if response.data and len(response.data) > 0:
            return response.data[0]
        else:
            # If no settings exist, create default ones
            from routes.cdc_report_settings import get_default_settings, update_cdc_settings
            default_settings = get_default_settings(institute_id)
            if 'institute_id' in default_settings:
                del default_settings['institute_id']
            updated = update_cdc_settings(institute_id, default_settings)
            return updated or default_settings
    except Exception as e:
        print(f"Error getting CDC settings: {e}")
        import traceback
        traceback.print_exc()
        return None

def get_grade_from_percentage(percentage, grading_scale):
    """Get grade and label from percentage using dynamic grading scale"""
    if not grading_scale:
        return 'E', 'Insufficient'
    
    for grade in grading_scale:
        min_val = grade.get('min', 0)
        max_val = grade.get('max', 100)
        if min_val <= percentage <= max_val:
            return grade.get('grade', 'E'), grade.get('label', grade.get('grade', 'Insufficient'))
    
    if grading_scale:
        lowest = min(grading_scale, key=lambda x: x.get('min', 0))
        return lowest.get('grade', 'E'), lowest.get('label', 'Insufficient')
    
    return 'E', 'Insufficient'

def get_achievement_level(percentage, achievement_levels):
    """Get achievement level from percentage using dynamic achievement levels"""
    if not achievement_levels:
        return 'Needs Improvement', '#ef4444'
    
    for level in achievement_levels:
        min_val = level.get('min', 0)
        max_val = level.get('max', 100)
        if min_val <= percentage <= max_val:
            return level.get('level', 'Needs Improvement'), level.get('color', '#ef4444')
    
    if achievement_levels:
        lowest = min(achievement_levels, key=lambda x: x.get('min', 0))
        return lowest.get('level', 'Needs Improvement'), lowest.get('color', '#ef4444')
    
    return 'Needs Improvement', '#ef4444'

def get_identifier(percentage, identifier_rules):
    """Get identifier based on percentage using dynamic identifier rules"""
    if not identifier_rules:
        if percentage >= 70:
            return '3'
        elif percentage >= 40:
            return '2'
        else:
            return '1'
    
    for rule in identifier_rules:
        min_val = rule.get('min', 0)
        max_val = rule.get('max', 100)
        if min_val <= percentage <= max_val:
            label = rule.get('label', str(rule.get('id', '1')))
            match = re.search(r'(\d+)', label)
            if match:
                return match.group(1)
            return str(rule.get('id', '1'))
    
    if identifier_rules:
        lowest = min(identifier_rules, key=lambda x: x.get('min', 0))
        label = lowest.get('label', '1')
        match = re.search(r'(\d+)', label)
        if match:
            return match.group(1)
        return '1'
    
    return '1'

def determine_result(subject_results, result_definitions):
    """
    Determine the result (1, 2, or 3) based on subject performance.
    """
    if not subject_results:
        return 3
    
    total_subjects = len(subject_results)
    
    grade_counts = {}
    for subject in subject_results:
        grade = subject.get('grade', 'E')
        grade_counts[grade] = grade_counts.get(grade, 0) + 1
    
    # Result 3: All subjects are grade E
    if grade_counts.get('E', 0) == total_subjects:
        return 3
    
    # Result 1: Minimum 8 subjects with grade D and above
    if total_subjects >= 8:
        passing_grades = ['A', 'B', 'C', 'D']
        passing_count = sum(grade_counts.get(g, 0) for g in passing_grades)
        if passing_count == total_subjects:
            return 1
    
    # Result 2: Minimum 8 subjects with grade E in not more than 2 subjects
    if total_subjects >= 8:
        e_count = grade_counts.get('E', 0)
        if e_count <= 2:
            return 2
    
    return 3

@competence_bp.route('/')
@role_required(['owner', 'teacher', 'accountant'])
def index():
    user = session.get('user')
    institute_id = get_institute_id_func(user['id'])
    
    if not institute_id:
        return render_template('competence/index.html', exams=[], classes=[], students=[], institute=None)
    
    try:
        institute_response = supabase.table('institutes')\
            .select('*')\
            .eq('id', institute_id)\
            .execute()
        
        institute = institute_response.data[0] if institute_response.data else {}
        
        exams_response = supabase.table('exams')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('exam_date', desc=True)\
            .execute()
        
        exams = exams_response.data if exams_response.data else []
        
        classes_response = supabase.table('classes')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('name')\
            .execute()
        
        classes = classes_response.data if classes_response.data else []
        
        students_response = supabase.table('students')\
            .select('id, name, student_id, class_id, classes(name), photo_url, gender, category')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')\
            .order('name')\
            .execute()
        
        students = students_response.data if students_response.data else []
        
        return render_template('competence/index.html', exams=exams, classes=classes, students=students, institute=institute)
        
    except Exception as e:
        print(f"Error loading competence page: {e}")
        return render_template('competence/index.html', exams=[], classes=[], students=[], institute=None)

@competence_bp.route('/api/exams/classify', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def classify_exams():
    user = session.get('user')
    institute_id = get_institute_id_func(user['id'])
   
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        exam_ids = data.get('exam_ids', [])
        
        if not exam_ids:
            return jsonify({'success': False, 'message': 'No exams selected'}), 400
        
        exams_response = supabase.table('exams')\
            .select('*')\
            .in_('id', exam_ids)\
            .execute()
        
        exams = exams_response.data if exams_response.data else []
        
        classified = {'a_series': [], 'bot': None, 'eot': None, 'mt': None, 'other': []}
        
        for exam in exams:
            exam_type = parse_exam_name(exam['exam_name'])
            if exam_type == 'A':
                match = re.search(r'(\d+)', exam['exam_name'])
                number = int(match.group(1)) if match else 0
                classified['a_series'].append({
                    'id': exam['id'], 'name': exam['exam_name'], 
                    'total_marks': exam['total_marks'], 'number': number
                })
            elif exam_type == 'BOT':
                classified['bot'] = {'id': exam['id'], 'name': exam['exam_name'], 'total_marks': exam['total_marks']}
            elif exam_type == 'EOT':
                classified['eot'] = {'id': exam['id'], 'name': exam['exam_name'], 'total_marks': exam['total_marks']}
            elif exam_type == 'MT':
                classified['mt'] = {'id': exam['id'], 'name': exam['exam_name'], 'total_marks': exam['total_marks']}
            else:
                classified['other'].append({'id': exam['id'], 'name': exam['exam_name'], 'total_marks': exam['total_marks']})
        
        classified['a_series'].sort(key=lambda x: x['number'])
        
        return jsonify({'success': True, 'classified': classified})
        
    except Exception as e:
        print(f"Error classifying exams: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

def build_competency_student_data_batch(student_ids, institute_id, exam_ids, cdc_settings, term=None, year=None):
    """
    Optimized batch data fetching for competency-based reports using MARKSHEETS.
    Fetches marks from specific marksheets based on term and year.
    """
    try:
        # Extract settings
        grading_scale = cdc_settings.get('grading_scale', [])
        achievement_levels = cdc_settings.get('achievement_levels', [])
        identifier_rules = cdc_settings.get('identifier_rules', [])
        result_definitions = cdc_settings.get('result_definitions', [])
        
        # 1. Get all students with their class info
        students_response = supabase.table('students')\
            .select('*, classes(id, name)')\
            .in_('id', student_ids)\
            .eq('institute_id', institute_id)\
            .execute()
        
        students = {s['id']: s for s in (students_response.data or [])}
        
        if not students:
            return {}
        
        # Get class_ids from students
        class_ids = list(set([s.get('class_id') for s in students.values() if s.get('class_id')]))
        
        # 2. Get all subjects for all classes in ONE query
        subjects_response = supabase.table('class_subjects')\
            .select('*, subjects(id, name)')\
            .in_('class_id', class_ids)\
            .eq('institute_id', institute_id)\
            .execute()
        
        # Group subjects by class_id
        subjects_by_class = {}
        for subj in (subjects_response.data or []):
            class_id = subj['class_id']
            if class_id not in subjects_by_class:
                subjects_by_class[class_id] = []
            subjects_by_class[class_id].append(subj)
        
        # 3. Get MARKSHEETS for this term and year for each exam
        marksheet_ids = []
        marksheet_by_exam = {}
        
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
                ms_id = marksheet_response.data[0]['id']
                marksheet_ids.append(ms_id)
                marksheet_by_exam[exam_id] = ms_id
        
        if not marksheet_ids:
            # No marksheets found for this term/year - return empty
            return {}
        
        # 4. Get all marks from these marksheets in ONE query
        marks_response = supabase.table('exam_marks')\
            .select('*')\
            .in_('student_id', student_ids)\
            .in_('exam_id', exam_ids)\
            .in_('marksheet_id', marksheet_ids)\
            .eq('institute_id', institute_id)\
            .execute()
        
        # Build marks lookup: (student_id, exam_id, subject_id) -> obtained_marks
        marks_lookup = {}
        for mark in (marks_response.data or []):
            key = (mark['student_id'], mark['exam_id'], mark['subject_id'])
            marks_lookup[key] = float(mark['obtained_marks'])
        
        # 5. Get all students for position calculation
        all_students_in_class_response = supabase.table('students')\
            .select('id, name, class_id')\
            .in_('class_id', class_ids)\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')\
            .execute()
        
        students_by_class_for_positions = {}
        for s in (all_students_in_class_response.data or []):
            class_id = s['class_id']
            if class_id not in students_by_class_for_positions:
                students_by_class_for_positions[class_id] = []
            students_by_class_for_positions[class_id].append(s)
        
        # 6. Get all marks for position calculation from the same marksheets
        all_student_ids_for_positions = [s['id'] for s in (all_students_in_class_response.data or [])]
        all_marks_for_positions_response = supabase.table('exam_marks')\
            .select('student_id, subject_id, exam_id, obtained_marks')\
            .in_('student_id', all_student_ids_for_positions)\
            .in_('exam_id', exam_ids)\
            .in_('marksheet_id', marksheet_ids)\
            .eq('institute_id', institute_id)\
            .execute()
        
        # Build marks lookup for position calculation
        position_marks_lookup = {}
        for mark in (all_marks_for_positions_response.data or []):
            key = (mark['student_id'], mark['exam_id'], mark['subject_id'])
            position_marks_lookup[key] = float(mark['obtained_marks'])
        
        # Get exam details
        exams_response = supabase.table('exams')\
            .select('*')\
            .in_('id', exam_ids)\
            .eq('institute_id', institute_id)\
            .execute()
        
        exams = exams_response.data if exams_response.data else []
        
        # Classify exams
        a_series = []
        eot_exam = None
        for exam in exams:
            exam_type = parse_exam_name(exam['exam_name'])
            if exam_type == 'A':
                match = re.search(r'(\d+)', exam['exam_name'])
                number = int(match.group(1)) if match else 0
                a_series.append({
                    'id': exam['id'],
                    'name': exam['exam_name'],
                    'total_marks': exam['total_marks'],
                    'number': number
                })
            elif exam_type == 'EOT':
                eot_exam = exam
        
        a_series.sort(key=lambda x: x['number'])
        
        # Now build data for each student
        result = {}
        
        for student_id, student in students.items():
            class_id = student.get('class_id')
            if not class_id:
                continue
            
            subjects = subjects_by_class.get(class_id, [])
            if not subjects:
                continue
            
            # Prepare subject results
            subject_results = []
            
            for subject in subjects:
                subject_name = subject['subjects']['name'] if subject.get('subjects') else 'N/A'
                subject_id = subject['subject_id']
                
                # Get A-series marks
                a_series_marks = {}
                for a_exam in a_series:
                    key = (student_id, a_exam['id'], subject_id)
                    obtained = marks_lookup.get(key, 0)
                    a_series_marks[a_exam['name']] = obtained
                
                # Calculate A-series average
                if a_series_marks and a_series:
                    avg_a = sum(a_series_marks.values()) / len(a_series_marks)
                    twenty_percent = (avg_a / a_series[0]['total_marks']) * 20 if a_series[0]['total_marks'] > 0 else 0
                else:
                    avg_a = 0
                    twenty_percent = 0
                
                # Get EOT mark
                if eot_exam:
                    key = (student_id, eot_exam['id'], subject_id)
                    eot_mark = marks_lookup.get(key, 0)
                    eighty_percent = (eot_mark / eot_exam['total_marks']) * 80 if eot_exam['total_marks'] > 0 else 0
                else:
                    eot_mark = 0
                    eighty_percent = 0
                
                total_percentage = twenty_percent + eighty_percent
                
                # Use dynamic grading scale
                grade, grade_label = get_grade_from_percentage(total_percentage, grading_scale)
                
                # Use dynamic achievement levels
                level, color = get_achievement_level(total_percentage, achievement_levels)
                
                # Use dynamic identifier rules
                identifier = get_identifier(total_percentage, identifier_rules)
                
                subject_results.append({
                    'code': f'SUB{len(subject_results)+1:03d}',
                    'name': subject_name,
                    'scores': a_series_marks,
                    'avg': round(avg_a, 1),
                    'weighted': {
                        '20%': round(twenty_percent, 1),
                        '80%': round(eighty_percent, 1),
                        '100%': round(total_percentage, 1)
                    },
                    'grade': grade,
                    'levelOfAchievement': level,
                    'teacherInitials': ''
                })
            
            # Calculate overall totals
            total_marks = {}
            for subject in subject_results:
                for exam_name, score in subject['scores'].items():
                    total_marks[exam_name] = total_marks.get(exam_name, 0) + score
            
            overall_avg = sum([s['weighted']['100%'] for s in subject_results]) / len(subject_results) if subject_results else 0
            
            # Calculate position using pre-fetched data
            class_students = students_by_class_for_positions.get(class_id, [])
            student_percentages = []
            
            for s in class_students:
                s_total = 0
                s_count = 0
                for subject in subjects:
                    subject_id = subject['subject_id']
                    for exam in exams:
                        exam_type = parse_exam_name(exam['exam_name'])
                        if exam_type in ['A', 'EOT']:
                            key = (s['id'], exam['id'], subject_id)
                            mark = position_marks_lookup.get(key, 0)
                            if exam_type == 'A':
                                s_total += mark * 0.2
                            elif exam_type == 'EOT':
                                s_total += mark * 0.8
                            s_count += 1
                
                avg = s_total / s_count if s_count > 0 else 0
                student_percentages.append({'id': s['id'], 'avg': avg})
            
            student_percentages.sort(key=lambda x: x['avg'], reverse=True)
            
            position = 1
            for idx, sp in enumerate(student_percentages, 1):
                if sp['id'] == student_id:
                    position = idx
                    break
            
            total_students = len(student_percentages)
            
            # Determine overall grade using dynamic settings
            overall_grade, _ = get_grade_from_percentage(overall_avg, grading_scale)
            overall_ident = get_identifier(overall_avg, identifier_rules)
            overall_achievement, _ = get_achievement_level(overall_avg, achievement_levels)
            
            # Determine result based on subject performance
            result_number = determine_result(subject_results, result_definitions)
            
            class_name = student.get('classes', {}).get('name') if student.get('classes') else 'N/A'
            
            # Build footer fields from settings
            footer_fields = cdc_settings.get('footer_fields', [])
            footer_values = []
            for field in footer_fields:
                if field.get('key') == 'term_ended_on':
                    footer_values.append({'label': field.get('label', 'Term Ended On'), 'value': datetime.now().strftime('%d/%m/%Y')})
                elif field.get('key') == 'next_term_begins':
                    footer_values.append({'label': field.get('label', 'Next Term Begins'), 'value': 'To be announced'})
                else:
                    footer_values.append({'label': field.get('label', ''), 'value': ''})
            
            result[student_id] = {
                'name': student.get('name', 'N/A'),
                'studentId': student.get('student_id', 'N/A'),
                'class': class_name,
                'gender': student.get('gender', 'N/A'),
                'division': overall_grade,
                'position': position,
                'outOf': total_students,
                'aggregates': int(overall_ident),
                'photoUrl': student.get('photo_url', ''),
                'subjects': subject_results,
                'totals': {
                    **total_marks,
                    'avg': round(overall_avg, 1),
                    'grade': overall_grade,
                    'result': result_number
                },
                'overall': [
                    {'label': 'Overall Identifier', 'value': overall_ident},
                    {'label': 'Overall Achievement', 'value': overall_achievement},
                    {'label': 'Overall grade', 'value': overall_grade}
                ],
                'classTeacherComment': f"{student.get('name', 'The student')} is making good progress.",
                'headTeacherComment': 'Keep up the good work.',
                'footerFields': footer_values
            }
        
        return result
        
    except Exception as e:
        print(f"Error building batch competency student data: {e}")
        import traceback
        traceback.print_exc()
        return {}

@competence_bp.route('/generate', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def generate_report():
    """Generate a single competence report using the Node.js API with MARKSHEET data"""
    user = session.get('user')
    institute_id = get_institute_id_func(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        student_id = data.get('student_id')
        exam_ids = data.get('exam_ids', [])
        term = data.get('term', '').strip()
        year = data.get('year', datetime.now().year)
        
        if not student_id or not exam_ids or not term:
            return jsonify({'success': False, 'message': 'Missing required fields'}), 400
        
        # Get CDC settings from database
        cdc_settings = get_cdc_settings(institute_id)
        if not cdc_settings:
            return jsonify({'success': False, 'message': 'CDC settings not found'}), 500
        
        # Get institute details
        institute_response = supabase.table('institutes')\
            .select('*')\
            .eq('id', institute_id)\
            .execute()
        
        institute = institute_response.data[0] if institute_response.data else {}
        
        # Use batch function with single student and marksheet-based fetching
        students_data_dict = build_competency_student_data_batch(
            [student_id], institute_id, exam_ids, cdc_settings, term, str(year)
        )
        
        student_data = students_data_dict.get(student_id)
        
        if not student_data:
            return jsonify({
                'success': False, 
                'message': f'No marks found for term "{term}" in year {year}. Please ensure marks have been entered for this term.'
            }), 500
        
        # Get exams for assessments
        exams_response = supabase.table('exams')\
            .select('*')\
            .in_('id', exam_ids)\
            .execute()
        
        exams = exams_response.data if exams_response.data else []
        
        # Get assessments (A-series exam names)
        assessments = []
        for exam in exams:
            if parse_exam_name(exam['exam_name']) == 'A':
                assessments.append(exam['exam_name'])
        assessments.sort()
        
        # Build payload for Node.js API using dynamic settings
        payload = {
            'school': {
                'name': institute.get('institute_name', 'Academic Institute'),
                'tagline': institute.get('target_line', 'Excellence in Education'),
                'address': institute.get('address', ''),
                'phone': institute.get('phone_number', ''),
                'motto': institute.get('footer_motto', 'Foundation for your digital ambitions'),
                'logoUrl': institute.get('logo_url', '')
            },
            'term': {
                'termYear': f'{term} {year}',
                'nextTermBegins': 'To be announced',
                'reportTitle': cdc_settings.get('report_title', 'COMPETENCY BASED ASSESSMENT REPORT')
            },
            'assessments': assessments,
            'weightedColumns': cdc_settings.get('weighted_columns', [
                {'key': '20%', 'label': '20%'},
                {'key': '80%', 'label': '80%'},
                {'key': '100%', 'label': '100%'}
            ]),
            'gradeScale': cdc_settings.get('grading_scale', []),
            'keyTerms': cdc_settings.get('key_terms', []),
            'resultDefinitions': cdc_settings.get('result_definitions', []),
            'student': student_data
        }
        
        # Call the Node.js API
        try:
            response = requests.post(
                f"{REPORT_API_URL}/generate-competency-report-card",
                json=payload,
                timeout=60,
                headers={'Content-Type': 'application/json'}
            )
            
            if response.status_code != 200:
                error_text = response.text[:500]
                print(f"API error: {response.status_code} - {error_text}")
                return jsonify({
                    'success': False, 
                    'message': f'Report API error: {response.status_code}'
                }), 500
            
            # Get the PDF from the response
            pdf_buffer = io.BytesIO(response.content)
            pdf_buffer.seek(0)
            
            student_name = student_data.get('name', 'Student').replace(' ', '_')
            
            return send_file(
                pdf_buffer,
                as_attachment=True,
                download_name=f"competence_report_{student_name}_{term}_{year}.pdf",
                mimetype='application/pdf'
            )
            
        except requests.exceptions.ConnectionError:
            return jsonify({
                'success': False, 
                'message': 'Report API is not available. Please ensure the Node.js service is running.'
            }), 503
        except requests.exceptions.Timeout:
            return jsonify({
                'success': False, 
                'message': 'Report generation timed out. Please try again.'
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
        print(f"Error generating competence report: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@competence_bp.route('/generate-class', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def generate_class_reports():
    """
    Generate competence reports for all students in a class using MARKSHEET data.
    Returns a single merged PDF containing all student reports.
    """
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
        
        if not class_id or not exam_ids or not term:
            return jsonify({'success': False, 'message': 'Missing required fields'}), 400
        
        # Get CDC settings from database
        cdc_settings = get_cdc_settings(institute_id)
        if not cdc_settings:
            return jsonify({'success': False, 'message': 'CDC settings not found'}), 500
        
        # Get all active students in the class
        students_response = supabase.table('students')\
            .select('id, name, student_id')\
            .eq('class_id', class_id)\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')\
            .order('name')\
            .execute()
        
        students = students_response.data if students_response.data else []
        
        if not students:
            return jsonify({'success': False, 'message': 'No students found in this class'}), 404
        
        student_ids = [s['id'] for s in students]
        
        print(f"Generating competency reports for {len(students)} students...")
        
        # Get institute details
        institute_response = supabase.table('institutes')\
            .select('*')\
            .eq('id', institute_id)\
            .execute()
        
        institute = institute_response.data[0] if institute_response.data else {}
        
        # Build student data in BATCH with marksheet-based fetching
        students_data_dict = build_competency_student_data_batch(
            student_ids, institute_id, exam_ids, cdc_settings, term, str(year)
        )
        
        # Convert to list in the original order
        students_data = []
        failed_students = []
        
        for student in students:
            student_data = students_data_dict.get(student['id'])
            if student_data:
                students_data.append(student_data)
            else:
                failed_students.append(student.get('name', 'Unknown'))
        
        if not students_data:
            return jsonify({
                'success': False, 
                'message': f'No marks found for term "{term}" in year {year}. Please ensure marks have been entered for this term.'
            }), 500
        
        # Get exams for assessments
        exams_response = supabase.table('exams')\
            .select('*')\
            .in_('id', exam_ids)\
            .execute()
        
        exams = exams_response.data if exams_response.data else []
        
        # Get assessments (A-series exam names)
        assessments = []
        for exam in exams:
            if parse_exam_name(exam['exam_name']) == 'A':
                assessments.append(exam['exam_name'])
        assessments.sort()
        
        # Build payload for Node.js API using dynamic settings
        payload = {
            'school': {
                'name': institute.get('institute_name', 'Academic Institute'),
                'tagline': institute.get('target_line', 'Excellence in Education'),
                'address': institute.get('address', ''),
                'phone': institute.get('phone_number', ''),
                'motto': institute.get('footer_motto', 'Foundation for your digital ambitions'),
                'logoUrl': institute.get('logo_url', '')
            },
            'term': {
                'termYear': f'{term} {year}',
                'nextTermBegins': 'To be announced',
                'reportTitle': cdc_settings.get('report_title', 'COMPETENCY BASED ASSESSMENT REPORT')
            },
            'assessments': assessments,
            'weightedColumns': cdc_settings.get('weighted_columns', [
                {'key': '20%', 'label': '20%'},
                {'key': '80%', 'label': '80%'},
                {'key': '100%', 'label': '100%'}
            ]),
            'gradeScale': cdc_settings.get('grading_scale', []),
            'keyTerms': cdc_settings.get('key_terms', []),
            'resultDefinitions': cdc_settings.get('result_definitions', []),
            'students': students_data
        }
        
        # Call the Node.js API
        try:
            print(f"Sending competency request to {REPORT_API_URL}/generate-competency-report-cards")
            print(f"Payload has {len(students_data)} students, {len(assessments)} assessments, term: {term}, year: {year}")
            
            response = requests.post(
                f"{REPORT_API_URL}/generate-competency-report-cards",
                json=payload,
                timeout=300,
                headers={'Content-Type': 'application/json'}
            )
            
            if response.status_code != 200:
                error_text = response.text[:500]
                print(f"API error: {response.status_code} - {error_text}")
                return jsonify({
                    'success': False, 
                    'message': f'Report API error: {response.status_code}'
                }), 500
            
            # Get the PDF from the response
            pdf_buffer = io.BytesIO(response.content)
            pdf_buffer.seek(0)
            
            # Get class name
            class_response = supabase.table('classes')\
                .select('name')\
                .eq('id', class_id)\
                .eq('institute_id', institute_id)\
                .execute()
            
            class_name = class_response.data[0]['name'] if class_response.data else 'Class'
            
            filename = f"competence_reports_{class_name}_{term}_{year}.pdf"
            
            return send_file(
                pdf_buffer,
                as_attachment=True,
                download_name=filename,
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
                'message': f'Error generating reports: {str(e)}'
            }), 500
        
    except Exception as e:
        print(f"Error generating class competency reports: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@competence_bp.route('/health', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def health_check():
    """Check if the Node.js API is available"""
    try:
        response = requests.get(f"{REPORT_API_URL}/health", timeout=5)
        if response.status_code == 200:
            return jsonify({
                'success': True, 
                'api_status': 'healthy',
                'api_url': REPORT_API_URL
            })
        else:
            return jsonify({
                'success': False, 
                'api_status': 'unhealthy',
                'api_url': REPORT_API_URL,
                'status_code': response.status_code
            }), 503
    except Exception as e:
        return jsonify({
            'success': False, 
            'api_status': 'unavailable',
            'api_url': REPORT_API_URL,
            'error': str(e)
        }), 503
