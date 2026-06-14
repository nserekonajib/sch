from routes.permissions.permissions import role_required
# accounts.py - Fixed get_institute_id to properly handle employee sessions
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

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

accounts_bp = Blueprint('accounts', __name__, url_prefix='/accounts')

def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Please login'}), 401
        return f(*args, **kwargs)
    return decorated_function

def get_institute_from_session(return_id_only=False):
    """Get institute details from current session - handles both owners and employees
    
    Args:
        return_id_only (bool): If True, returns only the institute ID (UUID string)
                              If False, returns the full institute object (dict)
    
    Returns:
        str or dict or None: Institute ID if return_id_only=True, 
                             Full institute object if return_id_only=False,
                             None if not found
    """
    user = session.get('user')
    if not user:
        print("No user in session")
        return None
    
    print(f"Getting institute for user: {user.get('id')}, is_employee: {user.get('is_employee')}")
    print(f"User institute_id from session: {user.get('institute_id')}")
    
    institute_id = None
    
    # CASE 1: Employee - has institute_id directly in session
    if user.get('is_employee') and user.get('institute_id'):
        institute_id = user.get('institute_id')
        print(f"Using employee institute_id from session: {institute_id}")
    
    # CASE 2: Owner - need to look up by user_id
    elif not user.get('is_employee') and user.get('id'):
        try:
            response = supabase.table('institutes')\
                .select('id')\
                .eq('user_id', user['id'])\
                .execute()
            
            if response.data and len(response.data) > 0:
                institute_id = response.data[0]['id']
                print(f"Found owner institute_id: {institute_id}")
            else:
                print(f"No institute found for owner user_id: {user['id']}")
        except Exception as e:
            print(f"Error finding owner institute: {e}")
    
    # CASE 3: Employee but institute_id not in session - fallback to lookup
    elif user.get('is_employee') and not user.get('institute_id'):
        try:
            employee_response = supabase.table('employees')\
                .select('institute_id')\
                .eq('id', user['id'])\
                .execute()
            
            if employee_response.data and len(employee_response.data) > 0:
                institute_id = employee_response.data[0].get('institute_id')
                print(f"Found employee institute_id from lookup: {institute_id}")
        except Exception as e:
            print(f"Error looking up employee institute: {e}")
    
    if not institute_id:
        print("No institute_id found")
        return None
    
    # If caller only wants the ID, return it directly
    if return_id_only:
        print(f"Returning institute ID only: {institute_id}")
        return institute_id
    
    # Otherwise, fetch and return full institute details
    try:
        response = supabase.table('institutes')\
            .select('*')\
            .eq('id', institute_id)\
            .execute()
        
        if response.data and len(response.data) > 0:
            print(f"Found institute: {response.data[0].get('institute_name')}")
            return response.data[0]
        else:
            print(f"No institute found with id: {institute_id}")
            return None
    except Exception as e:
        print(f"Error fetching institute details: {e}")
        return None


def get_institute_id(user_param=None):
    """Legacy function - returns institute ID (UUID string) intelligently
    
    This function can accept either a user object or None.
    If it receives a dictionary (old style), it extracts the user_id.
    If it receives None, it gets the current user from session.
    
    Returns:
        str or None: Institute ID as UUID string
    """
    # Handle different parameter types for backward compatibility
    if user_param is not None and isinstance(user_param, dict):
        # Old style: was called with user object
        user_id = user_param.get('id')
        if user_id:
            # Temporarily store the user_id in session context
            original_user = session.get('user')
            try:
                # Create a mock session user
                session['user'] = user_param
                # Get institute ID only
                result = get_institute_from_session(return_id_only=True)
                return result
            finally:
                # Restore original session user
                if original_user:
                    session['user'] = original_user
                else:
                    session.pop('user', None)
    else:
        # New style: get from current session
        result = get_institute_from_session(return_id_only=True)
        
        # If result is a dict (for some reason), extract the ID
        if isinstance(result, dict):
            return result.get('id')
        return result


# Optional: Add a convenience function for getting just the ID
def get_current_institute_id():
    """Convenience function to get just the institute ID from current session"""
    return get_institute_from_session(return_id_only=True)


# Optional: Add a convenience function for getting full object
def get_current_institute():
    """Convenience function to get full institute object from current session"""
    return get_institute_from_session(return_id_only=False)

@accounts_bp.route('/')
@role_required(['owner', 'teacher', 'accountant'])
def index():
    """Accounts Dashboard"""
    institute = get_institute_from_session()
    
    print(f"Institute in index route: {institute}")
    
    if not institute:
        return render_template('accounts/index.html', institute=None)
    
    return render_template('accounts/index.html', institute=institute)


@accounts_bp.route('/dashboard/stats', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_dashboard_stats():
    """Get enhanced dashboard statistics"""
    institute = get_institute_from_session()
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    print(f"Getting stats for institute: {institute['id']} - {institute.get('institute_name')}")
    
    try:
        # Get current month date range for school fees (current month only)
        today = datetime.now()
        month_start = today.replace(day=1).date()
        month_end = today.date()
        
        # For other income and expenses, get ALL TIME (or you can set to current year)
        # Option 1: Get current year
        year_start = datetime(today.year, 1, 1).date()
        
        # Option 2: Get ALL TIME (no date filter)
        # Just fetch all data without date filtering
        
        print(f"Date range for school fees (current month): {month_start} to {month_end}")
        print(f"Date range for other income (all time/current year): {year_start} to {month_end}")
        
        # Get school fees collected from payments table (current month only)
        payments_response = supabase.table('payments')\
            .select('amount, payment_date')\
            .eq('institute_id', institute['id'])\
            .execute()
        
        # Filter payments by current month date
        school_fees_collected = 0
        for payment in (payments_response.data or []):
            try:
                payment_date = payment.get('payment_date')
                if payment_date:
                    if isinstance(payment_date, str):
                        payment_date = datetime.strptime(payment_date, '%Y-%m-%d').date()
                    elif isinstance(payment_date, datetime):
                        payment_date = payment_date.date()
                    
                    if month_start <= payment_date <= month_end:
                        school_fees_collected += float(payment['amount'])
            except Exception as e:
                print(f"Error parsing payment date: {e}")
        
        print(f"School fees collected (current month): {school_fees_collected}")
        
        # Get other income from income_transactions (ALL TIME or CURRENT YEAR)
        other_income_response = supabase.table('income_transactions')\
            .select('amount, transaction_date, description')\
            .eq('institute_id', institute['id'])\
            .execute()
        
        print(f"All income transactions: {other_income_response.data}")
        
        # Calculate other income for CURRENT YEAR (or you can use ALL TIME by removing date filter)
        other_income = 0
        for item in (other_income_response.data or []):
            try:
                transaction_date = item.get('transaction_date')
                
                if transaction_date:
                    if isinstance(transaction_date, str):
                        if 'T' in transaction_date:
                            transaction_date = datetime.fromisoformat(transaction_date.replace('Z', '+00:00')).date()
                        else:
                            transaction_date = datetime.strptime(transaction_date, '%Y-%m-%d').date()
                    elif isinstance(transaction_date, datetime):
                        transaction_date = transaction_date.date()
                    
                    # Option A: Use current year (2026)
                    if transaction_date.year == today.year:
                        amount = float(item['amount'])
                        other_income += amount
                        print(f"✓ ADDED {amount} from {item.get('description', 'Unknown')} on {transaction_date}")
                    else:
                        print(f"✗ SKIPPED - year {transaction_date.year} not current year")
                        
            except Exception as e:
                print(f"Error parsing income date: {e}")
        
        print(f"Other income (current year): {other_income}")
        
        # Get expenses from expense_transactions (ALL TIME or CURRENT YEAR)
        expense_response = supabase.table('expense_transactions')\
            .select('amount, transaction_date')\
            .eq('institute_id', institute['id'])\
            .execute()
        
        total_expenses = 0
        for item in (expense_response.data or []):
            try:
                transaction_date = item.get('transaction_date')
                if transaction_date:
                    if isinstance(transaction_date, str):
                        if 'T' in transaction_date:
                            transaction_date = datetime.fromisoformat(transaction_date.replace('Z', '+00:00')).date()
                        else:
                            transaction_date = datetime.strptime(transaction_date, '%Y-%m-%d').date()
                    elif isinstance(transaction_date, datetime):
                        transaction_date = transaction_date.date()
                    
                    # Use current year for expenses as well
                    if transaction_date.year == today.year:
                        total_expenses += float(item['amount'])
            except Exception as e:
                print(f"Error parsing expense date: {e}")
        
        # Total income
        total_income = school_fees_collected + other_income
        
        # Net profit/loss
        net = total_income - total_expenses
        
        # Get total accounts for THIS institute only
        accounts_response = supabase.table('chart_of_accounts')\
            .select('id', count='exact')\
            .eq('institute_id', institute['id'])\
            .execute()
        
        total_accounts = accounts_response.count or 0
        
        # Get transaction count (current year)
        total_transactions = 0
        for payment in (payments_response.data or []):
            try:
                payment_date = payment.get('payment_date')
                if payment_date:
                    if isinstance(payment_date, str):
                        payment_date = datetime.strptime(payment_date, '%Y-%m-%d').date()
                    elif isinstance(payment_date, datetime):
                        payment_date = payment_date.date()
                    
                    if payment_date.year == today.year:
                        total_transactions += 1
            except:
                pass
        
        for item in (other_income_response.data or []):
            try:
                transaction_date = item.get('transaction_date')
                if transaction_date:
                    if isinstance(transaction_date, str):
                        transaction_date = datetime.strptime(transaction_date, '%Y-%m-%d').date()
                    
                    if transaction_date.year == today.year:
                        total_transactions += 1
            except:
                pass
        
        for item in (expense_response.data or []):
            try:
                transaction_date = item.get('transaction_date')
                if transaction_date:
                    if isinstance(transaction_date, str):
                        transaction_date = datetime.strptime(transaction_date, '%Y-%m-%d').date()
                    
                    if transaction_date.year == today.year:
                        total_transactions += 1
            except:
                pass
        
        print(f"Final stats - School Fees (current month): {school_fees_collected}, Other Income (current year): {other_income}, Total Income: {total_income}, Expenses: {total_expenses}, Net: {net}")
        
        return jsonify({
            'success': True,
            'stats': {
                'school_fees_collected': school_fees_collected,
                'other_income': other_income,
                'total_income': total_income,
                'total_expenses': total_expenses,
                'net': net,
                'total_accounts': total_accounts,
                'total_transactions': total_transactions
            }
        })
        
    except Exception as e:
        print(f"Error getting dashboard stats: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@accounts_bp.route('/chart-of-accounts', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_chart_of_accounts():
    """Get all chart of accounts for the current institute only"""
    institute = get_institute_from_session()
    
    print(f"Getting chart of accounts for institute: {institute['id'] if institute else 'None'} - {institute.get('institute_name') if institute else 'None'}")
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Get all accounts for THIS SPECIFIC institute only
        response = supabase.table('chart_of_accounts')\
            .select('*')\
            .eq('institute_id', institute['id'])\
            .order('account_type')\
            .order('account_name')\
            .execute()
        
        accounts = response.data if response.data else []
        
        print(f"Found {len(accounts)} accounts for institute {institute['id']}")
        
        # Group by type
        grouped = {
            'asset': [],
            'liability': [],
            'equity': [],
            'income': [],
            'expense': []
        }
        
        for account in accounts:
            account_type = account.get('account_type', 'expense')
            if account_type in grouped:
                grouped[account_type].append(account)
        
        return jsonify({'success': True, 'accounts': grouped})
        
    except Exception as e:
        print(f"Error getting chart of accounts: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@accounts_bp.route('/chart-of-accounts/create', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def create_account():
    """Create a new chart of account for the current institute"""
    institute = get_institute_from_session()
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        
        # Generate account code
        account_code = generate_account_code(institute['id'], data.get('account_type'))
        
        account_data = {
            'id': str(uuid.uuid4()),
            'institute_id': institute['id'],
            'account_code': account_code,
            'account_name': data.get('account_name', '').strip(),
            'account_type': data.get('account_type'),
            'description': data.get('description', ''),
            'is_active': True,
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        if not account_data['account_name']:
            return jsonify({'success': False, 'message': 'Account name is required'}), 400
        
        result = supabase.table('chart_of_accounts').insert(account_data).execute()
        
        if result.data:
            return jsonify({
                'success': True,
                'message': 'Account created successfully',
                'account': result.data[0]
            })
        else:
            return jsonify({'success': False, 'message': 'Failed to create account'}), 500
            
    except Exception as e:
        print(f"Error creating account: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@accounts_bp.route('/chart-of-accounts/delete/<account_id>', methods=['DELETE'])
@role_required(['owner', 'teacher', 'accountant'])
def delete_account(account_id):
    """Delete a chart of account for the current institute"""
    institute = get_institute_from_session()
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # First, check if the account exists and belongs to this institute
        check_response = supabase.table('chart_of_accounts')\
            .select('*')\
            .eq('id', account_id)\
            .eq('institute_id', institute['id'])\
            .execute()
        
        if not check_response.data:
            return jsonify({'success': False, 'message': 'Account not found or access denied'}), 404
        
        account = check_response.data[0]
        
        # Check if the account has any transactions linked to it
        # You might want to check different transaction tables based on your schema
        has_transactions = False
        
        # Check journal entries
        try:
            journal_response = supabase.table('journal_entries')\
                .select('id', count='exact')\
                .eq('account_id', account_id)\
                .limit(1)\
                .execute()
            
            if journal_response.count and journal_response.count > 0:
                has_transactions = True
        except:
            pass
        
        # Check general ledger entries
        if not has_transactions:
            try:
                ledger_response = supabase.table('general_ledger')\
                    .select('id', count='exact')\
                    .eq('account_id', account_id)\
                    .limit(1)\
                    .execute()
                
                if ledger_response.count and ledger_response.count > 0:
                    has_transactions = True
            except:
                pass
        
        # If account has transactions, prevent deletion
        if has_transactions:
            # Option 1: Soft delete (mark as inactive)
            update_response = supabase.table('chart_of_accounts')\
                .update({
                    'is_active': False,
                    'updated_at': datetime.now().isoformat()
                })\
                .eq('id', account_id)\
                .execute()
            
            if update_response.data:
                return jsonify({
                    'success': True, 
                    'message': 'Account has existing transactions. It has been deactivated instead of deleted.',
                    'soft_delete': True
                })
            else:
                return jsonify({
                    'success': False, 
                    'message': 'Account cannot be deleted due to existing transactions'
                }), 400
        
        # No transactions, safe to delete
        delete_response = supabase.table('chart_of_accounts')\
            .delete()\
            .eq('id', account_id)\
            .eq('institute_id', institute['id'])\
            .execute()
        
        if delete_response.data:
            return jsonify({
                'success': True,
                'message': f'Account "{account.get("account_name")}" deleted successfully'
            })
        else:
            return jsonify({'success': False, 'message': 'Failed to delete account'}), 500
            
    except Exception as e:
        print(f"Error deleting account: {e}")
        return jsonify({'success': False, 'message': 'An error occurred while deleting the account'}), 500

@accounts_bp.route('/income/create', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def create_income():
    """Record income transaction for the current institute"""
    institute = get_institute_from_session()
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        
        transaction_data = {
            'id': str(uuid.uuid4()),
            'institute_id': institute['id'],
            'account_id': data.get('account_id'),
            'amount': float(data.get('amount', 0)),
            'transaction_date': data.get('transaction_date'),
            'payment_method': data.get('payment_method'),
            'reference_number': data.get('reference_number', ''),
            'description': data.get('description', ''),
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        if transaction_data['amount'] <= 0:
            return jsonify({'success': False, 'message': 'Invalid amount'}), 400
        
        result = supabase.table('income_transactions').insert(transaction_data).execute()
        
        if result.data:
            return jsonify({
                'success': True,
                'message': 'Income recorded successfully',
                'transaction': result.data[0]
            })
        else:
            return jsonify({'success': False, 'message': 'Failed to record income'}), 500
            
    except Exception as e:
        print(f"Error creating income: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@accounts_bp.route('/expense/create', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def create_expense():
    """Record expense transaction for the current institute"""
    institute = get_institute_from_session()
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        
        transaction_data = {
            'id': str(uuid.uuid4()),
            'institute_id': institute['id'],
            'account_id': data.get('account_id'),
            'amount': float(data.get('amount', 0)),
            'transaction_date': data.get('transaction_date'),
            'payment_method': data.get('payment_method'),
            'reference_number': data.get('reference_number', ''),
            'description': data.get('description', ''),
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        if transaction_data['amount'] <= 0:
            return jsonify({'success': False, 'message': 'Invalid amount'}), 400
        
        result = supabase.table('expense_transactions').insert(transaction_data).execute()
        
        if result.data:
            return jsonify({
                'success': True,
                'message': 'Expense recorded successfully',
                'transaction': result.data[0]
            })
        else:
            return jsonify({'success': False, 'message': 'Failed to record expense'}), 500
            
    except Exception as e:
        print(f"Error creating expense: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@accounts_bp.route('/transactions', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_transactions():
    """Get all transactions for the current institute"""
    institute = get_institute_from_session()
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Get school fees payments
        payments_response = supabase.table('payments')\
            .select('*, students(name)')\
            .eq('institute_id', institute['id'])\
            .order('payment_date', desc=True)\
            .execute()
        
        # Get income transactions
        income_response = supabase.table('income_transactions')\
            .select('*, chart_of_accounts(account_name)')\
            .eq('institute_id', institute['id'])\
            .order('transaction_date', desc=True)\
            .execute()
        
        # Get expense transactions
        expense_response = supabase.table('expense_transactions')\
            .select('*, chart_of_accounts(account_name)')\
            .eq('institute_id', institute['id'])\
            .order('transaction_date', desc=True)\
            .execute()
        
        all_transactions = []
        
        # Add school fees payments
        for payment in (payments_response.data or []):
            all_transactions.append({
                'id': payment['id'],
                'type': 'fees',
                'type_label': 'School Fees',
                'date': payment['payment_date'],
                'account_name': 'School Fees Collection',
                'student_name': payment['students']['name'] if payment.get('students') else 'N/A',
                'amount': float(payment['amount']),
                'payment_method': payment['payment_method'],
                'reference': payment['receipt_number'],
                'description': f"Fees payment from {payment['students']['name'] if payment.get('students') else 'Student'}",
                'created_at': payment['created_at']
            })
        
        # Add income transactions
        for income in (income_response.data or []):
            all_transactions.append({
                'id': income['id'],
                'type': 'income',
                'type_label': 'Other Income',
                'date': income['transaction_date'],
                'account_name': income['chart_of_accounts']['account_name'] if income.get('chart_of_accounts') else 'N/A',
                'amount': float(income['amount']),
                'payment_method': income['payment_method'],
                'reference': income.get('reference_number', ''),
                'description': income.get('description', ''),
                'created_at': income['created_at']
            })
        
        # Add expense transactions
        for expense in (expense_response.data or []):
            all_transactions.append({
                'id': expense['id'],
                'type': 'expense',
                'type_label': 'Expense',
                'date': expense['transaction_date'],
                'account_name': expense['chart_of_accounts']['account_name'] if expense.get('chart_of_accounts') else 'N/A',
                'amount': float(expense['amount']),
                'payment_method': expense['payment_method'],
                'reference': expense.get('reference_number', ''),
                'description': expense.get('description', ''),
                'created_at': expense['created_at']
            })
        
        # Sort by date
        all_transactions.sort(key=lambda x: x['date'], reverse=True)
        
        return jsonify({'success': True, 'transactions': all_transactions})
        
    except Exception as e:
        print(f"Error getting transactions: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@accounts_bp.route('/account-report/<account_id>', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def get_account_report(account_id):
    """Get report for specific account with date filtering"""
    institute = get_institute_from_session()
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        
        # Get account details - ensure it belongs to current institute
        account_response = supabase.table('chart_of_accounts')\
            .select('*')\
            .eq('id', account_id)\
            .eq('institute_id', institute['id'])\
            .execute()
        
        if not account_response.data:
            return jsonify({'success': False, 'message': 'Account not found'}), 404
        
        account = account_response.data[0]
        
        transactions = []
        
        # Get transactions based on account type
        if account['account_type'] == 'income':
            # Get income transactions
            income_response = supabase.table('income_transactions')\
                .select('*')\
                .eq('account_id', account_id)\
                .eq('institute_id', institute['id'])\
                .execute()
            
            for trans in (income_response.data or []):
                if (not start_date or trans['transaction_date'] >= start_date) and (not end_date or trans['transaction_date'] <= end_date):
                    transactions.append({
                        'date': trans['transaction_date'],
                        'description': trans.get('description', ''),
                        'reference': trans.get('reference_number', ''),
                        'amount': float(trans['amount']),
                        'type': 'credit'
                    })
        
        elif account['account_type'] == 'expense':
            # Get expense transactions
            expense_response = supabase.table('expense_transactions')\
                .select('*')\
                .eq('account_id', account_id)\
                .eq('institute_id', institute['id'])\
                .execute()
            
            for trans in (expense_response.data or []):
                if (not start_date or trans['transaction_date'] >= start_date) and (not end_date or trans['transaction_date'] <= end_date):
                    transactions.append({
                        'date': trans['transaction_date'],
                        'description': trans.get('description', ''),
                        'reference': trans.get('reference_number', ''),
                        'amount': float(trans['amount']),
                        'type': 'debit'
                    })
        
        # Sort by date
        transactions.sort(key=lambda x: x['date'])
        
        total = sum(t['amount'] for t in transactions)
        
        return jsonify({
            'success': True,
            'account': account,
            'transactions': transactions,
            'total': total,
            'start_date': start_date,
            'end_date': end_date
        })
        
    except Exception as e:
        print(f"Error getting account report: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@accounts_bp.route('/export-report/<account_id>', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def export_account_report(account_id):
    """Export account report to Excel/CSV"""
    institute = get_institute_from_session()
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        format_type = data.get('format', 'excel')
        
        # Get account details - ensure it belongs to current institute
        account_response = supabase.table('chart_of_accounts')\
            .select('*')\
            .eq('id', account_id)\
            .eq('institute_id', institute['id'])\
            .execute()
        
        if not account_response.data:
            return jsonify({'success': False, 'message': 'Account not found'}), 404
        
        account = account_response.data[0]
        
        transactions = []
        
        # Get transactions
        if account['account_type'] == 'income':
            income_response = supabase.table('income_transactions')\
                .select('*')\
                .eq('account_id', account_id)\
                .eq('institute_id', institute['id'])\
                .execute()
            
            for trans in (income_response.data or []):
                if (not start_date or trans['transaction_date'] >= start_date) and (not end_date or trans['transaction_date'] <= end_date):
                    transactions.append({
                        'Date': trans['transaction_date'],
                        'Description': trans.get('description', ''),
                        'Reference': trans.get('reference_number', ''),
                        'Amount': float(trans['amount']),
                        'Type': 'Credit'
                    })
        
        else:
            expense_response = supabase.table('expense_transactions')\
                .select('*')\
                .eq('account_id', account_id)\
                .eq('institute_id', institute['id'])\
                .execute()
            
            for trans in (expense_response.data or []):
                if (not start_date or trans['transaction_date'] >= start_date) and (not end_date or trans['transaction_date'] <= end_date):
                    transactions.append({
                        'Date': trans['transaction_date'],
                        'Description': trans.get('description', ''),
                        'Reference': trans.get('reference_number', ''),
                        'Amount': float(trans['amount']),
                        'Type': 'Debit'
                    })
        
        # Create DataFrame
        df = pd.DataFrame(transactions)
        
        if df.empty:
            return jsonify({'success': False, 'message': 'No transactions found for the selected period'}), 404
        
        # Add summary row
        total = df['Amount'].sum()
        summary_df = pd.DataFrame([{
            'Date': 'TOTAL',
            'Description': '',
            'Reference': '',
            'Amount': total,
            'Type': ''
        }])
        df = pd.concat([df, summary_df], ignore_index=True)
        
        # Export
        output = io.BytesIO()
        
        if format_type == 'excel':
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name=f"{account['account_name']}_Report", index=False)
            mimetype = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            filename = f"{account['account_name']}_report_{datetime.now().strftime('%Y%m%d')}.xlsx"
        else:
            df.to_csv(output, index=False)
            mimetype = 'text/csv'
            filename = f"{account['account_name']}_report_{datetime.now().strftime('%Y%m%d')}.csv"
        
        output.seek(0)
        
        return send_file(
            output,
            mimetype=mimetype,
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        print(f"Error exporting report: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    


@accounts_bp.route('/expenses')
def expenses():
    """Render expenses management page"""
    return render_template('expenses/index.html')


@accounts_bp.route('/income')
def income():
    """Render the income management page"""
    return render_template('incomes/index.html')
    
    
def generate_account_code(institute_id, account_type):
    """Generate unique account code including institute ID"""
    try:
        # Get count of existing accounts of this type for this institute
        response = supabase.table('chart_of_accounts')\
            .select('id', count='exact')\
            .eq('institute_id', institute_id)\
            .eq('account_type', account_type)\
            .execute()
        
        count = (response.count or 0) + 1
        
        # Map account type to prefix
        prefixes = {
            'asset': 'AST',
            'liability': 'LIA', 
            'equity': 'EQT',
            'income': 'INC',
            'expense': 'EXP'
        }
        
        prefix = prefixes.get(account_type, 'ACC')
        # Include institute_id in the account code to make it unique per institute
        return f"{prefix}-{institute_id}-{str(count).zfill(4)}"
        
    except Exception as e:
        # Fallback with timestamp for uniqueness
        return f"ACC-{institute_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
 # Add these new routes to your accounts.py file

# ============ ASSET MANAGEMENT APIS ============

@accounts_bp.route('/assets', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_assets():
    """Get all asset accounts with their current balances"""
    institute = get_institute_from_session()
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Get all asset accounts from chart of accounts
        accounts_response = supabase.table('chart_of_accounts')\
            .select('*')\
            .eq('institute_id', institute['id'])\
            .eq('account_type', 'asset')\
            .order('account_name')\
            .execute()
        
        assets = []
        
        for account in (accounts_response.data or []):
            # Get current balance for this asset account (now synchronous)
            balance = get_account_balance_sync(account['id'], institute['id'])
            
            # Get recent transactions (now synchronous)
            transactions = get_account_transactions_sync(account['id'], institute['id'], limit=5)
            
            assets.append({
                'id': account['id'],
                'account_code': account['account_code'],
                'account_name': account['account_name'],
                'description': account.get('description', ''),
                'current_balance': balance,
                'is_active': account.get('is_active', True),
                'recent_transactions': transactions
            })
        
        return jsonify({
            'success': True,
            'assets': assets,
            'total_assets_value': sum(asset['current_balance'] for asset in assets)
        })
        
    except Exception as e:
        print(f"Error getting assets: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


@accounts_bp.route('/assets/create', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def create_asset():
    """Create a new asset account or record asset purchase"""
    institute = get_institute_from_session()
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        
        # Check if we're creating a new asset account or recording an asset transaction
        if data.get('create_new_account'):
            # Create new asset account
            account_data = {
                'id': str(uuid.uuid4()),
                'institute_id': institute['id'],
                'account_code': generate_account_code(institute['id'], 'asset'),
                'account_name': data.get('account_name', '').strip(),
                'account_type': 'asset',
                'description': data.get('description', ''),
                'is_active': True,
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }
            
            if not account_data['account_name']:
                return jsonify({'success': False, 'message': 'Account name is required'}), 400
            
            result = supabase.table('chart_of_accounts').insert(account_data).execute()
            
            if result.data:
                # If initial value is provided, record as opening balance
                if data.get('initial_value', 0) > 0:
                    record_asset_transaction_sync(
                        result.data[0]['id'],
                        institute['id'],
                        data['initial_value'],
                        'debit',
                        'Opening Balance',
                        data.get('purchase_date', datetime.now().date().isoformat()),
                        data.get('notes', 'Initial asset value')
                    )
                
                return jsonify({
                    'success': True,
                    'message': 'Asset account created successfully',
                    'asset': result.data[0]
                })
            else:
                return jsonify({'success': False, 'message': 'Failed to create asset account'}), 500
        
        else:
            # Record asset transaction (purchase, depreciation, disposal)
            return record_asset_transaction_api_sync(institute['id'], data)
            
    except Exception as e:
        print(f"Error creating asset: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


@accounts_bp.route('/assets/<asset_id>/transactions', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_asset_transactions(asset_id):
    """Get all transactions for a specific asset"""
    institute = get_institute_from_session()
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Verify asset belongs to institute
        asset_response = supabase.table('chart_of_accounts')\
            .select('*')\
            .eq('id', asset_id)\
            .eq('institute_id', institute['id'])\
            .eq('account_type', 'asset')\
            .execute()
        
        if not asset_response.data:
            return jsonify({'success': False, 'message': 'Asset not found'}), 404
        
        asset = asset_response.data[0]
        
        # Get all transactions for this asset
        transactions = get_account_transactions_sync(asset_id, institute['id'], limit=100)
        
        return jsonify({
            'success': True,
            'asset': asset,
            'transactions': transactions,
            'current_balance': get_account_balance_sync(asset_id, institute['id'])
        })
        
    except Exception as e:
        print(f"Error getting asset transactions: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


# ============ LIABILITY MANAGEMENT APIS ============

@accounts_bp.route('/liabilities', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_liabilities():
    """Get all liability accounts with their current balances"""
    institute = get_institute_from_session()
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Get all liability accounts from chart of accounts
        accounts_response = supabase.table('chart_of_accounts')\
            .select('*')\
            .eq('institute_id', institute['id'])\
            .eq('account_type', 'liability')\
            .order('account_name')\
            .execute()
        
        liabilities = []
        
        for account in (accounts_response.data or []):
            # Get current balance for this liability account (synchronous)
            balance = get_account_balance_sync(account['id'], institute['id'])
            
            # Get recent transactions (synchronous)
            transactions = get_account_transactions_sync(account['id'], institute['id'], limit=5)
            
            liabilities.append({
                'id': account['id'],
                'account_code': account['account_code'],
                'account_name': account['account_name'],
                'description': account.get('description', ''),
                'current_balance': balance,
                'is_active': account.get('is_active', True),
                'recent_transactions': transactions
            })
        
        total_liabilities = sum(liability['current_balance'] for liability in liabilities)
        
        return jsonify({
            'success': True,
            'liabilities': liabilities,
            'total_liabilities': total_liabilities
        })
        
    except Exception as e:
        print(f"Error getting liabilities: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


@accounts_bp.route('/liabilities/create', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def create_liability():
    """Create a new liability account or record liability transaction"""
    institute = get_institute_from_session()
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        
        # Check if we're creating a new liability account
        if data.get('create_new_account'):
            # Create new liability account
            account_data = {
                'id': str(uuid.uuid4()),
                'institute_id': institute['id'],
                'account_code': generate_account_code(institute['id'], 'liability'),
                'account_name': data.get('account_name', '').strip(),
                'account_type': 'liability',
                'description': data.get('description', ''),
                'is_active': True,
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }
            
            if not account_data['account_name']:
                return jsonify({'success': False, 'message': 'Account name is required'}), 400
            
            result = supabase.table('chart_of_accounts').insert(account_data).execute()
            
            if result.data:
                # If initial balance is provided, record as opening balance
                if data.get('initial_balance', 0) > 0:
                    record_liability_transaction_sync(
                        result.data[0]['id'],
                        institute['id'],
                        data['initial_balance'],
                        'credit',
                        'Opening Balance',
                        data.get('start_date', datetime.now().date().isoformat()),
                        data.get('notes', 'Initial liability balance')
                    )
                
                return jsonify({
                    'success': True,
                    'message': 'Liability account created successfully',
                    'liability': result.data[0]
                })
            else:
                return jsonify({'success': False, 'message': 'Failed to create liability account'}), 500
        
        else:
            # Record liability transaction (loan taken, payment made)
            return record_liability_transaction_api_sync(institute['id'], data)
            
    except Exception as e:
        print(f"Error creating liability: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


# ============ SYNCHRONOUS HELPER FUNCTIONS ============

def get_account_balance_sync(account_id, institute_id):
    """Calculate current balance for an account (synchronous version)"""
    try:
        total_debits = 0
        total_credits = 0
        
        # Check asset transactions table
        try:
            asset_tx_response = supabase.table('asset_transactions')\
                .select('amount, transaction_type')\
                .eq('account_id', account_id)\
                .eq('institute_id', institute_id)\
                .execute()
            
            for tx in (asset_tx_response.data or []):
                if tx['transaction_type'] == 'debit':
                    total_debits += float(tx['amount'])
                else:
                    total_credits += float(tx['amount'])
        except Exception as e:
            print(f"Error checking asset transactions: {e}")
        
        # Check liability transactions table
        try:
            liability_tx_response = supabase.table('liability_transactions')\
                .select('amount, transaction_type')\
                .eq('account_id', account_id)\
                .eq('institute_id', institute_id)\
                .execute()
            
            for tx in (liability_tx_response.data or []):
                if tx['transaction_type'] == 'debit':
                    total_debits += float(tx['amount'])
                else:
                    total_credits += float(tx['amount'])
        except Exception as e:
            print(f"Error checking liability transactions: {e}")
        
        # Get account type
        account_response = supabase.table('chart_of_accounts')\
            .select('account_type')\
            .eq('id', account_id)\
            .execute()
        
        if account_response.data:
            account_type = account_response.data[0]['account_type']
            if account_type == 'liability':
                # For liabilities, credit balance is positive
                return total_credits - total_debits
            else:
                # For assets, debit balance is positive
                return total_debits - total_credits
        
        return total_debits - total_credits
        
    except Exception as e:
        print(f"Error calculating account balance: {e}")
        return 0


def get_account_transactions_sync(account_id, institute_id, limit=50):
    """Get all transactions for a specific account (synchronous version)"""
    transactions = []
    
    try:
        # Check asset transactions
        try:
            asset_tx_response = supabase.table('asset_transactions')\
                .select('*')\
                .eq('account_id', account_id)\
                .eq('institute_id', institute_id)\
                .order('transaction_date', desc=True)\
                .limit(limit)\
                .execute()
            
            for tx in (asset_tx_response.data or []):
                transactions.append({
                    'id': tx['id'],
                    'date': tx['transaction_date'],
                    'type': tx['transaction_type'],
                    'amount': float(tx['amount']),
                    'description': tx.get('description', ''),
                    'reference': tx.get('reference_number', ''),
                    'source': 'asset_transaction'
                })
        except Exception as e:
            print(f"Error getting asset transactions: {e}")
        
        # Check liability transactions
        try:
            liability_tx_response = supabase.table('liability_transactions')\
                .select('*')\
                .eq('account_id', account_id)\
                .eq('institute_id', institute_id)\
                .order('transaction_date', desc=True)\
                .limit(limit)\
                .execute()
            
            for tx in (liability_tx_response.data or []):
                transactions.append({
                    'id': tx['id'],
                    'date': tx['transaction_date'],
                    'type': tx['transaction_type'],
                    'amount': float(tx['amount']),
                    'description': tx.get('description', ''),
                    'reference': tx.get('reference_number', ''),
                    'source': 'liability_transaction'
                })
        except Exception as e:
            print(f"Error getting liability transactions: {e}")
        
        # Sort by date
        transactions.sort(key=lambda x: x['date'], reverse=True)
        
        return transactions[:limit]
        
    except Exception as e:
        print(f"Error getting account transactions: {e}")
        return []


def record_asset_transaction_sync(account_id, institute_id, amount, transaction_type, description, date, notes=''):
    """Helper function to record asset transactions (synchronous version)"""
    transaction_data = {
        'id': str(uuid.uuid4()),
        'account_id': account_id,
        'institute_id': institute_id,
        'amount': amount,
        'transaction_type': transaction_type,
        'description': description,
        'notes': notes,
        'transaction_date': date,
        'reference_number': f'AST-{datetime.now().strftime("%Y%m%d%H%M%S")}',
        'created_at': datetime.now().isoformat(),
        'updated_at': datetime.now().isoformat()
    }
    
    result = supabase.table('asset_transactions').insert(transaction_data).execute()
    return result.data[0] if result.data else None


def record_liability_transaction_sync(account_id, institute_id, amount, transaction_type, description, date, notes='', reference=''):
    """Helper function to record liability transactions (synchronous version)"""
    transaction_data = {
        'id': str(uuid.uuid4()),
        'account_id': account_id,
        'institute_id': institute_id,
        'amount': amount,
        'transaction_type': transaction_type,
        'description': description,
        'notes': notes,
        'transaction_date': date,
        'reference_number': reference or f'LIA-{datetime.now().strftime("%Y%m%d%H%M%S")}',
        'created_at': datetime.now().isoformat(),
        'updated_at': datetime.now().isoformat()
    }
    
    result = supabase.table('liability_transactions').insert(transaction_data).execute()
    return result.data[0] if result.data else None


def record_asset_transaction_api_sync(institute_id, data):
    """Record asset transaction from API (synchronous version)"""
    transaction_data = {
        'id': str(uuid.uuid4()),
        'account_id': data.get('account_id'),
        'institute_id': institute_id,
        'amount': float(data.get('amount', 0)),
        'transaction_type': data.get('transaction_type', 'debit'),
        'description': data.get('description', ''),
        'notes': data.get('notes', ''),
        'transaction_date': data.get('transaction_date', datetime.now().date().isoformat()),
        'reference_number': data.get('reference_number', f'AST-{datetime.now().strftime("%Y%m%d%H%M%S")}'),
        'created_at': datetime.now().isoformat(),
        'updated_at': datetime.now().isoformat()
    }
    
    if transaction_data['amount'] <= 0:
        return jsonify({'success': False, 'message': 'Invalid amount'}), 400
    
    result = supabase.table('asset_transactions').insert(transaction_data).execute()
    
    if result.data:
        return jsonify({
            'success': True,
            'message': 'Asset transaction recorded successfully',
            'transaction': result.data[0]
        })
    else:
        return jsonify({'success': False, 'message': 'Failed to record transaction'}), 500


def record_liability_transaction_api_sync(institute_id, data):
    """Record liability transaction from API (synchronous version)"""
    transaction_data = {
        'id': str(uuid.uuid4()),
        'account_id': data.get('account_id'),
        'institute_id': institute_id,
        'amount': float(data.get('amount', 0)),
        'transaction_type': data.get('transaction_type', 'credit'),
        'description': data.get('description', ''),
        'notes': data.get('notes', ''),
        'transaction_date': data.get('transaction_date', datetime.now().date().isoformat()),
        'reference_number': data.get('reference_number', f'LIA-{datetime.now().strftime("%Y%m%d%H%M%S")}'),
        'created_at': datetime.now().isoformat(),
        'updated_at': datetime.now().isoformat()
    }
    
    if transaction_data['amount'] <= 0:
        return jsonify({'success': False, 'message': 'Invalid amount'}), 400
    
    result = supabase.table('liability_transactions').insert(transaction_data).execute()
    
    if result.data:
        return jsonify({
            'success': True,
            'message': 'Liability transaction recorded successfully',
            'transaction': result.data[0]
        })
    else:
        return jsonify({'success': False, 'message': 'Failed to record transaction'}), 500
    
    
    
    
# Add these expense management endpoints to your accounts.py

@accounts_bp.route('/expense/update/<expense_id>', methods=['PUT'])
@role_required(['owner', 'teacher', 'accountant'])
def update_expense(expense_id):
    """Update an existing expense transaction"""
    institute = get_institute_from_session()
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        
        # First, verify the expense exists and belongs to this institute
        check_response = supabase.table('expense_transactions')\
            .select('*')\
            .eq('id', expense_id)\
            .eq('institute_id', institute['id'])\
            .execute()
        
        if not check_response.data:
            return jsonify({'success': False, 'message': 'Expense not found or access denied'}), 404
        
        # Prepare update data
        update_data = {
            'account_id': data.get('account_id'),
            'amount': float(data.get('amount', 0)),
            'transaction_date': data.get('transaction_date'),
            'payment_method': data.get('payment_method'),
            'reference_number': data.get('reference_number', ''),
            'description': data.get('description', ''),
            'vendor': data.get('vendor', ''),
            'updated_at': datetime.now().isoformat()
        }
        
        if update_data['amount'] <= 0:
            return jsonify({'success': False, 'message': 'Invalid amount'}), 400
        
        # Update the expense
        result = supabase.table('expense_transactions')\
            .update(update_data)\
            .eq('id', expense_id)\
            .eq('institute_id', institute['id'])\
            .execute()
        
        if result.data:
            return jsonify({
                'success': True,
                'message': 'Expense updated successfully',
                'expense': result.data[0]
            })
        else:
            return jsonify({'success': False, 'message': 'Failed to update expense'}), 500
            
    except Exception as e:
        print(f"Error updating expense: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@accounts_bp.route('/expense/delete/<expense_id>', methods=['DELETE'])
@role_required(['owner', 'teacher', 'accountant'])
def delete_expense(expense_id):
    """Delete an expense transaction"""
    institute = get_institute_from_session()
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Verify the expense exists and belongs to this institute
        check_response = supabase.table('expense_transactions')\
            .select('*')\
            .eq('id', expense_id)\
            .eq('institute_id', institute['id'])\
            .execute()
        
        if not check_response.data:
            return jsonify({'success': False, 'message': 'Expense not found or access denied'}), 404
        
        # Delete the expense
        result = supabase.table('expense_transactions')\
            .delete()\
            .eq('id', expense_id)\
            .eq('institute_id', institute['id'])\
            .execute()
        
        if result.data:
            return jsonify({
                'success': True,
                'message': 'Expense deleted successfully'
            })
        else:
            return jsonify({'success': False, 'message': 'Failed to delete expense'}), 500
            
    except Exception as e:
        print(f"Error deleting expense: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@accounts_bp.route('/expense/<expense_id>', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_expense(expense_id):
    """Get a single expense transaction by ID"""
    institute = get_institute_from_session()
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        response = supabase.table('expense_transactions')\
            .select('*, chart_of_accounts(account_name, account_code)')\
            .eq('id', expense_id)\
            .eq('institute_id', institute['id'])\
            .execute()
        
        if not response.data:
            return jsonify({'success': False, 'message': 'Expense not found'}), 404
        
        expense = response.data[0]
        
        # Format the response
        result = {
            'id': expense['id'],
            'account_id': expense['account_id'],
            'account_name': expense['chart_of_accounts']['account_name'] if expense.get('chart_of_accounts') else 'N/A',
            'account_code': expense['chart_of_accounts']['account_code'] if expense.get('chart_of_accounts') else 'N/A',
            'amount': float(expense['amount']),
            'transaction_date': expense['transaction_date'],
            'payment_method': expense['payment_method'],
            'reference_number': expense.get('reference_number', ''),
            'description': expense.get('description', ''),
            'vendor': expense.get('vendor', ''),
            'created_at': expense['created_at'],
            'updated_at': expense['updated_at']
        }
        
        return jsonify({
            'success': True,
            'expense': result
        })
        
    except Exception as e:
        print(f"Error getting expense: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500