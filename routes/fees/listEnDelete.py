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


@payments_bp.route('/api/list', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant', 'admin'])
def get_payments():
    """Get payments with institute-specific filtering"""
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
        
        # Build the base query
        query = supabase.table('payments')\
            .select('*, students(name, student_id, classes(name)), institutes(institute_name)', count='exact')\
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
        
        # Apply search filter
        if search:
            # First, try to search by receipt number directly
            receipt_search = supabase.table('payments')\
                .select('id')\
                .eq('institute_id', institute_id if institute_id else '00000000-0000-0000-0000-000000000000')\
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
                # Search for payments with matching student_ids
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
                # Filter query by the matching IDs
                query = query.in_('id', all_matching_ids)
            else:
                # No matches found, return empty result
                return jsonify({
                    'success': True,
                    'payments': [],
                    'total': 0,
                    'page': page,
                    'per_page': per_page,
                    'total_pages': 0
                })
        
        # Execute query with pagination
        offset = (page - 1) * per_page
        query = query.range(offset, offset + per_page - 1)
        
        response = query.execute()
        payments = response.data if response.data else []
        
        # Get total count for pagination (without pagination)
        count_query = supabase.table('payments')\
            .select('id', count='exact')
        
        if institute_id:
            count_query = count_query.eq('institute_id', institute_id)
        
        if start_date:
            count_query = count_query.gte('payment_date', start_date)
        if end_date:
            count_query = count_query.lte('payment_date', end_date)
        if payment_method:
            count_query = count_query.eq('payment_method', payment_method)
        
        if search and 'all_matching_ids' in locals() and all_matching_ids:
            count_query = count_query.in_('id', all_matching_ids)
        
        count_response = count_query.execute()
        total_count = count_response.count if count_response.count else 0
        
        # Enhance payment data with additional info
        for payment in payments:
            # Get current balance for the student
            invoices_response = supabase.table('invoices')\
                .select('balance')\
                .eq('student_id', payment['student_id'])\
                .eq('institute_id', payment['institute_id'])\
                .execute()
            
            current_balance = sum(inv['balance'] for inv in invoices_response.data) if invoices_response.data else 0
            
            payment['current_balance'] = current_balance
            payment['balance_status'] = 'credit' if current_balance < 0 else 'due' if current_balance > 0 else 'paid'
            
            # Format student name properly
            if payment.get('students'):
                payment['student_name'] = payment['students'].get('name', 'N/A')
                payment['student_id_display'] = payment['students'].get('student_id', 'N/A')
                if payment['students'].get('classes'):
                    payment['class_name'] = payment['students']['classes'].get('name', 'N/A')
                else:
                    payment['class_name'] = 'N/A'
            else:
                payment['student_name'] = 'N/A'
                payment['student_id_display'] = 'N/A'
                payment['class_name'] = 'N/A'
            
            # Get institute name
            if payment.get('institutes'):
                payment['institute_name'] = payment['institutes'].get('institute_name', 'N/A')
            else:
                payment['institute_name'] = 'N/A'
        
        return jsonify({
            'success': True,
            'payments': payments,
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