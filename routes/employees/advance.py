# salary_advance.py - Complete Unified Salary & Advance Management Module
from flask import Blueprint, render_template, request, jsonify, session, send_file
from supabase import create_client, Client
import os
import uuid
import random
import string
from datetime import datetime, timedelta
import json
import io
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, mm
from functools import wraps
from dotenv import load_dotenv
import requests
from PIL import Image as PILImage
import tempfile
from routes.accounts.accounts import get_institute_id
from routes.permissions.permissions import role_required

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

salary_bp = Blueprint('salary', __name__, url_prefix='/salary')

# ==================== DECORATORS ====================

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Please login'}), 401
        return f(*args, **kwargs)
    return decorated_function


# ==================== ACCOUNTING HELPERS ====================

def get_salary_expense_account(institute_id):
    """Get or create salary expense account"""
    try:
        # First check if SALARIES account already exists (this is what you already have)
        response = supabase.table('chart_of_accounts')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .eq('account_name', 'SALARIES')\
            .eq('account_type', 'expense')\
            .execute()
        
        if response.data:
            return response.data[0]
        
        # Also check for SALARY EXPENSE (alternative name)
        response = supabase.table('chart_of_accounts')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .eq('account_name', 'SALARY EXPENSE')\
            .eq('account_type', 'expense')\
            .execute()
        
        if response.data:
            return response.data[0]
        
        # If not found, create new account with proper code
        # Get the max account code number to avoid duplicates
        count_response = supabase.table('chart_of_accounts')\
            .select('account_code')\
            .eq('institute_id', institute_id)\
            .eq('account_type', 'expense')\
            .execute()
        
        # Extract existing codes and find the max number
        existing_codes = [row['account_code'] for row in count_response.data] if count_response.data else []
        max_num = 0
        for code in existing_codes:
            if code.startswith('EXP-'):
                try:
                    num = int(code.split('-')[1])
                    if num > max_num:
                        max_num = num
                except:
                    pass
        
        new_num = max_num + 1
        account_code = f"EXP-{str(new_num).zfill(4)}"
        
        account_data = {
            'id': str(uuid.uuid4()),
            'institute_id': institute_id,
            'account_code': account_code,
            'account_name': 'SALARIES',  # Use the same name as your existing account
            'account_type': 'expense',
            'description': 'Employee salary expenses',
            'is_active': True,
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        result = supabase.table('chart_of_accounts').insert(account_data).execute()
        return result.data[0] if result.data else None
        
    except Exception as e:
        print(f"Error getting salary account: {e}")
        return None

def get_advance_liability_account(institute_id):
    """Get or create advance liability account"""
    try:
        response = supabase.table('chart_of_accounts')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .eq('account_name', 'EMPLOYEE ADVANCES')\
            .eq('account_type', 'liability')\
            .execute()
        
        if response.data:
            return response.data[0]
        
        # Get max liability code
        count_response = supabase.table('chart_of_accounts')\
            .select('account_code')\
            .eq('institute_id', institute_id)\
            .eq('account_type', 'liability')\
            .execute()
        
        existing_codes = [row['account_code'] for row in count_response.data] if count_response.data else []
        max_num = 0
        for code in existing_codes:
            if code.startswith('LIA-'):
                try:
                    num = int(code.split('-')[1])
                    if num > max_num:
                        max_num = num
                except:
                    pass
        
        new_num = max_num + 1
        account_code = f"LIA-{str(new_num).zfill(4)}"
        
        account_data = {
            'id': str(uuid.uuid4()),
            'institute_id': institute_id,
            'account_code': account_code,
            'account_name': 'EMPLOYEE ADVANCES',
            'account_type': 'liability',
            'description': 'Employee advance payments liability',
            'is_active': True,
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        result = supabase.table('chart_of_accounts').insert(account_data).execute()
        return result.data[0] if result.data else None
        
    except Exception as e:
        print(f"Error getting advance account: {e}")
        return None


def create_advance_journal_entry(institute_id, employee_id, advance_id, amount, advance_month):
    """Create journal entry when advance is given"""
    try:
        liability_account = get_advance_liability_account(institute_id)
        
        if liability_account:
            # Record the liability
            journal_entry = {
                'id': str(uuid.uuid4()),
                'institute_id': institute_id,
                'account_id': liability_account['id'],
                'amount': amount,
                'transaction_date': datetime.now().strftime('%Y-%m-%d'),
                'transaction_type': 'advance_given',
                'reference_number': f"ADV-{advance_id[:8]}",
                'description': f"Employee advance for {advance_month}",
                'employee_id': employee_id,
                'created_at': datetime.now().isoformat()
            }
            supabase.table('journal_entries').insert(journal_entry).execute()
        return True
    except Exception as e:
        print(f"Error creating journal entry: {e}")
        return False


def create_advance_deduction_journal_entry(institute_id, employee_id, advance_id, amount, payroll_month):
    """Create journal entry when advance is deducted from salary"""
    try:
        liability_account = get_advance_liability_account(institute_id)
        
        if liability_account:
            # Reduce the liability
            journal_entry = {
                'id': str(uuid.uuid4()),
                'institute_id': institute_id,
                'account_id': liability_account['id'],
                'amount': -amount,
                'transaction_date': datetime.now().strftime('%Y-%m-%d'),
                'transaction_type': 'advance_repayment',
                'reference_number': f"ADV-DED-{advance_id[:8]}",
                'description': f"Advance deduction from salary - {payroll_month}",
                'employee_id': employee_id,
                'created_at': datetime.now().isoformat()
            }
            supabase.table('journal_entries').insert(journal_entry).execute()
        return True
    except Exception as e:
        print(f"Error creating advance deduction journal entry: {e}")
        return False


# ==================== SALARY HELPERS ====================

def get_advance_deductions_batch(institute_id, employee_ids, payroll_month):
    """Get advance deductions for multiple employees in ONE query"""
    if not employee_ids:
        return {}
    
    try:
        advance_response = supabase.table('employee_advances')\
            .select('employee_id, id, monthly_deduction, remaining_amount, advance_amount, repaid_amount')\
            .eq('institute_id', institute_id)\
            .in_('employee_id', employee_ids)\
            .eq('status', 'active')\
            .lte('repayment_start_month', payroll_month)\
            .gte('repayment_end_month', payroll_month)\
            .execute()
        
        result = {}
        if advance_response.data:
            for advance in advance_response.data:
                emp_id = advance['employee_id']
                monthly_ded = float(advance['monthly_deduction'])
                remaining = float(advance['remaining_amount'])
                deduction = min(monthly_ded, remaining)
                result[emp_id] = {
                    'deduction': deduction,
                    'advance_id': advance['id'],
                    'advance_data': advance
                }
        return result
        
    except Exception as e:
        print(f"Error getting batch advances: {e}")
        return {}


def generate_salary_receipt_number(institute_id):
    """Generate unique salary receipt number"""
    try:
        year = datetime.now().strftime('%Y')
        month = datetime.now().strftime('%m')
        random_component = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
        
        response = supabase.table('salary_payments')\
            .select('id', count='exact')\
            .eq('institute_id', institute_id)\
            .gte('created_at', f"{year}-{month}-01")\
            .execute()
        
        count = (response.count or 0) + 1
        return f"SLP-{year}{month}-{random_component}-{str(count).zfill(3)}"
    except:
        return f"SLP-{datetime.now().strftime('%Y%m%d%H%M%S')}"


# ==================== ROUTES ====================

@salary_bp.route('/')
@role_required(['owner', 'teacher', 'accountant'])
def index():
    """Main Salary & Advance Management Page"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return render_template('salary/index.html', institute=None, now=datetime.now())
    
    institute_response = supabase.table('institutes')\
        .select('*')\
        .eq('id', institute_id)\
        .execute()
    
    institute = institute_response.data[0] if institute_response.data else None
    
    return render_template('salary/index.html', institute=institute, now=datetime.now())


# ==================== ADVANCE API ENDPOINTS ====================

@salary_bp.route('/api/advance/live-search', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def live_employee_search():
    """Live search for employees"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        search_term = request.args.get('q', '').strip()
        limit = request.args.get('limit', 20, type=int)
        
        query = supabase.table('employees')\
            .select('id, employee_id, name, role, monthly_salary, status')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')
        
        if search_term:
            query = query.or_(f"name.ilike.%{search_term}%,employee_id.ilike.%{search_term}%")
        
        response = query.limit(limit).order('name').execute()
        employees = response.data if response.data else []
        
        # Get advance summary for each employee
        for emp in employees:
            summary = get_employee_advance_summary(institute_id, emp['id'])
            emp['total_advances'] = summary['total_advance']
            emp['total_repaid'] = summary['total_repaid']
            emp['current_balance'] = summary['current_balance']
            emp['active_advances'] = summary['active_count']
        
        return jsonify({'success': True, 'employees': employees})
        
    except Exception as e:
        print(f"Error in live search: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@salary_bp.route('/api/advance/employee/<employee_id>', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_employee_advance_details(employee_id):
    """Get all advances for a specific employee"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Get all advances
        advances_response = supabase.table('employee_advances')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .eq('employee_id', employee_id)\
            .order('created_at', desc=True)\
            .execute()
        
        advances = advances_response.data if advances_response.data else []
        
        # Get payment history
        for advance in advances:
            payments_response = supabase.table('advance_payments')\
                .select('*')\
                .eq('advance_id', advance['id'])\
                .order('payment_date', desc=True)\
                .execute()
            advance['payments'] = payments_response.data if payments_response.data else []
        
        # Get employee details
        emp_response = supabase.table('employees')\
            .select('id, employee_id, name, role, monthly_salary')\
            .eq('id', employee_id)\
            .execute()
        
        employee = emp_response.data[0] if emp_response.data else None
        
        return jsonify({
            'success': True,
            'employee': employee,
            'advances': advances
        })
        
    except Exception as e:
        print(f"Error getting employee advances: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@salary_bp.route('/api/advance/create', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def create_advance():
    """Create a new employee advance"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        
        employee_id = data.get('employee_id')
        advance_amount = float(data.get('advance_amount', 0))
        advance_month = data.get('advance_month')
        repayment_months = int(data.get('repayment_months', 1))
        purpose = data.get('purpose', '')
        notes = data.get('notes', '')
        
        if not employee_id:
            return jsonify({'success': False, 'message': 'Employee ID required'}), 400
        
        if advance_amount <= 0:
            return jsonify({'success': False, 'message': 'Advance amount must be greater than 0'}), 400
        
        if not advance_month:
            return jsonify({'success': False, 'message': 'Advance month required'}), 400
        
        # Get employee details
        emp_response = supabase.table('employees')\
            .select('monthly_salary, name')\
            .eq('id', employee_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if not emp_response.data:
            return jsonify({'success': False, 'message': 'Employee not found'}), 404
        
        employee = emp_response.data[0]
        monthly_salary = float(employee.get('monthly_salary', 0))
        
        # Calculate monthly deduction
        monthly_deduction = advance_amount / repayment_months if repayment_months > 0 else advance_amount
        
        # Check if monthly deduction exceeds 50% of salary
        max_allowed_deduction = monthly_salary * 0.5
        if monthly_deduction > max_allowed_deduction:
            return jsonify({
                'success': False, 
                'message': f'Monthly deduction ({monthly_deduction:,.0f}) exceeds 50% of monthly salary ({max_allowed_deduction:,.0f})'
            }), 400
        
        # Calculate repayment period
        advance_date = datetime.strptime(advance_month, '%Y-%m')
        repayment_start_month = advance_date.strftime('%Y-%m')
        end_date = advance_date + timedelta(days=30 * (repayment_months - 1))
        repayment_end_month = end_date.strftime('%Y-%m')
        
        # Create advance record
        advance_id = str(uuid.uuid4())
        advance_data = {
            'id': advance_id,
            'institute_id': institute_id,
            'employee_id': employee_id,
            'advance_amount': advance_amount,
            'repaid_amount': 0,
            'remaining_amount': advance_amount,
            'advance_month': advance_month,
            'repayment_start_month': repayment_start_month,
            'repayment_end_month': repayment_end_month,
            'repayment_months': repayment_months,
            'monthly_deduction': round(monthly_deduction, 2),
            'purpose': purpose,
            'status': 'active',
            'approved_by': user['id'],
            'approved_at': datetime.now().isoformat(),
            'notes': notes,
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        result = supabase.table('employee_advances').insert(advance_data).execute()
        
        if not result.data:
            return jsonify({'success': False, 'message': 'Failed to create advance'}), 500
        
        # Create journal entry
        create_advance_journal_entry(institute_id, employee_id, advance_id, advance_amount, advance_month)
        
        return jsonify({
            'success': True,
            'message': f'Advance of UGX {advance_amount:,.0f} created successfully for {employee["name"]}',
            'advance': result.data[0],
            'monthly_deduction': monthly_deduction
        })
        
    except Exception as e:
        print(f"Error creating advance: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


@salary_bp.route('/api/advance/<advance_id>/repayment', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def record_repayment(advance_id):
    """Record a manual advance repayment"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        amount = float(data.get('amount', 0))
        payment_month = data.get('payment_month')
        
        if amount <= 0:
            return jsonify({'success': False, 'message': 'Amount must be greater than 0'}), 400
        
        # Get advance details
        advance_response = supabase.table('employee_advances')\
            .select('*')\
            .eq('id', advance_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if not advance_response.data:
            return jsonify({'success': False, 'message': 'Advance not found'}), 404
        
        advance = advance_response.data[0]
        
        if advance['status'] == 'completed':
            return jsonify({'success': False, 'message': 'Advance already fully repaid'}), 400
        
        if amount > advance['remaining_amount']:
            return jsonify({
                'success': False, 
                'message': f'Amount exceeds remaining balance of UGX {advance["remaining_amount"]:,.0f}'
            }), 400
        
        # Record repayment
        payment_data = {
            'id': str(uuid.uuid4()),
            'institute_id': institute_id,
            'advance_id': advance_id,
            'employee_id': advance['employee_id'],
            'amount': amount,
            'payment_month': payment_month or advance['advance_month'],
            'payment_date': datetime.now().strftime('%Y-%m-%d'),
            'is_repayment': True,
            'notes': data.get('notes', 'Manual repayment'),
            'created_at': datetime.now().isoformat()
        }
        
        supabase.table('advance_payments').insert(payment_data).execute()
        
        # Update advance totals
        new_repaid = float(advance['repaid_amount']) + amount
        new_remaining = float(advance['advance_amount']) - new_repaid
        new_status = 'completed' if new_remaining <= 0 else 'active'
        
        supabase.table('employee_advances')\
            .update({
                'repaid_amount': new_repaid,
                'remaining_amount': new_remaining,
                'status': new_status,
                'updated_at': datetime.now().isoformat()
            })\
            .eq('id', advance_id)\
            .execute()
        
        # Create journal entry for deduction
        create_advance_deduction_journal_entry(institute_id, advance['employee_id'], advance_id, amount, payment_month)
        
        return jsonify({
            'success': True,
            'message': f'Repayment of UGX {amount:,.0f} recorded successfully',
            'remaining_balance': new_remaining,
            'status': new_status
        })
        
    except Exception as e:
        print(f"Error recording repayment: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@salary_bp.route('/api/advance/delete/<advance_id>', methods=['DELETE'])
@role_required(['owner', 'teacher', 'accountant'])
def delete_advance(advance_id):
    """Delete an advance (only if not fully repaid)"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        advance_response = supabase.table('employee_advances')\
            .select('*')\
            .eq('id', advance_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if not advance_response.data:
            return jsonify({'success': False, 'message': 'Advance not found'}), 404
        
        advance = advance_response.data[0]
        
        if advance['repaid_amount'] > 0:
            return jsonify({'success': False, 'message': 'Cannot delete advance with partial repayments'}), 400
        
        supabase.table('advance_payments')\
            .eq('advance_id', advance_id)\
            .delete()\
            .execute()
        
        supabase.table('employee_advances')\
            .eq('id', advance_id)\
            .delete()\
            .execute()
        
        return jsonify({'success': True, 'message': 'Advance deleted successfully'})
        
    except Exception as e:
        print(f"Error deleting advance: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@salary_bp.route('/api/advance/summary', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_advance_summary():
    """Get summary of all advances"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Get active advances
        advances_response = supabase.table('employee_advances')\
            .select('*, employees(name, employee_id)')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')\
            .execute()
        
        active_advances = advances_response.data if advances_response.data else []
        
        # Get completed advances
        completed_response = supabase.table('employee_advances')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .eq('status', 'completed')\
            .execute()
        
        completed_advances = completed_response.data if completed_response.data else []
        
        total_outstanding = sum(float(a['remaining_amount']) for a in active_advances)
        total_advanced = sum(float(a['advance_amount']) for a in active_advances + completed_advances)
        total_repaid = sum(float(a['repaid_amount']) for a in active_advances + completed_advances)
        
        return jsonify({
            'success': True,
            'summary': {
                'active_advances_count': len(active_advances),
                'completed_advances_count': len(completed_advances),
                'total_advanced': total_advanced,
                'total_repaid': total_repaid,
                'total_outstanding': total_outstanding
            },
            'active_advances': active_advances
        })
        
    except Exception as e:
        print(f"Error getting advance summary: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


# ==================== SALARY API ENDPOINTS ====================

@salary_bp.route('/api/salary/employees', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_salary_employees():
    """Get all active employees with advance information for the selected month"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        month = request.args.get('month')
        
        if not month:
            return jsonify({'success': False, 'message': 'Month required'}), 400
        
        # Get all active employees
        employees_response = supabase.table('employees')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')\
            .order('name')\
            .execute()
        
        employees = employees_response.data if employees_response.data else []
        
        if not employees:
            return jsonify({'success': True, 'employees': [], 'month': month})
        
        # Get paid employees for this month
        paid_response = supabase.table('salary_payments')\
            .select('employee_id, gross_salary, advance_deduction, amount')\
            .eq('institute_id', institute_id)\
            .eq('payment_month', month)\
            .execute()
        
        paid_employee_ids = set(p['employee_id'] for p in paid_response.data) if paid_response.data else set()
        
        # Create lookup for paid data
        paid_lookup = {}
        if paid_response.data:
            for p in paid_response.data:
                paid_lookup[p['employee_id']] = {
                    'gross_salary': p['gross_salary'],
                    'advance_deduction': p['advance_deduction'],
                    'net_paid': p['amount']
                }
        
        # Get advance deductions in ONE query
        employee_ids = [emp['id'] for emp in employees]
        advance_lookup = get_advance_deductions_batch(institute_id, employee_ids, month)
        
        # Build employee data
        employees_data = []
        total_gross = 0
        total_advance_deductions = 0
        total_net_pay = 0
        
        for emp in employees:
            salary = float(emp.get('monthly_salary', 0))
            advance_info = advance_lookup.get(emp['id'], {})
            advance_deduction = advance_info.get('deduction', 0)
            is_paid = emp['id'] in paid_employee_ids
            
            if is_paid and emp['id'] in paid_lookup:
                paid_data = paid_lookup[emp['id']]
                actual_gross = paid_data['gross_salary']
                actual_advance = paid_data['advance_deduction']
                actual_net = paid_data['net_paid']
            else:
                actual_gross = salary
                actual_advance = advance_deduction
                actual_net = salary - advance_deduction
            
            employees_data.append({
                'id': emp['id'],
                'employee_id': emp['employee_id'],
                'name': emp['name'],
                'role': emp.get('role', 'Staff'),
                'monthly_salary': salary,
                'is_paid': is_paid,
                'advance_deduction': actual_advance,
                'advance_id': advance_info.get('advance_id'),
                'advance_info': advance_info.get('advance_data'),
                'net_pay': actual_net,
                'gross_expense': actual_gross
            })
            
            total_gross += actual_gross
            total_advance_deductions += actual_advance
            total_net_pay += actual_net
        
        return jsonify({
            'success': True,
            'employees': employees_data,
            'month': month,
            'summary': {
                'total_gross_expense': total_gross,
                'total_advance_deductions': total_advance_deductions,
                'total_net_pay': total_net_pay,
                'employee_count': len(employees_data),
                'paid_count': len(paid_employee_ids)
            }
        })
        
    except Exception as e:
        print(f"Error getting salary employees: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@salary_bp.route('/api/salary/process', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def process_salary_payments():
    """Process salary payments with proper expense tracking"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        payments_data = data.get('payments', [])
        payment_month = data.get('payment_month')
        payment_date = data.get('payment_date', datetime.now().strftime('%Y-%m-%d'))
        
        if not payments_data:
            return jsonify({'success': False, 'message': 'No payment data provided'}), 400
        
        if not payment_month:
            return jsonify({'success': False, 'message': 'Payment month required'}), 400
        
        salary_account = get_salary_expense_account(institute_id)
        
        if not salary_account:
            return jsonify({'success': False, 'message': 'Salary expense account not found'}), 400
        
        # Check existing payments
        employee_ids = [p.get('employee_id') for p in payments_data if p.get('employee_id')]
        
        existing_payments = supabase.table('salary_payments')\
            .select('employee_id')\
            .eq('institute_id', institute_id)\
            .eq('payment_month', payment_month)\
            .in_('employee_id', employee_ids)\
            .execute()
        
        paid_employee_ids = set(p['employee_id'] for p in existing_payments.data) if existing_payments.data else set()
        
        # Process each payment
        salary_payments = []
        expense_transactions = []
        advance_updates = []
        payments = []
        errors = []
        processed_count = 0
        total_net_pay = 0
        total_advance_deductions = 0
        
        for payment_item in payments_data:
            try:
                employee_id = payment_item.get('employee_id')
                employee_name = payment_item.get('name', 'Unknown')
                
                if employee_id in paid_employee_ids:
                    errors.append(f"{employee_name} already paid for {payment_month}")
                    continue
                
                salary_amount = float(payment_item.get('monthly_salary', 0))
                advance_deduction = float(payment_item.get('advance_deduction', 0))
                advance_id = payment_item.get('advance_id')
                deductions = float(payment_item.get('deductions', 0))
                bonuses = float(payment_item.get('bonuses', 0))
                
                net_pay = salary_amount - deductions + bonuses - advance_deduction
                
                if net_pay <= 0:
                    errors.append(f"Net pay for {employee_name} is zero or negative")
                    continue
                
                payment_id = str(uuid.uuid4())
                receipt_number = generate_salary_receipt_number(institute_id)
                
                # 1. Record salary payment
                salary_payments.append({
                    'id': payment_id,
                    'institute_id': institute_id,
                    'employee_id': employee_id,
                    'amount': float(net_pay),
                    'gross_salary': float(salary_amount),
                    'deductions': float(deductions),
                    'bonuses': float(bonuses),
                    'advance_deduction': float(advance_deduction),
                    'payment_month': payment_month,
                    'payment_date': payment_date,
                    'payment_method': payment_item.get('payment_method', 'bank_transfer'),
                    'receipt_number': receipt_number,
                    'notes': payment_item.get('notes', ''),
                    'status': 'paid',
                    'created_at': datetime.now().isoformat()
                })
                
                # 2. Record FULL salary as expense
                expense_transactions.append({
                    'id': str(uuid.uuid4()),
                    'institute_id': institute_id,
                    'account_id': salary_account['id'],
                    'amount': float(salary_amount),
                    'transaction_date': payment_date,
                    'payment_method': payment_item.get('payment_method', 'bank_transfer'),
                    'reference_number': receipt_number,
                    'description': f"Salary for {employee_name} - {payment_month}",
                    'employee_id': employee_id,
                    'created_at': datetime.now().isoformat(),
                    'updated_at': datetime.now().isoformat()
                })
                
                # 3. Track advance deduction for batch processing
                if advance_deduction > 0 and advance_id:
                    advance_updates.append({
                        'employee_id': employee_id,
                        'advance_id': advance_id,
                        'deduction': advance_deduction,
                        'advance_data': payment_item.get('advance_info'),
                        'payment_month': payment_month
                    })
                
                processed_count += 1
                total_net_pay += net_pay
                total_advance_deductions += advance_deduction
                payments.append({
                    'employee_name': employee_name,
                    'employee_id': payment_item.get('employee_id_code'),
                    'gross_salary': salary_amount,
                    'deductions': deductions,
                    'bonuses': bonuses,
                    'advance_deduction': advance_deduction,
                    'net_pay': net_pay,
                    'receipt_number': receipt_number
                })
                
            except Exception as e:
                errors.append(f"Error processing {payment_item.get('name', 'Unknown')}: {str(e)}")
        
        # Batch insert salary payments
        if salary_payments:
            supabase.table('salary_payments').insert(salary_payments).execute()
        
        # Batch insert expense transactions
        if expense_transactions:
            supabase.table('expense_transactions').insert(expense_transactions).execute()
        
        # Process advance deductions with journal entries
        if advance_updates:
            for update in advance_updates:
                # Update advance
                advance_response = supabase.table('employee_advances')\
                    .select('*')\
                    .eq('id', update['advance_id'])\
                    .eq('institute_id', institute_id)\
                    .execute()
                
                if advance_response.data:
                    advance = advance_response.data[0]
                    new_repaid = float(advance['repaid_amount']) + update['deduction']
                    new_remaining = float(advance['advance_amount']) - new_repaid
                    new_status = 'completed' if new_remaining <= 0 else 'active'
                    
                    supabase.table('employee_advances')\
                        .update({
                            'repaid_amount': new_repaid,
                            'remaining_amount': new_remaining,
                            'status': new_status,
                            'updated_at': datetime.now().isoformat()
                        })\
                        .eq('id', update['advance_id'])\
                        .execute()
                    
                    # Record repayment
                    payment_data = {
                        'id': str(uuid.uuid4()),
                        'institute_id': institute_id,
                        'advance_id': update['advance_id'],
                        'employee_id': update['employee_id'],
                        'amount': update['deduction'],
                        'payment_month': payment_month,
                        'payment_date': payment_date,
                        'is_repayment': True,
                        'notes': f'Auto-deduction from salary for {payment_month}',
                        'created_at': datetime.now().isoformat()
                    }
                    supabase.table('advance_payments').insert(payment_data).execute()
                    
                    # Create journal entry for deduction
                    create_advance_deduction_journal_entry(
                        institute_id, 
                        update['employee_id'], 
                        update['advance_id'], 
                        update['deduction'], 
                        payment_month
                    )
        
        if processed_count > 0:
            return jsonify({
                'success': True,
                'message': f'Successfully processed salary for {processed_count} employee(s)',
                'total_net_pay': total_net_pay,
                'total_advance_deductions': total_advance_deductions,
                'total_salary_expense': total_net_pay + total_advance_deductions,
                'payments': payments,
                'errors': errors if errors else None
            })
        else:
            return jsonify({
                'success': False,
                'message': 'No salaries were processed',
                'errors': errors
            }), 400
        
    except Exception as e:
        print(f"Error processing salary: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


@salary_bp.route('/api/salary/payslip/<receipt_number>', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def print_payslip(receipt_number):
    """Generate PDF salary slip"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Get institute details
        institute_response = supabase.table('institutes')\
            .select('*')\
            .eq('id', institute_id)\
            .execute()
        
        institute = institute_response.data[0] if institute_response.data else {}
        
        payment_response = supabase.table('salary_payments')\
            .select('*, employees(name, employee_id, role)')\
            .eq('receipt_number', receipt_number)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if not payment_response.data:
            return jsonify({'success': False, 'message': 'Payslip not found'}), 404
        
        payment = payment_response.data[0]
        employee = payment['employees']
        
        # Generate PDF
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=(80*mm, 200*mm),
                                rightMargin=5*mm, leftMargin=5*mm,
                                topMargin=5*mm, bottomMargin=5*mm)
        
        story = []
        styles = getSampleStyleSheet()
        
        title_style = ParagraphStyle(
            'Title',
            parent=styles['Normal'],
            fontSize=12,
            alignment=1,
            spaceAfter=5,
            fontName='Helvetica-Bold'
        )
        
        normal_style = ParagraphStyle(
            'Normal',
            parent=styles['Normal'],
            fontSize=9,
            alignment=0,
            spaceAfter=3
        )
        
        center_style = ParagraphStyle(
            'Center',
            parent=styles['Normal'],
            fontSize=9,
            alignment=1,
            spaceAfter=3
        )
        
        # Institute Header
        story.append(Paragraph(institute.get('institute_name', 'School Name'), title_style))
        story.append(Paragraph(institute.get('target_line', ''), center_style))
        story.append(Paragraph(institute.get('address', ''), center_style))
        story.append(Paragraph(f"Tel: {institute.get('phone_number', '')}", center_style))
        story.append(Spacer(1, 5))
        
        story.append(Paragraph("=" * 35, normal_style))
        story.append(Paragraph("SALARY PAYMENT SLIP", title_style))
        story.append(Paragraph("=" * 35, normal_style))
        story.append(Spacer(1, 5))
        
        # Employee Details
        emp_data = [
            ['Receipt No:', payment['receipt_number']],
            ['Date:', payment['payment_date']],
            ['Month:', payment['payment_month']],
            ['', ''],
            ['Employee ID:', employee['employee_id']],
            ['Employee Name:', employee['name']],
            ['Role:', employee.get('role', 'Staff').replace('_', ' ').title()],
        ]
        
        t = Table(emp_data, colWidths=[30*mm, 40*mm])
        t.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        story.append(t)
        story.append(Spacer(1, 5))
        
        # Salary Details
        story.append(Paragraph("-" * 35, normal_style))
        
        salary_data = [
            ['Gross Salary:', f"UGX {float(payment.get('gross_salary', 0)):,.0f}"],
        ]
        
        if payment.get('deductions', 0) > 0:
            salary_data.append(['Deductions:', f"- UGX {float(payment.get('deductions', 0)):,.0f}"])
        
        if payment.get('bonuses', 0) > 0:
            salary_data.append(['Bonuses:', f"+ UGX {float(payment.get('bonuses', 0)):,.0f}"])
        
        if payment.get('advance_deduction', 0) > 0:
            salary_data.append(['Advance Deduction:', f"- UGX {float(payment.get('advance_deduction', 0)):,.0f}"])
        
        salary_data.append(['', ''])
        salary_data.append(['NET PAYABLE:', f"UGX {float(payment['amount']):,.0f}"])
        
        t2 = Table(salary_data, colWidths=[30*mm, 40*mm])
        t2.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        
        t2.setStyle(TableStyle([
            ('FONTNAME', (0, -1), (1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, -1), (1, -1), 11),
        ]))
        
        story.append(t2)
        story.append(Spacer(1, 5))
        story.append(Paragraph(f"Payment Method: {payment['payment_method'].upper()}", normal_style))
        story.append(Paragraph("-" * 35, normal_style))
        story.append(Spacer(1, 8))
        story.append(Paragraph("Thank you for your service!", center_style))
        story.append(Paragraph("This is a computer generated payslip", center_style))
        
        doc.build(story)
        buffer.seek(0)
        
        return send_file(
            buffer,
            as_attachment=False,
            download_name=f"payslip_{receipt_number}.pdf",
            mimetype='application/pdf'
        )
        
    except Exception as e:
        print(f"Error generating payslip: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@salary_bp.route('/api/salary/download-pdf', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def download_salary_pdf():
    """Download salary summary as PDF"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    temp_logo_path = None
    
    try:
        institute_response = supabase.table('institutes')\
            .select('*')\
            .eq('id', institute_id)\
            .execute()
        
        institute = institute_response.data[0] if institute_response.data else {}
        
        data = request.get_json()
        employees = data.get('employees', [])
        month = data.get('month')
        
        if not employees:
            return jsonify({'success': False, 'message': 'No data to export'}), 400
        
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(A4),
                                rightMargin=20, leftMargin=20,
                                topMargin=20, bottomMargin=20)
        
        story = []
        styles = getSampleStyleSheet()
        
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=16,
            textColor=colors.HexColor('#ffa500'),
            alignment=1,
            spaceAfter=20
        )
        
        # Handle logo
        if institute.get('logo_url'):
            try:
                response = requests.get(institute['logo_url'], timeout=5)
                if response.status_code == 200:
                    img_data = response.content
                    img_buffer = io.BytesIO(img_data)
                    pil_img = PILImage.open(img_buffer)
                    
                    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
                        pil_img.save(tmp.name, 'JPEG')
                        temp_logo_path = tmp.name
                    
                    logo = Image(temp_logo_path, width=1.5*inch, height=1.5*inch)
                    logo.hAlign = 'CENTER'
                    story.append(logo)
            except Exception as e:
                print(f"Error loading logo: {e}")
                pass
        
        story.append(Paragraph(institute.get('institute_name', 'School Name'), title_style))
        story.append(Paragraph(institute.get('address', ''), styles['Normal']))
        story.append(Paragraph(f"Tel: {institute.get('phone_number', '')}", styles['Normal']))
        story.append(Spacer(1, 10))
        
        story.append(Paragraph(f"PAYROLL SUMMARY - {month}", title_style))
        story.append(Spacer(1, 10))
        
        # Table with advance deduction column
        table_data = [
            ['S/N', 'Employee Name', 'Gross Salary', 'Advance Deduction', 'Net Pay (UGX)']
        ]
        
        total_gross = 0
        total_advance = 0
        total_net = 0
        
        for idx, emp in enumerate(employees, 1):
            gross = float(emp.get('monthly_salary', 0))
            advance = float(emp.get('advance_deduction', 0))
            net = gross - advance
            
            total_gross += gross
            total_advance += advance
            total_net += net
            
            table_data.append([
                str(idx),
                emp.get('name', 'N/A'),
                f"{gross:,.0f}",
                f"{advance:,.0f}",
                f"{net:,.0f}"
            ])
        
        table_data.append(['', '', '', 'TOTAL:', f"{total_net:,.0f}"])
        
        table = Table(table_data, colWidths=[0.5*inch, 3*inch, 1.5*inch, 1.5*inch, 1.5*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#ffa500')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('ALIGN', (2, 1), (-1, -2), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#fef3c7')),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -2), 0.5, colors.grey),
            ('BOX', (0, -1), (-1, -1), 1, colors.black),
        ]))
        
        story.append(table)
        story.append(Spacer(1, 20))
        story.append(Paragraph(f"Generated on: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}", styles['Normal']))
        story.append(Paragraph("This is a computer generated document", styles['Normal']))
        
        doc.build(story)
        
        # Clean up temp file
        if temp_logo_path and os.path.exists(temp_logo_path):
            try:
                os.unlink(temp_logo_path)
            except:
                pass
        
        buffer.seek(0)
        
        return send_file(
            buffer,
            as_attachment=True,
            download_name=f"payroll_{month}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
            mimetype='application/pdf'
        )
        
    except Exception as e:
        if temp_logo_path and os.path.exists(temp_logo_path):
            try:
                os.unlink(temp_logo_path)
            except:
                pass
        print(f"Error generating PDF: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


# ==================== HELPER FUNCTIONS ====================

def get_employee_advance_summary(institute_id, employee_id):
    """Get advance summary for a specific employee"""
    try:
        advances_response = supabase.table('employee_advances')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .eq('employee_id', employee_id)\
            .execute()
        
        advances = advances_response.data if advances_response.data else []
        
        total_advance = sum(float(a['advance_amount']) for a in advances)
        total_repaid = sum(float(a['repaid_amount']) for a in advances)
        current_balance = total_advance - total_repaid
        active_count = len([a for a in advances if a['status'] == 'active'])
        
        return {
            'total_advance': total_advance,
            'total_repaid': total_repaid,
            'current_balance': current_balance,
            'active_count': active_count,
            'advances': advances
        }
    except Exception as e:
        print(f"Error getting advance summary: {e}")
        return {
            'total_advance': 0,
            'total_repaid': 0,
            'current_balance': 0,
            'active_count': 0,
            'advances': []
        }