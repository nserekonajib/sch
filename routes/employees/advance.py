# advance.py - Employee Advance Management Module
from flask import Blueprint, render_template, request, jsonify, session, send_file
from supabase import create_client, Client
import os
import uuid
import random
import string
from datetime import datetime, timedelta
import json
from functools import wraps
from dotenv import load_dotenv
from routes.accounts.accounts import get_institute_id
from routes.permissions.permissions import role_required

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

advance_bp = Blueprint('advance', __name__, url_prefix='/advance')

def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Please login'}), 401
        return f(*args, **kwargs)
    return decorated_function



def get_advance_liability_account(institute_id):
    """Get or create advance liability account for employees"""
    try:
        response = supabase.table('chart_of_accounts')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .eq('account_name', 'EMPLOYEE ADVANCES')\
            .eq('account_type', 'liability')\
            .execute()
        
        if response.data:
            return response.data[0]
        
        count_response = supabase.table('chart_of_accounts')\
            .select('id', count='exact')\
            .eq('institute_id', institute_id)\
            .eq('account_type', 'liability')\
            .execute()
        
        count = (count_response.count or 0) + 1
        account_code = f"LIA-{str(count).zfill(4)}"
        
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
        
        if result.data:
            return result.data[0]
        return None
        
    except Exception as e:
        print(f"Error getting advance account: {e}")
        return None


# ==================== ROUTES ====================

@advance_bp.route('/')
@role_required(['owner', 'teacher', 'accountant'])
def index():
    """Advance Management Page"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return render_template('advance/index.html', institute=None, now=datetime.now())
    
    # # Create tables if they don't exist
    # create_advance_tables(institute_id)
    
    # Get institute details
    institute_response = supabase.table('institutes')\
        .select('*')\
        .eq('id', institute_id)\
        .execute()
    
    institute = institute_response.data[0] if institute_response.data else None
    
    return render_template('advance/index.html', institute=institute, now=datetime.now())


@advance_bp.route('/api/live-search', methods=['GET'])
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
            .select('id, employee_id, name, role, monthly_salary, status, date_of_joining')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')
        
        if search_term:
            # Search by name or employee_id
            query = query.or_(f"name.ilike.%{search_term}%,employee_id.ilike.%{search_term}%")
        
        response = query.limit(limit).order('name').execute()
        
        employees = response.data if response.data else []
        
        # Get advance summary for each employee
        for emp in employees:
            advance_summary = get_employee_advance_summary(institute_id, emp['id'])
            emp['total_advances'] = advance_summary['total_advance']
            emp['total_repaid'] = advance_summary['total_repaid']
            emp['current_balance'] = advance_summary['current_balance']
            emp['active_advances'] = advance_summary['active_count']
        
        return jsonify({'success': True, 'employees': employees})
        
    except Exception as e:
        print(f"Error in live search: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@advance_bp.route('/api/employees/<employee_id>/advances', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_employee_advances(employee_id):
    """Get all advances for a specific employee"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Get all advances for this employee
        advances_response = supabase.table('employee_advances')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .eq('employee_id', employee_id)\
            .order('created_at', desc=True)\
            .execute()
        
        advances = advances_response.data if advances_response.data else []
        
        # Get payment history for each advance
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


@advance_bp.route('/api/create-advance', methods=['POST'])
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
        
        # Validation
        if not employee_id:
            return jsonify({'success': False, 'message': 'Employee ID required'}), 400
        
        if advance_amount <= 0:
            return jsonify({'success': False, 'message': 'Advance amount must be greater than 0'}), 400
        
        if not advance_month:
            return jsonify({'success': False, 'message': 'Advance month required'}), 400
        
        # Get employee details to check salary
        emp_response = supabase.table('employees')\
            .select('monthly_salary, name')\
            .eq('id', employee_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if not emp_response.data:
            return jsonify({'success': False, 'message': 'Employee not found'}), 404
        
        employee = emp_response.data[0]
        monthly_salary = float(employee.get('monthly_salary', 0))
        
        # Calculate monthly deduction (advance divided by repayment months)
        monthly_deduction = advance_amount / repayment_months if repayment_months > 0 else advance_amount
        
        # Check if monthly deduction exceeds 50% of salary (safety limit)
        max_allowed_deduction = monthly_salary * 0.5
        if monthly_deduction > max_allowed_deduction:
            return jsonify({
                'success': False, 
                'message': f'Monthly deduction ({monthly_deduction:,.0f}) exceeds 50% of monthly salary ({max_allowed_deduction:,.0f})'
            }), 400
        
        # Calculate repayment end month
        advance_date = datetime.strptime(advance_month, '%Y-%m')
        repayment_start_month = advance_date.strftime('%Y-%m')
        
        # Add repayment months
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
        
        # Create advance liability account entry
        liability_account = get_advance_liability_account(institute_id)
        if liability_account:
            # This would create a journal entry in your accounting system
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


@advance_bp.route('/api/advances/<advance_id>/repayment', methods=['POST'])
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
        payment_date = data.get('payment_date')
        notes = data.get('notes', '')
        
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
        payment_id = str(uuid.uuid4())
        payment_data = {
            'id': payment_id,
            'institute_id': institute_id,
            'advance_id': advance_id,
            'employee_id': advance['employee_id'],
            'amount': amount,
            'payment_month': payment_month or advance['advance_month'],
            'payment_date': payment_date or datetime.now().strftime('%Y-%m-%d'),
            'is_repayment': True,
            'notes': notes,
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
        
        return jsonify({
            'success': True,
            'message': f'Repayment of UGX {amount:,.0f} recorded successfully',
            'remaining_balance': new_remaining,
            'status': new_status
        })
        
    except Exception as e:
        print(f"Error recording repayment: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@advance_bp.route('/api/advances/<advance_id>', methods=['DELETE'])
@role_required(['owner', 'teacher', 'accountant'])
def delete_advance(advance_id):
    """Delete an advance (only if not fully repaid)"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Check advance status
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
        
        # Delete the advance and its payments
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


@advance_bp.route('/api/summary', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_advance_summary():
    """Get summary of all advances"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Get all active advances
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
        
        # Calculate totals
        total_outstanding = sum(float(a['remaining_amount']) for a in active_advances)
        total_advanced = sum(float(a['advance_amount']) for a in active_advances) + sum(float(a['advance_amount']) for a in completed_advances)
        total_repaid = sum(float(a['repaid_amount']) for a in active_advances) + sum(float(a['repaid_amount']) for a in completed_advances)
        
        # Get advances by month
        advances_by_month = {}
        for advance in active_advances + completed_advances:
            month = advance['advance_month']
            if month not in advances_by_month:
                advances_by_month[month] = {'total': 0, 'count': 0}
            advances_by_month[month]['total'] += float(advance['advance_amount'])
            advances_by_month[month]['count'] += 1
        
        return jsonify({
            'success': True,
            'summary': {
                'active_advances_count': len(active_advances),
                'completed_advances_count': len(completed_advances),
                'total_advanced': total_advanced,
                'total_repaid': total_repaid,
                'total_outstanding': total_outstanding
            },
            'active_advances': active_advances,
            'advances_by_month': advances_by_month
        })
        
    except Exception as e:
        print(f"Error getting advance summary: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@advance_bp.route('/api/apply-to-payroll', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def apply_advances_to_payroll():
    """Get all advances that should be deducted for a given month"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        payroll_month = data.get('payroll_month')
        
        if not payroll_month:
            return jsonify({'success': False, 'message': 'Payroll month required'}), 400
        
        # Get all active advances that should be deducted this month
        advances_response = supabase.table('employee_advances')\
            .select('*, employees(name, employee_id, monthly_salary)')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')\
            .lte('repayment_start_month', payroll_month)\
            .gte('repayment_end_month', payroll_month)\
            .execute()
        
        advances = advances_response.data if advances_response.data else []
        
        advance_deductions = []
        for advance in advances:
            # Check if already deducted this month
            existing_deduction = supabase.table('salary_payments')\
                .select('id')\
                .eq('employee_id', advance['employee_id'])\
                .eq('payment_month', payroll_month)\
                .eq('advance_deduction', advance['monthly_deduction'])\
                .execute()
            
            if not existing_deduction.data and advance['remaining_amount'] > 0:
                # Only deduct if remaining balance > 0
                deduction = min(advance['monthly_deduction'], advance['remaining_amount'])
                advance_deductions.append({
                    'advance_id': advance['id'],
                    'employee_id': advance['employee_id'],
                    'employee_name': advance['employees']['name'],
                    'employee_code': advance['employees']['employee_id'],
                    'deduction_amount': deduction,
                    'original_advance': advance['advance_amount'],
                    'remaining_balance': advance['remaining_amount'] - deduction
                })
        
        return jsonify({
            'success': True,
            'payroll_month': payroll_month,
            'deductions': advance_deductions,
            'total_deductions': sum(d['deduction_amount'] for d in advance_deductions)
        })
        
    except Exception as e:
        print(f"Error applying advances to payroll: {e}")
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


def create_advance_journal_entry(institute_id, employee_id, advance_id, amount, advance_month):
    """Create accounting journal entry for advance"""
    try:
        liability_account = get_advance_liability_account(institute_id)
        
        if liability_account:
            # Create a transaction record for the advance
            advance_transaction = {
                'id': str(uuid.uuid4()),
                'institute_id': institute_id,
                'account_id': liability_account['id'],
                'amount': amount,
                'transaction_date': datetime.now().strftime('%Y-%m-%d'),
                'transaction_type': 'advance',
                'reference_number': f"ADV-{advance_id[:8]}",
                'description': f"Employee advance for {advance_month}",
                'employee_id': employee_id,
                'created_at': datetime.now().isoformat()
            }
            
            supabase.table('journal_entries').insert(advance_transaction).execute()
        
        return True
    except Exception as e:
        print(f"Error creating journal entry: {e}")
        return False


def update_advance_on_salary_payment(employee_id, payment_month, advance_deduction):
    """Update advance balance when salary payment includes deduction"""
    try:
        # Find active advance for this employee for this month
        advance_response = supabase.table('employee_advances')\
            .select('*')\
            .eq('employee_id', employee_id)\
            .eq('status', 'active')\
            .lte('repayment_start_month', payment_month)\
            .gte('repayment_end_month', payment_month)\
            .execute()
        
        if not advance_response.data:
            return False
        
        advance = advance_response.data[0]
        
        # Update repaid amount and remaining amount
        new_repaid = float(advance['repaid_amount']) + advance_deduction
        new_remaining = float(advance['advance_amount']) - new_repaid
        new_status = 'completed' if new_remaining <= 0 else 'active'
        
        supabase.table('employee_advances')\
            .update({
                'repaid_amount': new_repaid,
                'remaining_amount': new_remaining,
                'status': new_status,
                'updated_at': datetime.now().isoformat()
            })\
            .eq('id', advance['id'])\
            .execute()
        
        # Record the automatic repayment
        payment_data = {
            'id': str(uuid.uuid4()),
            'institute_id': advance['institute_id'],
            'advance_id': advance['id'],
            'employee_id': employee_id,
            'amount': advance_deduction,
            'payment_month': payment_month,
            'payment_date': datetime.now().strftime('%Y-%m-%d'),
            'is_repayment': True,
            'notes': f'Auto-deduction from salary for {payment_month}',
            'created_at': datetime.now().isoformat()
        }
        
        supabase.table('advance_payments').insert(payment_data).execute()
        
        return True
        
    except Exception as e:
        print(f"Error updating advance on salary payment: {e}")
        return False


# Function to be called from payroll module when processing salary
def get_advance_deduction_for_employee(institute_id, employee_id, payroll_month):
    """Get the advance deduction amount for an employee for a specific month"""
    try:
        advance_response = supabase.table('employee_advances')\
            .select('monthly_deduction, remaining_amount')\
            .eq('institute_id', institute_id)\
            .eq('employee_id', employee_id)\
            .eq('status', 'active')\
            .lte('repayment_start_month', payroll_month)\
            .gte('repayment_end_month', payroll_month)\
            .execute()
        
        if not advance_response.data:
            return 0
        
        advance = advance_response.data[0]
        # Don't deduct more than remaining balance
        return min(float(advance['monthly_deduction']), float(advance['remaining_amount']))
        
    except Exception as e:
        print(f"Error getting advance deduction: {e}")
        return 0