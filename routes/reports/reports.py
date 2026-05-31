from flask import Blueprint, render_template, session, request, jsonify, redirect, url_for, flash
from supabase import create_client, Client
import os
from datetime import datetime, timedelta
from functools import wraps
from dotenv import load_dotenv

from routes.auth.auth import accountant_required, secretary_required, support_staff_required
from routes.accounts.accounts import get_institute_id

load_dotenv()

# Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Blueprint
reports_bp = Blueprint('reports', __name__, url_prefix='/reports')

# Role-based decorator
def reports_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('auth.login'))
        
        user = session.get('user', {})
        is_employee = user.get('is_employee', False)
        user_role = user.get('role')
        
        # Institute owners (not employees) have access
        if not is_employee:
            return f(*args, **kwargs)
        
        # Employees with these roles have access
        if is_employee and user_role in ['owner', 'accountant', 'admin']:
            return f(*args, **kwargs)
        
        flash('Access denied. Insufficient privileges.', 'error')
        return redirect(url_for('dashboard.index'))
    
    return decorated_function


# ============================================================
# REPORT ROUTES
# ============================================================

@reports_bp.route('/students')
@reports_required
def students_report():
    """Student list report"""
    institute_id = request.args.get('institute_id')
    if not institute_id:
        user_id = session.get('user_id') or session.get('user', {}).get('id')
        institute_id = get_institute_id(user_id)
    
    # Get students data
    students_response = supabase.table('students')\
        .select('*, classes(name)')\
        .eq('institute_id', institute_id)\
        .eq('status', 'active')\
        .order('name')\
        .execute()
    
    students = students_response.data or []
    
    # Get class distribution
    class_counts = {}
    for student in students:
        class_name = student.get('classes', {}).get('name') if student.get('classes') else 'No Class'
        class_counts[class_name] = class_counts.get(class_name, 0) + 1
    
    return render_template('reports/students.html', 
                         students=students, 
                         class_counts=class_counts,
                         institute_id=institute_id)


@reports_bp.route('/employees')
@reports_required
def employees_report():
    """Employee list report"""
    institute_id = request.args.get('institute_id')
    if not institute_id:
        user_id = session.get('user_id') or session.get('user', {}).get('id')
        institute_id = get_institute_id(user_id)
    
    # Get employees data
    employees_response = supabase.table('employees')\
        .select('*')\
        .eq('institute_id', institute_id)\
        .eq('status', 'active')\
        .order('name')\
        .execute()
    
    employees = employees_response.data or []
    
    # Group by role
    role_counts = {}
    for emp in employees:
        role = emp.get('role', 'other')
        role_counts[role] = role_counts.get(role, 0) + 1
    
    return render_template('reports/employees.html', 
                         employees=employees,
                         role_counts=role_counts,
                         institute_id=institute_id)


@reports_bp.route('/income')
@reports_required
def income_report():
    """Income report (school fees + other income)"""
    institute_id = request.args.get('institute_id')
    if not institute_id:
        user_id = session.get('user_id') or session.get('user', {}).get('id')
        institute_id = get_institute_id(user_id)
    
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    # Default to current month
    if not start_date:
        start_date = datetime.now().replace(day=1).strftime('%Y-%m-%d')
    if not end_date:
        end_date = datetime.now().strftime('%Y-%m-%d')
    
    # Get school fees payments
    payments_response = supabase.table('payments')\
        .select('*, student:students(name)')\
        .eq('institute_id', institute_id)\
        .gte('payment_date', start_date)\
        .lte('payment_date', end_date)\
        .order('payment_date', desc=True)\
        .execute()
    
    # Get other income
    income_response = supabase.table('income_transactions')\
        .select('*')\
        .eq('institute_id', institute_id)\
        .gte('transaction_date', start_date)\
        .lte('transaction_date', end_date)\
        .order('transaction_date', desc=True)\
        .execute()
    
    payments = payments_response.data or []
    other_income = income_response.data or []
    
    # Calculate totals
    total_fees = sum(float(p.get('amount', 0)) for p in payments)
    total_other = sum(float(i.get('amount', 0)) for i in other_income)
    total_income = total_fees + total_other
    
    return render_template('reports/income.html',
                         payments=payments,
                         other_income=other_income,
                         total_fees=total_fees,
                         total_other=total_other,
                         total_income=total_income,
                         start_date=start_date,
                         end_date=end_date,
                         institute_id=institute_id)


@reports_bp.route('/other-income')
@reports_required
def other_income_report():
    """Other income only report"""
    institute_id = request.args.get('institute_id')
    if not institute_id:
        user_id = session.get('user_id') or session.get('user', {}).get('id')
        institute_id = get_institute_id(user_id)
    
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    if not start_date:
        start_date = datetime.now().replace(day=1).strftime('%Y-%m-%d')
    if not end_date:
        end_date = datetime.now().strftime('%Y-%m-%d')
    
    # Get other income transactions
    income_response = supabase.table('income_transactions')\
        .select('*')\
        .eq('institute_id', institute_id)\
        .gte('transaction_date', start_date)\
        .lte('transaction_date', end_date)\
        .order('transaction_date', desc=True)\
        .execute()
    
    other_income = income_response.data or []
    total_other = sum(float(i.get('amount', 0)) for i in other_income)
    
    return render_template('reports/other_income.html',
                         other_income=other_income,
                         total_other=total_other,
                         start_date=start_date,
                         end_date=end_date,
                         institute_id=institute_id)


@reports_bp.route('/expenses')
@reports_required
def expenses_report():
    """Expenses report"""
    institute_id = request.args.get('institute_id')
    if not institute_id:
        user_id = session.get('user_id') or session.get('user', {}).get('id')
        institute_id = get_institute_id(user_id)
    
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    if not start_date:
        start_date = datetime.now().replace(day=1).strftime('%Y-%m-%d')
    if not end_date:
        end_date = datetime.now().strftime('%Y-%m-%d')
    
    # Get expenses
    expenses_response = supabase.table('expense_transactions')\
        .select('*')\
        .eq('institute_id', institute_id)\
        .gte('transaction_date', start_date)\
        .lte('transaction_date', end_date)\
        .order('transaction_date', desc=True)\
        .execute()
    
    expenses = expenses_response.data or []
    total_expenses = sum(float(e.get('amount', 0)) for e in expenses)
    
    # Group by category
    category_totals = {}
    for exp in expenses:
        category = exp.get('category', 'Uncategorized')
        category_totals[category] = category_totals.get(category, 0) + float(exp.get('amount', 0))
    
    return render_template('reports/expenses.html',
                         expenses=expenses,
                         total_expenses=total_expenses,
                         category_totals=category_totals,
                         start_date=start_date,
                         end_date=end_date,
                         institute_id=institute_id)


@reports_bp.route('/school-fees')
@reports_required
def school_fees_report():
    """School fees collection report"""
    institute_id = request.args.get('institute_id')
    if not institute_id:
        user_id = session.get('user_id') or session.get('user', {}).get('id')
        institute_id = get_institute_id(user_id)
    
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    if not start_date:
        start_date = datetime.now().replace(day=1).strftime('%Y-%m-%d')
    if not end_date:
        end_date = datetime.now().strftime('%Y-%m-%d')
    
    # Get payments with student details
    payments_response = supabase.table('payments')\
        .select('*, student:students(name, class:classes(name))')\
        .eq('institute_id', institute_id)\
        .gte('payment_date', start_date)\
        .lte('payment_date', end_date)\
        .order('payment_date', desc=True)\
        .execute()
    
    payments = payments_response.data or []
    total_collected = sum(float(p.get('amount', 0)) for p in payments)
    
    # Group by payment method
    method_totals = {}
    for payment in payments:
        method = payment.get('payment_method', 'other')
        method_totals[method] = method_totals.get(method, 0) + float(payment.get('amount', 0))
    
    return render_template('reports/school_fees.html',
                         payments=payments,
                         total_collected=total_collected,
                         method_totals=method_totals,
                         start_date=start_date,
                         end_date=end_date,
                         institute_id=institute_id)


@reports_bp.route('/profit-loss')
@reports_required
def profit_loss_report():
    """Profit & Loss statement"""
    institute_id = request.args.get('institute_id')
    if not institute_id:
        user_id = session.get('user_id') or session.get('user', {}).get('id')
        institute_id = get_institute_id(user_id)
    
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    if not start_date:
        start_date = datetime.now().replace(day=1).strftime('%Y-%m-%d')
    if not end_date:
        end_date = datetime.now().strftime('%Y-%m-%d')
    
    # Get school fees
    fees_response = supabase.table('payments')\
        .select('amount')\
        .eq('institute_id', institute_id)\
        .gte('payment_date', start_date)\
        .lte('payment_date', end_date)\
        .execute()
    
    # Get other income
    income_response = supabase.table('income_transactions')\
        .select('amount')\
        .eq('institute_id', institute_id)\
        .gte('transaction_date', start_date)\
        .lte('transaction_date', end_date)\
        .execute()
    
    # Get expenses
    expenses_response = supabase.table('expense_transactions')\
        .select('amount')\
        .eq('institute_id', institute_id)\
        .gte('transaction_date', start_date)\
        .lte('transaction_date', end_date)\
        .execute()
    
    school_fees = sum(float(p.get('amount', 0)) for p in (fees_response.data or []))
    other_income = sum(float(i.get('amount', 0)) for i in (income_response.data or []))
    total_expenses = sum(float(e.get('amount', 0)) for e in (expenses_response.data or []))
    total_income = school_fees + other_income
    net_profit = total_income - total_expenses
    
    return render_template('reports/profit_loss.html',
                         school_fees=school_fees,
                         other_income=other_income,
                         total_income=total_income,
                         total_expenses=total_expenses,
                         net_profit=net_profit,
                         start_date=start_date,
                         end_date=end_date,
                         institute_id=institute_id)


@reports_bp.route('/overall-profit')
@reports_required
def overall_profit_report():
    """Overall profit report (all time)"""
    institute_id = request.args.get('institute_id')
    if not institute_id:
        user_id = session.get('user_id') or session.get('user', {}).get('id')
        institute_id = get_institute_id(user_id)
    
    # Get all school fees
    fees_response = supabase.table('payments')\
        .select('amount, payment_date')\
        .eq('institute_id', institute_id)\
        .execute()
    
    # Get all other income
    income_response = supabase.table('income_transactions')\
        .select('amount, transaction_date')\
        .eq('institute_id', institute_id)\
        .execute()
    
    # Get all expenses
    expenses_response = supabase.table('expense_transactions')\
        .select('amount, transaction_date')\
        .eq('institute_id', institute_id)\
        .execute()
    
    school_fees = sum(float(p.get('amount', 0)) for p in (fees_response.data or []))
    other_income = sum(float(i.get('amount', 0)) for i in (income_response.data or []))
    total_expenses = sum(float(e.get('amount', 0)) for e in (expenses_response.data or []))
    total_income = school_fees + other_income
    net_profit = total_income - total_expenses
    
    # Get monthly breakdown
    monthly_data = {}
    
    for payment in (fees_response.data or []):
        date = payment.get('payment_date', '')[:7]  # YYYY-MM
        if date:
            monthly_data[date] = monthly_data.get(date, {'income': 0, 'expense': 0})
            monthly_data[date]['income'] += float(payment.get('amount', 0))
    
    for income in (income_response.data or []):
        date = income.get('transaction_date', '')[:7]
        if date:
            monthly_data[date] = monthly_data.get(date, {'income': 0, 'expense': 0})
            monthly_data[date]['income'] += float(income.get('amount', 0))
    
    for expense in (expenses_response.data or []):
        date = expense.get('transaction_date', '')[:7]
        if date:
            monthly_data[date] = monthly_data.get(date, {'income': 0, 'expense': 0})
            monthly_data[date]['expense'] += float(expense.get('amount', 0))
    
    # Sort by date
    monthly_breakdown = []
    for date in sorted(monthly_data.keys()):
        data = monthly_data[date]
        monthly_breakdown.append({
            'month': date,
            'income': data['income'],
            'expense': data['expense'],
            'profit': data['income'] - data['expense']
        })
    
    return render_template('reports/overall_profit.html',
                         school_fees=school_fees,
                         other_income=other_income,
                         total_income=total_income,
                         total_expenses=total_expenses,
                         net_profit=net_profit,
                         monthly_breakdown=monthly_breakdown,
                         institute_id=institute_id)