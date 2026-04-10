# staffAttendanceReport.py - Staff Attendance Report Blueprint
from flask import Blueprint, render_template, request, jsonify, session, send_file
from supabase import create_client, Client
import os
from datetime import datetime, timedelta
import pandas as pd
import io
from functools import wraps
from dotenv import load_dotenv

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

staff_attendance_report_bp = Blueprint('staff_attendance_report', __name__, url_prefix='/staff-attendance-report')

def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Please login'}), 401
        return f(*args, **kwargs)
    return decorated_function

def get_institute_id(user_id):
    """Get institute ID for the current user"""
    try:
        response = supabase.table('institutes')\
            .select('id')\
            .eq('user_id', user_id)\
            .execute()
        
        if response.data and len(response.data) > 0:
            return response.data[0]['id']
        return None
    except Exception as e:
        print(f"Error getting institute ID: {e}")
        return None

@staff_attendance_report_bp.route('/')
@login_required
def index():
    """Staff Attendance Report Page"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return render_template('staff_attendance_report/index.html', roles=[], employees=[], institute_id=None)
    
    try:
        # Get all roles for filter
        roles_response = supabase.table('employees')\
            .select('role')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')\
            .execute()
        
        roles = list(set([r['role'] for r in roles_response.data])) if roles_response.data else []
        
        # Get all active employees for filter
        employees_response = supabase.table('employees')\
            .select('id, name, employee_id, role')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')\
            .order('name')\
            .execute()
        
        employees = employees_response.data if employees_response.data else []
        
        return render_template('staff_attendance_report/index.html', 
                              roles=roles, 
                              employees=employees,
                              institute_id=institute_id)
        
    except Exception as e:
        print(f"Error loading report page: {e}")
        return render_template('staff_attendance_report/index.html', roles=[], employees=[], institute_id=None)

@staff_attendance_report_bp.route('/data', methods=['POST'])
@login_required
def get_attendance_data():
    """Get staff attendance data based on filters"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        role = data.get('role')
        employee_id = data.get('employee_id')
        status = data.get('status')  # 'present', 'absent', 'all'
        
        # Set default date range (current month)
        if not start_date:
            start_date = datetime.now().replace(day=1).date().isoformat()
        if not end_date:
            end_date = datetime.now().date().isoformat()
        
        # Get employees based on filters
        employees_query = supabase.table('employees')\
            .select('id, name, employee_id, role, photo_url')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')
        
        if role:
            employees_query = employees_query.eq('role', role)
        
        if employee_id:
            employees_query = employees_query.eq('id', employee_id)
        
        employees_response = employees_query.order('name').execute()
        employees = employees_response.data if employees_response.data else []
        
        if not employees:
            return jsonify({'success': True, 'attendance': [], 'summary': {}})
        
        # Get attendance records for the date range
        attendance_query = supabase.table('staff_attendance')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .gte('attendance_date', start_date)\
            .lte('attendance_date', end_date)
        
        if role:
            attendance_query = attendance_query.eq('role', role)
        
        attendance_response = attendance_query.execute()
        attendance_records = attendance_response.data if attendance_response.data else []
        
        # Create a lookup dictionary for attendance
        attendance_lookup = {}
        for record in attendance_records:
            employee_id_key = record['employee_id']
            date_key = record['attendance_date']
            if employee_id_key not in attendance_lookup:
                attendance_lookup[employee_id_key] = {}
            attendance_lookup[employee_id_key][date_key] = record
        
        # Generate date range
        start = datetime.strptime(start_date, '%Y-%m-%d').date()
        end = datetime.strptime(end_date, '%Y-%m-%d').date()
        date_range = []
        current = start
        while current <= end:
            # Only include weekdays if needed? Let's include all days
            date_range.append(current.isoformat())
            current += timedelta(days=1)
        
        # Prepare attendance data for each employee
        attendance_data = []
        summary = {
            'total_employees': len(employees),
            'total_days': len(date_range),
            'total_present': 0,
            'total_absent': 0,
            'attendance_percentage': 0,
            'role_wise': {}
        }
        
        for employee in employees:
            employee_attendance = []
            present_count = 0
            
            for date_str in date_range:
                is_present = employee['id'] in attendance_lookup and date_str in attendance_lookup[employee['id']]
                if is_present:
                    present_count += 1
                
                if status == 'present' and not is_present:
                    continue
                if status == 'absent' and is_present:
                    continue
                
                record = attendance_lookup.get(employee['id'], {}).get(date_str) if is_present else None
                
                employee_attendance.append({
                    'date': date_str,
                    'status': 'Present' if is_present else 'Absent',
                    'check_in_time': record['check_in_time'] if record else None,
                    'marked_by': record.get('marked_by', 'qr') if record else None
                })
            
            if employee_attendance:
                attendance_data.append({
                    'employee_id': employee['employee_id'],
                    'employee_name': employee['name'],
                    'role': employee.get('role', 'Staff'),
                    'photo_url': employee.get('photo_url'),
                    'attendance': employee_attendance,
                    'present_count': present_count,
                    'absent_count': len(date_range) - present_count,
                    'percentage': round((present_count / len(date_range) * 100), 1) if len(date_range) > 0 else 0
                })
            
            summary['total_present'] += present_count
            
            # Role-wise summary
            emp_role = employee.get('role', 'other')
            if emp_role not in summary['role_wise']:
                summary['role_wise'][emp_role] = {'total': 0, 'present': 0}
            summary['role_wise'][emp_role]['total'] += 1
            summary['role_wise'][emp_role]['present'] += present_count / len(date_range) if len(date_range) > 0 else 0
        
        total_possible = len(employees) * len(date_range)
        if total_possible > 0:
            summary['attendance_percentage'] = round((summary['total_present'] / total_possible * 100), 1)
        summary['total_absent'] = total_possible - summary['total_present']
        
        # Calculate average daily attendance
        summary['avg_daily_attendance'] = round(summary['total_present'] / len(date_range), 1) if len(date_range) > 0 else 0
        
        return jsonify({
            'success': True,
            'attendance': attendance_data,
            'summary': summary,
            'date_range': date_range,
            'start_date': start_date,
            'end_date': end_date
        })
        
    except Exception as e:
        print(f"Error getting attendance data: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@staff_attendance_report_bp.route('/export-excel', methods=['POST'])
@login_required
def export_excel():
    """Export staff attendance data to Excel"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        
        attendance_data = data.get('attendance', [])
        date_range = data.get('date_range', [])
        start_date = data.get('start_date', '')
        end_date = data.get('end_date', '')
        summary = data.get('summary', {})
        
        if not attendance_data:
            return jsonify({'success': False, 'message': 'No data to export'}), 400
        
        # Create DataFrame for Excel
        rows = []
        for employee in attendance_data:
            row = {
                'Employee ID': employee['employee_id'],
                'Employee Name': employee['employee_name'],
                'Role': employee['role'].replace('_', ' ').title() if employee['role'] else 'Staff',
                'Total Present': employee['present_count'],
                'Total Absent': employee['absent_count'],
                'Attendance %': employee['percentage']
            }
            
            # Add daily attendance
            for day_attendance in employee['attendance']:
                date_label = day_attendance['date']
                row[date_label] = day_attendance['status']
            
            rows.append(row)
        
        # Create DataFrame
        df = pd.DataFrame(rows)
        
        # Reorder columns: employee info first, then dates
        employee_cols = ['Employee ID', 'Employee Name', 'Role', 'Total Present', 'Total Absent', 'Attendance %']
        date_cols = [col for col in df.columns if col not in employee_cols]
        df = df[employee_cols + date_cols]
        
        # Create Excel file in memory
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Staff Attendance Report', index=False)
            
            # Get the workbook and worksheet
            workbook = writer.book
            worksheet = writer.sheets['Staff Attendance Report']
            
            # Add summary sheet
            summary_df = pd.DataFrame([
                ['Report Period', f'{start_date} to {end_date}'],
                ['Total Employees', summary.get('total_employees', 0)],
                ['Total Days', summary.get('total_days', 0)],
                ['Total Present', summary.get('total_present', 0)],
                ['Total Absent', summary.get('total_absent', 0)],
                ['Overall Attendance %', f"{summary.get('attendance_percentage', 0)}%"],
                ['Average Daily Attendance', summary.get('avg_daily_attendance', 0)],
                ['', ''],
                ['Role-wise Summary', ''],
            ])
            summary_df.to_excel(writer, sheet_name='Summary', index=False, header=False)
            
            # Add role-wise breakdown
            role_wise = summary.get('role_wise', {})
            role_data = []
            for role, stats in role_wise.items():
                role_data.append([
                    role.replace('_', ' ').title() if role else 'Other',
                    stats.get('total', 0),
                    round(stats.get('present', 0), 1),
                    round((stats.get('present', 0) / stats.get('total', 1) * 100), 1) if stats.get('total', 0) > 0 else 0
                ])
            
            if role_data:
                role_df = pd.DataFrame(role_data, columns=['Role', 'Total Employees', 'Avg Daily Present', 'Attendance %'])
                role_df.to_excel(writer, sheet_name='Summary', startrow=10, index=False)
            
            # Format columns
            for column in worksheet.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = min(max_length + 2, 30)
                worksheet.column_dimensions[column_letter].width = adjusted_width
        
        output.seek(0)
        
        filename = f"staff_attendance_report_{start_date}_to_{end_date}.xlsx"
        
        return send_file(
            output,
            as_attachment=True,
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        
    except Exception as e:
        print(f"Error exporting to Excel: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@staff_attendance_report_bp.route('/employee-summary/<employee_id>', methods=['GET'])
@login_required
def get_employee_summary(employee_id):
    """Get attendance summary for a specific employee"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Get employee details
        employee_response = supabase.table('employees')\
            .select('*')\
            .eq('id', employee_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if not employee_response.data:
            return jsonify({'success': False, 'message': 'Employee not found'}), 404
        
        employee = employee_response.data[0]
        
        # Get attendance for last 30 days
        thirty_days_ago = (datetime.now() - timedelta(days=30)).date().isoformat()
        
        attendance_response = supabase.table('staff_attendance')\
            .select('*')\
            .eq('employee_id', employee_id)\
            .eq('institute_id', institute_id)\
            .gte('attendance_date', thirty_days_ago)\
            .order('attendance_date', desc=True)\
            .execute()
        
        attendance = attendance_response.data if attendance_response.data else []
        
        # Calculate statistics
        total_days = 30
        present_days = len(attendance)
        absent_days = total_days - present_days
        percentage = round((present_days / total_days * 100), 1) if total_days > 0 else 0
        
        return jsonify({
            'success': True,
            'employee': {
                'id': employee['id'],
                'name': employee['name'],
                'employee_id': employee['employee_id'],
                'role': employee.get('role', 'Staff')
            },
            'summary': {
                'total_days': total_days,
                'present': present_days,
                'absent': absent_days,
                'percentage': percentage
            },
            'attendance': attendance
        })
        
    except Exception as e:
        print(f"Error getting employee summary: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500