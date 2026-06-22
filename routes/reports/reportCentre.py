# Center.py - Main Report Center Blueprint with Pagination
from flask import Blueprint, render_template, request, jsonify, session, send_file, json
from supabase import create_client, Client
import os
import pandas as pd
import io
from datetime import datetime, timedelta
from functools import wraps
from dotenv import load_dotenv
from routes.accounts.accounts import get_institute_id

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

center_bp = Blueprint('center', __name__, url_prefix='/center')

def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Please login'}), 401
        return f(*args, **kwargs)
    return decorated_function


@center_bp.route('/')
@login_required
def index():
    """Main Report Center Dashboard"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return render_template('center/dashboard.html', institute=None, classes=[], summary={})
    
    try:
        # Get institute details
        institute_response = supabase.table('institutes')\
            .select('*')\
            .eq('id', institute_id)\
            .execute()
        
        institute = institute_response.data[0] if institute_response.data else None
        
        # Get classes for filters
        classes_response = supabase.table('classes')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('name')\
            .execute()
        
        classes = classes_response.data if classes_response.data else []
        
        # Get summary statistics for dashboard
        summary = get_dashboard_summary(institute_id)
        
        return render_template('center/dashboard.html', 
                             institute=institute, 
                             classes=classes,
                             summary=summary,
                             now=datetime.now())
        
    except Exception as e:
        print(f"Error loading report center: {e}")
        return render_template('center/dashboard.html', institute=None, classes=[], summary={})


def get_dashboard_summary(institute_id):
    """Get summary statistics for dashboard"""
    try:
        # Get current month date range
        today = datetime.now()
        first_day = today.replace(day=1).strftime('%Y-%m-%d')
        last_day = today.strftime('%Y-%m-%d')
        
        # Current month collections
        payments_response = supabase.table('payments')\
            .select('amount')\
            .eq('institute_id', institute_id)\
            .gte('payment_date', first_day)\
            .lte('payment_date', last_day)\
            .execute()
        
        current_month_collection = sum(float(p['amount']) for p in (payments_response.data or []))
        
        # Total students
        students_response = supabase.table('students')\
            .select('id', count='exact')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')\
            .execute()
        
        total_students = students_response.count if hasattr(students_response, 'count') else len(students_response.data or [])
        
        # Outstanding balance
        invoices_response = supabase.table('invoices')\
            .select('balance')\
            .eq('institute_id', institute_id)\
            .neq('status', 'paid')\
            .execute()
        
        outstanding_balance = sum(float(inv['balance']) for inv in (invoices_response.data or []))
        
        # Total expenses current month
        expenses_response = supabase.table('expense_transactions')\
            .select('amount')\
            .eq('institute_id', institute_id)\
            .gte('transaction_date', first_day)\
            .lte('transaction_date', last_day)\
            .execute()
        
        current_month_expenses = sum(float(exp['amount']) for exp in (expenses_response.data or []))
        
        return {
            'current_month_collection': current_month_collection,
            'total_students': total_students,
            'outstanding_balance': outstanding_balance,
            'current_month_expenses': current_month_expenses,
            'net_income': current_month_collection - current_month_expenses
        }
    except Exception as e:
        print(f"Error getting summary: {e}")
        return {}


# ============================================================
# REPORT API ENDPOINTS WITH PAGINATION
# ============================================================

@center_bp.route('/api/daily-collection', methods=['POST'])
@login_required
def get_daily_collection():
    """Get daily collection report with pagination"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        page = data.get('page', 1)
        per_page = 20
        
        if not start_date:
            start_date = datetime.now().date().isoformat()
        if not end_date:
            end_date = datetime.now().date().isoformat()
        
        # Get payments within date range
        payments_response = supabase.table('payments')\
            .select('*, students(name, student_id, classes(name))')\
            .eq('institute_id', institute_id)\
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
                'student_uuid': payment['student_id'],
                'amount': amount,
                'payment_method': payment['payment_method'],
                'notes': payment.get('notes', '')
            })
        
        result = list(daily_data.values())
        total_pages = (len(result) + per_page - 1) // per_page if len(result) > 0 else 1
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        paginated_data = result[start_idx:end_idx]
        
        return jsonify({
            'success': True,
            'data': paginated_data,
            'total_collected': total_collected,
            'start_date': start_date,
            'end_date': end_date,
            'total_transactions': len(payments),
            'pagination': {
                'current_page': page,
                'total_pages': total_pages,
                'total_items': len(result),
                'per_page': per_page
            }
        })
        
    except Exception as e:
        print(f"Error getting daily collection: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    
    
@center_bp.route('/api/balance-report', methods=['POST'])
@login_required
def get_balance_report():
    """Get fees balance report with pagination - Optimized with batch queries"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        class_id = data.get('class_id')
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        page = data.get('page', 1)
        per_page = 20
        
        # ---------- STEP 1: Get all active students ----------
        students_query = supabase.table('students')\
            .select('id, name, student_id, contact_number, class_id')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')
        
        if class_id:
            students_query = students_query.eq('class_id', class_id)
        
        students_response = students_query.execute()
        students = students_response.data if students_response.data else []
        
        if not students:
            return jsonify({
                'success': True,
                'data': [],
                'summary': {
                    'total_invoiced': 0,
                    'total_paid': 0,
                    'total_discount': 0,
                    'total_balance': 0,
                    'student_count': 0
                },
                'pagination': {
                    'current_page': page,
                    'total_pages': 0,
                    'total_items': 0,
                    'per_page': per_page
                }
            })
        
        # Get all student IDs
        student_ids = [s['id'] for s in students]
        
        # ---------- STEP 2: Batch fetch all invoices for all students ----------
        invoices_query = supabase.table('invoices')\
            .select('student_id, total_amount, paid_amount, balance, discount_applied, created_at, status')\
            .eq('institute_id', institute_id)\
            .in_('student_id', student_ids)
        
        invoices_response = invoices_query.execute()
        all_invoices = invoices_response.data if invoices_response.data else []
        
        # ---------- STEP 3: Batch fetch all payments for all students ----------
        payments_query = supabase.table('payments')\
            .select('student_id, amount, payment_date')\
            .eq('institute_id', institute_id)\
            .in_('student_id', student_ids)
        
        payments_response = payments_query.execute()
        all_payments = payments_response.data if payments_response.data else []
        
        # ---------- STEP 4: Get class names in one query ----------
        class_ids = list(set([s.get('class_id') for s in students if s.get('class_id')]))
        classes_map = {}
        if class_ids:
            classes_response = supabase.table('classes')\
                .select('id, name')\
                .in_('id', class_ids)\
                .execute()
            if classes_response.data:
                classes_map = {c['id']: c['name'] for c in classes_response.data}
        
        # ---------- STEP 5: Aggregate data per student ----------
        # Initialize data structures
        student_invoices = {}
        student_payments = {}
        student_invoice_activity = set()
        student_payment_activity = set()
        
        # Group invoices by student
        for inv in all_invoices:
            student_id = inv['student_id']
            if student_id not in student_invoices:
                student_invoices[student_id] = []
            student_invoices[student_id].append(inv)
            
            # Check activity based on date filters
            if start_date or end_date:
                created_at = inv.get('created_at', '')
                if created_at:
                    inv_date = created_at.split('T')[0] if 'T' in created_at else created_at[:10]
                    if start_date and inv_date < start_date:
                        continue
                    if end_date and inv_date > end_date:
                        continue
                    student_invoice_activity.add(student_id)
            else:
                student_invoice_activity.add(student_id)
        
        # Group payments by student
        for pay in all_payments:
            student_id = pay['student_id']
            if student_id not in student_payments:
                student_payments[student_id] = []
            student_payments[student_id].append(pay)
            
            # Check activity based on date filters
            if start_date or end_date:
                pay_date = pay.get('payment_date', '')
                if pay_date:
                    if start_date and pay_date < start_date:
                        continue
                    if end_date and pay_date > end_date:
                        continue
                    student_payment_activity.add(student_id)
            else:
                student_payment_activity.add(student_id)
        
        # ---------- STEP 6: Build report data ----------
        report_data = []
        total_invoiced = 0
        total_paid = 0
        total_discount = 0
        total_balance = 0
        
        for student in students:
            student_id = student['id']
            
            # Get invoices for this student
            invoices = student_invoices.get(student_id, [])
            payments = student_payments.get(student_id, [])
            
            # Calculate totals
            student_total_invoiced = sum(float(inv.get('total_amount', 0)) for inv in invoices if float(inv.get('total_amount', 0)) > 0)
            student_total_paid = sum(float(p.get('amount', 0)) for p in payments)
            student_discount = sum(float(inv.get('discount_applied', 0)) for inv in invoices)
            student_balance = student_total_invoiced - student_total_paid - student_discount
            
            # Determine if student has activity in the date range
            has_activity = (student_id in student_invoice_activity) or (student_id in student_payment_activity)
            
            # Determine if we should include this student
            include_student = False
            if start_date or end_date:
                if has_activity:
                    include_student = True
            else:
                if student_balance != 0 or student_total_paid > 0 or student_total_invoiced > 0:
                    include_student = True
            
            if include_student and (len(invoices) > 0 or len(payments) > 0):
                class_name = classes_map.get(student.get('class_id'), 'N/A')
                
                report_data.append({
                    'student_uuid': student_id,
                    'student_name': student['name'],
                    'student_id': student.get('student_id', 'N/A'),
                    'mobile_number': student.get('contact_number', 'N/A'),
                    'class': class_name,
                    'total_invoiced': student_total_invoiced,
                    'total_paid': student_total_paid,
                    'discount': student_discount,
                    'balance': student_balance,
                    'has_activity_in_period': has_activity
                })
                
                total_invoiced += student_total_invoiced
                total_paid += student_total_paid
                total_discount += student_discount
                total_balance += student_balance
        
        # Sort by balance (highest first)
        report_data.sort(key=lambda x: x['balance'], reverse=True)
        
        # ---------- STEP 7: Apply pagination ----------
        total_items = len(report_data)
        total_pages = (total_items + per_page - 1) // per_page if total_items > 0 else 1
        start_idx = (page - 1) * per_page
        end_idx = min(start_idx + per_page, total_items)
        paginated_data = report_data[start_idx:end_idx]
        
        return jsonify({
            'success': True,
            'data': paginated_data,
            'summary': {
                'total_invoiced': total_invoiced,
                'total_paid': total_paid,
                'total_discount': total_discount,
                'total_balance': total_balance,
                'student_count': total_items
            },
            'pagination': {
                'current_page': page,
                'total_pages': total_pages,
                'total_items': total_items,
                'per_page': per_page
            }
        })
        
    except Exception as e:
        print(f"Error getting balance report: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500
@center_bp.route('/api/income-expense', methods=['POST'])
@login_required
def get_income_expense_report():
    """Get income and expense report with pagination"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        page = data.get('page', 1)
        per_page = 20
        
        if not start_date:
            start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        if not end_date:
            end_date = datetime.now().strftime('%Y-%m-%d')
        
        # Get fee payments
        payments_response = supabase.table('payments')\
            .select('amount, payment_date, payment_method, students(name, student_id)')\
            .eq('institute_id', institute_id)\
            .gte('payment_date', start_date)\
            .lte('payment_date', end_date)\
            .execute()
        
        # Get other income
        income_response = supabase.table('income_transactions')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .gte('transaction_date', start_date)\
            .lte('transaction_date', end_date)\
            .execute()
        
        # Get expenses
        expenses_response = supabase.table('expense_transactions')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .gte('transaction_date', start_date)\
            .lte('transaction_date', end_date)\
            .execute()
        
        payments = payments_response.data or []
        other_income = income_response.data or []
        expenses = expenses_response.data or []
        
        total_fee_income = sum(float(p['amount']) for p in payments)
        total_other_income = sum(float(i['amount']) for i in other_income)
        total_income = total_fee_income + total_other_income
        total_expenses = sum(float(e['amount']) for e in expenses)
        net_profit = total_income - total_expenses
        
        # Prepare transaction lists
        fee_transactions = [{
            'date': p['payment_date'],
            'description': f"Fee payment - {p['students']['name']} ({p['students']['student_id']})",
            'amount': float(p['amount']),
            'type': 'income',
            'category': 'School Fees',
            'payment_method': p.get('payment_method', 'cash')
        } for p in payments]
        
        other_income_transactions = [{
            'date': i['transaction_date'],
            'description': i.get('description', 'Other Income'),
            'amount': float(i['amount']),
            'type': 'income',
            'category': i.get('category', 'Other'),
            'payment_method': i.get('payment_method', 'cash')
        } for i in other_income]
        
        expense_transactions = [{
            'date': e['transaction_date'],
            'description': e.get('description', 'Expense'),
            'amount': float(e['amount']),
            'type': 'expense',
            'category': e.get('category', 'General'),
            'payment_method': e.get('payment_method', 'cash')
        } for e in expenses]
        
        # Combine and sort all transactions
        all_transactions = fee_transactions + other_income_transactions + expense_transactions
        all_transactions.sort(key=lambda x: x['date'], reverse=True)
        
        total_pages = (len(all_transactions) + per_page - 1) // per_page if len(all_transactions) > 0 else 1
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        paginated_data = all_transactions[start_idx:end_idx]
        
        return jsonify({
            'success': True,
            'summary': {
                'total_income': total_income,
                'total_fee_income': total_fee_income,
                'total_other_income': total_other_income,
                'total_expenses': total_expenses,
                'net_profit': net_profit
            },
            'transactions': paginated_data,
            'start_date': start_date,
            'end_date': end_date,
            'pagination': {
                'current_page': page,
                'total_pages': total_pages,
                'total_items': len(all_transactions),
                'per_page': per_page
            }
        })
        
    except Exception as e:
        print(f"Error getting income/expense report: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@center_bp.route('/api/student-report', methods=['POST'])
@login_required
def get_student_report():
    """Get student-wise report with pagination"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        class_id = data.get('class_id')
        search = data.get('search', '')
        page = data.get('page', 1)
        per_page = 20
        
        # Build query for students
        students_query = supabase.table('students')\
            .select('*, classes(name)')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')
        
        if class_id:
            students_query = students_query.eq('class_id', class_id)
        
        students_response = students_query.execute()
        students = students_response.data if students_response.data else []
        
        # Filter by search
        if search:
            students = [s for s in students if search.lower() in s['name'].lower() or search.lower() in s.get('student_id', '').lower()]
        
        report_data = []
        
        for student in students:
            # Get invoices
            invoices_response = supabase.table('invoices')\
                .select('*')\
                .eq('student_id', student['id'])\
                .eq('institute_id', institute_id)\
                .execute()
            
            invoices = invoices_response.data or []
            
            total_invoiced = sum(float(inv['total_amount']) for inv in invoices)
            total_paid = sum(float(inv['paid_amount']) for inv in invoices)
            balance = sum(float(inv['balance']) for inv in invoices)
            
            # Get recent payments
            payments_response = supabase.table('payments')\
                .select('amount, payment_date, receipt_number')\
                .eq('student_id', student['id'])\
                .eq('institute_id', institute_id)\
                .order('payment_date', desc=True)\
                .limit(3)\
                .execute()
            
            recent_payments = payments_response.data or []
            
            report_data.append({
                'student_uuid': student['id'],
                'student_id': student['student_id'],
                'student_name': student['name'],
                'class': student['classes']['name'] if student.get('classes') else 'N/A',
                'parent_contact': student.get('parent_contact', 'N/A'),
                'total_invoiced': total_invoiced,
                'total_paid': total_paid,
                'balance': balance,
                'status': 'Paid' if balance == 0 else 'Partial' if total_paid > 0 else 'Due',
                'recent_payments': recent_payments
            })
        
        # Sort by balance (highest first)
        report_data.sort(key=lambda x: x['balance'], reverse=True)
        
        total_pages = (len(report_data) + per_page - 1) // per_page if len(report_data) > 0 else 1
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        paginated_data = report_data[start_idx:end_idx]
        
        total_invoiced_sum = sum(s['total_invoiced'] for s in report_data)
        total_paid_sum = sum(s['total_paid'] for s in report_data)
        total_balance_sum = sum(s['balance'] for s in report_data)
        
        return jsonify({
            'success': True,
            'data': paginated_data,
            'summary': {
                'total_students': len(report_data),
                'total_invoiced': total_invoiced_sum,
                'total_paid': total_paid_sum,
                'total_balance': total_balance_sum
            },
            'pagination': {
                'current_page': page,
                'total_pages': total_pages,
                'total_items': len(report_data),
                'per_page': per_page
            }
        })
        
    except Exception as e:
        print(f"Error getting student report: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@center_bp.route('/api/class-report', methods=['POST'])
@login_required
def get_class_report():
    """Get class-wise report"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        page = data.get('page', 1)
        per_page = 20
        
        # Get all classes
        classes_response = supabase.table('classes')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .execute()
        
        classes = classes_response.data or []
        
        report_data = []
        total_students = 0
        total_collected = 0
        total_expected = 0
        
        for class_item in classes:
            # Get students in this class
            students_response = supabase.table('students')\
                .select('id')\
                .eq('class_id', class_item['id'])\
                .eq('institute_id', institute_id)\
                .eq('status', 'active')\
                .execute()
            
            student_ids = [s['id'] for s in (students_response.data or [])]
            student_count = len(student_ids)
            
            # Get payments for students in this class
            payments_query = supabase.table('payments')\
                .select('amount')\
                .eq('institute_id', institute_id)\
                .in_('student_id', student_ids) if student_ids else None
            
            if payments_query and start_date:
                payments_query = payments_query.gte('payment_date', start_date)
            if payments_query and end_date:
                payments_query = payments_query.lte('payment_date', end_date)
            
            payments_total = 0
            if payments_query:
                payments_response = payments_query.execute()
                payments_total = sum(float(p['amount']) for p in (payments_response.data or []))
            
            # Get expected fees (sum of invoice totals)
            invoices_query = supabase.table('invoices')\
                .select('total_amount')\
                .eq('institute_id', institute_id)\
                .in_('student_id', student_ids) if student_ids else None
            
            expected_total = 0
            if invoices_query:
                if start_date:
                    invoices_query = invoices_query.gte('created_at', f"{start_date}T00:00:00")
                if end_date:
                    invoices_query = invoices_query.lte('created_at', f"{end_date}T23:59:59")
                invoices_response = invoices_query.execute()
                expected_total = sum(float(inv['total_amount']) for inv in (invoices_response.data or []))
            
            report_data.append({
                'class_name': class_item['name'],
                'class_id': class_item['id'],
                'student_count': student_count,
                'total_collected': payments_total,
                'expected_fees': expected_total,
                'outstanding': expected_total - payments_total
            })
            
            total_students += student_count
            total_collected += payments_total
            total_expected += expected_total
        
        total_pages = (len(report_data) + per_page - 1) // per_page if len(report_data) > 0 else 1
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        paginated_data = report_data[start_idx:end_idx]
        
        return jsonify({
            'success': True,
            'data': paginated_data,
            'summary': {
                'total_classes': len(classes),
                'total_students': total_students,
                'total_collected': total_collected,
                'total_expected': total_expected,
                'total_outstanding': total_expected - total_collected
            },
            'pagination': {
                'current_page': page,
                'total_pages': total_pages,
                'total_items': len(report_data),
                'per_page': per_page
            }
        })
        
    except Exception as e:
        print(f"Error getting class report: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@center_bp.route('/api/payment-method-report', methods=['POST'])
@login_required
def get_payment_method_report():
    """Get payment method breakdown report"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        
        if not start_date:
            start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        if not end_date:
            end_date = datetime.now().strftime('%Y-%m-%d')
        
        # Get payments grouped by method
        payments_response = supabase.table('payments')\
            .select('payment_method, amount')\
            .eq('institute_id', institute_id)\
            .gte('payment_date', start_date)\
            .lte('payment_date', end_date)\
            .execute()
        
        payments = payments_response.data or []
        
        method_totals = {}
        for payment in payments:
            method = payment.get('payment_method', 'other')
            amount = float(payment['amount'])
            method_totals[method] = method_totals.get(method, 0) + amount
        
        # Also get expense payment methods
        expenses_response = supabase.table('expense_transactions')\
            .select('payment_method, amount')\
            .eq('institute_id', institute_id)\
            .gte('transaction_date', start_date)\
            .lte('transaction_date', end_date)\
            .execute()
        
        expenses = expenses_response.data or []
        
        expense_method_totals = {}
        for expense in expenses:
            method = expense.get('payment_method', 'cash')
            amount = float(expense['amount'])
            expense_method_totals[method] = expense_method_totals.get(method, 0) + amount
        
        report_data = []
        for method in set(list(method_totals.keys()) + list(expense_method_totals.keys())):
            report_data.append({
                'payment_method': method.upper(),
                'income': method_totals.get(method, 0),
                'expenses': expense_method_totals.get(method, 0),
                'net': method_totals.get(method, 0) - expense_method_totals.get(method, 0)
            })
        
        total_income = sum(method_totals.values())
        total_expenses = sum(expense_method_totals.values())
        
        return jsonify({
            'success': True,
            'data': report_data,
            'summary': {
                'total_income': total_income,
                'total_expenses': total_expenses,
                'net_flow': total_income - total_expenses
            },
            'start_date': start_date,
            'end_date': end_date
        })
        
    except Exception as e:
        print(f"Error getting payment method report: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


# ============================================================
# EXPORT ENDPOINTS
# ============================================================

@center_bp.route('/export', methods=['POST'])
@login_required
def export_report():
    """Export report data to Excel"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        report_type = data.get('report_type')
        report_data = data.get('data', [])
        start_date = data.get('start_date', '')
        end_date = data.get('end_date', '')
        
        if not report_data:
            return jsonify({'success': False, 'message': 'No data to export'}), 400
        
        # Get institute name for filename
        institute_response = supabase.table('institutes')\
            .select('institute_name')\
            .eq('id', institute_id)\
            .execute()
        
        institute_name = institute_response.data[0]['institute_name'] if institute_response.data else 'Institute'
        
        # Create DataFrame based on report type
        if report_type == 'daily_collection':
            flat_data = []
            for day in report_data:
                for transaction in day.get('transactions', []):
                    flat_data.append({
                        'Date': day['date'],
                        'Receipt Number': transaction['receipt_number'],
                        'Student Name': transaction['student_name'],
                        'Student ID': transaction['student_id'],
                        'Amount': transaction['amount'],
                        'Payment Method': transaction['payment_method'],
                        'Notes': transaction.get('notes', '')
                    })
            df = pd.DataFrame(flat_data)
            
        elif report_type == 'balance_report':
            df = pd.DataFrame(report_data)
            column_mapping = {
                'student_name': 'Student Name',
                'student_id': 'Student ID',
                'class': 'Class',
                'mobile_number': 'Contact Number',
                'total_invoiced': 'Total Invoiced',
                'total_paid': 'Total Paid',
                'discount': 'Discount',
                'balance': 'Balance'
            }
            df = df.rename(columns=column_mapping)
            
        elif report_type == 'income_expense':
            df = pd.DataFrame(report_data)
            column_mapping = {
                'date': 'Date',
                'description': 'Description',
                'amount': 'Amount',
                'type': 'Type',
                'category': 'Category'
            }
            df = df.rename(columns=column_mapping)
            
        elif report_type == 'student_report':
            df = pd.DataFrame(report_data)
            column_mapping = {
                'student_id': 'Student ID',
                'student_name': 'Student Name',
                'class': 'Class',
                'parent_contact': 'Parent Contact',
                'total_invoiced': 'Total Invoiced',
                'total_paid': 'Total Paid',
                'balance': 'Balance',
                'status': 'Status'
            }
            df = df.rename(columns=column_mapping)
            
        elif report_type == 'class_report':
            df = pd.DataFrame(report_data)
            column_mapping = {
                'class_name': 'Class Name',
                'student_count': 'Student Count',
                'total_collected': 'Total Collected',
                'expected_fees': 'Expected Fees',
                'outstanding': 'Outstanding'
            }
            df = df.rename(columns=column_mapping)
            
        elif report_type == 'payment_method':
            df = pd.DataFrame(report_data)
            column_mapping = {
                'payment_method': 'Payment Method',
                'income': 'Income',
                'expenses': 'Expenses',
                'net': 'Net'
            }
            df = df.rename(columns=column_mapping)
            
        else:
            df = pd.DataFrame(report_data)
        
        # Format currency columns
        currency_columns = ['Amount', 'Total Invoiced', 'Total Paid', 'Discount', 'Balance', 
                           'Total Collected', 'Expected Fees', 'Outstanding', 'Income', 'Expenses', 'Net']
        for col in currency_columns:
            if col in df.columns:
                df[col] = df[col].apply(lambda x: f'UGX {x:,.2f}' if pd.notna(x) else 'UGX 0')
        
        # Create Excel file with formatting
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name=report_type.replace('_', ' ').title(), index=False)
            
            summary_data = {
                'Report Type': [report_type.replace('_', ' ').title()],
                'Institute': [institute_name],
                'Generated Date': [datetime.now().strftime('%Y-%m-%d %H:%M:%S')],
                'Start Date': [start_date if start_date else 'N/A'],
                'End Date': [end_date if end_date else 'N/A'],
                'Total Records': [len(df)]
            }
            summary_df = pd.DataFrame(summary_data)
            summary_df.to_excel(writer, sheet_name='Summary', index=False)
            
            for sheet_name in writer.sheets:
                worksheet = writer.sheets[sheet_name]
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
        
        filename = f"{institute_name}_{report_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        
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
    
    
    
# ============================================================
# AI ANALYSIS ENDPOINTS
# ============================================================
@center_bp.route('/api/ai-analyze', methods=['POST'])
@login_required
def ai_analyze():
    """AI Analysis of selected report data"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        report_type = data.get('report_type')
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        class_id = data.get('class_id')
        search = data.get('search', '')
        
        # Validate date range (not more than a month)
        if start_date and end_date:
            start = datetime.strptime(start_date, '%Y-%m-%d')
            end = datetime.strptime(end_date, '%Y-%m-%d')
            days_diff = (end - start).days
            if days_diff > 31:
                return jsonify({
                    'success': False, 
                    'message': 'Date range cannot exceed 31 days (one month) for AI analysis'
                }), 400
        
        # Fetch report data based on type
        report_data = fetch_report_data(institute_id, report_type, start_date, end_date, class_id, search)
        
        if not report_data:
            return jsonify({
                'success': False,
                'message': 'No data available for the selected period'
            }), 400
        
        # Check if there's data to analyze
        has_data = False
        if isinstance(report_data.get('data'), list) and len(report_data.get('data', [])) > 0:
            has_data = True
        elif isinstance(report_data.get('data'), dict) and report_data.get('data'):
            has_data = True
        elif report_data.get('summary') and report_data['summary'].get('total_transactions', 0) > 0:
            has_data = True
            
        if not has_data:
            return jsonify({
                'success': False,
                'message': 'No data available for the selected period. Please try a different date range.'
            }), 400
        
        # Prepare data for AI analysis
        analysis_prompt = create_analysis_prompt(report_type, report_data, start_date, end_date)
        
        # Get AI analysis
        from routes.ai.ai import OpenRouterClient
        ai_client = OpenRouterClient()
        
        # For non-streaming analysis
        analysis_result = ai_client.chat(analysis_prompt, stream=False)
        
        # Format the analysis
        formatted_analysis = format_ai_analysis(analysis_result, report_type, report_data)
        
        # Prepare data sample safely
        data_sample = []
        if isinstance(report_data.get('data'), list):
            data_sample = report_data['data'][:10]
        elif isinstance(report_data.get('data'), dict):
            # For dict data (like income_expense), convert to list of key-value pairs
            data_sample = [{'metric': k, 'value': v} for k, v in list(report_data['data'].items())[:10]]
        
        return jsonify({
            'success': True,
            'analysis': formatted_analysis,
            'summary': report_data.get('summary', {}),
            'data_sample': data_sample
        })
        
    except Exception as e:
        print(f"Error in AI analysis: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


def fetch_report_data(institute_id, report_type, start_date, end_date, class_id=None, search=''):
    """Fetch report data for AI analysis"""
    
    if report_type == 'daily_collection':
        payments_response = supabase.table('payments')\
            .select('*, students(name, student_id, classes(name))')\
            .eq('institute_id', institute_id)\
            .gte('payment_date', start_date)\
            .lte('payment_date', end_date)\
            .execute()
        
        payments = payments_response.data or []
        
        daily_data = {}
        total_collected = 0
        payment_methods = {}
        
        for payment in payments:
            date = payment['payment_date']
            amount = float(payment['amount'])
            total_collected += amount
            
            if date not in daily_data:
                daily_data[date] = {
                    'date': date,
                    'total': 0,
                    'count': 0
                }
            
            daily_data[date]['total'] += amount
            daily_data[date]['count'] += 1
            
            method = payment.get('payment_method', 'cash')
            payment_methods[method] = payment_methods.get(method, 0) + amount
        
        return {
            'data': list(daily_data.values()),
            'summary': {
                'total_collected': total_collected,
                'total_transactions': len(payments),
                'date_range': f"{start_date} to {end_date}",
                'average_daily': total_collected / len(daily_data) if daily_data else 0,
                'payment_methods': payment_methods
            }
        }
    
    elif report_type == 'balance_report':
        students_query = supabase.table('students')\
            .select('*, classes(name)')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')
        
        if class_id:
            students_query = students_query.eq('class_id', class_id)
        
        students_response = students_query.execute()
        students = students_response.data or []
        
        report_data = []
        total_invoiced = 0
        total_paid = 0
        total_balance = 0
        students_with_balance = 0
        
        for student in students:
            invoices_response = supabase.table('invoices')\
                .select('*')\
                .eq('student_id', student['id'])\
                .eq('institute_id', institute_id)\
                .execute()
            
            invoices = invoices_response.data or []
            
            student_total_invoiced = sum(float(inv['total_amount']) for inv in invoices)
            student_total_paid = sum(float(inv['paid_amount']) for inv in invoices)
            student_balance = sum(float(inv['balance']) for inv in invoices if inv['status'] != 'paid')
            
            if student_balance > 0 or student_total_paid > 0:
                report_data.append({
                    'student_name': student['name'],
                    'student_id': student['student_id'],
                    'class': student['classes']['name'] if student.get('classes') else 'N/A',
                    'total_invoiced': student_total_invoiced,
                    'total_paid': student_total_paid,
                    'balance': student_balance
                })
                
                total_invoiced += student_total_invoiced
                total_paid += student_total_paid
                total_balance += student_balance
                if student_balance > 0:
                    students_with_balance += 1
        
        return {
            'data': report_data,
            'summary': {
                'total_invoiced': total_invoiced,
                'total_paid': total_paid,
                'total_balance': total_balance,
                'student_count': len(report_data),
                'students_with_balance': students_with_balance,
                'collection_rate': (total_paid / total_invoiced * 100) if total_invoiced > 0 else 0
            }
        }
    
    elif report_type == 'income_expense':
        # Get fee payments
        payments_response = supabase.table('payments')\
            .select('amount, payment_date')\
            .eq('institute_id', institute_id)\
            .gte('payment_date', start_date)\
            .lte('payment_date', end_date)\
            .execute()
        
        # Get other income
        income_response = supabase.table('income_transactions')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .gte('transaction_date', start_date)\
            .lte('transaction_date', end_date)\
            .execute()
        
        # Get expenses
        expenses_response = supabase.table('expense_transactions')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .gte('transaction_date', start_date)\
            .lte('transaction_date', end_date)\
            .execute()
        
        payments = payments_response.data or []
        other_income = income_response.data or []
        expenses = expenses_response.data or []
        
        total_fee_income = sum(float(p['amount']) for p in payments)
        total_other_income = sum(float(i['amount']) for i in other_income)
        total_expenses = sum(float(e['amount']) for e in expenses)
        
        # Group expenses by category
        expenses_by_category = {}
        for expense in expenses:
            category = expense.get('category', 'General')
            expenses_by_category[category] = expenses_by_category.get(category, 0) + float(expense['amount'])
        
        # Group income by category
        income_by_category = {'School Fees': total_fee_income}
        for inc in other_income:
            category = inc.get('category', 'Other Income')
            income_by_category[category] = income_by_category.get(category, 0) + float(inc['amount'])
        
        return {
            'data': {
                'fee_income': total_fee_income,
                'other_income': total_other_income,
                'total_income': total_fee_income + total_other_income,
                'total_expenses': total_expenses,
                'net_profit': total_fee_income + total_other_income - total_expenses,
                'expenses_by_category': expenses_by_category,
                'income_by_category': income_by_category
            },
            'summary': {
                'total_income': total_fee_income + total_other_income,
                'total_fee_income': total_fee_income,
                'total_other_income': total_other_income,
                'total_expenses': total_expenses,
                'net_profit': total_fee_income + total_other_income - total_expenses,
                'profit_margin': ((total_fee_income + total_other_income - total_expenses) / (total_fee_income + total_other_income) * 100) if (total_fee_income + total_other_income) > 0 else 0,
                'transaction_count': len(payments) + len(other_income) + len(expenses)
            }
        }
    
    elif report_type == 'class_report':
        classes_response = supabase.table('classes')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .execute()
        
        classes = classes_response.data or []
        
        report_data = []
        total_students_all = 0
        total_collected_all = 0
        
        for class_item in classes:
            students_response = supabase.table('students')\
                .select('id')\
                .eq('class_id', class_item['id'])\
                .eq('institute_id', institute_id)\
                .eq('status', 'active')\
                .execute()
            
            student_ids = [s['id'] for s in (students_response.data or [])]
            student_count = len(student_ids)
            
            # Get payments
            payments_total = 0
            if student_ids:
                payments_response = supabase.table('payments')\
                    .select('amount')\
                    .eq('institute_id', institute_id)\
                    .in_('student_id', student_ids)\
                    .execute()
                payments_total = sum(float(p['amount']) for p in (payments_response.data or []))
            
            report_data.append({
                'class_name': class_item['name'],
                'student_count': student_count,
                'total_collected': payments_total
            })
            
            total_students_all += student_count
            total_collected_all += payments_total
        
        return {
            'data': report_data,
            'summary': {
                'total_classes': len(classes),
                'total_students': total_students_all,
                'total_collected': total_collected_all,
                'average_per_class': total_collected_all / len(classes) if classes else 0
            }
        }
    
    return {'data': [], 'summary': {}}


def create_analysis_prompt(report_type, report_data, start_date, end_date):
    """Create AI analysis prompt based on report type"""
    
    report_name = report_type.replace('_', ' ').title()
    
    # Safely convert data to JSON string, handling different data types
    data_for_prompt = report_data.get('data', {})
    if isinstance(data_for_prompt, list):
        data_str = json.dumps(data_for_prompt[:20], indent=2, default=str)  # Limit to 20 items
    else:
        data_str = json.dumps(data_for_prompt, indent=2, default=str)
    
    prompt = f"""You are a financial analyst for an educational institution. Analyze the following {report_name} data for the period {start_date} to {end_date}.

REPORT SUMMARY:
{json.dumps(report_data.get('summary', {}), indent=2, default=str)}

SAMPLE DATA:
{data_str}

Please provide a comprehensive analysis in the following format:

## Executive Summary
[Brief overview of the financial health for this period]

## Key Metrics Analysis
- Present key figures in a table format
- Highlight important numbers and what they indicate

## Trends & Patterns
- Identify any notable patterns or anomalies in the data
- Compare against expected performance

## Actionable Insights
- Provide specific insights based on the data
- What is working well and what needs attention

## Recommendations
- Suggest specific actions to improve financial performance
- Prioritize recommendations by impact

## Risk Alerts
- Flag any concerning patterns that need immediate attention
- Identify potential issues before they become problems

Use markdown formatting with tables where appropriate. Keep the analysis professional but easy to understand for school administrators.

Important: If this is a balance report, focus on outstanding fees and collection efficiency.
If this is an income/expense report, focus on profitability and cost management.
If this is a daily collection report, focus on collection patterns and consistency.
If this is a class report, compare performance across different classes.
all money is in uganda shillings (UGX).
Be specific and reference actual numbers from the data provided."""
    
    return prompt


def format_ai_analysis(analysis_text, report_type, report_data):
    """Format AI analysis for display with proper styling"""
    
    # Add summary metrics at the beginning
    summary = report_data.get('summary', {})
    
    metrics_html = '<div class="bg-gradient-to-r from-orange-50 to-yellow-50 rounded-lg p-4 mb-6">'
    metrics_html += '<h4 class="font-bold text-gray-800 mb-3"><i class="fas fa-chart-line mr-2 text-orange-500"></i>Key Metrics</h4>'
    metrics_html += '<div class="grid grid-cols-2 md:grid-cols-4 gap-4">'
    
    # Show relevant metrics based on report type
    important_metrics = ['total_collected', 'total_income', 'total_expenses', 'net_profit', 
                         'total_balance', 'collection_rate', 'profit_margin', 'total_transactions']
    
    for key, value in summary.items():
        if key in important_metrics or len(summary.items()) <= 6:
            display_key = key.replace('_', ' ').title()
            if isinstance(value, (int, float)):
                if 'rate' in key or 'margin' in key:
                    formatted_value = f"{value:.1f}%"
                else:
                    formatted_value = f"UGX {value:,.0f}"
            else:
                formatted_value = str(value)
            
            metrics_html += f'''
            <div class="text-center">
                <p class="text-xs text-gray-500">{display_key}</p>
                <p class="text-lg font-bold text-gray-800">{formatted_value}</p>
            </div>
            '''
    
    metrics_html += '</div></div>'
    
    # Process the analysis text to add proper HTML formatting
    import re
    
    # Convert markdown headers
    analysis_html = analysis_text
    analysis_html = re.sub(r'### (.*?)\n', r'<h4 class="font-bold text-gray-800 mt-4 mb-2">\1</h4>', analysis_html)
    analysis_html = re.sub(r'## (.*?)\n', r'<h3 class="font-bold text-lg text-gray-800 mt-6 mb-3 border-b border-orange-200 pb-2">\1</h3>', analysis_html)
    
    # Convert bold
    analysis_html = re.sub(r'\*\*(.*?)\*\*', r'<strong class="text-orange-600">\1</strong>', analysis_html)
    
    # Convert lists
    analysis_html = re.sub(r'^\* (.*?)$', r'<li class="ml-4 mb-1">\1</li>', analysis_html, flags=re.MULTILINE)
    analysis_html = re.sub(r'^- (.*?)$', r'<li class="ml-4 mb-1">\1</li>', analysis_html, flags=re.MULTILINE)
    analysis_html = re.sub(r'(<li.*?</li>)', r'<ul class="list-disc mb-3">\1</ul>', analysis_html, flags=re.DOTALL)
    
    # Convert markdown tables to HTML
    table_pattern = r'\|(.+)\|\n\|[-:| ]+\|\n((?:\|.+\|\n?)+)'
    
    def convert_table(match):
        headers = [h.strip() for h in match.group(1).split('|') if h.strip()]
        rows = match.group(2).strip().split('\n')
        
        html = '<div class="overflow-x-auto my-4"><table class="min-w-full bg-white border border-gray-200 rounded-lg">'
        html += '<thead class="bg-gray-50"><tr>'
        for header in headers:
            html += f'<th class="px-4 py-2 text-left text-sm font-semibold text-gray-700 border-b">{header}</th>'
        html += '</tr></thead><tbody>'
        
        for row in rows:
            if row.strip():
                cells = [c.strip() for c in row.split('|') if c.strip()]
                if cells:
                    html += '<tr class="hover:bg-gray-50">'
                    for cell in cells:
                        # Format currency values
                        if cell.replace(',', '').replace('UGX', '').strip().isdigit() or (cell.startswith('UGX')):
                            pass  # Keep as is
                        html += f'<td class="px-4 py-2 text-sm text-gray-600 border-b">{cell}</td>'
                    html += '</tr>'
        
        html += '</tbody></table></div>'
        return html
    
    analysis_html = re.sub(table_pattern, convert_table, analysis_html, flags=re.MULTILINE)
    
    # Convert paragraphs
    paragraphs = analysis_html.split('\n\n')
    formatted_paragraphs = []
    for para in paragraphs:
        if not para.startswith('<h') and not para.startswith('<ul') and not para.startswith('<div') and para.strip() and not para.startswith('<table'):
            para = f'<p class="mb-3 text-gray-700">{para}</p>'
        formatted_paragraphs.append(para)
    
    analysis_html = '\n\n'.join(formatted_paragraphs)
    
    return metrics_html + analysis_html

@center_bp.route('/api/ai-report-options', methods=['GET'])
@login_required
def get_ai_report_options():
    """Get available report types for AI analysis"""
    return jsonify({
        'success': True,
        'report_types': [
            {'id': 'daily_collection', 'name': 'Daily Collection Report', 'requires_dates': True},
            {'id': 'balance_report', 'name': 'Balance Report', 'requires_dates': False},
            {'id': 'income_expense', 'name': 'Income & Expense Report', 'requires_dates': True},
            {'id': 'class_report', 'name': 'Class-wise Report', 'requires_dates': False}
        ]
    })