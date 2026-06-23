# Center.py - Optimized Report Center with Batch Processing
from flask import Blueprint, render_template, request, jsonify, session, send_file, json
from supabase import create_client, Client
import os
import pandas as pd
import io
from datetime import datetime, timedelta
from functools import wraps
from dotenv import load_dotenv
from routes.accounts.accounts import get_institute_id
import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

center_bp = Blueprint('center', __name__, url_prefix='/center')

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Thread pool for parallel processing
executor = ThreadPoolExecutor(max_workers=4)

def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Please login'}), 401
        return f(*args, **kwargs)
    return decorated_function

# ============================================================
# BATCH PROCESSING UTILITIES
# ============================================================

def batch_query(table, filters, select_fields, batch_size=500):
    """
    Execute batched queries to avoid timeout and memory issues
    """
    all_data = []
    offset = 0
    
    while True:
        query = supabase.table(table).select(select_fields)
        
        # Apply filters
        for key, value in filters.items():
            if isinstance(value, list):
                query = query.in_(key, value)
            elif isinstance(value, dict):
                if 'gte' in value:
                    query = query.gte(key, value['gte'])
                if 'lte' in value:
                    query = query.lte(key, value['lte'])
            else:
                query = query.eq(key, value)
        
        query = query.range(offset, offset + batch_size - 1)
        response = query.execute()
        
        if not response.data:
            break
            
        all_data.extend(response.data)
        
        if len(response.data) < batch_size:
            break
            
        offset += batch_size
    
    return all_data

def parallel_fetch(queries):
    """
    Execute multiple Supabase queries in parallel
    """
    def execute_query(query_config):
        table, filters, select_fields = query_config
        return batch_query(table, filters, select_fields)
    
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(execute_query, queries))
    
    return results

# ============================================================
# DASHBOARD
# ============================================================

@center_bp.route('/')
@login_required
def index():
    """Main Report Center Dashboard"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return render_template('center/dashboard.html', institute=None, classes=[], summary={})
    
    try:
        # Parallel fetch for dashboard data
        queries = [
            ('institutes', {'id': institute_id}, '*'),
            ('classes', {'institute_id': institute_id}, '*')
        ]
        
        institute_data, classes_data = parallel_fetch(queries)
        
        institute = institute_data[0] if institute_data else None
        classes = classes_data if classes_data else []
        
        # Get summary statistics
        summary = get_dashboard_summary_optimized(institute_id)
        
        return render_template('center/dashboard.html', 
                             institute=institute, 
                             classes=classes,
                             summary=summary,
                             now=datetime.now())
        
    except Exception as e:
        logger.error(f"Error loading report center: {e}")
        return render_template('center/dashboard.html', institute=None, classes=[], summary={})

def get_dashboard_summary_optimized(institute_id):
    """Get summary statistics for dashboard using parallel queries"""
    try:
        today = datetime.now()
        first_day = today.replace(day=1).strftime('%Y-%m-%d')
        last_day = today.strftime('%Y-%m-%d')
        
        # Prepare parallel queries
        queries = [
            ('payments', {
                'institute_id': institute_id,
                'payment_date': {'gte': first_day, 'lte': last_day}
            }, 'amount'),
            ('students', {
                'institute_id': institute_id,
                'status': 'active'
            }, 'id'),
            ('invoices', {
                'institute_id': institute_id
            }, 'balance, status'),
            ('expense_transactions', {
                'institute_id': institute_id,
                'transaction_date': {'gte': first_day, 'lte': last_day}
            }, 'amount')
        ]
        
        payments_data, students_data, invoices_data, expenses_data = parallel_fetch(queries)
        
        current_month_collection = sum(float(p['amount']) for p in payments_data)
        total_students = len(students_data)
        
        outstanding_balance = sum(float(inv['balance']) for inv in invoices_data if inv.get('status') != 'paid')
        current_month_expenses = sum(float(exp['amount']) for exp in expenses_data)
        
        return {
            'current_month_collection': current_month_collection,
            'total_students': total_students,
            'outstanding_balance': outstanding_balance,
            'current_month_expenses': current_month_expenses,
            'net_income': current_month_collection - current_month_expenses
        }
    except Exception as e:
        logger.error(f"Error getting summary: {e}")
        return {}

# ============================================================
# OPTIMIZED REPORT API ENDPOINTS
# ============================================================

@center_bp.route('/api/daily-collection', methods=['POST'])
@login_required
def get_daily_collection():
    """Get daily collection report with optimized batch processing"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        start_date = data.get('start_date', datetime.now().date().isoformat())
        end_date = data.get('end_date', datetime.now().date().isoformat())
        page = data.get('page', 1)
        per_page = min(data.get('per_page', 20), 100)  # Max 100 per page
        
        # Use batch query for payments with student data
        payments = batch_query('payments', 
            {
                'institute_id': institute_id,
                'payment_date': {'gte': start_date, 'lte': end_date}
            },
            '*, students(name, student_id, classes(name))'
        )
        
        if not payments:
            return jsonify({
                'success': True,
                'data': [],
                'total_collected': 0,
                'start_date': start_date,
                'end_date': end_date,
                'total_transactions': 0,
                'pagination': {
                    'current_page': page,
                    'total_pages': 0,
                    'total_items': 0,
                    'per_page': per_page
                }
            })
        
        # Use dictionary comprehension for faster aggregation
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
        
        # Sort by date descending
        result.sort(key=lambda x: x['date'], reverse=True)
        
        # Pagination
        total_items = len(result)
        total_pages = (total_items + per_page - 1) // per_page if total_items > 0 else 1
        start_idx = (page - 1) * per_page
        end_idx = min(start_idx + per_page, total_items)
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
                'total_items': total_items,
                'per_page': per_page
            }
        })
        
    except Exception as e:
        logger.error(f"Error getting daily collection: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@center_bp.route('/api/balance-report', methods=['POST'])
@login_required
def get_balance_report():
    """Get fees balance report with optimized batch queries and parallel processing"""
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
        per_page = min(data.get('per_page', 20), 100)
        
        # Step 1: Get all active students with class info in one query
        students_query = supabase.table('students')\
            .select('id, name, student_id, contact_number, class_id, classes(name)')\
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
        
        # Get student IDs in batches
        student_ids = [s['id'] for s in students]
        
        # Step 2: Parallel fetch invoices and payments
        queries = [
            ('invoices', {
                'institute_id': institute_id,
                'student_id': student_ids
            }, 'student_id, total_amount, paid_amount, balance, discount_applied, created_at, status'),
            ('payments', {
                'institute_id': institute_id,
                'student_id': student_ids
            }, 'student_id, amount, payment_date')
        ]
        
        all_invoices, all_payments = parallel_fetch(queries)
        
        # Step 3: Build fast lookup dictionaries
        invoices_by_student = {}
        payments_by_student = {}
        
        # Use defaultdict-like behavior with dict.setdefault for speed
        for inv in all_invoices:
            student_id = inv['student_id']
            if student_id not in invoices_by_student:
                invoices_by_student[student_id] = []
            invoices_by_student[student_id].append(inv)
        
        for pay in all_payments:
            student_id = pay['student_id']
            if student_id not in payments_by_student:
                payments_by_student[student_id] = []
            payments_by_student[student_id].append(pay)
        
        # Step 4: Build report data efficiently
        report_data = []
        total_invoiced = 0
        total_paid = 0
        total_discount = 0
        total_balance = 0
        
        # Pre-calculate activity check
        has_date_filter = bool(start_date or end_date)
        
        for student in students:
            student_id = student['id']
            invoices = invoices_by_student.get(student_id, [])
            payments = payments_by_student.get(student_id, [])
            
            # Calculate totals using generator expressions (more memory efficient)
            student_total_invoiced = sum(float(inv.get('total_amount', 0)) for inv in invoices)
            student_total_paid = sum(float(p.get('amount', 0)) for p in payments)
            student_discount = sum(float(inv.get('discount_applied', 0)) for inv in invoices)
            student_balance = student_total_invoiced - student_total_paid - student_discount
            
            # Check activity in date range if needed
            include_student = True
            if has_date_filter:
                has_invoice_activity = any(
                    start_date <= inv.get('created_at', '')[:10] <= end_date 
                    for inv in invoices 
                    if inv.get('created_at')
                ) if start_date and end_date else False
                
                has_payment_activity = any(
                    start_date <= pay.get('payment_date', '') <= end_date 
                    for pay in payments 
                    if pay.get('payment_date')
                ) if start_date and end_date else False
                
                include_student = has_invoice_activity or has_payment_activity
            
            if include_student and (invoices or payments):
                class_name = student.get('classes', {}).get('name', 'N/A') if isinstance(student.get('classes'), dict) else 'N/A'
                
                report_data.append({
                    'student_uuid': student_id,
                    'student_name': student['name'],
                    'student_id': student.get('student_id', 'N/A'),
                    'mobile_number': student.get('contact_number', 'N/A'),
                    'class': class_name,
                    'total_invoiced': student_total_invoiced,
                    'total_paid': student_total_paid,
                    'discount': student_discount,
                    'balance': student_balance
                })
                
                total_invoiced += student_total_invoiced
                total_paid += student_total_paid
                total_discount += student_discount
                total_balance += student_balance
        
        # Sort by balance (highest first) using key function
        report_data.sort(key=lambda x: x['balance'], reverse=True)
        
        # Apply pagination
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
        logger.error(f"Error getting balance report: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@center_bp.route('/api/income-expense', methods=['POST'])
@login_required
def get_income_expense_report():
    """Get income and expense report with parallel processing"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        start_date = data.get('start_date', (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'))
        end_date = data.get('end_date', datetime.now().strftime('%Y-%m-%d'))
        page = data.get('page', 1)
        per_page = min(data.get('per_page', 20), 100)
        
        # Parallel fetch for all transaction types
        queries = [
            ('payments', {
                'institute_id': institute_id,
                'payment_date': {'gte': start_date, 'lte': end_date}
            }, 'amount, payment_date, payment_method, students(name, student_id)'),
            ('income_transactions', {
                'institute_id': institute_id,
                'transaction_date': {'gte': start_date, 'lte': end_date}
            }, '*'),
            ('expense_transactions', {
                'institute_id': institute_id,
                'transaction_date': {'gte': start_date, 'lte': end_date}
            }, '*')
        ]
        
        payments, other_income, expenses = parallel_fetch(queries)
        
        # Calculate totals efficiently
        total_fee_income = sum(float(p['amount']) for p in payments)
        total_other_income = sum(float(i['amount']) for i in other_income)
        total_income = total_fee_income + total_other_income
        total_expenses = sum(float(e['amount']) for e in expenses)
        net_profit = total_income - total_expenses
        
        # Prepare transactions with list comprehensions (faster)
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
        
        # Pagination
        total_items = len(all_transactions)
        total_pages = (total_items + per_page - 1) // per_page if total_items > 0 else 1
        start_idx = (page - 1) * per_page
        end_idx = min(start_idx + per_page, total_items)
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
                'total_items': total_items,
                'per_page': per_page
            }
        })
        
    except Exception as e:
        logger.error(f"Error getting income/expense report: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@center_bp.route('/api/student-report', methods=['POST'])
@login_required
def get_student_report():
    """Get student-wise report with optimized queries"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        class_id = data.get('class_id')
        search = data.get('search', '').strip()
        page = data.get('page', 1)
        per_page = min(data.get('per_page', 20), 100)
        
        # Build student query with class info
        students_query = supabase.table('students')\
            .select('*, classes(name)')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')
        
        if class_id:
            students_query = students_query.eq('class_id', class_id)
        
        students_response = students_query.execute()
        students = students_response.data if students_response.data else []
        
        # Filter by search if provided
        if search:
            search_lower = search.lower()
            students = [s for s in students 
                       if search_lower in s['name'].lower() 
                       or search_lower in s.get('student_id', '').lower()]
        
        if not students:
            return jsonify({
                'success': True,
                'data': [],
                'summary': {
                    'total_students': 0,
                    'total_invoiced': 0,
                    'total_paid': 0,
                    'total_balance': 0
                },
                'pagination': {
                    'current_page': page,
                    'total_pages': 0,
                    'total_items': 0,
                    'per_page': per_page
                }
            })
        
        # Get student IDs
        student_ids = [s['id'] for s in students]
        
        # Parallel fetch invoices and recent payments
        queries = [
            ('invoices', {
                'institute_id': institute_id,
                'student_id': student_ids
            }, 'student_id, total_amount, paid_amount, balance, status'),
            ('payments', {
                'institute_id': institute_id,
                'student_id': student_ids
            }, 'student_id, amount, payment_date, receipt_number')
        ]
        
        all_invoices, all_payments = parallel_fetch(queries)
        
        # Group data by student
        invoices_by_student = {}
        payments_by_student = {}
        
        for inv in all_invoices:
            student_id = inv['student_id']
            if student_id not in invoices_by_student:
                invoices_by_student[student_id] = []
            invoices_by_student[student_id].append(inv)
        
        for pay in all_payments:
            student_id = pay['student_id']
            if student_id not in payments_by_student:
                payments_by_student[student_id] = []
            payments_by_student[student_id].append(pay)
        
        # Build report data
        report_data = []
        total_invoiced_sum = 0
        total_paid_sum = 0
        total_balance_sum = 0
        
        for student in students:
            student_id = student['id']
            invoices = invoices_by_student.get(student_id, [])
            payments = payments_by_student.get(student_id, [])
            
            total_invoiced = sum(float(inv['total_amount']) for inv in invoices)
            total_paid = sum(float(inv['paid_amount']) for inv in invoices)
            balance = sum(float(inv['balance']) for inv in invoices if inv.get('status') != 'paid')
            
            # Get 3 most recent payments
            recent_payments = sorted(payments, key=lambda x: x['payment_date'], reverse=True)[:3]
            
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
            
            total_invoiced_sum += total_invoiced
            total_paid_sum += total_paid
            total_balance_sum += balance
        
        # Sort by balance (highest first)
        report_data.sort(key=lambda x: x['balance'], reverse=True)
        
        # Pagination
        total_items = len(report_data)
        total_pages = (total_items + per_page - 1) // per_page if total_items > 0 else 1
        start_idx = (page - 1) * per_page
        end_idx = min(start_idx + per_page, total_items)
        paginated_data = report_data[start_idx:end_idx]
        
        return jsonify({
            'success': True,
            'data': paginated_data,
            'summary': {
                'total_students': total_items,
                'total_invoiced': total_invoiced_sum,
                'total_paid': total_paid_sum,
                'total_balance': total_balance_sum
            },
            'pagination': {
                'current_page': page,
                'total_pages': total_pages,
                'total_items': total_items,
                'per_page': per_page
            }
        })
        
    except Exception as e:
        logger.error(f"Error getting student report: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@center_bp.route('/api/class-report', methods=['POST'])
@login_required
def get_class_report():
    """Get class-wise report with optimized batch processing"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        page = data.get('page', 1)
        per_page = min(data.get('per_page', 20), 100)
        
        # Get all classes
        classes_response = supabase.table('classes')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .execute()
        
        classes = classes_response.data or []
        
        if not classes:
            return jsonify({
                'success': True,
                'data': [],
                'summary': {
                    'total_classes': 0,
                    'total_students': 0,
                    'total_collected': 0,
                    'total_expected': 0,
                    'total_outstanding': 0
                },
                'pagination': {
                    'current_page': page,
                    'total_pages': 0,
                    'total_items': 0,
                    'per_page': per_page
                }
            })
        
        # Get all students by class
        class_ids = [c['id'] for c in classes]
        students_response = supabase.table('students')\
            .select('id, class_id')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')\
            .in_('class_id', class_ids)\
            .execute()
        
        students = students_response.data or []
        
        # Group students by class
        students_by_class = {}
        for student in students:
            class_id = student['class_id']
            if class_id not in students_by_class:
                students_by_class[class_id] = []
            students_by_class[class_id].append(student['id'])
        
        # Get all payments and invoices for students
        all_student_ids = [s['id'] for s in students]
        
        queries = []
        if all_student_ids:
            payment_filters = {'institute_id': institute_id, 'student_id': all_student_ids}
            if start_date:
                payment_filters['payment_date'] = {'gte': start_date}
            if end_date:
                payment_filters['payment_date'] = {'lte': end_date} if 'payment_date' not in payment_filters else payment_filters['payment_date']
            
            invoice_filters = {'institute_id': institute_id, 'student_id': all_student_ids}
            if start_date:
                invoice_filters['created_at'] = {'gte': f"{start_date}T00:00:00"}
            if end_date:
                invoice_filters['created_at'] = {'lte': f"{end_date}T23:59:59"} if 'created_at' not in invoice_filters else invoice_filters['created_at']
            
            queries = [
                ('payments', payment_filters, 'student_id, amount'),
                ('invoices', invoice_filters, 'student_id, total_amount')
            ]
        
        all_payments, all_invoices = parallel_fetch(queries) if queries else ([], [])
        
        # Aggregate by student
        payments_by_student = {}
        invoices_by_student = {}
        
        for pay in all_payments:
            student_id = pay['student_id']
            if student_id not in payments_by_student:
                payments_by_student[student_id] = 0
            payments_by_student[student_id] += float(pay['amount'])
        
        for inv in all_invoices:
            student_id = inv['student_id']
            if student_id not in invoices_by_student:
                invoices_by_student[student_id] = 0
            invoices_by_student[student_id] += float(inv['total_amount'])
        
        # Build class report
        report_data = []
        total_students_all = 0
        total_collected_all = 0
        total_expected_all = 0
        
        for class_item in classes:
            class_id = class_item['id']
            student_ids = students_by_class.get(class_id, [])
            student_count = len(student_ids)
            
            # Calculate totals for this class
            class_collected = sum(payments_by_student.get(sid, 0) for sid in student_ids)
            class_expected = sum(invoices_by_student.get(sid, 0) for sid in student_ids)
            
            report_data.append({
                'class_name': class_item['name'],
                'class_id': class_id,
                'student_count': student_count,
                'total_collected': class_collected,
                'expected_fees': class_expected,
                'outstanding': class_expected - class_collected
            })
            
            total_students_all += student_count
            total_collected_all += class_collected
            total_expected_all += class_expected
        
        # Sort by class name
        report_data.sort(key=lambda x: x['class_name'])
        
        # Pagination
        total_items = len(report_data)
        total_pages = (total_items + per_page - 1) // per_page if total_items > 0 else 1
        start_idx = (page - 1) * per_page
        end_idx = min(start_idx + per_page, total_items)
        paginated_data = report_data[start_idx:end_idx]
        
        return jsonify({
            'success': True,
            'data': paginated_data,
            'summary': {
                'total_classes': len(classes),
                'total_students': total_students_all,
                'total_collected': total_collected_all,
                'total_expected': total_expected_all,
                'total_outstanding': total_expected_all - total_collected_all
            },
            'pagination': {
                'current_page': page,
                'total_pages': total_pages,
                'total_items': total_items,
                'per_page': per_page
            }
        })
        
    except Exception as e:
        logger.error(f"Error getting class report: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@center_bp.route('/api/payment-method-report', methods=['POST'])
@login_required
def get_payment_method_report():
    """Get payment method breakdown report with optimized queries"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        start_date = data.get('start_date', (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'))
        end_date = data.get('end_date', datetime.now().strftime('%Y-%m-%d'))
        
        # Parallel fetch payments and expenses
        queries = [
            ('payments', {
                'institute_id': institute_id,
                'payment_date': {'gte': start_date, 'lte': end_date}
            }, 'payment_method, amount'),
            ('expense_transactions', {
                'institute_id': institute_id,
                'transaction_date': {'gte': start_date, 'lte': end_date}
            }, 'payment_method, amount')
        ]
        
        payments, expenses = parallel_fetch(queries)
        
        # Aggregate using dictionary comprehensions
        method_totals = {}
        for payment in payments:
            method = payment.get('payment_method', 'other')
            method_totals[method] = method_totals.get(method, 0) + float(payment['amount'])
        
        expense_method_totals = {}
        for expense in expenses:
            method = expense.get('payment_method', 'cash')
            expense_method_totals[method] = expense_method_totals.get(method, 0) + float(expense['amount'])
        
        # Build report data
        all_methods = set(method_totals.keys()) | set(expense_method_totals.keys())
        report_data = []
        
        for method in all_methods:
            report_data.append({
                'payment_method': method.upper(),
                'income': method_totals.get(method, 0),
                'expenses': expense_method_totals.get(method, 0),
                'net': method_totals.get(method, 0) - expense_method_totals.get(method, 0)
            })
        
        # Sort by income descending
        report_data.sort(key=lambda x: x['income'], reverse=True)
        
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
        logger.error(f"Error getting payment method report: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

# ============================================================
# EXPORT ENDPOINT (Optimized)
# ============================================================

@center_bp.route('/export', methods=['POST'])
@login_required
def export_report():
    """Export report data to Excel with optimized processing"""
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
        
        # Get institute name (cached or single query)
        institute_response = supabase.table('institutes')\
            .select('institute_name')\
            .eq('id', institute_id)\
            .execute()
        
        institute_name = institute_response.data[0]['institute_name'] if institute_response.data else 'Institute'
        
        # Define column mappings for each report type
        report_configs = {
            'daily_collection': {
                'columns': ['Date', 'Receipt Number', 'Student Name', 'Student ID', 'Amount', 'Payment Method', 'Notes'],
                'data_mapper': lambda data: [{
                    'Date': day['date'],
                    'Receipt Number': t['receipt_number'],
                    'Student Name': t['student_name'],
                    'Student ID': t['student_id'],
                    'Amount': t['amount'],
                    'Payment Method': t['payment_method'],
                    'Notes': t.get('notes', '')
                } for day in data for t in day.get('transactions', [])],
                'currency_cols': ['Amount']
            },
            'balance_report': {
                'columns': ['Student Name', 'Student ID', 'Class', 'Contact Number', 'Total Invoiced', 'Total Paid', 'Discount', 'Balance'],
                'data_mapper': lambda data: data,
                'currency_cols': ['Total Invoiced', 'Total Paid', 'Discount', 'Balance'],
                'column_mapping': {
                    'student_name': 'Student Name',
                    'student_id': 'Student ID',
                    'class': 'Class',
                    'mobile_number': 'Contact Number',
                    'total_invoiced': 'Total Invoiced',
                    'total_paid': 'Total Paid',
                    'discount': 'Discount',
                    'balance': 'Balance'
                }
            },
            'income_expense': {
                'columns': ['Date', 'Description', 'Amount', 'Type', 'Category'],
                'data_mapper': lambda data: data,
                'currency_cols': ['Amount'],
                'column_mapping': {
                    'date': 'Date',
                    'description': 'Description',
                    'amount': 'Amount',
                    'type': 'Type',
                    'category': 'Category'
                }
            },
            'student_report': {
                'columns': ['Student ID', 'Student Name', 'Class', 'Parent Contact', 'Total Invoiced', 'Total Paid', 'Balance', 'Status'],
                'data_mapper': lambda data: data,
                'currency_cols': ['Total Invoiced', 'Total Paid', 'Balance'],
                'column_mapping': {
                    'student_id': 'Student ID',
                    'student_name': 'Student Name',
                    'class': 'Class',
                    'parent_contact': 'Parent Contact',
                    'total_invoiced': 'Total Invoiced',
                    'total_paid': 'Total Paid',
                    'balance': 'Balance',
                    'status': 'Status'
                }
            },
            'class_report': {
                'columns': ['Class Name', 'Student Count', 'Total Collected', 'Expected Fees', 'Outstanding'],
                'data_mapper': lambda data: data,
                'currency_cols': ['Total Collected', 'Expected Fees', 'Outstanding'],
                'column_mapping': {
                    'class_name': 'Class Name',
                    'student_count': 'Student Count',
                    'total_collected': 'Total Collected',
                    'expected_fees': 'Expected Fees',
                    'outstanding': 'Outstanding'
                }
            },
            'payment_method': {
                'columns': ['Payment Method', 'Income', 'Expenses', 'Net'],
                'data_mapper': lambda data: data,
                'currency_cols': ['Income', 'Expenses', 'Net'],
                'column_mapping': {
                    'payment_method': 'Payment Method',
                    'income': 'Income',
                    'expenses': 'Expenses',
                    'net': 'Net'
                }
            }
        }
        
        config = report_configs.get(report_type, {'data_mapper': lambda x: x, 'currency_cols': []})
        
        # Transform data
        if report_type in report_configs:
            if report_type == 'daily_collection':
                df_data = config['data_mapper'](report_data)
            else:
                df_data = report_data
                if 'column_mapping' in config:
                    df_data = [{config['column_mapping'].get(k, k): v for k, v in item.items()} 
                              for item in df_data]
        else:
            df_data = report_data
        
        df = pd.DataFrame(df_data)
        
        # Format currency columns
        currency_cols = config.get('currency_cols', [])
        for col in currency_cols:
            if col in df.columns:
                df[col] = df[col].apply(lambda x: f'UGX {x:,.2f}' if pd.notna(x) else 'UGX 0')
        
        # Create Excel file
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            sheet_name = report_type.replace('_', ' ').title()
            df.to_excel(writer, sheet_name=sheet_name[:31], index=False)
            
            # Summary sheet
            summary_data = {
                'Report Type': [sheet_name],
                'Institute': [institute_name],
                'Generated Date': [datetime.now().strftime('%Y-%m-%d %H:%M:%S')],
                'Start Date': [start_date if start_date else 'N/A'],
                'End Date': [end_date if end_date else 'N/A'],
                'Total Records': [len(df)]
            }
            summary_df = pd.DataFrame(summary_data)
            summary_df.to_excel(writer, sheet_name='Summary', index=False)
            
            # Auto-adjust column widths
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
        logger.error(f"Error exporting to Excel: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

# ============================================================
# AI ANALYSIS ENDPOINTS (Optimized)
# ============================================================

@center_bp.route('/api/ai-analyze', methods=['POST'])
@login_required
def ai_analyze():
    """AI Analysis of selected report data with optimized fetching"""
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
        
        # Fetch report data using optimized functions
        report_data = fetch_report_data_optimized(institute_id, report_type, start_date, end_date, class_id, search)
        
        if not report_data or not report_data.get('data'):
            return jsonify({
                'success': False,
                'message': 'No data available for the selected period. Please try a different date range.'
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
        
        # Prepare data sample efficiently
        data_sample = []
        if isinstance(report_data.get('data'), list):
            data_sample = report_data['data'][:10]
        elif isinstance(report_data.get('data'), dict):
            data_sample = [{'metric': k, 'value': v} for k, v in list(report_data['data'].items())[:10]]
        
        return jsonify({
            'success': True,
            'analysis': formatted_analysis,
            'summary': report_data.get('summary', {}),
            'data_sample': data_sample
        })
        
    except Exception as e:
        logger.error(f"Error in AI analysis: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

def fetch_report_data_optimized(institute_id, report_type, start_date, end_date, class_id=None, search=''):
    """Fetch report data for AI analysis using optimized queries"""
    
    if report_type == 'daily_collection':
        payments = batch_query('payments',
            {
                'institute_id': institute_id,
                'payment_date': {'gte': start_date, 'lte': end_date}
            },
            '*, students(name, student_id, classes(name))'
        )
        
        if not payments:
            return {'data': [], 'summary': {}}
        
        daily_data = {}
        total_collected = 0
        payment_methods = {}
        
        for payment in payments:
            date = payment['payment_date']
            amount = float(payment['amount'])
            total_collected += amount
            
            if date not in daily_data:
                daily_data[date] = {'date': date, 'total': 0, 'count': 0}
            
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
        # Get students with class info
        students_query = supabase.table('students')\
            .select('*, classes(name)')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')
        
        if class_id:
            students_query = students_query.eq('class_id', class_id)
        
        students_response = students_query.execute()
        students = students_response.data or []
        
        if not students:
            return {'data': [], 'summary': {}}
        
        student_ids = [s['id'] for s in students]
        
        # Parallel fetch invoices and payments
        queries = [
            ('invoices', {
                'institute_id': institute_id,
                'student_id': student_ids
            }, 'student_id, total_amount, paid_amount, balance, status'),
            ('payments', {
                'institute_id': institute_id,
                'student_id': student_ids
            }, 'student_id, amount')
        ]
        
        all_invoices, all_payments = parallel_fetch(queries)
        
        # Aggregate
        invoices_by_student = {}
        for inv in all_invoices:
            student_id = inv['student_id']
            if student_id not in invoices_by_student:
                invoices_by_student[student_id] = []
            invoices_by_student[student_id].append(inv)
        
        payments_by_student = {}
        for pay in all_payments:
            student_id = pay['student_id']
            if student_id not in payments_by_student:
                payments_by_student[student_id] = 0
            payments_by_student[student_id] += float(pay['amount'])
        
        report_data = []
        total_invoiced = 0
        total_paid = 0
        total_balance = 0
        students_with_balance = 0
        
        for student in students:
            student_id = student['id']
            invoices = invoices_by_student.get(student_id, [])
            
            student_total_invoiced = sum(float(inv['total_amount']) for inv in invoices)
            student_total_paid = payments_by_student.get(student_id, 0)
            student_balance = sum(float(inv['balance']) for inv in invoices if inv.get('status') != 'paid')
            
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
        # Parallel fetch all transactions
        queries = [
            ('payments', {
                'institute_id': institute_id,
                'payment_date': {'gte': start_date, 'lte': end_date}
            }, 'amount, payment_date'),
            ('income_transactions', {
                'institute_id': institute_id,
                'transaction_date': {'gte': start_date, 'lte': end_date}
            }, 'amount, category'),
            ('expense_transactions', {
                'institute_id': institute_id,
                'transaction_date': {'gte': start_date, 'lte': end_date}
            }, 'amount, category')
        ]
        
        payments, other_income, expenses = parallel_fetch(queries)
        
        total_fee_income = sum(float(p['amount']) for p in payments)
        total_other_income = sum(float(i['amount']) for i in other_income)
        total_expenses = sum(float(e['amount']) for e in expenses)
        
        # Group by category
        expenses_by_category = {}
        for expense in expenses:
            category = expense.get('category', 'General')
            expenses_by_category[category] = expenses_by_category.get(category, 0) + float(expense['amount'])
        
        income_by_category = {'School Fees': total_fee_income}
        for inc in other_income:
            category = inc.get('category', 'Other Income')
            income_by_category[category] = income_by_category.get(category, 0) + float(inc['amount'])
        
        total_income = total_fee_income + total_other_income
        net_profit = total_income - total_expenses
        
        return {
            'data': {
                'fee_income': total_fee_income,
                'other_income': total_other_income,
                'total_income': total_income,
                'total_expenses': total_expenses,
                'net_profit': net_profit,
                'expenses_by_category': expenses_by_category,
                'income_by_category': income_by_category
            },
            'summary': {
                'total_income': total_income,
                'total_fee_income': total_fee_income,
                'total_other_income': total_other_income,
                'total_expenses': total_expenses,
                'net_profit': net_profit,
                'profit_margin': (net_profit / total_income * 100) if total_income > 0 else 0,
                'transaction_count': len(payments) + len(other_income) + len(expenses)
            }
        }
    
    elif report_type == 'class_report':
        classes_response = supabase.table('classes')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .execute()
        
        classes = classes_response.data or []
        
        if not classes:
            return {'data': [], 'summary': {}}
        
        class_ids = [c['id'] for c in classes]
        
        # Get students by class
        students_response = supabase.table('students')\
            .select('id, class_id')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')\
            .in_('class_id', class_ids)\
            .execute()
        
        students = students_response.data or []
        
        students_by_class = {}
        for student in students:
            class_id = student['class_id']
            if class_id not in students_by_class:
                students_by_class[class_id] = []
            students_by_class[class_id].append(student['id'])
        
        all_student_ids = [s['id'] for s in students]
        
        # Get payments
        payments_by_student = {}
        if all_student_ids:
            payments = batch_query('payments',
                {
                    'institute_id': institute_id,
                    'student_id': all_student_ids
                },
                'student_id, amount'
            )
            for pay in payments:
                student_id = pay['student_id']
                payments_by_student[student_id] = payments_by_student.get(student_id, 0) + float(pay['amount'])
        
        report_data = []
        total_students_all = 0
        total_collected_all = 0
        
        for class_item in classes:
            class_id = class_item['id']
            student_ids = students_by_class.get(class_id, [])
            student_count = len(student_ids)
            
            class_collected = sum(payments_by_student.get(sid, 0) for sid in student_ids)
            
            report_data.append({
                'class_name': class_item['name'],
                'student_count': student_count,
                'total_collected': class_collected
            })
            
            total_students_all += student_count
            total_collected_all += class_collected
        
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
    
    # Safely convert data to JSON string
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
    
    summary = report_data.get('summary', {})
    
    metrics_html = '<div class="bg-gradient-to-r from-orange-50 to-yellow-50 rounded-lg p-4 mb-6">'
    metrics_html += '<h4 class="font-bold text-gray-800 mb-3"><i class="fas fa-chart-line mr-2 text-orange-500"></i>Key Metrics</h4>'
    metrics_html += '<div class="grid grid-cols-2 md:grid-cols-4 gap-4">'
    
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
    
    # Process the analysis text with regex
    import re
    
    analysis_html = analysis_text
    analysis_html = re.sub(r'### (.*?)\n', r'<h4 class="font-bold text-gray-800 mt-4 mb-2">\1</h4>', analysis_html)
    analysis_html = re.sub(r'## (.*?)\n', r'<h3 class="font-bold text-lg text-gray-800 mt-6 mb-3 border-b border-orange-200 pb-2">\1</h3>', analysis_html)
    analysis_html = re.sub(r'\*\*(.*?)\*\*', r'<strong class="text-orange-600">\1</strong>', analysis_html)
    
    # Convert lists
    analysis_html = re.sub(r'^\* (.*?)$', r'<li class="ml-4 mb-1">\1</li>', analysis_html, flags=re.MULTILINE)
    analysis_html = re.sub(r'^- (.*?)$', r'<li class="ml-4 mb-1">\1</li>', analysis_html, flags=re.MULTILINE)
    analysis_html = re.sub(r'(<li.*?</li>)', r'<ul class="list-disc mb-3">\1</ul>', analysis_html, flags=re.DOTALL)
    
    # Convert markdown tables
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