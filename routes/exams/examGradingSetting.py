# examGradingSetting.py - Exam Grading Settings Blueprint
from flask import Blueprint, render_template, request, jsonify, session
from supabase import create_client, Client
import os
import uuid
from datetime import datetime
import json
from functools import wraps
from dotenv import load_dotenv

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

grading_bp = Blueprint('grading', __name__, url_prefix='/exam-grading')

def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Please login'}), 401
        return f(*args, **kwargs)
    return decorated_function

def get_institute_id(user_id):
    """Get institute for the current user"""
    try:
        response = supabase.table('institutes')\
            .select('id')\
            .eq('user_id', user_id)\
            .execute()
        
        if response.data and len(response.data) > 0:
            return response.data[0]['id']
        return None
    except Exception as e:
        print(f"Error getting institute: {e}")
        return None

@grading_bp.route('/')
@login_required
def index():
    """Exam Grading Settings Page"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return render_template('grading/index.html', grades=[], fail_criteria=None)
    
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
        
        return render_template('grading/index.html', grades=grades, fail_criteria=fail_criteria)
        
    except Exception as e:
        print(f"Error loading grading page: {e}")
        return render_template('grading/index.html', grades=[], fail_criteria={'overall_percentage': 30, 'subject_percentage': 15})

@grading_bp.route('/api/grades', methods=['GET'])
@login_required
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
@login_required
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
        
        # Insert new grades
        saved_count = 0
        for grade in grades:
            grade_data = {
                'id': str(uuid.uuid4()),
                'institute_id': institute_id,
                'grade_name': grade.get('grade_name', '').strip().upper(),
                'min_percentage': float(grade.get('min_percentage')),
                'max_percentage': float(grade.get('max_percentage')),
                'status': grade.get('status', 'Pass'),
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

@grading_bp.route('/api/fail-criteria/save', methods=['POST'])
@login_required
def save_fail_criteria():
    """Save fail criteria settings"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        overall_percentage = data.get('overall_percentage', 30)
        subject_percentage = data.get('subject_percentage', 15)
        
        # Validate
        if overall_percentage < 0 or overall_percentage > 100:
            return jsonify({'success': False, 'message': 'Overall percentage must be between 0 and 100'}), 400
        
        if subject_percentage < 0 or subject_percentage > 100:
            return jsonify({'success': False, 'message': 'Subject percentage must be between 0 and 100'}), 400
        
        # Check if exists
        existing = supabase.table('exam_fail_criteria')\
            .select('id')\
            .eq('institute_id', institute_id)\
            .execute()
        
        if existing.data:
            # Update
            result = supabase.table('exam_fail_criteria')\
                .update({
                    'overall_percentage': overall_percentage,
                    'subject_percentage': subject_percentage,
                    'updated_at': datetime.now().isoformat()
                })\
                .eq('institute_id', institute_id)\
                .execute()
        else:
            # Insert
            fail_data = {
                'id': str(uuid.uuid4()),
                'institute_id': institute_id,
                'overall_percentage': overall_percentage,
                'subject_percentage': subject_percentage,
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }
            result = supabase.table('exam_fail_criteria').insert(fail_data).execute()
        
        if result.data:
            return jsonify({'success': True, 'message': 'Fail criteria saved successfully'})
        else:
            return jsonify({'success': False, 'message': 'Failed to save fail criteria'}), 500
            
    except Exception as e:
        print(f"Error saving fail criteria: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@grading_bp.route('/api/reset-default', methods=['POST'])
@login_required
def reset_default():
    """Reset to default grading settings"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Default grading scale
        default_grades = [
            {'grade_name': 'A', 'min_percentage': 80, 'max_percentage': 100, 'status': 'Pass'},
            {'grade_name': 'B', 'min_percentage': 70, 'max_percentage': 79, 'status': 'Pass'},
            {'grade_name': 'C', 'min_percentage': 60, 'max_percentage': 69, 'status': 'Pass'},
            {'grade_name': 'D', 'min_percentage': 50, 'max_percentage': 59, 'status': 'Pass'},
            {'grade_name': 'F', 'min_percentage': 0, 'max_percentage': 49, 'status': 'Fail'}
        ]
        
        # Delete existing
        supabase.table('exam_grading')\
            .delete()\
            .eq('institute_id', institute_id)\
            .execute()
        
        # Insert default grades
        for grade in default_grades:
            grade_data = {
                'id': str(uuid.uuid4()),
                'institute_id': institute_id,
                'grade_name': grade['grade_name'],
                'min_percentage': grade['min_percentage'],
                'max_percentage': grade['max_percentage'],
                'status': grade['status'],
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }
            supabase.table('exam_grading').insert(grade_data).execute()
        
        # Reset fail criteria
        default_fail = {
            'overall_percentage': 30,
            'subject_percentage': 15
        }
        
        existing_fail = supabase.table('exam_fail_criteria')\
            .select('id')\
            .eq('institute_id', institute_id)\
            .execute()
        
        if existing_fail.data:
            supabase.table('exam_fail_criteria')\
                .update({
                    'overall_percentage': default_fail['overall_percentage'],
                    'subject_percentage': default_fail['subject_percentage'],
                    'updated_at': datetime.now().isoformat()
                })\
                .eq('institute_id', institute_id)\
                .execute()
        else:
            fail_data = {
                'id': str(uuid.uuid4()),
                'institute_id': institute_id,
                'overall_percentage': default_fail['overall_percentage'],
                'subject_percentage': default_fail['subject_percentage'],
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }
            supabase.table('exam_fail_criteria').insert(fail_data).execute()
        
        return jsonify({'success': True, 'message': 'Reset to default settings successfully'})
        
    except Exception as e:
        print(f"Error resetting to default: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@grading_bp.route('/api/calculate-grade', methods=['POST'])
@login_required
def calculate_grade():
    """Calculate grade based on percentage"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        percentage = float(data.get('percentage', 0))
        
        # Get grading settings
        grades_response = supabase.table('exam_grading')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('min_percentage', desc=True)\
            .execute()
        
        grades = grades_response.data if grades_response.data else []
        
        # Find matching grade
        grade_info = None
        for grade in grades:
            if grade['min_percentage'] <= percentage <= grade['max_percentage']:
                grade_info = grade
                break
        
        # Get fail criteria
        fail_response = supabase.table('exam_fail_criteria')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .execute()
        
        fail_criteria = fail_response.data[0] if fail_response.data else {'overall_percentage': 30, 'subject_percentage': 15}
        
        # Determine if fail
        is_fail = percentage <= fail_criteria.get('overall_percentage', 30)
        
        return jsonify({
            'success': True,
            'grade': grade_info['grade_name'] if grade_info else 'N/A',
            'status': grade_info['status'] if grade_info else ('Fail' if is_fail else 'Pass'),
            'is_fail': is_fail,
            'fail_criteria': fail_criteria
        })
        
    except Exception as e:
        print(f"Error calculating grade: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500