# dashboard.py - Main Dashboard Blueprint
from flask import Blueprint, render_template, request, jsonify, session
from supabase import create_client, Client
import os
from datetime import datetime, timedelta
from functools import wraps
from dotenv import load_dotenv

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

dashboard_bp = Blueprint('dashboard', __name__, url_prefix='/dashboard')

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Please login'}), 401
        return f(*args, **kwargs)
    return decorated_function

def get_institute_id(user_id):
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

@dashboard_bp.route('/')
@login_required
def index():
    """Main Dashboard Page"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return render_template('dashboard/index.html', institute_id=None)
    
    return render_template('dashboard/index.html', institute_id=institute_id)

@dashboard_bp.route('/api/stats', methods=['GET'])
@login_required
def get_dashboard_stats():
    """Get all dashboard statistics"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Get date filters
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        # Set default to current month if not provided
        if not start_date:
            start_date = datetime.now().replace(day=1).date().isoformat()
        if not end_date:
            end_date = datetime.now().date().isoformat()
        
        # 1. Total Students
        students_response = supabase.table('students')\
            .select('id', count='exact')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')\
            .execute()
        total_students = students_response.count or 0
        
        # 2. Total Employees
        employees_response = supabase.table('employees')\
            .select('id', count='exact')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')\
            .execute()
        total_employees = employees_response.count or 0
        
        # 3. Revenue Collected (from payments table)
        payments_response = supabase.table('payments')\
            .select('amount')\
            .eq('institute_id', institute_id)\
            .gte('payment_date', start_date)\
            .lte('payment_date', end_date)\
            .execute()
        
        revenue_collected = sum(float(p['amount']) for p in (payments_response.data or []))
        
        # 4. Total Profit/Loss
        # Get income from income_transactions
        income_response = supabase.table('income_transactions')\
            .select('amount')\
            .eq('institute_id', institute_id)\
            .gte('transaction_date', start_date)\
            .lte('transaction_date', end_date)\
            .execute()
        
        total_income = sum(i['amount'] for i in (income_response.data or []))
        
        # Get expenses from expense_transactions
        expense_response = supabase.table('expense_transactions')\
            .select('amount')\
            .eq('institute_id', institute_id)\
            .gte('transaction_date', start_date)\
            .lte('transaction_date', end_date)\
            .execute()
        
        total_expenses = sum(e['amount'] for e in (expense_response.data or []))
        
        # Add school fees to income
        revenue_collected = revenue_collected or 0
        total_income += revenue_collected
        
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

@dashboard_bp.route('/api/income-expense-graph', methods=['GET'])
@login_required
def get_income_expense_graph():
    """Get income vs expense data for line graph"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Get date range (last 12 months)
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
            
            # Get income for this month (including fees)
            fees_response = supabase.table('payments')\
                .select('amount')\
                .eq('institute_id', institute_id)\
                .gte('payment_date', month_start)\
                .lte('payment_date', month_end)\
                .execute()
            
            income_response = supabase.table('income_transactions')\
                .select('amount')\
                .eq('institute_id', institute_id)\
                .gte('transaction_date', month_start)\
                .lte('transaction_date', month_end)\
                .execute()
            
            monthly_income = sum(float(f['amount']) for f in (fees_response.data or []))
            monthly_income += sum(i['amount'] for i in (income_response.data or []))
            
            # Get expenses for this month
            expense_response = supabase.table('expense_transactions')\
                .select('amount')\
                .eq('institute_id', institute_id)\
                .gte('transaction_date', month_start)\
                .lte('transaction_date', month_end)\
                .execute()
            
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
def get_class_attendance():
    """Get attendance statistics by class"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        today = datetime.now().date().isoformat()
        
        # Get all classes
        classes_response = supabase.table('classes')\
            .select('id, name')\
            .eq('institute_id', institute_id)\
            .order('name')\
            .execute()
        
        classes = classes_response.data if classes_response.data else []
        
        class_data = []
        for class_item in classes:
            # Get students in this class
            students_response = supabase.table('students')\
                .select('id')\
                .eq('class_id', class_item['id'])\
                .eq('institute_id', institute_id)\
                .eq('status', 'active')\
                .execute()
            
            total_students = len(students_response.data or [])
            
            if total_students > 0:
                # Get present students today
                present_response = supabase.table('attendance')\
                    .select('student_id')\
                    .eq('institute_id', institute_id)\
                    .eq('scan_date', today)\
                    .execute()
                
                present_ids = set(a['student_id'] for a in (present_response.data or []))
                
                # Count present students in this class
                present_count = 0
                for student in (students_response.data or []):
                    if student['id'] in present_ids:
                        present_count += 1
                
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
def get_staff_attendance():
    """Get staff attendance statistics by role"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        today = datetime.now().date().isoformat()
        
        # Get all employees grouped by role
        employees_response = supabase.table('employees')\
            .select('id, role')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')\
            .execute()
        
        employees = employees_response.data if employees_response.data else []
        
        # Get present employees today
        present_response = supabase.table('staff_attendance')\
            .select('employee_id')\
            .eq('institute_id', institute_id)\
            .eq('attendance_date', today)\
            .execute()
        
        present_ids = set(p['employee_id'] for p in (present_response.data or []))
        
        # Group by role
        role_stats = {}
        for emp in employees:
            role = emp.get('role', 'other')
            if role not in role_stats:
                role_stats[role] = {'total': 0, 'present': 0}
            role_stats[role]['total'] += 1
            if emp['id'] in present_ids:
                role_stats[role]['present'] += 1
        
        # Format for chart
        role_data = []
        for role, stats in role_stats.items():
            absent = stats['total'] - stats['present']
            role_data.append({
                'role': role.replace('_', ' ').title() if role else 'Other',
                'total': stats['total'],
                'present': stats['present'],
                'absent': absent,
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
def get_recent_activities():
    """Get recent activities across the system"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        activities = []
        
        # Recent student additions
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
        
        # Recent fee payments
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
        
        # Recent employee additions
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
        activities = activities[:10]
        
        return jsonify({
            'success': True,
            'activities': activities
        })
        
    except Exception as e:
        print(f"Error getting recent activities: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@dashboard_bp.route('/api/class-distribution', methods=['GET'])
@login_required
def get_class_distribution():
    """Get student distribution by class"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Get all classes with student count
        classes_response = supabase.table('classes')\
            .select('id, name')\
            .eq('institute_id', institute_id)\
            .order('name')\
            .execute()
        
        class_data = []
        for class_item in (classes_response.data or []):
            # Count active students in this class
            students_response = supabase.table('students')\
                .select('id', count='exact')\
                .eq('class_id', class_item['id'])\
                .eq('institute_id', institute_id)\
                .eq('status', 'active')\
                .execute()
            
            count = students_response.count or 0
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