# dashboard.py - Optimized Main Dashboard Blueprint (FIXED)
from flask import Blueprint, render_template, request, jsonify, session
from supabase import create_client, Client
import os
from datetime import datetime, timedelta
from functools import wraps
from dotenv import load_dotenv
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

# Fix imports - use relative imports
from routes.auth.auth import accountant_required, secretary_required, support_staff_required, librarian_required, teacher_required, role_required
from routes.accounts.accounts import get_institute_from_session

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

dashboard_bp = Blueprint('dashboard', __name__, url_prefix='/dashboard')

# Simple in-memory cache
cache = {}
CACHE_TTL = 300  # 5 minutes

def cached(ttl=300):
    """Cache decorator - preserves original function name"""
    def decorator(func):
        @wraps(func)  # This preserves the original function name
        def wrapper(*args, **kwargs):
            cache_key = f"{func.__name__}:{str(args)}:{str(kwargs)}"
            now = datetime.now()
            
            if cache_key in cache:
                cached_data, timestamp = cache[cache_key]
                if (now - timestamp).seconds < ttl:
                    return cached_data
            
            result = func(*args, **kwargs)
            cache[cache_key] = (result, now)
            return result
        return wrapper
    return decorator

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Please login'}), 401
        return f(*args, **kwargs)
    return decorated_function

@dashboard_bp.route('/')
@role_required(['owner', 'teacher', 'accountant'])
def index():
    """Main Dashboard Page"""
    institute = get_institute_from_session()
    
    if not institute:
        return render_template('dashboard/index.html', institute_id=None, institute_name=None)
    
    return render_template('dashboard/index.html', 
                         institute_id=institute.get('id'), 
                         institute_name=institute.get('institute_name'))

@dashboard_bp.route('/api/stats', methods=['GET'])
@login_required
@cached(ttl=60)  # Cache for 1 minute
def get_dashboard_stats():
    """Get all dashboard statistics - OPTIMIZED with single queries"""
    institute = get_institute_from_session()
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    institute_id = institute.get('id')
    
    try:
        # Get date filters
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        if not start_date:
            start_date = datetime.now().replace(day=1).date().isoformat()
        if not end_date:
            end_date = datetime.now().date().isoformat()
        
        # OPTIMIZATION: Use parallel queries
        with ThreadPoolExecutor(max_workers=3) as executor:
            # Submit all queries in parallel
            students_future = executor.submit(
                lambda: supabase.table('students').select('id', count='exact')
                .eq('institute_id', institute_id).eq('status', 'active').execute()
            )
            
            employees_future = executor.submit(
                lambda: supabase.table('employees').select('id', count='exact')
                .eq('institute_id', institute_id).eq('status', 'active').execute()
            )
            
            # Combined financial query
            financial_future = executor.submit(
                lambda: get_financial_data(institute_id, start_date, end_date)
            )
        
        # Get results
        students_result = students_future.result()
        employees_result = employees_future.result()
        
        total_students = students_result.count or 0
        total_employees = employees_result.count or 0
        
        # Handle financial data
        revenue_collected, total_income, total_expenses = financial_future.result()
        
        total_profit = total_income - total_expenses
        
        return jsonify({
            'success': True,
            'stats': {
                'total_students': total_students,
                'total_employees': total_employees,
                'revenue_collected': revenue_collected,
                'total_income': total_income,
                'total_expenses': total_expenses,
                'total_profit': total_profit,
                'start_date': start_date,
                'end_date': end_date
            }
        })
        
    except Exception as e:
        print(f"Error getting dashboard stats: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

def get_financial_data(institute_id, start_date, end_date):
    """Helper function to get financial data"""
    try:
        # Get payments
        payments_response = supabase.table('payments')\
            .select('amount')\
            .eq('institute_id', institute_id)\
            .gte('payment_date', start_date)\
            .lte('payment_date', end_date)\
            .execute()
        revenue_collected = sum(float(p['amount']) for p in (payments_response.data or []))
        
        # Get income
        income_response = supabase.table('income_transactions')\
            .select('amount')\
            .eq('institute_id', institute_id)\
            .gte('transaction_date', start_date)\
            .lte('transaction_date', end_date)\
            .execute()
        total_income = sum(i['amount'] for i in (income_response.data or [])) + revenue_collected
        
        # Get expenses
        expense_response = supabase.table('expense_transactions')\
            .select('amount')\
            .eq('institute_id', institute_id)\
            .gte('transaction_date', start_date)\
            .lte('transaction_date', end_date)\
            .execute()
        total_expenses = sum(e['amount'] for e in (expense_response.data or []))
        
        return revenue_collected, total_income, total_expenses
    except Exception as e:
        print(f"Error in get_financial_data: {e}")
        return 0, 0, 0

@dashboard_bp.route('/api/income-expense-graph', methods=['GET'])
@login_required
@cached(ttl=300)  # Cache for 5 minutes
def get_income_expense_graph():
    """Get income vs expense data for line graph - OPTIMIZED"""
    institute = get_institute_from_session()
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    institute_id = institute.get('id')
    
    try:
        # Get last 12 months
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365)
        
        monthly_data = []
        current = start_date.replace(day=1)
        
        while current <= end_date:
            month_start = current.date().isoformat()
            if current.month == 12:
                next_month = current.replace(year=current.year + 1, month=1)
            else:
                next_month = current.replace(month=current.month + 1)
            month_end = (next_month - timedelta(days=1)).date().isoformat()
            
            # Get payments for this month
            payments_response = supabase.table('payments')\
                .select('amount')\
                .eq('institute_id', institute_id)\
                .gte('payment_date', month_start)\
                .lte('payment_date', month_end)\
                .execute()
            
            # Get income transactions for this month
            income_response = supabase.table('income_transactions')\
                .select('amount')\
                .eq('institute_id', institute_id)\
                .gte('transaction_date', month_start)\
                .lte('transaction_date', month_end)\
                .execute()
            
            # Get expenses for this month
            expense_response = supabase.table('expense_transactions')\
                .select('amount')\
                .eq('institute_id', institute_id)\
                .gte('transaction_date', month_start)\
                .lte('transaction_date', month_end)\
                .execute()
            
            monthly_income = sum(float(f['amount']) for f in (payments_response.data or []))
            monthly_income += sum(i['amount'] for i in (income_response.data or []))
            monthly_expense = sum(e['amount'] for e in (expense_response.data or []))
            
            monthly_data.append({
                'month': current.strftime('%b %Y'),
                'income': monthly_income,
                'expense': monthly_expense
            })
            
            # Move to next month
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)
        
        return jsonify({
            'success': True,
            'data': monthly_data
        })
        
    except Exception as e:
        print(f"Error getting income/expense graph: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@dashboard_bp.route('/api/class-attendance', methods=['GET'])
@login_required
@cached(ttl=120)  # Cache for 2 minutes
def get_class_attendance():
    """Get attendance statistics by class - OPTIMIZED"""
    institute = get_institute_from_session()
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    institute_id = institute.get('id')
    
    try:
        today = datetime.now().date().isoformat()
        
        # Get all classes
        classes_response = supabase.table('classes')\
            .select('id, name')\
            .eq('institute_id', institute_id)\
            .order('name')\
            .execute()
        
        # Get all active students in one query
        all_students = supabase.table('students')\
            .select('id, class_id')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')\
            .execute()
        
        students_by_class = defaultdict(list)
        for student in (all_students.data or []):
            if student.get('class_id'):
                students_by_class[student['class_id']].append(student['id'])
        
        # Get all attendance for today in one query
        attendance_response = supabase.table('attendance')\
            .select('student_id')\
            .eq('institute_id', institute_id)\
            .eq('scan_date', today)\
            .execute()
        
        present_students = set(a['student_id'] for a in (attendance_response.data or []))
        
        class_data = []
        for class_item in (classes_response.data or []):
            class_students = students_by_class.get(class_item['id'], [])
            total_students = len(class_students)
            
            if total_students > 0:
                present_count = sum(1 for s in class_students if s in present_students)
                absent_count = total_students - present_count
                
                class_data.append({
                    'class_name': class_item['name'],
                    'total': total_students,
                    'present': present_count,
                    'absent': absent_count,
                    'percentage': round((present_count / total_students * 100), 1) if total_students > 0 else 0
                })
        
        return jsonify({
            'success': True,
            'data': class_data
        })
        
    except Exception as e:
        print(f"Error getting class attendance: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@dashboard_bp.route('/api/staff-attendance', methods=['GET'])
@login_required
@cached(ttl=120)
def get_staff_attendance():
    """Get staff attendance statistics by role - OPTIMIZED"""
    institute = get_institute_from_session()
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    institute_id = institute.get('id')
    
    try:
        today = datetime.now().date().isoformat()
        
        # Get all employees
        employees_response = supabase.table('employees')\
            .select('id, role')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')\
            .execute()
        
        # Get attendance for today
        attendance_response = supabase.table('staff_attendance')\
            .select('employee_id')\
            .eq('institute_id', institute_id)\
            .eq('attendance_date', today)\
            .execute()
        
        present_ids = set(p['employee_id'] for p in (attendance_response.data or []))
        
        role_stats = defaultdict(lambda: {'total': 0, 'present': 0})
        for emp in (employees_response.data or []):
            role = emp.get('role', 'other')
            role_stats[role]['total'] += 1
            if emp['id'] in present_ids:
                role_stats[role]['present'] += 1
        
        role_data = []
        for role, stats in role_stats.items():
            role_data.append({
                'role': role.replace('_', ' ').title() if role else 'Other',
                'total': stats['total'],
                'present': stats['present'],
                'absent': stats['total'] - stats['present'],
                'percentage': round((stats['present'] / stats['total'] * 100), 1) if stats['total'] > 0 else 0
            })
        
        return jsonify({
            'success': True,
            'data': role_data
        })
        
    except Exception as e:
        print(f"Error getting staff attendance: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@dashboard_bp.route('/api/recent-activities', methods=['GET'])
@login_required
@cached(ttl=60)
def get_recent_activities():
    """Get recent activities across the system - OPTIMIZED"""
    institute = get_institute_from_session()
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    institute_id = institute.get('id')
    
    try:
        activities = []
        
        # Get recent students
        students_response = supabase.table('students')\
            .select('name, created_at')\
            .eq('institute_id', institute_id)\
            .order('created_at', desc=True)\
            .limit(5)\
            .execute()
        
        for student in (students_response.data or []):
            activities.append({
                'type': 'student',
                'title': 'New Student Added',
                'description': f'{student["name"]} was enrolled',
                'time': student['created_at'],
                'icon': 'user-graduate',
                'color': 'green'
            })
        
        # Get recent payments
        payments_response = supabase.table('payments')\
            .select('amount, receipt_number, created_at, students(name)')\
            .eq('institute_id', institute_id)\
            .order('created_at', desc=True)\
            .limit(5)\
            .execute()
        
        for payment in (payments_response.data or []):
            student_name = payment['students']['name'] if payment.get('students') else 'Student'
            activities.append({
                'type': 'payment',
                'title': 'Fee Payment Received',
                'description': f'UGX {float(payment["amount"]):,.0f} from {student_name}',
                'time': payment['created_at'],
                'icon': 'money-bill-wave',
                'color': 'blue'
            })
        
        # Get recent employees
        employees_response = supabase.table('employees')\
            .select('name, created_at')\
            .eq('institute_id', institute_id)\
            .order('created_at', desc=True)\
            .limit(5)\
            .execute()
        
        for employee in (employees_response.data or []):
            activities.append({
                'type': 'employee',
                'title': 'New Employee Added',
                'description': f'{employee["name"]} joined the staff',
                'time': employee['created_at'],
                'icon': 'user-tie',
                'color': 'purple'
            })
        
        # Sort by time and take latest 10
        activities.sort(key=lambda x: x['time'], reverse=True)
        
        return jsonify({
            'success': True,
            'activities': activities[:10]
        })
        
    except Exception as e:
        print(f"Error getting recent activities: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@dashboard_bp.route('/api/class-distribution', methods=['GET'])
@login_required
@cached(ttl=300)
def get_class_distribution():
    """Get student distribution by class - OPTIMIZED"""
    institute = get_institute_from_session()
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    institute_id = institute.get('id')
    
    try:
        # Get all classes with student count
        classes_response = supabase.table('classes')\
            .select('id, name')\
            .eq('institute_id', institute_id)\
            .order('name')\
            .execute()
        
        # Get all students with their class IDs in one query
        students_response = supabase.table('students')\
            .select('class_id')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')\
            .execute()
        
        class_counts = defaultdict(int)
        for student in (students_response.data or []):
            if student.get('class_id'):
                class_counts[student['class_id']] += 1
        
        class_data = []
        for class_item in (classes_response.data or []):
            count = class_counts.get(class_item['id'], 0)
            if count > 0:
                class_data.append({
                    'name': class_item['name'],
                    'count': count
                })
        
        return jsonify({
            'success': True,
            'data': class_data
        })
        
    except Exception as e:
        print(f"Error getting class distribution: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

# Helper function
def get_institute_id(user_id):
    """Legacy function - kept for compatibility"""
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