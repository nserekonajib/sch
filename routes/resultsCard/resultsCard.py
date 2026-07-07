# resultsCard.py - Optimized with Marksheet-based Data Fetching

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
REPORT_API_URL = os.getenv('REPORT_API_URL', 'http://d44cgg048cgckw4kwo4osw4k.195.200.15.127.sslip.io')

results_bp = Blueprint('results', __name__, url_prefix='/results')

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Please login'}), 401
        return f(*args, **kwargs)
    return decorated_function

def get_grade_comment(percentage, grading_settings):
    for grade in grading_settings:
        if grade['min_percentage'] <= percentage <= grade['max_percentage']:
            return grade['grade_name'], grade['status']
    return 'N/A', 'No Grade Assigned'

@results_bp.route('/r')
@role_required(['owner', 'teacher', 'accountant'])
def r():
    return render_template('results/index2.html')

@results_bp.route('/')
@role_required(['owner', 'teacher', 'accountant'])
def index():
    user = session.get('user')
    institute_id = get_institute_id_func(user['id'])
    
    if not institute_id:
        return render_template('results/index.html', exams=[], classes=[], students=[], institute=None)
    
    try:
        # Get institute details
        institute_response = supabase.table('institutes')\
            .select('*')\
            .eq('id', institute_id)\
            .execute()
        
        institute = institute_response.data[0] if institute_response.data else {}
        
        # Get all exams with class info
        exams_response = supabase.table('exams')\
            .select('*, classes(name)')\
            .eq('institute_id', institute_id)\
            .order('created_at', desc=True)\
            .execute()
        
        exams = exams_response.data if exams_response.data else []
        
        # Get all classes
        classes_response = supabase.table('classes')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('name')\
            .execute()
        
        classes = classes_response.data if classes_response.data else []
        
        # Get distinct terms from exam_marksheets
        terms_response = supabase.table('exam_marksheets')\
            .select('term')\
            .eq('institute_id', institute_id)\
            .execute()
        terms = sorted(set([t['term'] for t in terms_response.data if t.get('term')])) if terms_response.data else []
        
        # Get distinct years from exam_marksheets
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
        
        return render_template('results/index.html', 
                             exams=exams, 
                             classes=classes, 
                             students=students, 
                             institute=institute,
                             terms=terms,
                             years=years)
        
    except Exception as e:
        print(f"Error loading results page: {e}")
        import traceback
        traceback.print_exc()
        return render_template('results/index.html', exams=[], classes=[], students=[], institute=None)

def build_student_report_data_batch(student_ids, exam_ids, institute_id, grading_settings, term=None, year=None):
    """
    Optimized batch data fetching using MARKSHEETS for the specific term and year.
    Uses 4-5 queries total instead of N+1 queries.
    """
    try:
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
        
        # 2. Get all subjects for all classes in one query
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
        
        # 3. Get the marksheet for this specific term, year, and exam combination
        # For each exam, find the marksheet that matches the term and year
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
            # No marksheets found for this term/year
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
        
        # 5. Get all students for position calculation (all students in the class)
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
        exam_names = [exam['exam_name'] for exam in exams]
        
        # Build subject max marks lookup
        subject_max_marks = {}
        for class_id, subjects in subjects_by_class.items():
            for subj in subjects:
                subject_max_marks[(class_id, subj['subject_id'])] = float(subj['marks'])
        
        # Now build data for each student
        result = {}
        
        for student_id, student in students.items():
            class_id = student.get('class_id')
            if not class_id:
                continue
            
            subjects = subjects_by_class.get(class_id, [])
            if not subjects:
                continue
            
            # Build subject data for this student
            subject_results = []
            subject_totals = {}
            
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
                    subject_grade, subject_comment = get_grade_comment(subject_average, grading_settings)
                else:
                    subject_average = 0
                    subject_grade = 'N/A'
                    subject_comment = 'No Data'
                
                subject_results.append({
                    'name': subject_name,
                    'scores': scores,
                    'avg': round(subject_average, 1),
                    'grade': subject_grade,
                    'remarks': subject_comment
                })
                
                subject_totals[subject_name] = {
                    'obtained': total_obtained,
                    'possible': total_possible,
                    'average': subject_average
                }
            
            # Calculate overall totals
            total_obtained_all = sum([s['obtained'] for s in subject_totals.values()])
            total_possible_all = sum([s['possible'] for s in subject_totals.values()])
            overall_percentage = (total_obtained_all / total_possible_all * 100) if total_possible_all > 0 else 0
            overall_grade, overall_comment = get_grade_comment(overall_percentage, grading_settings)
            
            # Calculate position for this student
            class_students = students_by_class_for_positions.get(class_id, [])
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
            
            # Build exam totals
            exam_totals = {}
            for exam in exams:
                exam_name = exam['exam_name']
                exam_total = 0
                for subject in subject_results:
                    exam_total += subject['scores'].get(exam_name, 0)
                exam_totals[exam_name] = exam_total
            
            class_name = student.get('classes', {}).get('name') if student.get('classes') else 'N/A'
            
            result[student_id] = {
                'name': student.get('name', 'N/A'),
                'studentId': student.get('student_id', 'N/A'),
                'class': class_name,
                'gender': student.get('gender', 'N/A'),
                'division': overall_grade,
                'position': position,
                'outOf': total_students,
                'photoUrl': student.get('photo_url', ''),
                'subjects': subject_results,
                'totals': {
                    **exam_totals,
                    'avg': round(overall_percentage, 1),
                    'grade': overall_grade
                },
                'classTeacherComment': overall_comment,
                'headTeacherComment': 'Good performance. Keep it up!',
                'requirements': ''
            }
        
        return result
        
    except Exception as e:
        print(f"Error building batch student data: {e}")
        import traceback
        traceback.print_exc()
        return {}

@results_bp.route('/generate-class', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def generate_class_results():
    """Generate merged PDF for entire class using Node.js API - Optimized batch version"""
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
        
        if not class_id:
            return jsonify({'success': False, 'message': 'Please select a class'}), 400
        
        if not exam_ids:
            return jsonify({'success': False, 'message': 'Please select at least one exam'}), 400
        
        if not term:
            return jsonify({'success': False, 'message': 'Please enter the term'}), 400
        
        # Get all students in the class
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
        
        # Get grading settings
        grading_response = supabase.table('exam_grading')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('min_percentage', desc=True)\
            .execute()
        
        grading = grading_response.data if grading_response.data else []
        
        # Get institute details
        institute_response = supabase.table('institutes')\
            .select('*')\
            .eq('id', institute_id)\
            .execute()
        
        institute = institute_response.data[0] if institute_response.data else {}
        
        # Get exam names
        exams_response = supabase.table('exams')\
            .select('exam_name')\
            .in_('id', exam_ids)\
            .eq('institute_id', institute_id)\
            .execute()
        
        exam_names = [exam['exam_name'] for exam in (exams_response.data or [])]
        
        # Build student data using MARKSHEET-based fetching
        students_data_dict = build_student_report_data_batch(
            student_ids, exam_ids, institute_id, grading, term, year
        )
        
        # Convert to list in the original order
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
                'message': f'No marks found for term "{term}" in year {year}. Please ensure marks have been entered for this term.'
            }), 500
        
        # Build the payload for the Node.js API
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
                'reportTitle': 'Academic Report Card'
            },
            'exams': exam_names,
            'students': students_data
        }
        
        # Call the Node.js API
        try:
            print(f"Sending request to {REPORT_API_URL}/generate-report-cards")
            print(f"Payload has {len(students_data)} students, {len(exam_names)} exams, term: {term}, year: {year}")
            
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
                    'message': f'Report API error: {response.status_code}'
                }), 500
            
            pdf_buffer = io.BytesIO(response.content)
            pdf_buffer.seek(0)
            
            class_response = supabase.table('classes')\
                .select('name')\
                .eq('id', class_id)\
                .eq('institute_id', institute_id)\
                .execute()
            
            class_name = class_response.data[0]['name'] if class_response.data else 'Class'
            
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

@results_bp.route('/generate', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def generate_results():
    """Generate single student report card using Node.js API"""
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
        
        if not student_id:
            return jsonify({'success': False, 'message': 'Please select a student'}), 400
        
        if not exam_ids:
            return jsonify({'success': False, 'message': 'Please select at least one exam'}), 400
        
        if not term:
            return jsonify({'success': False, 'message': 'Please enter the term'}), 400
        
        # Get grading settings
        grading_response = supabase.table('exam_grading')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('min_percentage', desc=True)\
            .execute()
        
        grading = grading_response.data if grading_response.data else []
        
        # Get institute details
        institute_response = supabase.table('institutes')\
            .select('*')\
            .eq('id', institute_id)\
            .execute()
        
        institute = institute_response.data[0] if institute_response.data else {}
        
        # Get exam names
        exams_response = supabase.table('exams')\
            .select('exam_name')\
            .in_('id', exam_ids)\
            .eq('institute_id', institute_id)\
            .execute()
        
        exam_names = [exam['exam_name'] for exam in (exams_response.data or [])]
        
        # Use batch function with single student and marksheet-based fetching
        students_data_dict = build_student_report_data_batch(
            [student_id], exam_ids, institute_id, grading, term, year
        )
        
        student_data = students_data_dict.get(student_id)
        
        if not student_data:
            return jsonify({
                'success': False, 
                'message': f'No marks found for term "{term}" in year {year}. Please ensure marks have been entered for this term.'
            }), 500
        
        # Build the payload for the Node.js API
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
                'reportTitle': 'Academic Report Card'
            },
            'exams': exam_names,
            'student': student_data
        }
        
        # Call the Node.js API
        try:
            response = requests.post(
                f"{REPORT_API_URL}/generate-report-card",
                json=payload,
                timeout=60,
                headers={'Content-Type': 'application/json'}
            )
            
            if response.status_code != 200:
                return jsonify({
                    'success': False, 
                    'message': f'Report API error: {response.status_code}'
                }), 500
            
            pdf_buffer = io.BytesIO(response.content)
            pdf_buffer.seek(0)
            
            student_response = supabase.table('students')\
                .select('name')\
                .eq('id', student_id)\
                .eq('institute_id', institute_id)\
                .execute()
            
            student_name = student_response.data[0]['name'] if student_response.data else 'Student'
            
            return send_file(
                pdf_buffer,
                as_attachment=True,
                download_name=f"report_card_{student_name}_{term}_{year}.pdf",
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
            return jsonify({
                'success': False, 
                'message': f'Error generating report: {str(e)}'
            }), 500
        
    except Exception as e:
        print(f"Error generating results: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@results_bp.route('/health', methods=['GET'])
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