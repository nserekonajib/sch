# listEnDelete.py - Payment listing, filtering, export, and deletion (Institute-Specific)
from flask import Blueprint, render_template, request, jsonify, session, send_file
from supabase import create_client, Client
import os
import uuid
from datetime import datetime, timedelta
import json
import io
import pandas as pd
from functools import wraps
from dotenv import load_dotenv
import requests
from routes.permissions.permissions import role_required
from routes.accounts.accounts import get_institute_id

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

payments_bp = Blueprint('payments_list', __name__, url_prefix='/payments')


def admin_required(f):
    """Decorator to require admin access"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Please login'}), 401
        user_email = session.get('user', {}).get('email', '')
        admin_emails = os.getenv('ADMIN_EMAILS', '').split(',')
        if user_email not in admin_emails:
            return jsonify({'success': False, 'message': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated_function


@payments_bp.route('/')
@role_required(['owner', 'teacher', 'accountant', 'admin'])
def index():
    """Payments listing page - institute specific"""
    user = session.get('user')
    user_email = user.get('email', '')
    admin_emails = os.getenv('ADMIN_EMAILS', '').split(',')
    is_admin = user_email in admin_emails
    
    # Get institute details for non-admin users
    institute = None
    if not is_admin:
        institute_id = get_institute_id(user['id'])
        if institute_id:
            # Fetch institute details
            inst_response = supabase.table('institutes')\
                .select('id, institute_name')\
                .eq('id', institute_id)\
                .execute()
            if inst_response.data:
                institute = inst_response.data[0]
    
    return render_template('payments/list.html', 
                         is_admin=is_admin,
                         institute=institute)

# Change the route mapping - remove the duplicate /api/list route and keep only one
# Remove the second @payments_bp.route('/api/list') and keep the main one

# Update the main get_payments function to include phone numbers
@payments_bp.route('/api/list', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant', 'admin'])
def get_payments():
    """Get payments with institute-specific filtering and phone numbers"""
    try:
        user = session.get('user')
        user_email = user.get('email', '')
        admin_emails = os.getenv('ADMIN_EMAILS', '').split(',')
        is_admin = user_email in admin_emails
        
        # Get query parameters
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 20))
        search = request.args.get('search', '').strip()
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        payment_method = request.args.get('payment_method', '')
        whatsapp_status = request.args.get('whatsapp_status', '')
        
        # Get institute ID for filtering
        institute_id = None
        if not is_admin:
            institute_id = get_institute_id(user['id'])
            if not institute_id:
                return jsonify({
                    'success': True,
                    'payments': [],
                    'total': 0,
                    'page': page,
                    'per_page': per_page,
                    'total_pages': 0
                })
        else:
            institute_id = request.args.get('institute_id', '')
        
        # Build the base query - get payments first
        query = supabase.table('payments')\
            .select('*')\
            .order('payment_date', desc=True)
        
        # Apply institute filter
        if institute_id:
            query = query.eq('institute_id', institute_id)
        
        # Apply date filters
        if start_date:
            query = query.gte('payment_date', start_date)
        if end_date:
            query = query.lte('payment_date', end_date)
        
        # Apply payment method filter
        if payment_method:
            query = query.eq('payment_method', payment_method)
        
        # Apply WhatsApp status filter
        if whatsapp_status:
            query = query.eq('whatsapp_status', whatsapp_status)
        
        # Apply search filter
        if search:
            # Search for students matching the search term
            student_search = supabase.table('students')\
                .select('id')\
                .ilike('name', f'%{search}%')\
                .execute()
            
            student_ids = [s['id'] for s in student_search.data] if student_search.data else []
            
            # Also search by student_id (display ID)
            student_id_search = supabase.table('students')\
                .select('id')\
                .ilike('student_id', f'%{search}%')\
                .execute()
            
            if student_id_search.data:
                for s in student_id_search.data:
                    if s['id'] not in student_ids:
                        student_ids.append(s['id'])
            
            # Get payment IDs from student matches
            payment_ids_from_students = []
            if student_ids:
                for sid in student_ids:
                    student_payments = supabase.table('payments')\
                        .select('id')\
                        .eq('student_id', sid)\
                        .execute()
                    if student_payments.data:
                        payment_ids_from_students.extend([p['id'] for p in student_payments.data])
            
            # Also search by receipt number
            receipt_search = supabase.table('payments')\
                .select('id')\
                .ilike('receipt_number', f'%{search}%')\
                .execute()
            
            receipt_ids = [p['id'] for p in receipt_search.data] if receipt_search.data else []
            
            # Combine all matching payment IDs
            all_matching_ids = list(set(receipt_ids + payment_ids_from_students))
            
            if all_matching_ids:
                query = query.in_('id', all_matching_ids)
            else:
                return jsonify({
                    'success': True,
                    'payments': [],
                    'total': 0,
                    'page': page,
                    'per_page': per_page,
                    'total_pages': 0
                })
        
        # Get total count
        count_response = query.execute()
        total_count = len(count_response.data) if count_response.data else 0
        
        # Apply pagination
        offset = (page - 1) * per_page
        query = query.range(offset, offset + per_page - 1)
        response = query.execute()
        payments = response.data if response.data else []
        
        # Collect all student UUIDs from payments
        student_uuids = []
        for payment in payments:
            student_uuid = payment.get('student_id')
            if student_uuid and student_uuid not in student_uuids:
                student_uuids.append(student_uuid)
        
        # Fetch all students data in one query
        students_map = {}
        if student_uuids:
            student_resp = supabase.table('students')\
                .select('id, name, student_id, contact_number, class_id')\
                .in_('id', student_uuids)\
                .execute()
            
            if student_resp.data:
                for student in student_resp.data:
                    students_map[student['id']] = student
                    print(f"Student: {student.get('name')}, Phone: {student.get('contact_number')}")
        
        # Fetch all classes data
        class_ids = []
        for student in students_map.values():
            if student.get('class_id') and student['class_id'] not in class_ids:
                class_ids.append(student['class_id'])
        
        classes_map = {}
        if class_ids:
            class_resp = supabase.table('classes')\
                .select('id, name')\
                .in_('id', class_ids)\
                .execute()
            
            if class_resp.data:
                for cls in class_resp.data:
                    classes_map[cls['id']] = cls
        
        # Get institute name
        institute_name = ''
        if institute_id:
            inst_resp = supabase.table('institutes')\
                .select('institute_name')\
                .eq('id', institute_id)\
                .execute()
            if inst_resp.data:
                institute_name = inst_resp.data[0].get('institute_name', '')
        
        # Build formatted payments
        formatted_payments = []
        for payment in payments:
            student_uuid = payment.get('student_id')
            student = students_map.get(student_uuid, {})
            
            # Get class name from student's class_id
            class_name = 'N/A'
            if student.get('class_id'):
                class_name = classes_map.get(student['class_id'], {}).get('name', 'N/A')
            
            phone_number = student.get('contact_number', '')
            
            # Get current balance
            current_balance = 0
            balance_status = 'paid'
            if student_uuid and institute_id:
                invoices_response = supabase.table('invoices')\
                    .select('balance')\
                    .eq('student_id', student_uuid)\
                    .eq('institute_id', institute_id)\
                    .execute()
                if invoices_response.data:
                    current_balance = sum(inv['balance'] for inv in invoices_response.data)
                    balance_status = 'credit' if current_balance < 0 else 'due' if current_balance > 0 else 'paid'
            
            formatted_payments.append({
                'id': payment.get('id'),
                'receipt_number': payment.get('receipt_number'),
                'payment_date': payment.get('payment_date'),
                'student_name': student.get('name', 'N/A'),
                'student_id_display': student.get('student_id', 'N/A'),
                'phone_number': phone_number,
                'class_name': class_name,
                'institute_name': institute_name,
                'amount': float(payment.get('amount', 0)),
                'payment_method': payment.get('payment_method', ''),
                'current_balance': current_balance,
                'balance_status': balance_status,
                'whatsapp_status': payment.get('whatsapp_status', ''),
                'whatsapp_sent_at': payment.get('whatsapp_sent_at')
            })
        
        return jsonify({
            'success': True,
            'payments': formatted_payments,
            'total': total_count,
            'page': page,
            'per_page': per_page,
            'total_pages': (total_count + per_page - 1) // per_page if total_count else 0
        })
        
    except Exception as e:
        print(f"Error getting payments: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@payments_bp.route('/api/export', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant', 'admin'])
def export_payments():
    """Export payments to Excel or CSV - institute specific"""
    try:
        user = session.get('user')
        user_email = user.get('email', '')
        admin_emails = os.getenv('ADMIN_EMAILS', '').split(',')
        is_admin = user_email in admin_emails
        
        data = request.get_json()
        export_format = data.get('format', 'excel')
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        payment_method = data.get('payment_method', '')
        search = data.get('search', '').strip()
        
        # Get institute ID for filtering
        institute_id = None
        institute = None
        
        if not is_admin:
            institute_id = get_institute_id(user['id'])
            if institute_id:
                # Get institute details for naming
                inst_response = supabase.table('institutes')\
                    .select('institute_name')\
                    .eq('id', institute_id)\
                    .execute()
                if inst_response.data:
                    institute = inst_response.data[0]
        else:
            institute_id = data.get('institute_id', '')
            if institute_id:
                inst_response = supabase.table('institutes')\
                    .select('institute_name')\
                    .eq('id', institute_id)\
                    .execute()
                if inst_response.data:
                    institute = inst_response.data[0]
        
        # Build query
        query = supabase.table('payments')\
            .select('*, students(name, student_id, classes(name)), institutes(institute_name, institute_code)')\
            .order('payment_date', desc=True)
        
        # Apply institute filter
        if institute_id:
            query = query.eq('institute_id', institute_id)
        
        if start_date:
            query = query.gte('payment_date', start_date)
        if end_date:
            query = query.lte('payment_date', end_date)
        if payment_method:
            query = query.eq('payment_method', payment_method)
        
        # Apply search filter
        if search:
            # First, try to search by receipt number directly
            receipt_search = supabase.table('payments')\
                .select('id')\
                .ilike('receipt_number', f'%{search}%')\
                .execute()
            
            receipt_ids = [p['id'] for p in receipt_search.data] if receipt_search.data else []
            
            # Search for students matching the search term
            student_ids = []
            if institute_id:
                student_search = supabase.table('students')\
                    .select('id')\
                    .eq('institute_id', institute_id)\
                    .ilike('name', f'%{search}%')\
                    .execute()
                
                if student_search.data:
                    student_ids.extend([s['id'] for s in student_search.data])
                
                # Also search by student_id
                student_id_search = supabase.table('students')\
                    .select('id')\
                    .eq('institute_id', institute_id)\
                    .ilike('student_id', f'%{search}%')\
                    .execute()
                
                if student_id_search.data:
                    for s in student_id_search.data:
                        if s['id'] not in student_ids:
                            student_ids.append(s['id'])
            
            # Get payment IDs from student matches
            payment_ids_from_students = []
            if student_ids:
                for sid in student_ids:
                    student_payments = supabase.table('payments')\
                        .select('id')\
                        .eq('student_id', sid)\
                        .execute()
                    if student_payments.data:
                        payment_ids_from_students.extend([p['id'] for p in student_payments.data])
            
            # Combine all matching payment IDs
            all_matching_ids = list(set(receipt_ids + payment_ids_from_students))
            
            if all_matching_ids:
                query = query.in_('id', all_matching_ids)
            else:
                # No matches found
                query = query.eq('id', '00000000-0000-0000-0000-000000000000')
        
        response = query.execute()
        payments = response.data if response.data else []
        
        # Prepare data for export
        export_data = []
        for payment in payments:
            # Get current balance
            invoices_response = supabase.table('invoices')\
                .select('balance')\
                .eq('student_id', payment['student_id'])\
                .eq('institute_id', payment['institute_id'])\
                .execute()
            
            current_balance = sum(inv['balance'] for inv in invoices_response.data) if invoices_response.data else 0
            
            export_data.append({
                'Receipt Number': payment['receipt_number'],
                'Payment Date': payment['payment_date'],
                'Student Name': payment.get('students', {}).get('name', 'N/A'),
                'Student ID': payment.get('students', {}).get('student_id', 'N/A'),
                'Class': payment.get('students', {}).get('classes', {}).get('name', 'N/A') if payment.get('students') else 'N/A',
                'Institute': payment.get('institutes', {}).get('institute_name', 'N/A'),
                'Amount Paid (UGX)': float(payment['amount']),
                'Payment Method': payment['payment_method'].upper(),
                'Fee Month': payment.get('fee_month', 'N/A'),
                'Current Balance (UGX)': float(current_balance),
                'Status': 'Credit' if current_balance < 0 else 'Due' if current_balance > 0 else 'Paid',
                'Notes': payment.get('notes', ''),
                'Created At': payment.get('created_at', '')
            })
        
        # Create DataFrame
        df = pd.DataFrame(export_data)
        
        # Format currency columns
        if 'Amount Paid (UGX)' in df.columns and not df.empty:
            df['Amount Paid (UGX)'] = df['Amount Paid (UGX)'].apply(lambda x: f"{x:,.0f}")
        if 'Current Balance (UGX)' in df.columns and not df.empty:
            df['Current Balance (UGX)'] = df['Current Balance (UGX)'].apply(lambda x: f"{x:,.0f}")
        
        # Generate file
        institute_name = institute.get('institute_name', 'all_institutes') if institute else 'all_institutes'
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        if export_format == 'csv':
            output = io.StringIO()
            df.to_csv(output, index=False)
            output.seek(0)
            
            return send_file(
                io.BytesIO(output.getvalue().encode('utf-8')),
                mimetype='text/csv',
                as_attachment=True,
                download_name=f'payments_{institute_name}_{timestamp}.csv'
            )
        else:
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='Payments', index=False)
                
                if not df.empty:
                    # Auto-adjust column widths
                    worksheet = writer.sheets['Payments']
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
            return send_file(
                output,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                as_attachment=True,
                download_name=f'payments_{institute_name}_{timestamp}.xlsx'
            )
        
    except Exception as e:
        print(f"Error exporting payments: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


@payments_bp.route('/api/delete/<payment_id>', methods=['DELETE'])
@role_required(['owner'])
def delete_payment(payment_id):
    """Delete a payment record (admin only)"""
    try:
        # Get payment details before deletion
        payment_response = supabase.table('payments')\
            .select('*, students(name), institutes(institute_name)')\
            .eq('id', payment_id)\
            .execute()
        
        if not payment_response.data:
            return jsonify({'success': False, 'message': 'Payment not found'}), 404
        
        payment = payment_response.data[0]
        
        # Get the invoice(s) affected by this payment
        affected_invoices = []
        
        # If payment was for a specific invoice
        if payment.get('invoice_id'):
            invoice_response = supabase.table('invoices')\
                .select('*')\
                .eq('id', payment['invoice_id'])\
                .execute()
            
            if invoice_response.data:
                invoice = invoice_response.data[0]
                # Reverse the payment on this invoice
                new_paid_amount = invoice['paid_amount'] - payment['amount']
                new_balance = invoice['total_amount'] - new_paid_amount
                
                # Update invoice status
                if new_balance <= 0:
                    if new_balance < 0:
                        new_status = 'credit'
                    else:
                        new_status = 'paid'
                elif new_paid_amount > 0:
                    new_status = 'partial'
                else:
                    new_status = 'pending'
                
                supabase.table('invoices')\
                    .update({
                        'paid_amount': new_paid_amount,
                        'balance': new_balance,
                        'status': new_status,
                        'updated_at': datetime.now().isoformat()
                    })\
                    .eq('id', payment['invoice_id'])\
                    .execute()
                
                affected_invoices.append({
                    'invoice_number': invoice['invoice_number'],
                    'new_balance': new_balance
                })
        
        # Delete the payment
        supabase.table('payments')\
            .delete()\
            .eq('id', payment_id)\
            .execute()
        
        return jsonify({
            'success': True,
            'message': f'Payment {payment["receipt_number"]} deleted successfully',
            'affected_invoices': affected_invoices
        })
        
    except Exception as e:
        print(f"Error deleting payment: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


@payments_bp.route('/api/bulk-delete', methods=['POST'])
@admin_required
def bulk_delete_payments():
    """Delete multiple payments at once (admin only)"""
    try:
        data = request.get_json()
        payment_ids = data.get('payment_ids', [])
        
        if not payment_ids:
            return jsonify({'success': False, 'message': 'No payments selected'}), 400
        
        deleted_count = 0
        failed_payments = []
        
        for payment_id in payment_ids:
            try:
                # Get payment details
                payment_response = supabase.table('payments')\
                    .select('*')\
                    .eq('id', payment_id)\
                    .execute()
                
                if payment_response.data:
                    payment = payment_response.data[0]
                    
                    # Reverse payment on invoice if applicable
                    if payment.get('invoice_id'):
                        invoice_response = supabase.table('invoices')\
                            .select('*')\
                            .eq('id', payment['invoice_id'])\
                            .execute()
                        
                        if invoice_response.data:
                            invoice = invoice_response.data[0]
                            new_paid_amount = invoice['paid_amount'] - payment['amount']
                            new_balance = invoice['total_amount'] - new_paid_amount
                            
                            if new_balance <= 0:
                                new_status = 'credit' if new_balance < 0 else 'paid'
                            elif new_paid_amount > 0:
                                new_status = 'partial'
                            else:
                                new_status = 'pending'
                            
                            supabase.table('invoices')\
                                .update({
                                    'paid_amount': new_paid_amount,
                                    'balance': new_balance,
                                    'status': new_status,
                                    'updated_at': datetime.now().isoformat()
                                })\
                                .eq('id', payment['invoice_id'])\
                                .execute()
                    
                    # Delete the payment
                    supabase.table('payments')\
                        .delete()\
                        .eq('id', payment_id)\
                        .execute()
                    
                    deleted_count += 1
                else:
                    failed_payments.append(payment_id)
                    
            except Exception as e:
                print(f"Error deleting payment {payment_id}: {e}")
                failed_payments.append(payment_id)
        
        return jsonify({
            'success': True,
            'message': f'Successfully deleted {deleted_count} payment(s)',
            'deleted_count': deleted_count,
            'failed_payments': failed_payments
        })
        
    except Exception as e:
        print(f"Error in bulk delete: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@payments_bp.route('/api/summary', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant', 'admin'])
def get_payment_summary():
    """Get payment summary statistics - institute specific"""
    try:
        user = session.get('user')
        user_email = user.get('email', '')
        admin_emails = os.getenv('ADMIN_EMAILS', '').split(',')
        is_admin = user_email in admin_emails
        
        # Get date range from query params
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        # Get institute ID for filtering
        if not is_admin:
            institute_id = get_institute_id(user['id'])
            if not institute_id:
                return jsonify({
                    'success': True,
                    'summary': {
                        'total_payments': 0,
                        'total_amount': 0,
                        'average_payment': 0,
                        'method_breakdown': {},
                        'daily_payments': []
                    }
                })
        else:
            institute_id = request.args.get('institute_id', '')
        
        # Build query
        query = supabase.table('payments')\
            .select('amount, payment_method, payment_date')\
            .order('payment_date', desc=True)
        
        # Apply institute filter
        if institute_id:
            query = query.eq('institute_id', institute_id)
        
        if start_date:
            query = query.gte('payment_date', start_date)
        if end_date:
            query = query.lte('payment_date', end_date)
        
        response = query.execute()
        payments = response.data if response.data else []
        
        # Calculate statistics
        total_payments = len(payments)
        total_amount = sum(p['amount'] for p in payments)
        
        # Payment method breakdown
        method_breakdown = {}
        for p in payments:
            method = p['payment_method']
            method_breakdown[method] = method_breakdown.get(method, 0) + p['amount']
        
        # Daily payments (last 30 days)
        daily_payments = {}
        thirty_days_ago = datetime.now().date() - timedelta(days=30)
        
        for p in payments:
            payment_date = datetime.strptime(p['payment_date'], '%Y-%m-%d').date()
            if payment_date >= thirty_days_ago:
                date_str = payment_date.strftime('%Y-%m-%d')
                daily_payments[date_str] = daily_payments.get(date_str, 0) + p['amount']
        
        return jsonify({
            'success': True,
            'summary': {
                'total_payments': total_payments,
                'total_amount': total_amount,
                'average_payment': total_amount / total_payments if total_payments > 0 else 0,
                'method_breakdown': method_breakdown,
                'daily_payments': [{'date': d, 'amount': a} for d, a in daily_payments.items()]
            }
        })
        
    except Exception as e:
        print(f"Error getting payment summary: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@payments_bp.route('/api/institutes', methods=['GET'])
@admin_required
def get_institutes_for_filter():
    """Get list of institutes for filter dropdown (admin only)"""
    try:
        response = supabase.table('institutes')\
            .select('id, institute_name, institute_code')\
            .order('institute_name')\
            .execute()
        
        institutes = response.data if response.data else []
        
        return jsonify({
            'success': True,
            'institutes': institutes
        })
        
    except Exception as e:
        print(f"Error getting institutes: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@payments_bp.route('/api/institute-info', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_institute_info():
    """Get current user's institute information"""
    try:
        user = session.get('user')
        institute_id = get_institute_id(user['id'])
        
        if institute_id:
            # Fetch institute details
            inst_response = supabase.table('institutes')\
                .select('id, institute_name, institute_code, address, phone_number')\
                .eq('id', institute_id)\
                .execute()
            
            if inst_response.data:
                return jsonify({
                    'success': True,
                    'institute': inst_response.data[0]
                })
            else:
                return jsonify({
                    'success': False,
                    'message': 'Institute not found'
                }), 404
        else:
            return jsonify({
                'success': False,
                'message': 'No institute associated with this user'
            }), 404
            
    except Exception as e:
        print(f"Error getting institute info: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
 # ==================== WHATSAPP RECEIPT ROUTES ====================
@payments_bp.route('/api/receipt-pdf/<receipt_number>', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant', 'admin'])
def get_receipt_pdf(receipt_number):
    """Generate receipt PDF for WhatsApp"""
    try:
        user = session.get('user')
        user_email = user.get('email', '')
        admin_emails = os.getenv('ADMIN_EMAILS', '').split(',')
        is_admin = user_email in admin_emails
        
        # Get institute ID for filtering
        if not is_admin:
            institute_id = get_institute_id(user['id'])
            if not institute_id:
                return jsonify({'success': False, 'message': 'Institute not found'}), 404
        else:
            institute_id = request.args.get('institute_id', '')
        
        # Get payment data
        query = supabase.table('payments')\
            .select('*')\
            .eq('receipt_number', receipt_number)
        
        # Apply institute filter for non-admin
        if institute_id:
            query = query.eq('institute_id', institute_id)
        elif not is_admin:
            query = query.eq('institute_id', institute_id)
        
        response = query.execute()
        
        if not response.data:
            return jsonify({'success': False, 'message': 'Receipt not found or access denied'}), 404
        
        payment = response.data[0]
        
        # Get student data
        student_data = {}
        student_uuid = payment.get('student_id')
        if student_uuid:
            student_resp = supabase.table('students')\
                .select('name, student_id, contact_number, class_id')\
                .eq('id', student_uuid)\
                .execute()
            if student_resp.data:
                student_data = student_resp.data[0]
        
        # Get class data
        class_name = 'N/A'
        class_id = student_data.get('class_id')
        if class_id:
            class_resp = supabase.table('classes')\
                .select('name')\
                .eq('id', class_id)\
                .execute()
            if class_resp.data:
                class_name = class_resp.data[0].get('name', 'N/A')
        
        # Generate PDF using reportlab
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.units import inch
        from reportlab.pdfgen import canvas
        from reportlab.lib import colors
        import io
        from datetime import datetime
        
        buffer = io.BytesIO()
        c = canvas.Canvas(buffer, pagesize=letter)
        width, height = letter
        
        # Header
        c.setFont("Helvetica-Bold", 16)
        c.drawString(1*inch, height - 1*inch, "CAPITAL COLLEGE")
        c.setFont("Helvetica", 10)
        c.drawString(1*inch, height - 1.2*inch, "Payment Receipt")
        
        # Receipt details
        c.setFont("Helvetica-Bold", 12)
        c.drawString(1*inch, height - 1.8*inch, f"Receipt: {receipt_number}")
        c.setFont("Helvetica", 11)
        c.drawString(1*inch, height - 2.2*inch, f"Date: {payment.get('payment_date', datetime.now().strftime('%Y-%m-%d'))}")
        c.drawString(1*inch, height - 2.6*inch, f"Student: {student_data.get('name', 'N/A')}")
        c.drawString(1*inch, height - 3.0*inch, f"Student ID: {student_data.get('student_id', 'N/A')}")
        c.drawString(1*inch, height - 3.4*inch, f"Class: {class_name}")
        
        # Amount
        c.setFont("Helvetica-Bold", 14)
        c.setFillColor(colors.green)
        c.drawString(1*inch, height - 4.2*inch, f"Amount Paid: UGX {float(payment.get('amount', 0)):,.0f}")
        c.setFillColor(colors.black)
        c.setFont("Helvetica", 11)
        c.drawString(1*inch, height - 4.6*inch, f"Method: {payment.get('payment_method', 'N/A').upper()}")
        
        # Balance
        balance = float(payment.get('current_balance', 0))
        balance_color = colors.green if balance < 0 else colors.red
        c.setFillColor(balance_color)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(1*inch, height - 5.0*inch, f"Balance: UGX {abs(balance):,.0f} { '(Credit)' if balance < 0 else '(Due)' }")
        
        # Footer
        c.setFillColor(colors.grey)
        c.setFont("Helvetica", 8)
        c.drawString(1*inch, 1*inch, "This is a system-generated receipt. For inquiries, contact the accounts department.")
        c.drawString(1*inch, 0.8*inch, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        c.save()
        buffer.seek(0)
        
        return send_file(
            buffer, 
            mimetype='application/pdf', 
            as_attachment=True, 
            download_name=f'receipt_{receipt_number}.pdf'
        )
        
    except Exception as e:
        print(f"Error generating receipt PDF: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


@payments_bp.route('/api/get/<payment_id>', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant', 'admin'])
def get_payment(payment_id):
    """Get single payment details with student info"""
    try:
        user = session.get('user')
        user_email = user.get('email', '')
        admin_emails = os.getenv('ADMIN_EMAILS', '').split(',')
        is_admin = user_email in admin_emails
        
        # Get institute ID for filtering
        if not is_admin:
            institute_id = get_institute_id(user['id'])
            if not institute_id:
                return jsonify({'success': False, 'message': 'Institute not found'}), 404
        else:
            institute_id = request.args.get('institute_id', '')
        
        # First get the payment to get student_id
        payment_query = supabase.table('payments')\
            .select('*')\
            .eq('id', payment_id)
        
        if institute_id:
            payment_query = payment_query.eq('institute_id', institute_id)
        elif not is_admin:
            payment_query = payment_query.eq('institute_id', institute_id)
        
        payment_response = payment_query.execute()
        
        if not payment_response.data:
            return jsonify({'success': False, 'message': 'Payment not found or access denied'}), 404
        
        payment = payment_response.data[0]
        student_id = payment.get('student_id')
        
        # Get student info including phone number
        student_data = {}
        if student_id:
            student_query = supabase.table('students')\
                .select('name, student_id, contact_number')\
                .eq('id', student_id)\
                .execute()
            
            if student_query.data:
                student_data = student_query.data[0]
        
        phone_number = student_data.get('contact_number', '')
        
        return jsonify({
            'success': True, 
            'payment': {
                'id': payment.get('id'),
                'receipt_number': payment.get('receipt_number'),
                'amount': payment.get('amount'),
                'payment_date': payment.get('payment_date'),
                'payment_method': payment.get('payment_method'),
                'student_name': student_data.get('name', 'N/A'),
                'student_id': student_data.get('student_id', 'N/A'),
                'phone_number': phone_number
            }
        })
        
    except Exception as e:
        print(f"Error getting payment: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@payments_bp.route('/api/update-whatsapp-status/<payment_id>', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant', 'admin'])
def update_whatsapp_status(payment_id):
    """Update WhatsApp status for a payment"""
    try:
        user = session.get('user')
        user_email = user.get('email', '')
        admin_emails = os.getenv('ADMIN_EMAILS', '').split(',')
        is_admin = user_email in admin_emails
        
        # Get institute ID for filtering
        if not is_admin:
            institute_id = get_institute_id(user['id'])
            if not institute_id:
                return jsonify({'success': False, 'message': 'Institute not found'}), 404
        else:
            institute_id = request.args.get('institute_id', '')
        
        # Verify payment exists and belongs to institute
        query = supabase.table('payments')\
            .select('id')\
            .eq('id', payment_id)
        
        if institute_id:
            query = query.eq('institute_id', institute_id)
        elif not is_admin:
            query = query.eq('institute_id', institute_id)
        
        check_response = query.execute()
        if not check_response.data:
            return jsonify({'success': False, 'message': 'Payment not found or access denied'}), 404
        
        # Update WhatsApp status
        data = request.get_json()
        status = data.get('status', 'sent')
        
        update_data = {
            'whatsapp_status': status,
            'whatsapp_sent_at': datetime.now().isoformat()
        }
        
        # Increment sent count if status is sent
        if status == 'sent':
            # Get current count first
            current = supabase.table('payments')\
                .select('whatsapp_sent_count')\
                .eq('id', payment_id)\
                .execute()
            
            current_count = current.data[0].get('whatsapp_sent_count', 0) if current.data else 0
            update_data['whatsapp_sent_count'] = current_count + 1
        
        response = supabase.table('payments')\
            .update(update_data)\
            .eq('id', payment_id)\
            .execute()
        
        return jsonify({
            'success': True, 
            'message': f'WhatsApp status updated to {status}'
        })
        
    except Exception as e:
        print(f"Error updating WhatsApp status: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@payments_bp.route('/api/bulk-send-whatsapp', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant', 'admin'])
def bulk_send_whatsapp():
    """Bulk send receipts via WhatsApp"""
    try:
        user = session.get('user')
        user_email = user.get('email', '')
        admin_emails = os.getenv('ADMIN_EMAILS', '').split(',')
        is_admin = user_email in admin_emails
        
        # Get institute ID for filtering
        if not is_admin:
            institute_id = get_institute_id(user['id'])
            if not institute_id:
                return jsonify({'success': False, 'message': 'Institute not found'}), 404
        else:
            institute_id = request.args.get('institute_id', '')
        
        data = request.get_json()
        payment_ids = data.get('payment_ids', [])
        
        if not payment_ids:
            return jsonify({'success': False, 'message': 'No payment IDs provided'}), 400
        
        # Get payments with student info
        query = supabase.table('payments')\
            .select('*, students!inner(name, student_id, contact_number)')\
            .in_('id', payment_ids)
        
        if institute_id:
            query = query.eq('institute_id', institute_id)
        elif not is_admin:
            query = query.eq('institute_id', institute_id)
        
        response = query.execute()
        payments = response.data if response.data else []
        
        if not payments:
            return jsonify({'success': False, 'message': 'No valid payments found'}), 404
        
        # Process each payment
        results = []
        for payment in payments:
            # Get phone from students data
            phone = payment.get('students', {}).get('contact_number', '')
            
            if not phone:
                results.append({
                    'id': payment['id'],
                    'receipt': payment['receipt_number'],
                    'student': payment.get('students', {}).get('name', 'Unknown'),
                    'status': 'skipped',
                    'message': 'No phone number'
                })
                continue
            
            # Forward to WhatsApp integration
            try:
                # Generate receipt PDF first
                receipt_pdf = generate_receipt_pdf(payment['receipt_number'], payment['id'])
                if not receipt_pdf:
                    results.append({
                        'id': payment['id'],
                        'receipt': payment['receipt_number'],
                        'student': payment.get('students', {}).get('name', 'Unknown'),
                        'status': 'failed',
                        'message': 'Failed to generate PDF'
                    })
                    continue
                
                whatsapp_response = requests.post(
                    f"{os.getenv('WHATSAPP_API_URL', 'http://localhost:3000')}/api/send-pdf",
                    json={
                        'number': phone,
                        'pdfBuffer': receipt_pdf,
                        'filename': f"Receipt_{payment['receipt_number']}.pdf",
                        'instituteId': payment.get('institute_id') or institute_id
                    },
                    timeout=60
                )
                
                if whatsapp_response.status_code == 200:
                    # Update status
                    supabase.table('payments')\
                        .update({
                            'whatsapp_status': 'sent',
                            'whatsapp_sent_at': datetime.now().isoformat()
                        })\
                        .eq('id', payment['id'])\
                        .execute()
                    
                    results.append({
                        'id': payment['id'],
                        'receipt': payment['receipt_number'],
                        'student': payment.get('students', {}).get('name', 'Unknown'),
                        'phone': phone,
                        'status': 'sent'
                    })
                else:
                    results.append({
                        'id': payment['id'],
                        'receipt': payment['receipt_number'],
                        'student': payment.get('students', {}).get('name', 'Unknown'),
                        'status': 'failed',
                        'message': 'WhatsApp API error'
                    })
            except Exception as e:
                results.append({
                    'id': payment['id'],
                    'receipt': payment['receipt_number'],
                    'student': payment.get('students', {}).get('name', 'Unknown'),
                    'status': 'failed',
                    'message': str(e)
                })
        
        return jsonify({
            'success': True,
            'results': results,
            'summary': {
                'total': len(results),
                'sent': len([r for r in results if r['status'] == 'sent']),
                'failed': len([r for r in results if r['status'] == 'failed']),
                'skipped': len([r for r in results if r['status'] == 'skipped'])
            }
        })
        
    except Exception as e:
        print(f"Error bulk sending WhatsApp: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

def generate_receipt_pdf(receipt_number, payment_id=None):
    """Helper function to generate receipt PDF and return base64"""
    try:
        # Get payment data
        query = supabase.table('payments')\
            .select('*')\
            .eq('receipt_number', receipt_number)
        
        if payment_id:
            query = query.eq('id', payment_id)
        
        response = query.execute()
        
        if not response.data:
            return None
        
        payment = response.data[0]
        
        # Get student data
        student_data = {}
        student_uuid = payment.get('student_id')
        if student_uuid:
            student_resp = supabase.table('students')\
                .select('name, student_id, contact_number, class_id')\
                .eq('id', student_uuid)\
                .execute()
            if student_resp.data:
                student_data = student_resp.data[0]
        
        # Get class data
        class_name = 'N/A'
        class_id = student_data.get('class_id')
        if class_id:
            class_resp = supabase.table('classes')\
                .select('name')\
                .eq('id', class_id)\
                .execute()
            if class_resp.data:
                class_name = class_resp.data[0].get('name', 'N/A')
        
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.units import inch
        from reportlab.pdfgen import canvas
        from reportlab.lib import colors
        import io
        from datetime import datetime
        
        buffer = io.BytesIO()
        c = canvas.Canvas(buffer, pagesize=letter)
        width, height = letter
        
        # Header
        c.setFont("Helvetica-Bold", 16)
        c.drawString(1*inch, height - 1*inch, "CAPITAL COLLEGE")
        c.setFont("Helvetica", 10)
        c.drawString(1*inch, height - 1.2*inch, "Payment Receipt")
        
        # Receipt details
        c.setFont("Helvetica-Bold", 12)
        c.drawString(1*inch, height - 1.8*inch, f"Receipt: {receipt_number}")
        c.setFont("Helvetica", 11)
        c.drawString(1*inch, height - 2.2*inch, f"Date: {payment.get('payment_date', datetime.now().strftime('%Y-%m-%d'))}")
        c.drawString(1*inch, height - 2.6*inch, f"Student: {student_data.get('name', 'N/A')}")
        c.drawString(1*inch, height - 3.0*inch, f"Student ID: {student_data.get('student_id', 'N/A')}")
        c.drawString(1*inch, height - 3.4*inch, f"Class: {class_name}")
        
        # Amount
        c.setFont("Helvetica-Bold", 14)
        c.setFillColor(colors.green)
        c.drawString(1*inch, height - 4.2*inch, f"Amount Paid: UGX {float(payment.get('amount', 0)):,.0f}")
        c.setFillColor(colors.black)
        c.setFont("Helvetica", 11)
        c.drawString(1*inch, height - 4.6*inch, f"Method: {payment.get('payment_method', 'N/A').upper()}")
        
        # Balance
        balance = float(payment.get('current_balance', 0))
        balance_color = colors.green if balance < 0 else colors.red
        c.setFillColor(balance_color)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(1*inch, height - 5.0*inch, f"Balance: UGX {abs(balance):,.0f} { '(Credit)' if balance < 0 else '(Due)' }")
        
        # Footer
        c.setFillColor(colors.grey)
        c.setFont("Helvetica", 8)
        c.drawString(1*inch, 1*inch, "This is a system-generated receipt. For inquiries, contact the accounts department.")
        c.drawString(1*inch, 0.8*inch, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        c.save()
        buffer.seek(0)
        
        # Convert to base64
        import base64
        return base64.b64encode(buffer.getvalue()).decode('utf-8')
        
    except Exception as e:
        print(f"Error generating PDF: {e}")
        import traceback
        traceback.print_exc()
        return None


@payments_bp.route('/api/check-whatsapp-status/<payment_id>', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant', 'admin'])
def check_whatsapp_status(payment_id):
    """Check WhatsApp status for a payment"""
    try:
        user = session.get('user')
        user_email = user.get('email', '')
        admin_emails = os.getenv('ADMIN_EMAILS', '').split(',')
        is_admin = user_email in admin_emails
        
        # Get institute ID for filtering
        if not is_admin:
            institute_id = get_institute_id(user['id'])
            if not institute_id:
                return jsonify({'success': False, 'message': 'Institute not found'}), 404
        else:
            institute_id = request.args.get('institute_id', '')
        
        query = supabase.table('payments')\
            .select('whatsapp_status, whatsapp_sent_at, whatsapp_sent_count')\
            .eq('id', payment_id)
        
        if institute_id:
            query = query.eq('institute_id', institute_id)
        elif not is_admin:
            query = query.eq('institute_id', institute_id)
        
        response = query.execute()
        
        if not response.data:
            return jsonify({'success': False, 'message': 'Payment not found or access denied'}), 404
        
        return jsonify({
            'success': True,
            'status': response.data[0]
        })
        
    except Exception as e:
        print(f"Error checking WhatsApp status: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@payments_bp.route('/api/whatsapp-stats', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant', 'admin'])
def get_whatsapp_stats():
    """Get WhatsApp statistics for payments"""
    try:
        user = session.get('user')
        user_email = user.get('email', '')
        admin_emails = os.getenv('ADMIN_EMAILS', '').split(',')
        is_admin = user_email in admin_emails
        
        # Get institute ID for filtering
        if not is_admin:
            institute_id = get_institute_id(user['id'])
            if not institute_id:
                return jsonify({
                    'success': True,
                    'stats': {
                        'sent': 0,
                        'pending': 0,
                        'failed': 0,
                        'total': 0
                    }
                })
        else:
            institute_id = request.args.get('institute_id', '')
        
        # Build query
        query = supabase.table('payments')\
            .select('whatsapp_status', count='exact')
        
        if institute_id:
            query = query.eq('institute_id', institute_id)
        elif not is_admin:
            query = query.eq('institute_id', institute_id)
        
        response = query.execute()
        payments = response.data if response.data else []
        
        # Calculate stats
        stats = {
            'sent': len([p for p in payments if p.get('whatsapp_status') == 'sent']),
            'pending': len([p for p in payments if p.get('whatsapp_status') == 'pending']),
            'failed': len([p for p in payments if p.get('whatsapp_status') == 'failed']),
            'total': len(payments)
        }
        
        return jsonify({
            'success': True,
            'stats': stats
        })
        
    except Exception as e:
        print(f"Error getting WhatsApp stats: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    
    

# Add a public route for receipt PDFs (no authentication required for viewing)
@payments_bp.route('/public/receipt/<receipt_number>', methods=['GET'])
def public_receipt_pdf(receipt_number):
    """Public route to view receipt PDF - accessible via link"""
    try:
        # Get payment data
        query = supabase.table('payments')\
            .select('*')\
            .eq('receipt_number', receipt_number)
        
        response = query.execute()
        
        if not response.data:
            return "Receipt not found", 404
        
        payment = response.data[0]
        
        # Get student data
        student_data = {}
        student_uuid = payment.get('student_id')
        if student_uuid:
            student_resp = supabase.table('students')\
                .select('name, student_id, contact_number, class_id')\
                .eq('id', student_uuid)\
                .execute()
            if student_resp.data:
                student_data = student_resp.data[0]
        
        # Get class data
        class_name = 'N/A'
        class_id = student_data.get('class_id')
        if class_id:
            class_resp = supabase.table('classes')\
                .select('name')\
                .eq('id', class_id)\
                .execute()
            if class_resp.data:
                class_name = class_resp.data[0].get('name', 'N/A')
        
        # Generate PDF
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.units import inch
        from reportlab.pdfgen import canvas
        from reportlab.lib import colors
        import io
        from datetime import datetime
        
        buffer = io.BytesIO()
        c = canvas.Canvas(buffer, pagesize=letter)
        width, height = letter
        
        # Header
        c.setFont("Helvetica-Bold", 16)
        c.drawString(1*inch, height - 1*inch, "CAPITAL COLLEGE")
        c.setFont("Helvetica", 10)
        c.drawString(1*inch, height - 1.2*inch, "Payment Receipt")
        
        # Receipt details
        c.setFont("Helvetica-Bold", 12)
        c.drawString(1*inch, height - 1.8*inch, f"Receipt: {receipt_number}")
        c.setFont("Helvetica", 11)
        c.drawString(1*inch, height - 2.2*inch, f"Date: {payment.get('payment_date', datetime.now().strftime('%Y-%m-%d'))}")
        c.drawString(1*inch, height - 2.6*inch, f"Student: {student_data.get('name', 'N/A')}")
        c.drawString(1*inch, height - 3.0*inch, f"Student ID: {student_data.get('student_id', 'N/A')}")
        c.drawString(1*inch, height - 3.4*inch, f"Class: {class_name}")
        
        # Amount
        c.setFont("Helvetica-Bold", 14)
        c.setFillColor(colors.green)
        c.drawString(1*inch, height - 4.2*inch, f"Amount Paid: UGX {float(payment.get('amount', 0)):,.0f}")
        c.setFillColor(colors.black)
        c.setFont("Helvetica", 11)
        c.drawString(1*inch, height - 4.6*inch, f"Method: {payment.get('payment_method', 'N/A').upper()}")
        
        # Balance
        balance = float(payment.get('current_balance', 0))
        balance_color = colors.green if balance < 0 else colors.red
        c.setFillColor(balance_color)
        c.setFont("Helvetica-Bold", 12)
        c.drawString(1*inch, height - 5.0*inch, f"Balance: UGX {abs(balance):,.0f} { '(Credit)' if balance < 0 else '(Due)' }")
        
        # Footer
        c.setFillColor(colors.grey)
        c.setFont("Helvetica", 8)
        c.drawString(1*inch, 1*inch, "This is a system-generated receipt. For inquiries, contact the accounts department.")
        c.drawString(1*inch, 0.8*inch, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        c.save()
        buffer.seek(0)
        
        return send_file(
            buffer, 
            mimetype='application/pdf', 
            as_attachment=False,  # Display in browser
            download_name=f'receipt_{receipt_number}.pdf'
        )
        
    except Exception as e:
        print(f"Error generating public receipt PDF: {e}")
        return "Error generating receipt", 500
    
    
@payments_bp.route('/api/send-whatsapp-link/<payment_id>', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant', 'admin'])
def send_whatsapp_link(payment_id):
    """Send WhatsApp message with receipt link - returns the message data for frontend"""
    print(f"\n=== SEND WHATSAPP LINK START ===")
    print(f"Payment ID: {payment_id}")
    
    try:
        user = session.get('user')
        user_email = user.get('email', '')
        admin_emails = os.getenv('ADMIN_EMAILS', '').split(',')
        is_admin = user_email in admin_emails
        print(f"User: {user_email}, Is Admin: {is_admin}")
        
        # First get the payment
        print(f"🔍 Querying payment with ID: {payment_id}")
        payment_query = supabase.table('payments')\
            .select('*')\
            .eq('id', payment_id)
        
        payment_response = payment_query.execute()
        print(f"Payment response data: {payment_response.data}")
        
        if not payment_response.data:
            print("❌ Payment not found")
            return jsonify({'success': False, 'message': 'Payment not found'}), 404
        
        payment = payment_response.data[0]
        print(f"✅ Payment found: {payment.get('receipt_number')}")
        
        # Get institute_id from the payment
        institute_id = payment.get('institute_id')
        print(f"Institute ID from payment: {institute_id}")
        
        # Get student data separately
        student_data = {}
        student_uuid = payment.get('student_id')
        print(f"Student UUID from payment: {student_uuid}")
        
        if student_uuid:
            print(f"🔍 Querying student with UUID: {student_uuid}")
            student_resp = supabase.table('students')\
                .select('name, student_id, contact_number')\
                .eq('id', student_uuid)\
                .execute()
            
            print(f"Student response data: {student_resp.data}")
            
            if student_resp.data:
                student_data = student_resp.data[0]
                print(f"✅ Student found: {student_data.get('name')}, Phone: {student_data.get('contact_number')}")
            else:
                print("❌ Student not found for UUID")
        else:
            print("❌ No student UUID in payment")
        
        phone_number = student_data.get('contact_number', '')
        print(f"Phone number extracted: '{phone_number}'")
        
        if not phone_number:
            print("❌ No phone number available")
            return jsonify({'success': False, 'message': 'Student has no phone number'}), 400
        
        # Get the base URL from request
        base_url = request.host_url.rstrip('/')
        print(f"Base URL: {base_url}")
        
        receipt_url = f"{base_url}/payments/public/receipt/{payment['receipt_number']}"
        print(f"Receipt URL: {receipt_url}")
        
        # Create message with link
        message = f"""🎓 *Payment Receipt*

Dear {student_data.get('name', 'Student')},

Your payment receipt is ready. Click the link below to view/download your receipt:

📄 {receipt_url}

Receipt: {payment['receipt_number']}
Amount: UGX {float(payment['amount']):,.0f}
Date: {payment['payment_date']}

Thank you for your payment!

"""
        print(f"Message length: {len(message)} characters")
        
        # Return the message data so frontend can call the Flask endpoint
        return jsonify({
            'success': True,
            'data': {
                'phone_number': phone_number,
                'message': message,
                'receipt_url': receipt_url,
                'payment_id': payment_id
            }
        })
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500
    

@payments_bp.route('/api/edit/<payment_id>', methods=['PUT'])
@role_required(['owner', 'accountant'])
def edit_payment(payment_id):
    """Edit payment amount - updates payment and reverses/reapplies to invoice"""
    try:
        user = session.get('user')
        user_email = user.get('email', '')
        admin_emails = os.getenv('ADMIN_EMAILS', '').split(',')
        is_admin = user_email in admin_emails
        
        # Get institute ID for filtering
        if not is_admin:
            institute_id = get_institute_id(user['id'])
            if not institute_id:
                return jsonify({'success': False, 'message': 'Institute not found'}), 404
        else:
            institute_id = request.args.get('institute_id', '')
        
        # Get the payment data
        data = request.get_json()
        new_amount = data.get('amount')
        
        if new_amount is None:
            return jsonify({'success': False, 'message': 'Amount is required'}), 400
        
        try:
            new_amount = float(new_amount)
            if new_amount <= 0:
                return jsonify({'success': False, 'message': 'Amount must be greater than 0'}), 400
        except (ValueError, TypeError):
            return jsonify({'success': False, 'message': 'Invalid amount format'}), 400
        
        # Get the existing payment
        query = supabase.table('payments')\
            .select('*')\
            .eq('id', payment_id)
        
        if institute_id and not is_admin:
            query = query.eq('institute_id', institute_id)
        elif institute_id and is_admin:
            query = query.eq('institute_id', institute_id)
        
        payment_response = query.execute()
        
        if not payment_response.data:
            return jsonify({'success': False, 'message': 'Payment not found or access denied'}), 404
        
        payment = payment_response.data[0]
        old_amount = float(payment['amount'])
        difference = new_amount - old_amount
        
        # If amount hasn't changed, return early
        if difference == 0:
            return jsonify({
                'success': True,
                'message': 'No changes made',
                'payment': payment
            })
        
        affected_invoices = []
        
        # If payment was linked to an invoice, update the invoice
        if payment.get('invoice_id'):
            invoice_response = supabase.table('invoices')\
                .select('*')\
                .eq('id', payment['invoice_id'])\
                .execute()
            
            if invoice_response.data:
                invoice = invoice_response.data[0]
                
                # Calculate new invoice values
                new_paid_amount = float(invoice['paid_amount']) + difference
                new_balance = float(invoice['total_amount']) - new_paid_amount
                
                # Determine new status
                if new_balance <= 0:
                    if new_balance < 0:
                        new_status = 'credit'
                    else:
                        new_status = 'paid'
                elif new_paid_amount > 0:
                    new_status = 'partial'
                else:
                    new_status = 'pending'
                
                # Update the invoice
                supabase.table('invoices')\
                    .update({
                        'paid_amount': new_paid_amount,
                        'balance': new_balance,
                        'status': new_status,
                        'updated_at': datetime.now().isoformat()
                    })\
                    .eq('id', payment['invoice_id'])\
                    .execute()
                
                affected_invoices.append({
                    'invoice_number': invoice['invoice_number'],
                    'old_balance': float(invoice['balance']),
                    'new_balance': new_balance
                })
        
        # Update the payment with new amount
        update_data = {
            'amount': new_amount,
            'updated_at': datetime.now().isoformat()
        }
        
        # Add a note about the edit
        notes = payment.get('notes', '')
        edit_note = f"Amount changed from UGX {old_amount:,.0f} to UGX {new_amount:,.0f} on {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        if notes:
            update_data['notes'] = f"{notes}\n{edit_note}"
        else:
            update_data['notes'] = edit_note
        
        response = supabase.table('payments')\
            .update(update_data)\
            .eq('id', payment_id)\
            .execute()
        
        if not response.data:
            return jsonify({'success': False, 'message': 'Failed to update payment'}), 500
        
        updated_payment = response.data[0]
        
        return jsonify({
            'success': True,
            'message': f'Payment amount updated from UGX {old_amount:,.0f} to UGX {new_amount:,.0f}',
            'payment': {
                'id': updated_payment['id'],
                'receipt_number': updated_payment['receipt_number'],
                'old_amount': old_amount,
                'new_amount': new_amount,
                'difference': difference
            },
            'affected_invoices': affected_invoices
        })
        
    except Exception as e:
        print(f"Error editing payment: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


@payments_bp.route('/api/edit/<payment_id>', methods=['GET'])
@role_required(['owner', 'accountant'])
def get_payment_for_edit(payment_id):
    """Get payment details for editing"""
    try:
        user = session.get('user')
        user_email = user.get('email', '')
        admin_emails = os.getenv('ADMIN_EMAILS', '').split(',')
        is_admin = user_email in admin_emails
        
        # Get institute ID for filtering
        if not is_admin:
            institute_id = get_institute_id(user['id'])
            if not institute_id:
                return jsonify({'success': False, 'message': 'Institute not found'}), 404
        else:
            institute_id = request.args.get('institute_id', '')
        
        # Get the payment with student info
        query = supabase.table('payments')\
            .select('*, students(name, student_id, contact_number, class_id)')\
            .eq('id', payment_id)
        
        if institute_id and not is_admin:
            query = query.eq('institute_id', institute_id)
        elif institute_id and is_admin:
            query = query.eq('institute_id', institute_id)
        
        payment_response = query.execute()
        
        if not payment_response.data:
            return jsonify({'success': False, 'message': 'Payment not found or access denied'}), 404
        
        payment = payment_response.data[0]
        student = payment.get('students', {})
        
        # Get class name
        class_name = 'N/A'
        if student.get('class_id'):
            class_resp = supabase.table('classes')\
                .select('name')\
                .eq('id', student['class_id'])\
                .execute()
            if class_resp.data:
                class_name = class_resp.data[0].get('name', 'N/A')
        
        # Get current balance
        current_balance = 0
        balance_invoices = supabase.table('invoices')\
            .select('balance')\
            .eq('student_id', payment['student_id'])\
            .eq('institute_id', payment['institute_id'])\
            .execute()
        
        if balance_invoices.data:
            current_balance = sum(inv['balance'] for inv in balance_invoices.data)
        
        return jsonify({
            'success': True,
            'payment': {
                'id': payment['id'],
                'receipt_number': payment['receipt_number'],
                'amount': float(payment['amount']),
                'payment_date': payment['payment_date'],
                'payment_method': payment['payment_method'],
                'student_name': student.get('name', 'N/A'),
                'student_id': student.get('student_id', 'N/A'),
                'phone_number': student.get('contact_number', 'N/A'),
                'class_name': class_name,
                'current_balance': current_balance,
                'notes': payment.get('notes', ''),
                'invoice_id': payment.get('invoice_id')
            }
        })
        
    except Exception as e:
        print(f"Error getting payment for edit: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500