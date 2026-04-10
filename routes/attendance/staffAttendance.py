# staffAttendance.py - Staff Attendance with QR Code Scanning (Fixed)
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

staff_attendance_bp = Blueprint('staff_attendance', __name__, url_prefix='/staff-attendance')

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

@staff_attendance_bp.route('/')
@login_required
def index():
    """Staff Attendance Page"""
    user = session.get('user')
    institute = get_institute(user['id'])
    
    if not institute:
        return render_template('staff_attendance/index.html', institute=None, roles=[], employees=[])
    
    try:
        # Get all roles for filter
        roles_response = supabase.table('employees')\
            .select('role')\
            .eq('institute_id', institute['id'])\
            .eq('status', 'active')\
            .execute()
        
        roles = list(set([r['role'] for r in roles_response.data])) if roles_response.data else []
        
        # Get all active employees
        employees_response = supabase.table('employees')\
            .select('id, name, employee_id, role, photo_url')\
            .eq('institute_id', institute['id'])\
            .eq('status', 'active')\
            .order('name')\
            .execute()
        
        employees = employees_response.data if employees_response.data else []
        
        return render_template('staff_attendance/index.html', institute=institute, roles=roles, employees=employees)
        
    except Exception as e:
        print(f"Error loading staff attendance page: {e}")
        return render_template('staff_attendance/index.html', institute=institute, roles=[], employees=[])

@staff_attendance_bp.route('/scan', methods=['POST'])
@login_required
def scan_qr():
    """Process QR code scan and record staff attendance"""
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
        
        # Parse QR data format: "institute_code|employee_id|name"
        parts = qr_data.split('|')
        
        if len(parts) < 2:
            return jsonify({'success': False, 'message': 'Invalid QR code format'}), 400
        
        scanned_institute_code = parts[0]
        employee_id = parts[1]
        employee_name = parts[2] if len(parts) > 2 else ''
        
        print(f"Parsed QR data: {parts}")
        
        # Verify institute matches by comparing institute_code
        if scanned_institute_code != institute.get('institute_code'):
            return jsonify({
                'success': False, 
                'message': f'QR code belongs to different institution'
            }), 403
        
        # Check if employee exists in database
        employee_response = supabase.table('employees')\
            .select('id, name, employee_id, role, photo_url, status')\
            .eq('employee_id', employee_id)\
            .eq('institute_id', institute['id'])\
            .execute()
        
        if not employee_response.data:
            return jsonify({'success': False, 'message': f'Employee with ID {employee_id} not found'}), 404
        
        employee = employee_response.data[0]
        
        # Check if employee is active
        if employee.get('status') != 'active':
            return jsonify({'success': False, 'message': f'Employee {employee["name"]} is not active'}), 403
        
        # Check if already marked present today
        today = datetime.now().date().isoformat()
        today_check = supabase.table('staff_attendance')\
            .select('id')\
            .eq('employee_id', employee['id'])\
            .eq('institute_id', institute['id'])\
            .eq('attendance_date', today)\
            .execute()
        
        if today_check.data:
            return jsonify({
                'success': False,
                'message': f'{employee["name"]} already marked present today at {datetime.fromisoformat(today_check.data[0]["created_at"]).strftime("%H:%M:%S")}'
            }), 409
        
        # Record attendance
        attendance_id = str(uuid.uuid4())
        attendance_data = {
            'id': attendance_id,
            'institute_id': institute['id'],
            'employee_id': employee['id'],
            'employee_name': employee['name'],
            'employee_number': employee['employee_id'],
            'role': employee.get('role', 'Staff'),
            'photo_url': employee.get('photo_url'),
            'check_in_time': datetime.now().isoformat(),
            'attendance_date': today,
            'created_at': datetime.now().isoformat(),
            'marked_by': 'qr'
        }
        
        result = supabase.table('staff_attendance').insert(attendance_data).execute()
        
        if result.data:
            return jsonify({
                'success': True,
                'message': f'Attendance recorded for {employee["name"]}',
                'employee': {
                    'id': employee['id'],
                    'employee_id': employee['employee_id'],
                    'name': employee['name'],
                    'role': employee.get('role', 'Staff'),
                    'photo_url': employee.get('photo_url'),
                    'check_in_time': datetime.now().strftime('%H:%M:%S'),
                    'attendance_date': today
                }
            })
        else:
            return jsonify({'success': False, 'message': 'Failed to record attendance'}), 500
            
    except Exception as e:
        print(f"Error processing QR scan: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@staff_attendance_bp.route('/manual', methods=['POST'])
@login_required
def manual_attendance():
    """Record manual attendance for a staff member"""
    user = session.get('user')
    institute = get_institute(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        employee_id = data.get('employee_id')
        
        if not employee_id:
            return jsonify({'success': False, 'message': 'Employee ID required'}), 400
        
        # Get employee details
        employee_response = supabase.table('employees')\
            .select('id, name, employee_id, role, photo_url, status')\
            .eq('id', employee_id)\
            .eq('institute_id', institute['id'])\
            .execute()
        
        if not employee_response.data:
            return jsonify({'success': False, 'message': 'Employee not found'}), 404
        
        employee = employee_response.data[0]
        
        # Check if employee is active
        if employee.get('status') != 'active':
            return jsonify({'success': False, 'message': f'Employee {employee["name"]} is not active'}), 403
        
        # Check if already marked present today
        today = datetime.now().date().isoformat()
        today_check = supabase.table('staff_attendance')\
            .select('id')\
            .eq('employee_id', employee['id'])\
            .eq('institute_id', institute['id'])\
            .eq('attendance_date', today)\
            .execute()
        
        if today_check.data:
            return jsonify({
                'success': False,
                'message': f'{employee["name"]} already marked present today'
            }), 409
        
        # Record attendance
        attendance_id = str(uuid.uuid4())
        attendance_data = {
            'id': attendance_id,
            'institute_id': institute['id'],
            'employee_id': employee['id'],
            'employee_name': employee['name'],
            'employee_number': employee['employee_id'],
            'role': employee.get('role', 'Staff'),
            'photo_url': employee.get('photo_url'),
            'check_in_time': datetime.now().isoformat(),
            'attendance_date': today,
            'created_at': datetime.now().isoformat(),
            'marked_by': 'manual'
        }
        
        result = supabase.table('staff_attendance').insert(attendance_data).execute()
        
        if result.data:
            return jsonify({
                'success': True,
                'message': f'Attendance recorded for {employee["name"]}',
                'employee': {
                    'id': employee['id'],
                    'employee_id': employee['employee_id'],
                    'name': employee['name'],
                    'role': employee.get('role', 'Staff'),
                    'photo_url': employee.get('photo_url'),
                    'check_in_time': datetime.now().strftime('%H:%M:%S'),
                    'attendance_date': today
                }
            })
        else:
            return jsonify({'success': False, 'message': 'Failed to record attendance'}), 500
            
    except Exception as e:
        print(f"Error processing manual attendance: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@staff_attendance_bp.route('/bulk', methods=['POST'])
@login_required
def bulk_attendance():
    """Record bulk attendance for multiple staff members"""
    user = session.get('user')
    institute = get_institute(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        employee_ids = data.get('employee_ids', [])
        role = data.get('role')
        
        if not employee_ids and not role:
            return jsonify({'success': False, 'message': 'No staff selected'}), 400
        
        # If role provided but no specific employees, get all employees with that role
        if role and not employee_ids:
            employees_response = supabase.table('employees')\
                .select('id')\
                .eq('role', role)\
                .eq('institute_id', institute['id'])\
                .eq('status', 'active')\
                .execute()
            
            if employees_response.data:
                employee_ids = [e['id'] for e in employees_response.data]
        
        if not employee_ids:
            return jsonify({'success': False, 'message': 'No staff found'}), 404
        
        today = datetime.now().date().isoformat()
        successful = []
        failed = []
        
        for employee_id in employee_ids:
            # Check if already marked present today
            today_check = supabase.table('staff_attendance')\
                .select('id')\
                .eq('employee_id', employee_id)\
                .eq('institute_id', institute['id'])\
                .eq('attendance_date', today)\
                .execute()
            
            if today_check.data:
                failed.append({'id': employee_id, 'reason': 'Already marked present'})
                continue
            
            # Get employee details
            employee_response = supabase.table('employees')\
                .select('id, name, employee_id, role, photo_url')\
                .eq('id', employee_id)\
                .eq('institute_id', institute['id'])\
                .execute()
            
            if not employee_response.data:
                failed.append({'id': employee_id, 'reason': 'Employee not found'})
                continue
            
            employee = employee_response.data[0]
            
            # Record attendance
            attendance_id = str(uuid.uuid4())
            attendance_data = {
                'id': attendance_id,
                'institute_id': institute['id'],
                'employee_id': employee['id'],
                'employee_name': employee['name'],
                'employee_number': employee['employee_id'],
                'role': employee.get('role', 'Staff'),
                'photo_url': employee.get('photo_url'),
                'check_in_time': datetime.now().isoformat(),
                'attendance_date': today,
                'created_at': datetime.now().isoformat(),
                'marked_by': 'bulk'
            }
            
            result = supabase.table('staff_attendance').insert(attendance_data).execute()
            
            if result.data:
                successful.append(employee_id)
            else:
                failed.append({'id': employee_id, 'reason': 'Failed to record'})
        
        return jsonify({
            'success': True,
            'message': f'Successfully marked attendance for {len(successful)} staff member(s)',
            'successful_count': len(successful),
            'failed_count': len(failed),
            'failed': failed if failed else None
        })
        
    except Exception as e:
        print(f"Error processing bulk attendance: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@staff_attendance_bp.route('/today', methods=['GET'])
@login_required
def get_today_attendance():
    """Get today's staff attendance records"""
    user = session.get('user')
    institute = get_institute(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        today = datetime.now().date().isoformat()
        
        response = supabase.table('staff_attendance')\
            .select('*')\
            .eq('institute_id', institute['id'])\
            .eq('attendance_date', today)\
            .order('check_in_time', desc=True)\
            .execute()
        
        attendance = response.data if response.data else []
        
        return jsonify({'success': True, 'attendance': attendance, 'count': len(attendance)})
        
    except Exception as e:
        print(f"Error getting today's attendance: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@staff_attendance_bp.route('/stats', methods=['GET'])
@login_required
def get_attendance_stats():
    """Get staff attendance statistics - FIXED"""
    user = session.get('user')
    institute = get_institute(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Get today's attendance count
        today = datetime.now().date().isoformat()
        today_response = supabase.table('staff_attendance')\
            .select('id', count='exact')\
            .eq('institute_id', institute['id'])\
            .eq('attendance_date', today)\
            .execute()
        
        today_count = today_response.count or 0
        
        # Get total active employees
        employees_response = supabase.table('employees')\
            .select('id', count='exact')\
            .eq('institute_id', institute['id'])\
            .eq('status', 'active')\
            .execute()
        
        total_employees = employees_response.count or 0
        
        # Get this week's attendance
        week_ago = (datetime.now() - timedelta(days=7)).date().isoformat()
        week_response = supabase.table('staff_attendance')\
            .select('id', count='exact')\
            .eq('institute_id', institute['id'])\
            .gte('attendance_date', week_ago)\
            .execute()
        
        week_count = week_response.count or 0
        
        # Get attendance by role - FIXED: Properly query and count by role
        role_response = supabase.table('staff_attendance')\
            .select('role')\
            .eq('institute_id', institute['id'])\
            .eq('attendance_date', today)\
            .execute()
        
        role_stats = {}
        if role_response.data:
            for record in role_response.data:
                role_name = record.get('role', 'other')
                role_stats[role_name] = role_stats.get(role_name, 0) + 1
        
        return jsonify({
            'success': True,
            'stats': {
                'today_count': today_count,
                'total_employees': total_employees,
                'attendance_percentage': round((today_count / total_employees * 100) if total_employees > 0 else 0, 1),
                'week_count': week_count,
                'role_stats': role_stats
            }
        })
        
    except Exception as e:
        print(f"Error getting attendance stats: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@staff_attendance_bp.route('/employees/search', methods=['GET'])
@login_required
def search_employees():
    """Search employees for manual attendance"""
    user = session.get('user')
    institute = get_institute(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        search_term = request.args.get('q', '').strip()
        role = request.args.get('role', '')
        
        query = supabase.table('employees')\
            .select('id, name, employee_id, role, photo_url, status')\
            .eq('institute_id', institute['id'])\
            .eq('status', 'active')
        
        if role:
            query = query.eq('role', role)
        
        if search_term and len(search_term) >= 2:
            query = query.or_(f"name.ilike.%{search_term}%,employee_id.ilike.%{search_term}%")
        
        response = query.limit(50).execute()
        print(response)
        
        employees = response.data if response.data else []
        
        # Mark which employees are already present today
        today = datetime.now().date().isoformat()
        present_response = supabase.table('staff_attendance')\
            .select('employee_id')\
            .eq('institute_id', institute['id'])\
            .eq('attendance_date', today)\
            .execute()
        
        present_ids = set(a['employee_id'] for a in present_response.data) if present_response.data else set()
        
        for employee in employees:
            employee['is_present'] = employee['id'] in present_ids
        
        return jsonify({'success': True, 'employees': employees})
        
    except Exception as e:
        print(f"Error searching employees: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500