# exams.py - Complete redesign with term, year, marks validation, and batch processing

from flask import Blueprint, render_template, request, jsonify, session, send_file
from supabase import create_client, Client
import os
import uuid
import random
import string
from datetime import datetime, timedelta
import json
import io
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from functools import wraps
from dotenv import load_dotenv
from routes.accounts.accounts import get_institute_id as get_institute
from routes.permissions.permissions import role_required

load_dotenv()

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

exams_bp = Blueprint('exams', __name__, url_prefix='/exams')

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Please login'}), 401
        return f(*args, **kwargs)
    return decorated_function

# ==================== ROUTES ====================

@exams_bp.route('/')
@role_required(['owner', 'teacher', 'accountant'])
def index():
    user = session.get('user')
    institute_id = get_institute(user['id'])
    
    if not institute_id:
        return render_template('exams/index.html', exams=[], institute=None, datetime=datetime)
    
    try:
        institute_response = supabase.table('institutes')\
            .select('*')\
            .eq('id', institute_id)\
            .execute()
        institute = institute_response.data[0] if institute_response.data else None
        
        academic_year = request.args.get('academic_year')
        term = request.args.get('term')
        
        query = supabase.table('exams')\
            .select('*, classes(name)')\
            .eq('institute_id', institute_id)
        
        if academic_year:
            query = query.eq('academic_year', academic_year)
        if term:
            query = query.eq('term', term)
        
        exams_response = query.order('exam_date', desc=True).execute()
        exams = exams_response.data if exams_response.data else []
        
        classes_response = supabase.table('classes')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('name')\
            .execute()
        classes = classes_response.data if classes_response.data else []
        
        return render_template('exams/index.html', 
                             exams=exams, 
                             institute=institute, 
                             classes=classes,
                             datetime=datetime,
                             selected_year=academic_year,
                             selected_term=term)
        
    except Exception as e:
        print(f"Error loading exams page: {e}")
        return render_template('exams/index.html', exams=[], institute=None, classes=[], datetime=datetime)

@exams_bp.route('/marks')
@role_required(['owner', 'teacher', 'accountant'])
def marks():
    user = session.get('user')
    institute_id = get_institute(user['id'])
    
    if not institute_id:
        return render_template('exams/marks.html', exams=[], classes=[], institute=None, current_year=datetime.now().year)
    
    try:
        institute_response = supabase.table('institutes')\
            .select('*')\
            .eq('id', institute_id)\
            .execute()
        institute = institute_response.data[0] if institute_response.data else None
        
        exams_response = supabase.table('exams')\
            .select('*, classes(name)')\
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
        
        years_response = supabase.table('exams')\
            .select('academic_year')\
            .eq('institute_id', institute_id)\
            .execute()
        years = sorted(set([y['academic_year'] for y in years_response.data if y.get('academic_year')])) if years_response.data else []
        
        terms_response = supabase.table('exams')\
            .select('term')\
            .eq('institute_id', institute_id)\
            .execute()
        terms = sorted(set([t['term'] for t in terms_response.data if t.get('term')])) if terms_response.data else []
        
        return render_template('exams/marks.html', 
                             exams=exams, 
                             classes=classes, 
                             institute=institute, 
                             years=years,
                             terms=terms,
                             current_year=datetime.now().year,
                             current_term=f"Term {((datetime.now().month - 1) // 4) + 1}")
        
    except Exception as e:
        print(f"Error loading marks page: {e}")
        return render_template('exams/marks.html', exams=[], classes=[], institute=None, years=[], terms=[], current_year=datetime.now().year)

# ==================== API ENDPOINTS ====================

@exams_bp.route('/api/exams', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_exams():
    user = session.get('user')
    institute_id = get_institute(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        academic_year = request.args.get('academic_year')
        term = request.args.get('term')
        class_id = request.args.get('class_id')
        
        query = supabase.table('exams')\
            .select('*, classes(name)')\
            .eq('institute_id', institute_id)
        
        if academic_year:
            query = query.eq('academic_year', academic_year)
        if term:
            query = query.eq('term', term)
        if class_id:
            query = query.eq('class_id', class_id)
        
        response = query.order('exam_date', desc=True).execute()
        exams = response.data if response.data else []
        
        return jsonify({'success': True, 'exams': exams})
        
    except Exception as e:
        print(f"Error getting exams: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@exams_bp.route('/api/exams/create', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def create_exam():
    user = session.get('user')
    institute_id = get_institute(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        exam_name = data.get('exam_name', '').strip()
        total_marks = float(data.get('total_marks', 0))
        exam_date = data.get('exam_date')
        academic_year = data.get('academic_year')
        term = data.get('term')
        class_id = data.get('class_id')
        
        if not exam_name:
            return jsonify({'success': False, 'message': 'Exam name is required'}), 400
        if total_marks <= 0:
            return jsonify({'success': False, 'message': 'Total marks must be greater than 0'}), 400
        if not exam_date:
            return jsonify({'success': False, 'message': 'Exam date is required'}), 400
        if not academic_year:
            return jsonify({'success': False, 'message': 'Academic year is required'}), 400
        if not term:
            return jsonify({'success': False, 'message': 'Term is required'}), 400
        if not class_id:
            return jsonify({'success': False, 'message': 'Class is required'}), 400
        
        class_response = supabase.table('classes')\
            .select('id')\
            .eq('id', class_id)\
            .eq('institute_id', institute_id)\
            .execute()
        if not class_response.data:
            return jsonify({'success': False, 'message': 'Class not found'}), 404
        
        exam_id = str(uuid.uuid4())
        exam_data = {
            'id': exam_id,
            'institute_id': institute_id,
            'exam_name': exam_name,
            'total_marks': total_marks,
            'exam_date': exam_date,
            'academic_year': academic_year,
            'term': term,
            'class_id': class_id,
            'is_published': False,
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        result = supabase.table('exams').insert(exam_data).execute()
        
        if result.data:
            return jsonify({'success': True, 'message': 'Exam created successfully', 'exam': result.data[0]})
        else:
            return jsonify({'success': False, 'message': 'Failed to create exam'}), 500
            
    except Exception as e:
        print(f"Error creating exam: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@exams_bp.route('/api/exams/<exam_id>/toggle-publish', methods=['PUT'])
@role_required(['owner', 'teacher', 'accountant'])
def toggle_publish(exam_id):
    user = session.get('user')
    institute_id = get_institute(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        is_published = data.get('is_published', False)
        
        result = supabase.table('exams')\
            .update({'is_published': is_published, 'updated_at': datetime.now().isoformat()})\
            .eq('id', exam_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if result.data:
            return jsonify({'success': True, 'message': f'Exam {"published" if is_published else "unpublished"} successfully'})
        else:
            return jsonify({'success': False, 'message': 'Exam not found'}), 404
            
    except Exception as e:
        print(f"Error toggling publish: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@exams_bp.route('/api/exams/<exam_id>', methods=['DELETE'])
@role_required(['owner', 'teacher', 'accountant'])
def delete_exam(exam_id):
    user = session.get('user')
    institute_id = get_institute(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        supabase.table('exam_marks')\
            .delete()\
            .eq('exam_id', exam_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        supabase.table('exam_marks_history')\
            .delete()\
            .eq('exam_id', exam_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        result = supabase.table('exams')\
            .delete()\
            .eq('id', exam_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if result.data:
            return jsonify({'success': True, 'message': 'Exam deleted successfully'})
        else:
            return jsonify({'success': False, 'message': 'Exam not found'}), 404
            
    except Exception as e:
        print(f"Error deleting exam: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@exams_bp.route('/api/marks', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_marks():
    user = session.get('user')
    institute_id = get_institute(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        exam_id = request.args.get('exam_id')
        class_id = request.args.get('class_id')
        academic_year = request.args.get('academic_year', str(datetime.now().year))
        term = request.args.get('term')  # ADDED: Get term from request
        version = request.args.get('version', 'current')
        history_date = request.args.get('history_date')
        
        if not exam_id or not class_id:
            return jsonify({'success': False, 'message': 'Exam ID and Class ID required'}), 400
        
        # Get exam details
        exam_response = supabase.table('exams')\
            .select('total_marks, exam_name, academic_year, term')\
            .eq('id', exam_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if not exam_response.data:
            return jsonify({'success': False, 'message': 'Exam not found'}), 404
        
        exam = exam_response.data[0]
        exam_total_marks = exam['total_marks']
        exam_term = exam.get('term')  # The exam's term from creation
        exam_year = exam.get('academic_year')
        
        # Get subjects for the class - BATCH GET
        subjects_response = supabase.table('class_subjects')\
            .select('*, subjects!inner(name)')\
            .eq('class_id', class_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        subjects = subjects_response.data if subjects_response.data else []
        
        formatted_subjects = []
        total_max_all_subjects = 0
        for subject in subjects:
            max_marks = subject['marks']
            total_max_all_subjects += max_marks
            formatted_subjects.append({
                'id': subject['subject_id'],
                'name': subject['subjects']['name'] if subject.get('subjects') else 'Unknown',
                'max_marks': max_marks
            })
        
        if not formatted_subjects:
            return jsonify({
                'success': True,
                'students': [],
                'subjects': [],
                'exam_total_marks': exam_total_marks,
                'total_max_all_subjects': 0,
                'message': 'No subjects assigned to this class'
            })
        
        # Get enrolled students for the specific academic year
        enrollments_response = supabase.table('class_enrollments')\
            .select('student_id')\
            .eq('class_id', class_id)\
            .eq('academic_year', int(academic_year))\
            .execute()
        
        student_ids = [e['student_id'] for e in enrollments_response.data] if enrollments_response.data else []
        
        if not student_ids:
            all_students_response = supabase.table('students')\
                .select('id, name, student_id')\
                .eq('institute_id', institute_id)\
                .order('name')\
                .execute()
            all_students = all_students_response.data if all_students_response.data else []
            
            marks_data = []
            for student in all_students:
                student_marks = {
                    'student_id': student['id'],
                    'student_name': student['name'],
                    'student_number': student['student_id'],
                    'subjects': [],
                    'enrollment_status': 'not_enrolled',
                    'total_obtained': 0,
                    'total_max_all_subjects': total_max_all_subjects,
                    'percentage': 0
                }
                for subject in formatted_subjects:
                    student_marks['subjects'].append({
                        'subject_id': subject['id'],
                        'subject_name': subject['name'],
                        'max_marks': subject['max_marks'],
                        'obtained': None
                    })
                marks_data.append(student_marks)
            
            return jsonify({
                'success': True,
                'students': marks_data,
                'subjects': formatted_subjects,
                'exam_total_marks': exam_total_marks,
                'total_max_all_subjects': total_max_all_subjects,
                'warning': f'No students enrolled in this class for {academic_year}. Showing all students.'
            })
        
        # Get student details - BATCH GET
        students_response = supabase.table('students')\
            .select('id, name, student_id')\
            .eq('institute_id', institute_id)\
            .in_('id', student_ids)\
            .order('name')\
            .execute()
        students = students_response.data if students_response.data else []
        
        # Get marks for this specific exam, class, and term
        # We need to find the marksheet for this term or get current marks
        if version == 'historical' and history_date:
            marks_response = supabase.table('exam_marks_history')\
                .select('*')\
                .eq('exam_id', exam_id)\
                .eq('class_id', class_id)\
                .eq('institute_id', institute_id)\
                .eq('record_date', history_date)\
                .in_('student_id', student_ids)\
                .execute()
        else:
            # IMPORTANT: Get marks from the most recent marksheet for this term
            # First, find the latest marksheet for this exam, class, and term
            marksheet_response = supabase.table('exam_marksheets')\
                .select('id')\
                .eq('exam_id', exam_id)\
                .eq('class_id', class_id)\
                .eq('institute_id', institute_id)\
                .eq('academic_year', str(academic_year))\
                .eq('term', term if term else exam_term)\
                .order('generated_at', desc=True)\
                .limit(1)\
                .execute()
            
            if marksheet_response.data:
                # Get marks for this specific marksheet
                marks_response = supabase.table('exam_marks')\
                    .select('*')\
                    .eq('exam_id', exam_id)\
                    .eq('class_id', class_id)\
                    .eq('institute_id', institute_id)\
                    .eq('marksheet_id', marksheet_response.data[0]['id'])\
                    .in_('student_id', student_ids)\
                    .execute()
            else:
                # No marksheet found for this term - return empty marks
                marks_response = supabase.table('exam_marks')\
                    .select('*')\
                    .eq('exam_id', exam_id)\
                    .eq('class_id', class_id)\
                    .eq('institute_id', institute_id)\
                    .eq('academic_year', str(academic_year))\
                    .limit(0)\
                    .execute()
        
        existing_marks = {}
        for mark in marks_response.data if marks_response.data else []:
            key = f"{mark['student_id']}_{mark['subject_id']}"
            existing_marks[key] = mark
        
        # Prepare marks data
        marks_data = []
        for student in students:
            student_marks = {
                'student_id': student['id'],
                'student_name': student['name'],
                'student_number': student['student_id'],
                'subjects': [],
                'enrollment_status': 'enrolled'
            }
            
            total_obtained = 0
            
            for subject in formatted_subjects:
                key = f"{student['id']}_{subject['id']}"
                obtained = existing_marks.get(key, {}).get('obtained_marks') if key in existing_marks else None
                
                if obtained is not None:
                    total_obtained += float(obtained)
                
                student_marks['subjects'].append({
                    'subject_id': subject['id'],
                    'subject_name': subject['name'],
                    'max_marks': subject['max_marks'],
                    'obtained': obtained
                })
            
            percentage = round((total_obtained / total_max_all_subjects * 100), 1) if total_max_all_subjects > 0 else 0
            
            student_marks['total_obtained'] = total_obtained
            student_marks['total_max_all_subjects'] = total_max_all_subjects
            student_marks['percentage'] = percentage
            marks_data.append(student_marks)
        
        return jsonify({
            'success': True,
            'students': marks_data,
            'subjects': formatted_subjects,
            'exam_total_marks': exam_total_marks,
            'total_max_all_subjects': total_max_all_subjects,
            'exam_term': exam.get('term'),
            'exam_year': exam.get('academic_year'),
            'current_term': term if term else exam_term
        })
        
    except Exception as e:
        print(f"Error getting marks: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


@exams_bp.route('/api/marks/save', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def save_marks():
    user = session.get('user')
    institute_id = get_institute(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        exam_id = data.get('exam_id')
        class_id = data.get('class_id')
        academic_year = data.get('academic_year', datetime.now().year)
        term = data.get('term')  # ADDED: Get term from request
        marks_data = data.get('marks', [])
        
        if not exam_id or not class_id:
            return jsonify({'success': False, 'message': 'Exam ID and Class ID required'}), 400
        
        if not term:
            return jsonify({'success': False, 'message': 'Term is required'}), 400
        
        # Get exam details - SINGLE QUERY
        exam_response = supabase.table('exams')\
            .select('total_marks, academic_year, term')\
            .eq('id', exam_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if not exam_response.data:
            return jsonify({'success': False, 'message': 'Exam not found'}), 404
        
        exam_total_marks = exam_response.data[0]['total_marks']
        
        # Get subject max marks for validation - SINGLE QUERY
        subjects_response = supabase.table('class_subjects')\
            .select('subject_id, marks')\
            .eq('class_id', class_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        subject_max_marks = {}
        for s in subjects_response.data if subjects_response.data else []:
            subject_max_marks[s['subject_id']] = s['marks']
        
        saved_count = 0
        errors = []
        skipped_count = 0
        
        # Check if there's an existing marksheet for this term
        existing_marksheet_response = supabase.table('exam_marksheets')\
            .select('id, marksheet_number')\
            .eq('exam_id', exam_id)\
            .eq('class_id', class_id)\
            .eq('institute_id', institute_id)\
            .eq('academic_year', str(academic_year))\
            .eq('term', term)\
            .order('generated_at', desc=True)\
            .limit(1)\
            .execute()
        
        if existing_marksheet_response.data:
            # Use existing marksheet - update marks on it
            marksheet_id = existing_marksheet_response.data[0]['id']
            marksheet_number = existing_marksheet_response.data[0]['marksheet_number']
        else:
            # Create new marksheet for this term
            marksheet_id = str(uuid.uuid4())
            marksheet_number = f"MS-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"
            
            marksheet_data = {
                'id': marksheet_id,
                'institute_id': institute_id,
                'exam_id': exam_id,
                'class_id': class_id,
                'academic_year': str(academic_year),
                'term': term,
                'marksheet_number': marksheet_number,
                'generated_at': datetime.now().isoformat(),
                'created_at': datetime.now().isoformat()
            }
            supabase.table('exam_marksheets').insert(marksheet_data).execute()
        
        # Prepare batch data
        marks_to_insert = []
        marks_to_update = []
        history_records = []
        
        # Get all existing marks in one batch query for this marksheet
        student_ids = list(set([m['student_id'] for m in marks_data]))
        subject_ids = list(set([m['subject_id'] for m in marks_data]))
        
        if student_ids and subject_ids:
            existing_response = supabase.table('exam_marks')\
                .select('id, student_id, subject_id, obtained_marks')\
                .eq('exam_id', exam_id)\
                .eq('class_id', class_id)\
                .eq('institute_id', institute_id)\
                .eq('marksheet_id', marksheet_id)\
                .in_('student_id', student_ids)\
                .in_('subject_id', subject_ids)\
                .execute()
            
            existing_map = {}
            for record in existing_response.data if existing_response.data else []:
                key = f"{record['student_id']}_{record['subject_id']}"
                existing_map[key] = record
        
        for mark_entry in marks_data:
            try:
                student_id = mark_entry.get('student_id')
                subject_id = mark_entry.get('subject_id')
                obtained_marks = mark_entry.get('obtained_marks')
                
                if obtained_marks is None or obtained_marks == '':
                    skipped_count += 1
                    continue
                
                obtained_marks = float(obtained_marks)
                
                # Validate against subject max marks
                subject_max = subject_max_marks.get(subject_id, 0)
                if obtained_marks > subject_max:
                    errors.append(f"Marks ({obtained_marks}) exceed subject max ({subject_max}) for student {student_id}")
                    continue
                
                # Validate against exam total
                if obtained_marks > exam_total_marks:
                    errors.append(f"Marks ({obtained_marks}) exceed exam total ({exam_total_marks}) for student {student_id}")
                    continue
                
                key = f"{student_id}_{subject_id}"
                
                if key in existing_map:
                    # Save to history before updating
                    history_records.append({
                        'id': str(uuid.uuid4()),
                        'institute_id': institute_id,
                        'exam_id': exam_id,
                        'class_id': class_id,
                        'student_id': student_id,
                        'subject_id': subject_id,
                        'obtained_marks': existing_map[key]['obtained_marks'],
                        'exam_total_marks': exam_total_marks,
                        'marksheet_id': marksheet_id,
                        'record_date': datetime.now().date().isoformat(),
                        'created_at': datetime.now().isoformat()
                    })
                    
                    marks_to_update.append({
                        'id': existing_map[key]['id'],
                        'obtained_marks': obtained_marks,
                        'exam_total_marks': exam_total_marks,
                        'marksheet_id': marksheet_id,
                        'updated_at': datetime.now().isoformat()
                    })
                else:
                    # Insert new
                    mark_id = str(uuid.uuid4())
                    marks_to_insert.append({
                        'id': mark_id,
                        'institute_id': institute_id,
                        'exam_id': exam_id,
                        'class_id': class_id,
                        'student_id': student_id,
                        'subject_id': subject_id,
                        'obtained_marks': obtained_marks,
                        'exam_total_marks': exam_total_marks,
                        'marksheet_id': marksheet_id,
                        'created_at': datetime.now().isoformat(),
                        'updated_at': datetime.now().isoformat()
                    })
                    
                    # Save initial entry to history
                    history_records.append({
                        'id': str(uuid.uuid4()),
                        'institute_id': institute_id,
                        'exam_id': exam_id,
                        'class_id': class_id,
                        'student_id': student_id,
                        'subject_id': subject_id,
                        'obtained_marks': obtained_marks,
                        'exam_total_marks': exam_total_marks,
                        'marksheet_id': marksheet_id,
                        'record_date': datetime.now().date().isoformat(),
                        'created_at': datetime.now().isoformat()
                    })
                
                saved_count += 1
                
            except Exception as e:
                errors.append(f"Error saving marks for student {mark_entry.get('student_id')}: {str(e)}")
        
        # Execute batch operations
        if history_records:
            supabase.table('exam_marks_history').insert(history_records).execute()
        
        if marks_to_insert:
            supabase.table('exam_marks').insert(marks_to_insert).execute()
        
        if marks_to_update:
            for update in marks_to_update:
                supabase.table('exam_marks')\
                    .update(update)\
                    .eq('id', update['id'])\
                    .execute()
        
        return jsonify({
            'success': True,
            'message': f'Saved {saved_count} mark(s) successfully',
            'marksheet_id': marksheet_id,
            'marksheet_number': marksheet_number,
            'term': term,
            'skipped': skipped_count,
            'errors': errors if errors else None
        })
        
    except Exception as e:
        print(f"Error saving marks: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@exams_bp.route('/api/marksheets/list', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def list_marksheets():
    """List all marksheets filtered by year, term, and exam"""
    user = session.get('user')
    institute_id = get_institute(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        academic_year = request.args.get('academic_year')
        term = request.args.get('term')
        exam_id = request.args.get('exam_id')
        class_id = request.args.get('class_id')
        
        query = supabase.table('exam_marksheets')\
            .select('*, exams(exam_name, total_marks), classes(name)')\
            .eq('institute_id', institute_id)
        
        if academic_year:
            query = query.eq('academic_year', academic_year)
        if term:
            query = query.eq('term', term)
        if exam_id:
            query = query.eq('exam_id', exam_id)
        if class_id:
            query = query.eq('class_id', class_id)
        
        response = query.order('generated_at', desc=True).execute()
        marksheets = response.data if response.data else []
        
        return jsonify({'success': True, 'marksheets': marksheets})
        
    except Exception as e:
        print(f"Error listing marksheets: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@exams_bp.route('/api/marks/by-marksheet', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_marks_by_marksheet():
    """Get marks for a specific marksheet"""
    user = session.get('user')
    institute_id = get_institute(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        marksheet_id = request.args.get('marksheet_id')
        
        if not marksheet_id:
            return jsonify({'success': False, 'message': 'Marksheet ID required'}), 400
        
        # Get marksheet details
        marksheet_response = supabase.table('exam_marksheets')\
            .select('*, exams(exam_name, total_marks, exam_date), classes(name)')\
            .eq('id', marksheet_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if not marksheet_response.data:
            return jsonify({'success': False, 'message': 'Marksheet not found'}), 404
        
        marksheet = marksheet_response.data[0]
        exam = marksheet.get('exams', {})
        exam_total_marks = exam.get('total_marks', 0)
        
        # Get all marks for this marksheet - BATCH GET
        marks_response = supabase.table('exam_marks')\
            .select('*, students(name, student_id)')\
            .eq('marksheet_id', marksheet_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        marks = marks_response.data if marks_response.data else []
        
        # Get subjects for the class - BATCH GET
        subjects_response = supabase.table('class_subjects')\
            .select('*, subjects(name)')\
            .eq('class_id', marksheet['class_id'])\
            .eq('institute_id', institute_id)\
            .execute()
        
        subjects = subjects_response.data if subjects_response.data else []
        
        # Calculate total max marks
        total_max_all_subjects = sum([s['marks'] for s in subjects])
        
        # Group marks by student
        students_marks = {}
        for mark in marks:
            student_id = mark['student_id']
            if student_id not in students_marks:
                students_marks[student_id] = {
                    'student_id': student_id,
                    'student_name': mark['students']['name'] if mark.get('students') else 'N/A',
                    'student_number': mark['students']['student_id'] if mark.get('students') else 'N/A',
                    'marks': {}
                }
            students_marks[student_id]['marks'][mark['subject_id']] = mark['obtained_marks']
        
        # Prepare marks data
        marks_data = []
        for student_id, student_data in students_marks.items():
            student_marks = {
                'student_id': student_data['student_id'],
                'student_name': student_data['student_name'],
                'student_number': student_data['student_number'],
                'subjects': []
            }
            
            total_obtained = 0
            
            for subject in subjects:
                subject_id = subject['subject_id']
                subject_name = subject['subjects']['name'] if subject.get('subjects') else 'N/A'
                max_marks = subject['marks']
                
                obtained = student_data['marks'].get(subject_id)
                
                student_marks['subjects'].append({
                    'subject_id': subject_id,
                    'subject_name': subject_name,
                    'max_marks': max_marks,
                    'obtained': obtained
                })
                
                if obtained:
                    total_obtained += float(obtained)
            
            # CORRECT PERCENTAGE: based on total max marks across all subjects
            percentage = round((total_obtained / total_max_all_subjects * 100), 1) if total_max_all_subjects > 0 else 0
            
            student_marks['total_obtained'] = total_obtained
            student_marks['total_max_all_subjects'] = total_max_all_subjects
            student_marks['percentage'] = percentage
            marks_data.append(student_marks)
        
        return jsonify({
            'success': True,
            'marksheet': {
                'id': marksheet['id'],
                'marksheet_number': marksheet['marksheet_number'],
                'exam_name': exam.get('exam_name', 'N/A'),
                'exam_date': exam.get('exam_date', 'N/A'),
                'class_name': marksheet.get('classes', {}).get('name', 'N/A'),
                'academic_year': marksheet['academic_year'],
                'term': marksheet['term'],
                'generated_at': marksheet['generated_at']
            },
            'students': marks_data,
            'subjects': [{'id': s['subject_id'], 'name': s['subjects']['name'], 'max_marks': s['marks']} for s in subjects],
            'exam_total_marks': exam_total_marks,
            'total_max_all_subjects': total_max_all_subjects
        })
        
    except Exception as e:
        print(f"Error getting marks by marksheet: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@exams_bp.route('/api/marksheet/excel', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def export_marksheet_excel():
    user = session.get('user')
    institute_id = get_institute(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        exam_id = data.get('exam_id')
        class_id = data.get('class_id')
        academic_year = data.get('academic_year', datetime.now().year)
        version = data.get('version', 'current')
        history_date = data.get('history_date')
        
        if not exam_id or not class_id:
            return jsonify({'success': False, 'message': 'Exam ID and Class ID required'}), 400
        
        # Get institute details
        institute_response = supabase.table('institutes')\
            .select('*')\
            .eq('id', institute_id)\
            .execute()
        institute = institute_response.data[0] if institute_response.data else {}
        
        # Get exam details
        exam_response = supabase.table('exams')\
            .select('*, classes(name)')\
            .eq('id', exam_id)\
            .execute()
        exam = exam_response.data[0] if exam_response.data else None
        
        # Get class details
        class_response = supabase.table('classes')\
            .select('*')\
            .eq('id', class_id)\
            .execute()
        class_info = class_response.data[0] if class_response.data else None
        
        # Get students - BATCH GET
        enrollments_response = supabase.table('class_enrollments')\
            .select('student_id')\
            .eq('class_id', class_id)\
            .eq('academic_year', int(academic_year))\
            .execute()
        
        student_ids = [e['student_id'] for e in enrollments_response.data] if enrollments_response.data else []
        
        all_students = []
        if student_ids:
            students_response = supabase.table('students')\
                .select('id, name, student_id')\
                .eq('institute_id', institute_id)\
                .in_('id', student_ids)\
                .order('name')\
                .execute()
            all_students = students_response.data if students_response.data else []
        
        # Get subjects - BATCH GET
        subjects_response = supabase.table('class_subjects')\
            .select('*, subjects(name)')\
            .eq('class_id', class_id)\
            .eq('institute_id', institute_id)\
            .order('created_at')\
            .execute()
        subjects = subjects_response.data if subjects_response.data else []
        
        # Calculate total max marks
        total_max_all_subjects = sum([s['marks'] for s in subjects])
        
        # Get marks - BATCH GET
        if version == 'historical' and history_date:
            marks_response = supabase.table('exam_marks_history')\
                .select('*')\
                .eq('exam_id', exam_id)\
                .eq('class_id', class_id)\
                .eq('institute_id', institute_id)\
                .eq('record_date', history_date)\
                .execute()
        else:
            if student_ids:
                marks_response = supabase.table('exam_marks')\
                    .select('*')\
                    .eq('exam_id', exam_id)\
                    .eq('class_id', class_id)\
                    .eq('institute_id', institute_id)\
                    .in_('student_id', student_ids)\
                    .execute()
            else:
                marks_response = supabase.table('exam_marks')\
                    .select('*')\
                    .eq('exam_id', exam_id)\
                    .eq('class_id', class_id)\
                    .eq('institute_id', institute_id)\
                    .execute()
        
        # Group marks by student
        students_marks = {}
        for mark in marks_response.data if marks_response.data else []:
            student_id = mark['student_id']
            if student_id not in students_marks:
                students_marks[student_id] = {'marks': {}}
            students_marks[student_id]['marks'][mark['subject_id']] = mark['obtained_marks']
        
        # Calculate statistics
        percentages = []
        highest_score = 0
        lowest_score = 100
        
        # Create DataFrame
        data_rows = []
        exam_total_marks = exam['total_marks'] if exam else 0
        
        for idx, student in enumerate(all_students, 1):
            row = {'S/N': idx, 'Student Name': student['name'], 'Student ID': student['student_id']}
            total_obtained = 0
            
            for subject in subjects:
                subject_name = subject['subjects']['name'] if subject.get('subjects') else 'N/A'
                
                if student['id'] in students_marks:
                    obtained = students_marks[student['id']]['marks'].get(subject['subject_id'], '-')
                    if obtained != '-':
                        total_obtained += float(obtained)
                    row[subject_name] = obtained if obtained != '-' else '-'
                else:
                    row[subject_name] = '-'
            
            # CORRECT PERCENTAGE: based on total max marks across all subjects
            percentage = round((total_obtained / total_max_all_subjects * 100), 1) if total_max_all_subjects > 0 else 0
            percentages.append(percentage)
            if percentage > highest_score:
                highest_score = percentage
            if percentage < lowest_score:
                lowest_score = percentage
            
            row['Total'] = f"{total_obtained}/{total_max_all_subjects}"
            row['Percentage'] = f"{percentage}%"
            data_rows.append(row)
        
        if not data_rows:
            return jsonify({'success': False, 'message': 'No data to export'}), 404
        
        df = pd.DataFrame(data_rows)
        class_average = sum(percentages) / len(percentages) if percentages else 0
        
        # Create Excel file
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Marksheet', index=False)
            
            workbook = writer.book
            worksheet = writer.sheets['Marksheet']
            
            header_font = Font(name='Calibri', size=11, bold=True, color='FFFFFF')
            header_fill = PatternFill(start_color='1e3a5f', end_color='1e3a5f', fill_type='solid')
            header_alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
            cell_alignment_center = Alignment(horizontal='center', vertical='center')
            cell_alignment_left = Alignment(horizontal='left', vertical='center')
            thin_border = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))
            
            # Style headers
            for col in range(1, len(df.columns) + 1):
                cell = worksheet.cell(row=1, column=col)
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = header_alignment
                cell.border = thin_border
                column_letter = get_column_letter(col)
                max_length = max(df[df.columns[col-1]].astype(str).map(len).max(), len(df.columns[col-1])) + 2
                worksheet.column_dimensions[column_letter].width = min(max_length, 25)
            
            # Style data cells
            for row in range(2, len(df) + 2):
                for col in range(1, len(df.columns) + 1):
                    cell = worksheet.cell(row=row, column=col)
                    cell.border = thin_border
                    cell.alignment = cell_alignment_center if col != 2 else cell_alignment_left
                    if row % 2 == 0:
                        cell.fill = PatternFill(start_color='f8fafc', end_color='f8fafc', fill_type='solid')
            
            # Add title row
            worksheet.insert_rows(1)
            worksheet.row_dimensions[1].height = 30
            institute_cell = worksheet.cell(row=1, column=1, value=institute.get('institute_name', 'SCHOOL NAME'))
            institute_cell.font = Font(name='Calibri', size=16, bold=True, color='1e3a5f')
            institute_cell.alignment = Alignment(horizontal='center', vertical='center')
            worksheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(df.columns))
            
            # Add info row
            worksheet.insert_rows(2)
            term_info = f"Term: {exam.get('term', 'N/A')} | Year: {exam.get('academic_year', 'N/A')}" if exam else ''
            version_text = f"{version.upper()} MARKS" if version == 'current' else f"HISTORICAL MARKS - {history_date}"
            info_cell = worksheet.cell(row=2, column=1, value=f"EXAMINATION: {exam['exam_name'] if exam else 'N/A'} | CLASS: {class_info['name'] if class_info else 'N/A'} | {term_info} | {version_text} | DATE: {datetime.now().strftime('%d %B, %Y')}")
            info_cell.font = Font(name='Calibri', size=10, italic=True, color='4b5563')
            info_cell.alignment = Alignment(horizontal='center', vertical='center')
            worksheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(df.columns))
            
            # Adjust header row
            for col in range(1, len(df.columns) + 1):
                header_cell = worksheet.cell(row=3, column=col)
                header_cell.font = header_font
                header_cell.fill = header_fill
                header_cell.alignment = header_alignment
                header_cell.border = thin_border
            
            # Add summary sheet
            summary_data = {
                'Metric': ['Version', 'Academic Year', 'Term', 'Total Students', 'Total Subjects', 'Total Max Marks', 'Class Average', 'Highest Score', 'Lowest Score'],
                'Value': [
                    version_text,
                    exam.get('academic_year', 'N/A') if exam else 'N/A',
                    exam.get('term', 'N/A') if exam else 'N/A',
                    len(all_students),
                    len(subjects),
                    total_max_all_subjects,
                    f"{class_average:.1f}%",
                    f"{highest_score:.1f}%",
                    f"{lowest_score:.1f}%"
                ]
            }
            summary_df = pd.DataFrame(summary_data)
            summary_df.to_excel(writer, sheet_name='Summary', index=False)
            
            summary_ws = writer.sheets['Summary']
            for col in range(1, 3):
                summary_ws.column_dimensions[get_column_letter(col)].width = 25
                header_cell = summary_ws.cell(row=1, column=col)
                header_cell.font = header_font
                header_cell.fill = header_fill
                header_cell.alignment = header_alignment
        
        output.seek(0)
        
        filename = f"MARKSHEET_{exam['exam_name']}_{class_info['name']}_{exam.get('academic_year', '')}_{exam.get('term', '')}_{version}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        
        return send_file(output, as_attachment=True, download_name=filename, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        
    except Exception as e:
        print(f"Error generating marksheet Excel: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@exams_bp.route('/api/filters', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_filters():
    """Get available years and terms for filters"""
    user = session.get('user')
    institute_id = get_institute(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        years_response = supabase.table('exams')\
            .select('academic_year')\
            .eq('institute_id', institute_id)\
            .execute()
        years = sorted(set([y['academic_year'] for y in years_response.data if y.get('academic_year')])) if years_response.data else []
        
        terms_response = supabase.table('exams')\
            .select('term')\
            .eq('institute_id', institute_id)\
            .execute()
        terms = sorted(set([t['term'] for t in terms_response.data if t.get('term')])) if terms_response.data else []
        
        classes_response = supabase.table('classes')\
            .select('id, name')\
            .eq('institute_id', institute_id)\
            .order('name')\
            .execute()
        classes = classes_response.data if classes_response.data else []
        
        return jsonify({
            'success': True,
            'years': years,
            'terms': terms,
            'classes': classes
        })
        
    except Exception as e:
        print(f"Error getting filters: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@exams_bp.route('/api/marks/history/dates', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_history_dates():
    """Get available history dates for an exam and class"""
    user = session.get('user')
    institute_id = get_institute(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        exam_id = request.args.get('exam_id')
        class_id = request.args.get('class_id')
        
        if not exam_id or not class_id:
            return jsonify({'success': False, 'message': 'Exam ID and Class ID required'}), 400
        
        response = supabase.table('exam_marks_history')\
            .select('record_date')\
            .eq('exam_id', exam_id)\
            .eq('class_id', class_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        dates_set = set()
        for record in response.data if response.data else []:
            if record.get('record_date'):
                dates_set.add(record['record_date'])
        
        dates = sorted(list(dates_set), reverse=True)
        
        return jsonify({'success': True, 'dates': dates})
        
    except Exception as e:
        print(f"Error getting history dates: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500