# studentAttendance.py - Fixed without marked_by column
from flask import Blueprint, render_template, request, jsonify, session
from supabase import create_client, Client
import os
from datetime import datetime, timedelta
import uuid
from functools import wraps
from dotenv import load_dotenv

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

attendance_bp = Blueprint('attendance', __name__, url_prefix='/attendance')

def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Please login'}), 401
        return f(*args, **kwargs)
    return decorated_function

def get_institute(user_id):
    """Get institute for the current user"""
    try:
        response = supabase.table('institutes')\
            .select('*')\
            .eq('user_id', user_id)\
            .execute()
        
        if response.data and len(response.data) > 0:
            return response.data[0]
        return None
    except Exception as e:
        print(f"Error getting institute: {e}")
        return None

@attendance_bp.route('/')
@login_required
def index():
    """Attendance Scanner Page"""
    user = session.get('user')
    institute = get_institute(user['id'])
    
    if not institute:
        return render_template('attendance/index.html', institute=None, classes=[], students=[])
    
    try:
        # Get all classes for manual attendance
        classes_response = supabase.table('classes')\
            .select('*')\
            .eq('institute_id', institute['id'])\
            .order('name')\
            .execute()
        
        classes = classes_response.data if classes_response.data else []
        
        # Get all active students
        students_response = supabase.table('students')\
            .select('id, name, student_id, class_id, classes(name)')\
            .eq('institute_id', institute['id'])\
            .eq('status', 'active')\
            .order('name')\
            .execute()
        
        students = students_response.data if students_response.data else []
        
        return render_template('attendance/index.html', institute=institute, classes=classes, students=students)
        
    except Exception as e:
        print(f"Error loading attendance page: {e}")
        return render_template('attendance/index.html', institute=institute, classes=[], students=[])

@attendance_bp.route('/scan', methods=['POST'])
@login_required
def scan_qr():
    """Process QR code scan and record attendance"""
    user = session.get('user')
    institute = get_institute(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        qr_data = data.get('qr_data', '')
        
        if not qr_data:
            return jsonify({'success': False, 'message': 'No QR data received'}), 400
        
        print(f"Received QR data: {qr_data}")
        
        # Parse QR data format: "institute_code|student_id|name"
        parts = qr_data.split('|')
        
        if len(parts) < 2:
            return jsonify({'success': False, 'message': 'Invalid QR code format'}), 400
        
        scanned_institute_code = parts[0]
        student_id = parts[1]
        student_name = parts[2] if len(parts) > 2 else ''
        
        print(f"Parsed QR data: {parts}")
        print(f"Institute code from QR: {scanned_institute_code}")
        print(f"Actual institute code: {institute.get('institute_code')}")
        
        # Verify institute matches by comparing institute_code
        if scanned_institute_code != institute.get('institute_code'):
            return jsonify({
                'success': False, 
                'message': f'QR code belongs to different institution. Expected: {institute.get("institute_code")}, Got: {scanned_institute_code}'
            }), 403
        
        return record_attendance(student_id, institute)
            
    except Exception as e:
        print(f"Error processing QR scan: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@attendance_bp.route('/manual', methods=['POST'])
@login_required
def manual_attendance():
    """Record manual attendance for a student"""
    user = session.get('user')
    institute = get_institute(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        student_id = data.get('student_id')
        
        if not student_id:
            return jsonify({'success': False, 'message': 'Student ID required'}), 400
        
        return record_attendance_by_id(student_id, institute)
        
    except Exception as e:
        print(f"Error processing manual attendance: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@attendance_bp.route('/bulk', methods=['POST'])
@login_required
def bulk_attendance():
    """Record bulk attendance for multiple students"""
    user = session.get('user')
    institute = get_institute(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        student_ids = data.get('student_ids', [])
        class_id = data.get('class_id')
        
        if not student_ids and not class_id:
            return jsonify({'success': False, 'message': 'No students selected'}), 400
        
        # If class_id provided but no specific students, get all students in class
        if class_id and not student_ids:
            students_response = supabase.table('students')\
                .select('id')\
                .eq('class_id', class_id)\
                .eq('institute_id', institute['id'])\
                .eq('status', 'active')\
                .execute()
            
            if students_response.data:
                student_ids = [s['id'] for s in students_response.data]
        
        if not student_ids:
            return jsonify({'success': False, 'message': 'No students found'}), 404
        
        successful = []
        failed = []
        
        for student_id in student_ids:
            result = record_attendance_by_id(student_id, institute, silent=True)
            if result.get('success'):
                successful.append(student_id)
            else:
                failed.append({'id': student_id, 'reason': result.get('message')})
        
        return jsonify({
            'success': True,
            'message': f'Successfully marked attendance for {len(successful)} student(s)',
            'successful_count': len(successful),
            'failed_count': len(failed),
            'failed': failed if failed else None
        })
        
    except Exception as e:
        print(f"Error processing bulk attendance: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

def record_attendance(student_id, institute):
    """Record attendance using student_id (string like PRI202600001)"""
    # Check if student exists in database
    student_response = supabase.table('students')\
        .select('id, name, student_id, class_id, classes(name), status, contact_number')\
        .eq('student_id', student_id)\
        .eq('institute_id', institute['id'])\
        .execute()
    
    print(f"Student lookup result: {student_response.data}")
    
    if not student_response.data:
        return jsonify({'success': False, 'message': f'Student with ID {student_id} not found'}), 404
    
    student = student_response.data[0]
    
    return record_attendance_by_id(student['id'], institute)

def record_attendance_by_id(student_uuid, institute, silent=False):
    """Record attendance using student UUID"""
    # Get student details
    student_response = supabase.table('students')\
        .select('id, name, student_id, class_id, classes(name), status, contact_number')\
        .eq('id', student_uuid)\
        .eq('institute_id', institute['id'])\
        .execute()
    
    if not student_response.data:
        return {'success': False, 'message': 'Student not found'}
    
    student = student_response.data[0]
    
    # Check if student is active
    if student.get('status') != 'active':
        return {'success': False, 'message': f'Student {student["name"]} is not active'}
    
    # Check if already marked present today
    today = datetime.now().date().isoformat()
    today_check = supabase.table('attendance')\
        .select('id')\
        .eq('student_id', student['id'])\
        .eq('institute_id', institute['id'])\
        .eq('scan_date', today)\
        .execute()
    
    if today_check.data:
        return {'success': False, 'message': f'{student["name"]} already marked present today'}
    
    # Record attendance
    attendance_id = str(uuid.uuid4())
    attendance_data = {
        'id': attendance_id,
        'institute_id': institute['id'],
        'student_id': student['id'],
        'student_name': student['name'],
        'student_number': student['student_id'],
        'class_name': student['classes']['name'] if student.get('classes') else 'N/A',
        'scan_time': datetime.now().isoformat(),
        'scan_date': today,
        'created_at': datetime.now().isoformat()
    }
    
    result = supabase.table('attendance').insert(attendance_data).execute()
    
    if result.data:
        if not silent:
            return {
                'success': True,
                'message': f'Attendance recorded for {student["name"]}',
                'student': {
                    'id': student['id'],
                    'student_id': student['student_id'],
                    'name': student['name'],
                    'class': student['classes']['name'] if student.get('classes') else 'N/A',
                    'contact': student.get('contact_number', 'N/A'),
                    'scan_time': datetime.now().strftime('%H:%M:%S'),
                    'scan_date': today
                }
            }
        else:
            return {'success': True, 'message': f'Attendance recorded for {student["name"]}'}
    else:
        return {'success': False, 'message': 'Failed to record attendance'}

@attendance_bp.route('/today', methods=['GET'])
@login_required
def get_today_attendance():
    """Get today's attendance records"""
    user = session.get('user')
    institute = get_institute(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        today = datetime.now().date().isoformat()
        
        response = supabase.table('attendance')\
            .select('*, students(photo_url)')\
            .eq('institute_id', institute['id'])\
            .eq('scan_date', today)\
            .order('created_at', desc=True)\
            .execute()
        
        attendance = response.data if response.data else []
        
        # Add photo URLs
        for record in attendance:
            if record.get('students') and record['students'].get('photo_url'):
                record['photo_url'] = record['students']['photo_url']
        
        return jsonify({'success': True, 'attendance': attendance, 'count': len(attendance)})
        
    except Exception as e:
        print(f"Error getting today's attendance: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@attendance_bp.route('/stats', methods=['GET'])
@login_required
def get_attendance_stats():
    """Get attendance statistics"""
    user = session.get('user')
    institute = get_institute(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Get today's attendance count
        today = datetime.now().date().isoformat()
        today_response = supabase.table('attendance')\
            .select('id', count='exact')\
            .eq('institute_id', institute['id'])\
            .eq('scan_date', today)\
            .execute()
        
        today_count = today_response.count or 0
        
        # Get total active students
        students_response = supabase.table('students')\
            .select('id', count='exact')\
            .eq('institute_id', institute['id'])\
            .eq('status', 'active')\
            .execute()
        
        total_students = students_response.count or 0
        
        # Get this week's attendance
        week_ago = (datetime.now() - timedelta(days=7)).date().isoformat()
        week_response = supabase.table('attendance')\
            .select('id', count='exact')\
            .eq('institute_id', institute['id'])\
            .gte('scan_date', week_ago)\
            .execute()
        
        week_count = week_response.count or 0
        
        return jsonify({
            'success': True,
            'stats': {
                'today_count': today_count,
                'total_students': total_students,
                'attendance_percentage': round((today_count / total_students * 100) if total_students > 0 else 0, 1),
                'week_count': week_count
            }
        })
        
    except Exception as e:
        print(f"Error getting attendance stats: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@attendance_bp.route('/students/search', methods=['GET'])
@login_required
def search_students():
    """Search students for manual attendance"""
    user = session.get('user')
    institute = get_institute(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        search_term = request.args.get('q', '').strip()
        class_id = request.args.get('class_id', '')
        
        query = supabase.table('students')\
            .select('id, name, student_id, class_id, classes(name), status')\
            .eq('institute_id', institute['id'])\
            .eq('status', 'active')
        
        if class_id:
            query = query.eq('class_id', class_id)
        
        if search_term and len(search_term) >= 2:
            query = query.or_(f"name.ilike.%{search_term}%,student_id.ilike.%{search_term}%")
        
        response = query.limit(50).execute()
        
        students = response.data if response.data else []
        
        # Mark which students are already present today
        today = datetime.now().date().isoformat()
        present_response = supabase.table('attendance')\
            .select('student_id')\
            .eq('institute_id', institute['id'])\
            .eq('scan_date', today)\
            .execute()
        
        present_ids = set(a['student_id'] for a in present_response.data) if present_response.data else set()
        
        for student in students:
            student['is_present'] = student['id'] in present_ids
        
        return jsonify({'success': True, 'students': students})
        
    except Exception as e:
        print(f"Error searching students: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500