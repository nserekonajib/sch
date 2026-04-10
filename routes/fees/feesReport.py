# feesReports.py - Fee Reports Blueprint
from flask import Blueprint, render_template, request, jsonify, session, send_file
from supabase import create_client, Client
import os
import pandas as pd
import io
from datetime import datetime, timedelta
from functools import wraps
from dotenv import load_dotenv

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

fee_reports_bp = Blueprint('fee_reports', __name__, url_prefix='/fee-reports')

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
            .select('*')\
            .eq('user_id', user_id)\
            .execute()
        
        if response.data and len(response.data) > 0:
            return response.data[0]
        return None
    except Exception as e:
        print(f"Error getting institute: {e}")
        return None

@fee_reports_bp.route('/')
@login_required
def index():
    """Fee Reports Dashboard"""
    user = session.get('user')
    institute = get_institute_id(user['id'])
    
    if not institute:
        return render_template('fees/reports.html', institute=None, classes=[])
    
    try:
        # Get classes for filter
        classes_response = supabase.table('classes')\
            .select('*')\
            .eq('institute_id', institute['id'])\
            .order('name')\
            .execute()
        
        classes = classes_response.data if classes_response.data else []
        
        return render_template('fees/reports.html', institute=institute, classes=classes, now=datetime.now())
        
    except Exception as e:
        print(f"Error loading reports page: {e}")
        return render_template('fees/reports.html', institute=institute, classes=[])

@fee_reports_bp.route('/daily-collection', methods=['POST'])
@login_required
def get_daily_collection():
    """Get daily collection report"""
    user = session.get('user')
    institute = get_institute_id(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        
        if not start_date:
            start_date = datetime.now().date().isoformat()
        if not end_date:
            end_date = datetime.now().date().isoformat()
        
        # Get payments within date range
        payments_response = supabase.table('payments')\
            .select('*, students(name, student_id, classes(name))')\
            .eq('institute_id', institute['id'])\
            .gte('payment_date', start_date)\
            .lte('payment_date', end_date)\
            .order('payment_date', desc=True)\
            .execute()
        
        payments = payments_response.data if payments_response.data else []
        
        # Group by date
        daily_data = {}
        total_collected = 0
        
        for payment in payments:
            date = payment['payment_date']
            amount = float(payment['amount'])
            total_collected += amount
            
            if date not in daily_data:
                daily_data[date] = {
                    'date': date,
                    'total': 0,
                    'count': 0,
                    'transactions': []
                }
            
            daily_data[date]['total'] += amount
            daily_data[date]['count'] += 1
            daily_data[date]['transactions'].append({
                'receipt_number': payment['receipt_number'],
                'student_name': payment['students']['name'],
                'student_id': payment['students']['student_id'],
                'amount': amount,
                'payment_method': payment['payment_method'],
                'notes': payment.get('notes', '')
            })
        
        # Convert to list
        result = list(daily_data.values())
        
        return jsonify({
            'success': True,
            'data': result,
            'total_collected': total_collected,
            'start_date': start_date,
            'end_date': end_date,
            'total_transactions': len(payments)
        })
        
    except Exception as e:
        print(f"Error getting daily collection: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@fee_reports_bp.route('/balance-report', methods=['POST'])
@login_required
def get_balance_report():
    """Get fees balance report"""
    user = session.get('user')
    institute = get_institute_id(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        class_id = data.get('class_id')
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        
        # Build query for students
        students_query = supabase.table('students')\
            .select('*, classes(name)')\
            .eq('institute_id', institute['id'])\
            .eq('status', 'active')
        
        if class_id:
            students_query = students_query.eq('class_id', class_id)
        
        students_response = students_query.execute()
        students = students_response.data if students_response.data else []
        
        report_data = []
        total_invoiced = 0
        total_paid = 0
        total_discount = 0
        total_balance = 0
        
        for student in students:
            # Get invoices for this student
            invoices_query = supabase.table('invoices')\
                .select('*')\
                .eq('student_id', student['id'])\
                .eq('institute_id', institute['id'])
            
            if start_date:
                invoices_query = invoices_query.gte('created_at', f"{start_date}T00:00:00")
            if end_date:
                invoices_query = invoices_query.lte('created_at', f"{end_date}T23:59:59")
            
            invoices_response = invoices_query.execute()
            invoices = invoices_response.data if invoices_response.data else []
            
            student_total_invoiced = sum(float(inv['total_amount']) for inv in invoices)
            student_total_paid = sum(float(inv['paid_amount']) for inv in invoices)
            student_discount = sum(float(inv.get('discount_applied', 0)) for inv in invoices)
            student_balance = sum(float(inv['balance']) for inv in invoices if inv['status'] != 'paid')
            
            if student_balance > 0 or student_total_paid > 0:
                report_data.append({
                    'date': datetime.now().strftime('%Y-%m-%d'),
                    'student_name': student['name'],
                    'student_id': student['student_id'],
                    'mobile_number': student.get('contact_number', 'N/A'),
                    'class': student['classes']['name'] if student.get('classes') else 'N/A',
                    'total_invoiced': student_total_invoiced,
                    'total_paid': student_total_paid,
                    'discount': student_discount,
                    'balance': student_balance
                })
                
                total_invoiced += student_total_invoiced
                total_paid += student_total_paid
                total_discount += student_discount
                total_balance += student_balance
        
        return jsonify({
            'success': True,
            'data': report_data,
            'summary': {
                'total_invoiced': total_invoiced,
                'total_paid': total_paid,
                'total_discount': total_discount,
                'total_balance': total_balance,
                'student_count': len(report_data)
            }
        })
        
    except Exception as e:
        print(f"Error getting balance report: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@fee_reports_bp.route('/general-report', methods=['POST'])
@login_required
def get_general_report():
    """Get general fees report with statistics"""
    user = session.get('user')
    institute = get_institute_id(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        
        # Get all students
        students_response = supabase.table('students')\
            .select('id')\
            .eq('institute_id', institute['id'])\
            .eq('status', 'active')\
            .execute()
        
        total_students = len(students_response.data) if students_response.data else 0
        
        # Get all invoices
        invoices_query = supabase.table('invoices')\
            .select('*')\
            .eq('institute_id', institute['id'])
        
        if start_date:
            invoices_query = invoices_query.gte('created_at', f"{start_date}T00:00:00")
        if end_date:
            invoices_query = invoices_query.lte('created_at', f"{end_date}T23:59:59")
        
        invoices_response = invoices_query.execute()
        invoices = invoices_response.data if invoices_response.data else []
        
        total_invoiced = sum(float(inv['total_amount']) for inv in invoices)
        total_paid = sum(float(inv['paid_amount']) for inv in invoices)
        total_discount = sum(float(inv.get('discount_applied', 0)) for inv in invoices)
        total_balance = sum(float(inv['balance']) for inv in invoices)
        
        # Count by status
        fully_paid = sum(1 for inv in invoices if inv['status'] == 'paid')
        partially_paid = sum(1 for inv in invoices if inv['status'] == 'partial')
        unpaid = sum(1 for inv in invoices if inv['status'] == 'pending')
        
        return jsonify({
            'success': True,
            'summary': {
                'total_students': total_students,
                'total_invoices': len(invoices),
                'total_invoiced': total_invoiced,
                'total_paid': total_paid,
                'total_discount': total_discount,
                'total_balance': total_balance,
                'fully_paid': fully_paid,
                'partially_paid': partially_paid,
                'unpaid': unpaid
            }
        })
        
    except Exception as e:
        print(f"Error getting general report: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    
@fee_reports_bp.route('/send-reminders', methods=['POST'])
@login_required
def send_fee_reminders():
    """Send fee reminders to students with balance"""
    user = session.get('user')
    institute = get_institute_id(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        print(f"Received data: {data}")
        
        student_ids = data.get('student_ids', [])
        
        if not student_ids:
            return jsonify({'success': False, 'message': 'No student IDs provided'}), 400
        
        # Check if the IDs are internal UUIDs or display student_ids
        # Internal UUIDs are 36 characters with hyphens, display IDs are like PRI202604-KBML-004
        internal_ids = []
        display_ids = []
        
        for sid in student_ids:
            if len(sid) == 36 and '-' in sid:
                internal_ids.append(sid)
            else:
                display_ids.append(sid)
        
        # If we have display IDs, convert them to internal UUIDs
        if display_ids:
            for display_id in display_ids:
                student_response = supabase.table('students')\
                    .select('id')\
                    .eq('student_id', display_id)\
                    .eq('institute_id', institute['id'])\
                    .execute()
                
                if student_response.data:
                    internal_ids.append(student_response.data[0]['id'])
                else:
                    print(f"Student not found with ID: {display_id}")
        
        if not internal_ids:
            return jsonify({'success': False, 'message': 'No valid students found'}), 400
        
        # Get SMS settings
        sms_response = supabase.table('sms_settings')\
            .select('*')\
            .eq('institute_id', institute['id'])\
            .eq('enabled', True)\
            .execute()
        
        if not sms_response.data:
            return jsonify({'success': False, 'message': 'SMS not configured or disabled. Please configure SMS settings first.'}), 400
        
        settings = sms_response.data[0]
        
        # Send reminders
        reminders_sent = 0
        failed = []
        
        for student_uuid in internal_ids:
            # Get student details
            student_response = supabase.table('students')\
                .select('name, student_id, contact_number')\
                .eq('id', student_uuid)\
                .eq('institute_id', institute['id'])\
                .execute()
            
            if not student_response.data:
                failed.append({'student_uuid': student_uuid, 'reason': 'Student not found'})
                continue
            
            student = student_response.data[0]
            phone = student.get('contact_number')
            
            if not phone:
                failed.append({'student': student['name'], 'reason': 'No phone number'})
                continue
            
            # Get student balance
            invoices_response = supabase.table('invoices')\
                .select('balance')\
                .eq('student_id', student_uuid)\
                .eq('institute_id', institute['id'])\
                .neq('status', 'paid')\
                .execute()
            
            total_balance = sum(float(inv['balance']) for inv in (invoices_response.data or []))
            
            if total_balance <= 0:
                continue
            
            # Format phone number
            phone = phone.strip().replace(' ', '').replace('-', '')
            if not phone.startswith('+'):
                phone = '+' + phone if phone.startswith('256') else phone
            
            # Prepare message
            message = f"""Fee Payment Reminder

Dear Parent/Guardian,

This is to remind you that your child {student['name']} (ID: {student['student_id']}) has an outstanding fee balance of UGX {total_balance:,.0f}.

Please clear the balance to avoid any inconvenience.

{institute.get('institute_name', 'School Administration')}
Thank you."""
            
            # Send SMS
            try:
                from comms_sdk import CommsSDK, MessagePriority
                
                sdk = CommsSDK.authenticate(
                    settings['api_username'], 
                    settings['api_key']
                )
                
                result = sdk.send_sms(
                    [phone],
                    message,
                    sender_id=settings.get('sender_id', 'SCHOOL'),
                    priority=MessagePriority.HIGHEST
                )
                reminders_sent += 1
                print(f"SMS sent to {student['name']} ({student['student_id']}) at {phone}")
            except Exception as e:
                failed.append({'student': student['name'], 'student_id': student['student_id'], 'reason': str(e)})
                print(f"Failed to send SMS to {student['name']}: {e}")
        
        return jsonify({
            'success': True,
            'message': f'Reminders sent to {reminders_sent} students',
            'sent': reminders_sent,
            'failed': failed
        })
        
    except Exception as e:
        print(f"Error sending reminders: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@fee_reports_bp.route('/export-excel', methods=['POST'])
@login_required
def export_to_excel():
    """Export report data to Excel"""
    user = session.get('user')
    institute = get_institute_id(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        report_type = data.get('report_type')
        report_data = data.get('data', [])
        
        if not report_data:
            return jsonify({'success': False, 'message': 'No data to export'}), 400
        
        # Create DataFrame
        df = pd.DataFrame(report_data)
        
        # Format currency columns
        currency_columns = ['total_invoiced', 'total_paid', 'discount', 'balance', 'amount', 'total']
        for col in currency_columns:
            if col in df.columns:
                df[col] = df[col].apply(lambda x: f'UGX {x:,.2f}' if pd.notna(x) else 'UGX 0')
        
        # Create Excel file
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name=report_type, index=False)
            
            # Auto-adjust column widths
            worksheet = writer.sheets[report_type]
            for column in worksheet.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = min(max_length + 2, 50)
                worksheet.column_dimensions[column_letter].width = adjusted_width
        
        output.seek(0)
        
        filename = f"{report_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        
        return send_file(
            output,
            as_attachment=True,
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        
    except Exception as e:
        print(f"Error exporting to Excel: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500