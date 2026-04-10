# studentAttendanceReport.py - Attendance Report Blueprint
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

attendance_report_bp = Blueprint('attendance_report', __name__, url_prefix='/attendance-report')

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

@attendance_report_bp.route('/')
@login_required
def index():
    """Attendance Report Page"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return render_template('attendance_report/index.html', classes=[], students=[], institute_id=None)
    
    try:
        # Get all classes for filter
        classes_response = supabase.table('classes')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('name')\
            .execute()
        
        classes = classes_response.data if classes_response.data else []
        
        # Get all active students for filter
        students_response = supabase.table('students')\
            .select('id, name, student_id, class_id, classes(name)')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')\
            .order('name')\
            .execute()
        
        students = students_response.data if students_response.data else []
        
        return render_template('attendance_report/index.html', 
                              classes=classes, 
                              students=students,
                              institute_id=institute_id)
        
    except Exception as e:
        print(f"Error loading report page: {e}")
        return render_template('attendance_report/index.html', classes=[], students=[], institute_id=None)

@attendance_report_bp.route('/data', methods=['POST'])
@login_required
def get_attendance_data():
    """Get attendance data based on filters"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        class_id = data.get('class_id')
        student_id = data.get('student_id')
        status = data.get('status')  # 'present', 'absent', 'all'
        
        # Set default date range (current month)
        if not start_date:
            start_date = datetime.now().replace(day=1).date().isoformat()
        if not end_date:
            end_date = datetime.now().date().isoformat()
        
        # Get students based on filters
        students_query = supabase.table('students')\
            .select('id, name, student_id, class_id, classes(name), gender')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')
        
        if class_id:
            students_query = students_query.eq('class_id', class_id)
        
        if student_id:
            students_query = students_query.eq('id', student_id)
        
        students_response = students_query.order('name').execute()
        students = students_response.data if students_response.data else []
        
        if not students:
            return jsonify({'success': True, 'attendance': [], 'summary': {}})
        
        # Get attendance records for the date range
        attendance_query = supabase.table('attendance')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .gte('scan_date', start_date)\
            .lte('scan_date', end_date)
        
        if class_id:
            attendance_query = attendance_query.eq('class_id', class_id)
        
        attendance_response = attendance_query.execute()
        attendance_records = attendance_response.data if attendance_response.data else []
        
        # Create a lookup dictionary for attendance
        attendance_lookup = {}
        for record in attendance_records:
            student_id_key = record['student_id']
            date_key = record['scan_date']
            if student_id_key not in attendance_lookup:
                attendance_lookup[student_id_key] = {}
            attendance_lookup[student_id_key][date_key] = record
        
        # Generate date range
        start = datetime.strptime(start_date, '%Y-%m-%d').date()
        end = datetime.strptime(end_date, '%Y-%m-%d').date()
        date_range = []
        current = start
        while current <= end:
            date_range.append(current.isoformat())
            current += timedelta(days=1)
        
        # Prepare attendance data for each student
        attendance_data = []
        summary = {
            'total_students': len(students),
            'total_days': len(date_range),
            'total_present': 0,
            'total_absent': 0,
            'attendance_percentage': 0
        }
        
        for student in students:
            student_attendance = []
            present_count = 0
            
            for date_str in date_range:
                is_present = student['id'] in attendance_lookup and date_str in attendance_lookup[student['id']]
                if is_present:
                    present_count += 1
                
                if status == 'present' and not is_present:
                    continue
                if status == 'absent' and is_present:
                    continue
                
                record = attendance_lookup.get(student['id'], {}).get(date_str) if is_present else None
                
                student_attendance.append({
                    'date': date_str,
                    'status': 'Present' if is_present else 'Absent',
                    'scan_time': record['scan_time'] if record else None,
                    'marked_by': record.get('marked_by', 'qr') if record else None
                })
            
            if student_attendance:
                attendance_data.append({
                    'student_id': student['student_id'],
                    'student_name': student['name'],
                    'class_name': student['classes']['name'] if student.get('classes') else 'N/A',
                    'gender': student.get('gender', 'N/A'),
                    'attendance': student_attendance,
                    'present_count': present_count,
                    'absent_count': len(date_range) - present_count,
                    'percentage': round((present_count / len(date_range) * 100), 1) if len(date_range) > 0 else 0
                })
            
            summary['total_present'] += present_count
        
        total_possible = len(students) * len(date_range)
        if total_possible > 0:
            summary['attendance_percentage'] = round((summary['total_present'] / total_possible * 100), 1)
        summary['total_absent'] = total_possible - summary['total_present']
        
        return jsonify({
            'success': True,
            'attendance': attendance_data,
            'summary': summary,
            'date_range': date_range
        })
        
    except Exception as e:
        print(f"Error getting attendance data: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@attendance_report_bp.route('/export-excel', methods=['POST'])
@login_required
def export_excel():
    """Export attendance data to Excel"""
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
        
        if not attendance_data:
            return jsonify({'success': False, 'message': 'No data to export'}), 400
        
        # Create DataFrame for Excel
        # First, create a list of dictionaries for each student
        rows = []
        for student in attendance_data:
            row = {
                'Student ID': student['student_id'],
                'Student Name': student['student_name'],
                'Class': student['class_name'],
                'Gender': student['gender'],
                'Total Present': student['present_count'],
                'Total Absent': student['absent_count'],
                'Attendance %': student['percentage']
            }
            
            # Add daily attendance
            for day_attendance in student['attendance']:
                date_label = day_attendance['date']
                row[date_label] = day_attendance['status']
            
            rows.append(row)
        
        # Create DataFrame
        df = pd.DataFrame(rows)
        
        # Reorder columns: student info first, then dates
        student_cols = ['Student ID', 'Student Name', 'Class', 'Gender', 'Total Present', 'Total Absent', 'Attendance %']
        date_cols = [col for col in df.columns if col not in student_cols]
        df = df[student_cols + date_cols]
        
        # Create Excel file in memory
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Attendance Report', index=False)
            
            # Get the workbook and worksheet
            workbook = writer.book
            worksheet = writer.sheets['Attendance Report']
            
            # Add summary sheet
            summary_data = data.get('summary', {})
            summary_df = pd.DataFrame([
                ['Report Period', f'{start_date} to {end_date}'],
                ['Total Students', summary_data.get('total_students', 0)],
                ['Total Days', summary_data.get('total_days', 0)],
                ['Total Present', summary_data.get('total_present', 0)],
                ['Total Absent', summary_data.get('total_absent', 0)],
                ['Overall Attendance %', f"{summary_data.get('attendance_percentage', 0)}%"]
            ])
            summary_df.to_excel(writer, sheet_name='Summary', index=False, header=False)
            
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
        
        filename = f"attendance_report_{start_date}_to_{end_date}.xlsx"
        
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

@attendance_report_bp.route('/student-summary/<student_id>', methods=['GET'])
@login_required
def get_student_summary(student_id):
    """Get attendance summary for a specific student"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Get student details
        student_response = supabase.table('students')\
            .select('*')\
            .eq('id', student_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if not student_response.data:
            return jsonify({'success': False, 'message': 'Student not found'}), 404
        
        student = student_response.data[0]
        
        # Get attendance for last 30 days
        thirty_days_ago = (datetime.now() - timedelta(days=30)).date().isoformat()
        
        attendance_response = supabase.table('attendance')\
            .select('*')\
            .eq('student_id', student_id)\
            .eq('institute_id', institute_id)\
            .gte('scan_date', thirty_days_ago)\
            .order('scan_date', desc=True)\
            .execute()
        
        attendance = attendance_response.data if attendance_response.data else []
        
        # Calculate statistics
        total_days = 30
        present_days = len(attendance)
        absent_days = total_days - present_days
        percentage = round((present_days / total_days * 100), 1) if total_days > 0 else 0
        
        return jsonify({
            'success': True,
            'student': {
                'id': student['id'],
                'name': student['name'],
                'student_id': student['student_id'],
                'class': student.get('class_name', 'N/A')
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
        print(f"Error getting student summary: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500