# profitLossAndBalanceSheet.py - Financial Reports Module
# This module handles Profit & Loss, Balance Sheet, and Trial Balance reports
# with dynamic drill-down capabilities for transaction details

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
import traceback

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Create blueprint with unique name to avoid conflicts
financial_reports_bp = Blueprint('financial_reports', __name__, url_prefix='/financial-reports')

# Import role_required from auth (not permissions)
from routes.auth.auth import role_required
from routes.accounts.accounts import get_institute_id

# ==========================================
# HELPER FUNCTIONS
# ==========================================

def get_institute_from_session(return_id_only=False):
    """Get institute details from current session - handles both owners and employees"""
    user = session.get('user')
    if not user:
        print("No user in session")
        return None
    
    # Use the existing get_institute_id function
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return None
    
    if return_id_only:
        return institute_id
    
    try:
        response = supabase.table('institutes')\
            .select('*')\
            .eq('id', institute_id)\
            .execute()
        
        if response.data and len(response.data) > 0:
            return response.data[0]
        return None
    except Exception as e:
        print(f"Error fetching institute details: {e}")
        return None

def parse_date(date_str):
    """Parse date string to date object"""
    if not date_str:
        return None
    try:
        if isinstance(date_str, datetime):
            return date_str.date()
        if 'T' in date_str:
            return datetime.fromisoformat(date_str.replace('Z', '+00:00')).date()
        return datetime.strptime(date_str, '%Y-%m-%d').date()
    except:
        return None

def format_currency(amount):
    """Format amount as currency"""
    try:
        return f"{float(amount):,.2f}"
    except:
        return f"{0:,.2f}"

# ==========================================
# PAGE ROUTES
# ==========================================

@financial_reports_bp.route('/')
@role_required(['owner', 'teacher', 'accountant'])
def index():
    """Financial Reports Dashboard"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    institute = get_institute_from_session()
    
    if not institute:
        return render_template('financialreports/index.html', institute=None)
    
    available_years = get_available_years(institute_id)
    
    return render_template('financialreports/index.html', 
                         institute=institute,
                         available_years=available_years)

@financial_reports_bp.route('/profit-loss')
@role_required(['owner', 'teacher', 'accountant'])
def profit_loss_page():
    """Profit & Loss Statement Page"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    institute = get_institute_from_session()
    
    if not institute:
        return render_template('financialreports/profit_loss.html', institute=None)
    
    available_years = get_available_years(institute_id)
    
    return render_template('financialreports/profit_loss.html',
                         institute=institute,
                         available_years=available_years)

@financial_reports_bp.route('/balance-sheet')
@role_required(['owner', 'teacher', 'accountant'])
def balance_sheet_page():
    """Balance Sheet Page"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    institute = get_institute_from_session()
    
    if not institute:
        return render_template('financialreports/balance_sheet.html', institute=None)
    
    available_years = get_available_years(institute_id)
    
    return render_template('financialreports/balance_sheet.html',
                         institute=institute,
                         available_years=available_years)

@financial_reports_bp.route('/trial-balance')
@role_required(['owner', 'teacher', 'accountant'])
def trial_balance_page():
    """Trial Balance Page"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    institute = get_institute_from_session()
    
    if not institute:
        return render_template('financialreports/trial_balance.html', institute=None)
    
    available_years = get_available_years(institute_id)
    
    return render_template('financialreports/trial_balance.html',
                         institute=institute,
                         available_years=available_years)

# ==========================================
# DATA RETRIEVAL FUNCTIONS
# ==========================================

def get_available_years(institute_id):
    """Get available years for filtering"""
    years = []
    current_year = datetime.now().year
    
    # Check payments table
    try:
        response = supabase.table('payments')\
            .select('payment_date')\
            .eq('institute_id', institute_id)\
            .order('payment_date')\
            .execute()
        
        for item in (response.data or []):
            date = parse_date(item.get('payment_date'))
            if date and date.year not in years:
                years.append(date.year)
    except:
        pass
    
    # Check income_transactions
    try:
        response = supabase.table('income_transactions')\
            .select('transaction_date')\
            .eq('institute_id', institute_id)\
            .order('transaction_date')\
            .execute()
        
        for item in (response.data or []):
            date = parse_date(item.get('transaction_date'))
            if date and date.year not in years:
                years.append(date.year)
    except:
        pass
    
    # Check expense_transactions
    try:
        response = supabase.table('expense_transactions')\
            .select('transaction_date')\
            .eq('institute_id', institute_id)\
            .order('transaction_date')\
            .execute()
        
        for item in (response.data or []):
            date = parse_date(item.get('transaction_date'))
            if date and date.year not in years:
                years.append(date.year)
    except:
        pass
    
    # Check asset_transactions
    try:
        response = supabase.table('asset_transactions')\
            .select('transaction_date')\
            .eq('institute_id', institute_id)\
            .order('transaction_date')\
            .execute()
        
        for item in (response.data or []):
            date = parse_date(item.get('transaction_date'))
            if date and date.year not in years:
                years.append(date.year)
    except:
        pass
    
    # Check liability_transactions
    try:
        response = supabase.table('liability_transactions')\
            .select('transaction_date')\
            .eq('institute_id', institute_id)\
            .order('transaction_date')\
            .execute()
        
        for item in (response.data or []):
            date = parse_date(item.get('transaction_date'))
            if date and date.year not in years:
                years.append(date.year)
    except:
        pass
    
    if not years:
        years = [current_year]
    
    return sorted(years)

# Replace the get_revenue_data and get_expense_data functions with these updated versions

def get_revenue_data(institute_id, start_date, end_date):
    """Get revenue data for the period with proper account details"""
    revenue = []
    total_revenue = 0
    
    # Get school fees payments - these are a separate income source
    try:
        payments_response = supabase.table('payments')\
            .select('*, students(name)')\
            .eq('institute_id', institute_id)\
            .execute()
        
        for payment in (payments_response.data or []):
            payment_date = parse_date(payment.get('payment_date'))
            if payment_date and start_date <= payment_date <= end_date:
                amount = float(payment.get('amount', 0))
                total_revenue += amount
                revenue.append({
                    'id': payment.get('id'),
                    'account_id': 'school_fees',  # Special identifier for school fees
                    'date': payment_date.isoformat(),
                    'description': f"Fees from {payment.get('students', {}).get('name', 'Student')}",
                    'amount': amount,
                    'category': 'School Fees',
                    'account_name': 'School Fees Collection',
                    'account_code': 'INC-SF',
                    'type': 'revenue',
                    'reference': payment.get('receipt_number', ''),
                    'source': 'payments'
                })
    except Exception as e:
        print(f"Error getting payments: {e}")
    
    # Get other income transactions from the chart of accounts
    try:
        # First get all income accounts
        accounts_response = supabase.table('chart_of_accounts')\
            .select('id, account_name, account_code')\
            .eq('institute_id', institute_id)\
            .eq('account_type', 'income')\
            .eq('is_active', True)\
            .execute()
        
        income_accounts = {acc['id']: acc for acc in (accounts_response.data or [])}
        
        # Get income transactions
        income_response = supabase.table('income_transactions')\
            .select('*, chart_of_accounts(account_name, account_code)')\
            .eq('institute_id', institute_id)\
            .execute()
        
        for income in (income_response.data or []):
            income_date = parse_date(income.get('transaction_date'))
            if income_date and start_date <= income_date <= end_date:
                amount = float(income.get('amount', 0))
                total_revenue += amount
                account_id = income.get('account_id')
                account = income_accounts.get(account_id, {})
                
                revenue.append({
                    'id': income.get('id'),
                    'account_id': account_id,
                    'date': income_date.isoformat(),
                    'description': income.get('description', account.get('account_name', 'Other Income')),
                    'amount': amount,
                    'category': account.get('account_name', 'Other Income'),
                    'account_name': account.get('account_name', 'Other Income'),
                    'account_code': account.get('account_code', 'INC'),
                    'type': 'revenue',
                    'reference': income.get('reference_number', ''),
                    'source': 'income_transactions'
                })
    except Exception as e:
        print(f"Error getting income transactions: {e}")
    
    return revenue, total_revenue

def get_expense_data(institute_id, start_date, end_date):
    """Get expense data for the period with proper account details"""
    expenses = []
    total_expenses = 0
    
    try:
        # First get all expense accounts
        accounts_response = supabase.table('chart_of_accounts')\
            .select('id, account_name, account_code')\
            .eq('institute_id', institute_id)\
            .eq('account_type', 'expense')\
            .eq('is_active', True)\
            .execute()
        
        expense_accounts = {acc['id']: acc for acc in (accounts_response.data or [])}
        
        # Get expense transactions
        expense_response = supabase.table('expense_transactions')\
            .select('*, chart_of_accounts(account_name, account_code)')\
            .eq('institute_id', institute_id)\
            .execute()
        
        for expense in (expense_response.data or []):
            expense_date = parse_date(expense.get('transaction_date'))
            if expense_date and start_date <= expense_date <= end_date:
                amount = float(expense.get('amount', 0))
                total_expenses += amount
                account_id = expense.get('account_id')
                account = expense_accounts.get(account_id, {})
                
                expenses.append({
                    'id': expense.get('id'),
                    'account_id': account_id,
                    'date': expense_date.isoformat(),
                    'description': expense.get('description', account.get('account_name', 'Other Expense')),
                    'amount': amount,
                    'category': account.get('account_name', 'Other Expense'),
                    'account_name': account.get('account_name', 'Other Expense'),
                    'account_code': account.get('account_code', 'EXP'),
                    'type': 'expense',
                    'reference': expense.get('reference_number', ''),
                    'source': 'expense_transactions'
                })
    except Exception as e:
        print(f"Error getting expenses: {e}")
    
    return expenses, total_expenses

def get_asset_data(institute_id, as_of_date):
    """Get asset data as of a specific date"""
    assets = []
    total_assets = 0
    
    try:
        # Get all asset accounts
        accounts_response = supabase.table('chart_of_accounts')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .eq('account_type', 'asset')\
            .eq('is_active', True)\
            .execute()
        
        for account in (accounts_response.data or []):
            # Calculate balance as of the date
            balance = calculate_account_balance_as_of(account['id'], institute_id, as_of_date)
            
            if balance != 0:
                total_assets += balance
                assets.append({
                    'id': account['id'],
                    'account_code': account['account_code'],
                    'account_name': account['account_name'],
                    'description': account.get('description', ''),
                    'balance': balance,
                    'type': 'asset'
                })
    except Exception as e:
        print(f"Error getting assets: {e}")
    
    return assets, total_assets

def get_liability_data(institute_id, as_of_date):
    """Get liability data as of a specific date"""
    liabilities = []
    total_liabilities = 0
    
    try:
        # Get all liability accounts
        accounts_response = supabase.table('chart_of_accounts')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .eq('account_type', 'liability')\
            .eq('is_active', True)\
            .execute()
        
        for account in (accounts_response.data or []):
            # Calculate balance as of the date
            balance = calculate_account_balance_as_of(account['id'], institute_id, as_of_date)
            
            if balance != 0:
                total_liabilities += balance
                liabilities.append({
                    'id': account['id'],
                    'account_code': account['account_code'],
                    'account_name': account['account_name'],
                    'description': account.get('description', ''),
                    'balance': balance,
                    'type': 'liability'
                })
    except Exception as e:
        print(f"Error getting liabilities: {e}")
    
    return liabilities, total_liabilities

def get_equity_data(institute_id, as_of_date):
    """Get equity data as of a specific date"""
    equity = []
    total_equity = 0
    
    try:
        # Get all equity accounts
        accounts_response = supabase.table('chart_of_accounts')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .eq('account_type', 'equity')\
            .eq('is_active', True)\
            .execute()
        
        for account in (accounts_response.data or []):
            # Calculate balance as of the date
            balance = calculate_account_balance_as_of(account['id'], institute_id, as_of_date)
            
            if balance != 0:
                total_equity += balance
                equity.append({
                    'id': account['id'],
                    'account_code': account['account_code'],
                    'account_name': account['account_name'],
                    'description': account.get('description', ''),
                    'balance': balance,
                    'type': 'equity'
                })
    except Exception as e:
        print(f"Error getting equity: {e}")
    
    return equity, total_equity

def calculate_account_balance_as_of(account_id, institute_id, as_of_date):
    """Calculate account balance as of a specific date"""
    try:
        total_debits = 0
        total_credits = 0
        
        # Check asset transactions
        try:
            response = supabase.table('asset_transactions')\
                .select('amount, transaction_type')\
                .eq('account_id', account_id)\
                .eq('institute_id', institute_id)\
                .lte('transaction_date', as_of_date.isoformat())\
                .execute()
            
            for tx in (response.data or []):
                if tx['transaction_type'] == 'debit':
                    total_debits += float(tx['amount'])
                else:
                    total_credits += float(tx['amount'])
        except:
            pass
        
        # Check liability transactions
        try:
            response = supabase.table('liability_transactions')\
                .select('amount, transaction_type')\
                .eq('account_id', account_id)\
                .eq('institute_id', institute_id)\
                .lte('transaction_date', as_of_date.isoformat())\
                .execute()
            
            for tx in (response.data or []):
                if tx['transaction_type'] == 'debit':
                    total_debits += float(tx['amount'])
                else:
                    total_credits += float(tx['amount'])
        except:
            pass
        
        # Check income transactions (credits)
        try:
            response = supabase.table('income_transactions')\
                .select('amount')\
                .eq('account_id', account_id)\
                .eq('institute_id', institute_id)\
                .lte('transaction_date', as_of_date.isoformat())\
                .execute()
            
            for tx in (response.data or []):
                total_credits += float(tx['amount'])
        except:
            pass
        
        # Check expense transactions (debits)
        try:
            response = supabase.table('expense_transactions')\
                .select('amount')\
                .eq('account_id', account_id)\
                .eq('institute_id', institute_id)\
                .lte('transaction_date', as_of_date.isoformat())\
                .execute()
            
            for tx in (response.data or []):
                total_debits += float(tx['amount'])
        except:
            pass
        
        # Check payments (credits)
        try:
            response = supabase.table('payments')\
                .select('amount')\
                .eq('institute_id', institute_id)\
                .lte('payment_date', as_of_date.isoformat())\
                .execute()
            
            for tx in (response.data or []):
                total_credits += float(tx['amount'])
        except:
            pass
        
        # Get account type
        account_response = supabase.table('chart_of_accounts')\
            .select('account_type')\
            .eq('id', account_id)\
            .execute()
        
        if account_response.data:
            account_type = account_response.data[0]['account_type']
            if account_type in ['liability', 'equity', 'income']:
                # For liabilities, equity, and income, credit balance is positive
                return total_credits - total_debits
            else:
                # For assets and expenses, debit balance is positive
                return total_debits - total_credits
        
        return total_debits - total_credits
        
    except Exception as e:
        print(f"Error calculating account balance: {e}")
        return 0

def get_transaction_details(entry_id, source_table, institute_id):
    """Get detailed transaction information for drill-down"""
    try:
        if source_table == 'payments':
            response = supabase.table('payments')\
                .select('*, students(name, class)')\
                .eq('id', entry_id)\
                .eq('institute_id', institute_id)\
                .execute()
        elif source_table == 'income_transactions':
            response = supabase.table('income_transactions')\
                .select('*, chart_of_accounts(account_name, account_code)')\
                .eq('id', entry_id)\
                .eq('institute_id', institute_id)\
                .execute()
        elif source_table == 'expense_transactions':
            response = supabase.table('expense_transactions')\
                .select('*, chart_of_accounts(account_name, account_code)')\
                .eq('id', entry_id)\
                .eq('institute_id', institute_id)\
                .execute()
        elif source_table == 'asset_transactions':
            response = supabase.table('asset_transactions')\
                .select('*, chart_of_accounts(account_name, account_code)')\
                .eq('id', entry_id)\
                .eq('institute_id', institute_id)\
                .execute()
        elif source_table == 'liability_transactions':
            response = supabase.table('liability_transactions')\
                .select('*, chart_of_accounts(account_name, account_code)')\
                .eq('id', entry_id)\
                .eq('institute_id', institute_id)\
                .execute()
        else:
            return None
        
        if response.data:
            return response.data[0]
        return None
    except Exception as e:
        print(f"Error getting transaction details: {e}")
        return None

def get_trial_balance_data(institute_id, as_of_date):
    """Get trial balance data as of a specific date"""
    accounts = []
    total_debits = 0
    total_credits = 0
    
    try:
        # Get all active accounts
        accounts_response = supabase.table('chart_of_accounts')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .eq('is_active', True)\
            .order('account_type')\
            .order('account_name')\
            .execute()
        
        for account in (accounts_response.data or []):
            # Calculate balance as of the date
            balance = calculate_account_balance_as_of(account['id'], institute_id, as_of_date)
            
            if balance != 0:
                account_data = {
                    'account_id': account['id'],
                    'account_code': account['account_code'],
                    'account_name': account['account_name'],
                    'account_type': account['account_type'],
                    'debit': 0,
                    'credit': 0
                }
                
                # Determine if balance is debit or credit based on account type
                if account['account_type'] in ['asset', 'expense']:
                    # Asset and expense accounts normally have debit balances
                    if balance > 0:
                        account_data['debit'] = balance
                        total_debits += balance
                    else:
                        account_data['credit'] = abs(balance)
                        total_credits += abs(balance)
                else:
                    # Liability, equity, and income accounts normally have credit balances
                    if balance > 0:
                        account_data['credit'] = balance
                        total_credits += balance
                    else:
                        account_data['debit'] = abs(balance)
                        total_debits += abs(balance)
                
                accounts.append(account_data)
        
        # Sort accounts: assets, liabilities, equity, income, expenses
        type_order = {'asset': 0, 'liability': 1, 'equity': 2, 'income': 3, 'expense': 4}
        accounts.sort(key=lambda x: type_order.get(x['account_type'], 5))
        
        is_balanced = abs(total_debits - total_credits) < 0.01
        
        return {
            'accounts': accounts,
            'totals': {
                'debits': total_debits,
                'credits': total_credits,
                'is_balanced': is_balanced,
                'difference': abs(total_debits - total_credits)
            }
        }
        
    except Exception as e:
        print(f"Error getting trial balance: {e}")
        traceback.print_exc()
        return {
            'accounts': [],
            'totals': {
                'debits': 0,
                'credits': 0,
                'is_balanced': True,
                'difference': 0
            }
        }

def get_account_transactions_for_period(account_id, institute_id, start_date, end_date):
    """Get all transactions for a specific account within a date range"""
    transactions = []
    
    try:
        account_response = supabase.table('chart_of_accounts')\
            .select('account_type')\
            .eq('id', account_id)\
            .execute()
        
        if not account_response.data:
            return transactions
        
        account_type = account_response.data[0]['account_type']
        
        # For asset accounts
        if account_type == 'asset':
            response = supabase.table('asset_transactions')\
                .select('*')\
                .eq('account_id', account_id)\
                .eq('institute_id', institute_id)\
                .gte('transaction_date', start_date.isoformat())\
                .lte('transaction_date', end_date.isoformat())\
                .order('transaction_date')\
                .execute()
            
            for tx in (response.data or []):
                transactions.append({
                    'id': tx['id'],
                    'date': tx['transaction_date'],
                    'type': tx['transaction_type'],
                    'amount': float(tx['amount']),
                    'description': tx.get('description', ''),
                    'reference': tx.get('reference_number', ''),
                    'source': 'asset_transactions'
                })
        
        # For liability accounts
        elif account_type == 'liability':
            response = supabase.table('liability_transactions')\
                .select('*')\
                .eq('account_id', account_id)\
                .eq('institute_id', institute_id)\
                .gte('transaction_date', start_date.isoformat())\
                .lte('transaction_date', end_date.isoformat())\
                .order('transaction_date')\
                .execute()
            
            for tx in (response.data or []):
                transactions.append({
                    'id': tx['id'],
                    'date': tx['transaction_date'],
                    'type': tx['transaction_type'],
                    'amount': float(tx['amount']),
                    'description': tx.get('description', ''),
                    'reference': tx.get('reference_number', ''),
                    'source': 'liability_transactions'
                })
        
        # For income accounts
        elif account_type == 'income':
            # Get income transactions
            response = supabase.table('income_transactions')\
                .select('*')\
                .eq('account_id', account_id)\
                .eq('institute_id', institute_id)\
                .gte('transaction_date', start_date.isoformat())\
                .lte('transaction_date', end_date.isoformat())\
                .order('transaction_date')\
                .execute()
            
            for tx in (response.data or []):
                transactions.append({
                    'id': tx['id'],
                    'date': tx['transaction_date'],
                    'type': 'credit',
                    'amount': float(tx['amount']),
                    'description': tx.get('description', ''),
                    'reference': tx.get('reference_number', ''),
                    'source': 'income_transactions'
                })
            
            # Also get payments (school fees are income)
            payments_response = supabase.table('payments')\
                .select('*, students(name)')\
                .eq('institute_id', institute_id)\
                .gte('payment_date', start_date.isoformat())\
                .lte('payment_date', end_date.isoformat())\
                .order('payment_date')\
                .execute()
            
            for tx in (payments_response.data or []):
                transactions.append({
                    'id': tx['id'],
                    'date': tx['payment_date'],
                    'type': 'credit',
                    'amount': float(tx['amount']),
                    'description': f"Fees from {tx.get('students', {}).get('name', 'Student')}",
                    'reference': tx.get('receipt_number', ''),
                    'source': 'payments'
                })
        
        # For expense accounts
        elif account_type == 'expense':
            response = supabase.table('expense_transactions')\
                .select('*')\
                .eq('account_id', account_id)\
                .eq('institute_id', institute_id)\
                .gte('transaction_date', start_date.isoformat())\
                .lte('transaction_date', end_date.isoformat())\
                .order('transaction_date')\
                .execute()
            
            for tx in (response.data or []):
                transactions.append({
                    'id': tx['id'],
                    'date': tx['transaction_date'],
                    'type': 'debit',
                    'amount': float(tx['amount']),
                    'description': tx.get('description', ''),
                    'reference': tx.get('reference_number', ''),
                    'source': 'expense_transactions'
                })
        
        # Sort by date
        transactions.sort(key=lambda x: x['date'])
        
        # Calculate running balance
        running_balance = 0
        for tx in transactions:
            if tx['type'] == 'debit':
                running_balance += tx['amount']
            else:
                running_balance -= tx['amount']
            tx['running_balance'] = running_balance
        
        return transactions
        
    except Exception as e:
        print(f"Error getting account transactions: {e}")
        return []

# ==========================================
# API ROUTES - PROFIT & LOSS
# ==========================================

@financial_reports_bp.route('/api/profit-loss', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def get_profit_loss_data():
    """Get Profit & Loss statement data with drill-down capability"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        start_date_str = data.get('start_date')
        end_date_str = data.get('end_date')
        
        if not start_date_str or not end_date_str:
            today = datetime.now()
            start_date = datetime(today.year, 1, 1).date()
            end_date = today.date()
        else:
            start_date = parse_date(start_date_str)
            end_date = parse_date(end_date_str)
        
        if not start_date or not end_date:
            return jsonify({'success': False, 'message': 'Invalid date range'}), 400
        
        # Get revenue data with proper account details
        revenue, total_revenue = get_revenue_data(institute_id, start_date, end_date)
        
        # Get expense data with proper account details
        expenses, total_expenses = get_expense_data(institute_id, start_date, end_date)
        
        # Calculate net income/loss
        net_income = total_revenue - total_expenses
        
        # Group revenue by account for display
        revenue_by_account = {}
        for item in revenue:
            account_id = item.get('account_id', 'unknown')
            if account_id not in revenue_by_account:
                revenue_by_account[account_id] = {
                    'account_id': account_id,
                    'account_name': item.get('account_name', 'Unknown'),
                    'account_code': item.get('account_code', 'N/A'),
                    'amount': 0,
                    'transactions': []
                }
            revenue_by_account[account_id]['amount'] += item['amount']
            revenue_by_account[account_id]['transactions'].append(item)
        
        # Group expenses by account for display
        expense_by_account = {}
        for item in expenses:
            account_id = item.get('account_id', 'unknown')
            if account_id not in expense_by_account:
                expense_by_account[account_id] = {
                    'account_id': account_id,
                    'account_name': item.get('account_name', 'Unknown'),
                    'account_code': item.get('account_code', 'N/A'),
                    'amount': 0,
                    'transactions': []
                }
            expense_by_account[account_id]['amount'] += item['amount']
            expense_by_account[account_id]['transactions'].append(item)
        
        # Prepare response
        income_details = []
        if total_revenue > 0:
            # Add total revenue summary first
            income_details.append({
                'account_id': 'revenue_total',
                'account_name': 'Total Revenue',
                'account_code': 'REV',
                'amount': total_revenue,
                'is_summary': True
            })
            
            # Add individual income accounts
            for account_id, data in revenue_by_account.items():
                # Skip school fees special case - it will be handled separately
                if account_id == 'school_fees':
                    income_details.append({
                        'account_id': 'school_fees',
                        'account_name': 'School Fees Collection',
                        'account_code': 'INC-SF',
                        'amount': data['amount'],
                        'is_summary': False,
                        'is_school_fees': True
                    })
                elif account_id and account_id != 'unknown':
                    income_details.append({
                        'account_id': account_id,
                        'account_name': data['account_name'],
                        'account_code': data['account_code'],
                        'amount': data['amount'],
                        'is_summary': False
                    })
        
        expense_details = []
        if total_expenses > 0:
            # Add total expenses summary first
            expense_details.append({
                'account_id': 'expense_total',
                'account_name': 'Total Expenses',
                'account_code': 'EXP',
                'amount': total_expenses,
                'is_summary': True
            })
            
            # Add individual expense accounts
            for account_id, data in expense_by_account.items():
                if account_id and account_id != 'unknown':
                    expense_details.append({
                        'account_id': account_id,
                        'account_name': data['account_name'],
                        'account_code': data['account_code'],
                        'amount': data['amount'],
                        'is_summary': False
                    })
        
        return jsonify({
            'success': True,
            'report': {
                'income': {
                    'total': total_revenue,
                    'details': income_details
                },
                'expenses': {
                    'total': total_expenses,
                    'details': expense_details
                },
                'net_profit_loss': net_income,
                'is_profit': net_income >= 0,
                'start_date': start_date.isoformat(),
                'end_date': end_date.isoformat()
            }
        })
        
    except Exception as e:
        print(f"Error getting profit & loss data: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

# ==========================================
# API ROUTES - TRIAL BALANCE
# ==========================================

@financial_reports_bp.route('/api/trial-balance', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def get_trial_balance():
    """Get Trial Balance data with drill-down capability"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        as_of_date_str = data.get('as_of_date')
        
        if not as_of_date_str:
            as_of_date = datetime.now().date()
        else:
            as_of_date = parse_date(as_of_date_str)
        
        if not as_of_date:
            return jsonify({'success': False, 'message': 'Invalid date'}), 400
        
        trial_balance = get_trial_balance_data(institute_id, as_of_date)
        
        return jsonify({
            'success': True,
            'report': {
                'accounts': trial_balance['accounts'],
                'totals': trial_balance['totals'],
                'as_of_date': as_of_date.isoformat()
            }
        })
        
    except Exception as e:
        print(f"Error getting trial balance: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

# ==========================================
# API ROUTES - BALANCE SHEET
# ==========================================

@financial_reports_bp.route('/api/balance-sheet', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def get_balance_sheet_data():
    """Get Balance Sheet data with drill-down capability"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        as_of_date_str = data.get('as_of_date')
        
        if not as_of_date_str:
            as_of_date = datetime.now().date()
        else:
            as_of_date = parse_date(as_of_date_str)
        
        if not as_of_date:
            return jsonify({'success': False, 'message': 'Invalid date'}), 400
        
        # Get ALL accounts from chart of accounts
        accounts_response = supabase.table('chart_of_accounts')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .eq('is_active', True)\
            .execute()
        
        all_accounts = accounts_response.data or []
        
        # Initialize collections
        assets = []
        liabilities = []
        equity = []
        
        total_assets = 0
        total_liabilities = 0
        total_equity = 0
        
        for account in all_accounts:
            # Calculate balance as of the date using the CORRECT method
            balance = calculate_balance_correct(account['id'], institute_id, as_of_date, account['account_type'])
            
            if balance == 0:
                continue
                
            account_info = {
                'id': account['id'],
                'account_code': account['account_code'],
                'account_name': account['account_name'],
                'description': account.get('description', ''),
                'balance': balance,
                'type': account['account_type']
            }
            
            if account['account_type'] == 'asset':
                assets.append(account_info)
                total_assets += balance
            elif account['account_type'] == 'liability':
                liabilities.append(account_info)
                total_liabilities += balance
            elif account['account_type'] == 'equity':
                equity.append(account_info)
                total_equity += balance
        
        # Calculate net income for the year to date
        year_start = datetime(as_of_date.year, 1, 1).date()
        revenue, total_revenue = get_revenue_data(institute_id, year_start, as_of_date)
        expenses, total_expenses = get_expense_data(institute_id, year_start, as_of_date)
        year_to_date_income = total_revenue - total_expenses
        
        # Add retained earnings to equity
        if year_to_date_income != 0:
            equity.append({
                'id': 'retained_earnings',
                'account_code': 'RE',
                'account_name': 'Retained Earnings (YTD)',
                'description': 'Year-to-date net income',
                'balance': year_to_date_income,
                'type': 'equity'
            })
            total_equity += year_to_date_income
        
        # Group assets by category (current vs non-current)
        current_assets = []
        non_current_assets = []
        current_assets_total = 0
        non_current_assets_total = 0
        
        for asset in assets:
            # Check if it's a current asset based on account name
            name_lower = asset['account_name'].lower()
            if any(keyword in name_lower for keyword in ['cash', 'bank', 'receivable', 'inventory', 'account receivable', 'debtor']):
                current_assets.append(asset)
                current_assets_total += asset['balance']
            else:
                non_current_assets.append(asset)
                non_current_assets_total += asset['balance']
        
        # Group liabilities by current vs non-current
        current_liabilities = []
        non_current_liabilities = []
        current_liabilities_total = 0
        non_current_liabilities_total = 0
        
        for liability in liabilities:
            name_lower = liability['account_name'].lower()
            if any(keyword in name_lower for keyword in ['payable', 'accrued', 'short', 'current', 'overdraft']):
                current_liabilities.append(liability)
                current_liabilities_total += liability['balance']
            else:
                non_current_liabilities.append(liability)
                non_current_liabilities_total += liability['balance']
        
        # Calculate working capital and ratios
        working_capital = current_assets_total - current_liabilities_total
        current_ratio = current_assets_total / current_liabilities_total if current_liabilities_total > 0 else 0
        
        return jsonify({
            'success': True,
            'report': {
                'as_of_date': as_of_date.isoformat(),
                'assets': {
                    'current': current_assets,
                    'current_total': current_assets_total,
                    'non_current': non_current_assets,
                    'non_current_total': non_current_assets_total,
                    'all': assets,
                    'total': total_assets
                },
                'liabilities': {
                    'current': current_liabilities,
                    'current_total': current_liabilities_total,
                    'non_current': non_current_liabilities,
                    'non_current_total': non_current_liabilities_total,
                    'all': liabilities,
                    'total': total_liabilities
                },
                'equity': {
                    'items': equity,
                    'total': total_equity
                },
                'ratios': {
                    'working_capital': working_capital,
                    'working_capital_formatted': format_currency(working_capital),
                    'current_ratio': round(current_ratio, 2)
                }
            }
        })
        
    except Exception as e:
        print(f"Error getting balance sheet data: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500
    
    
def calculate_balance_correct(account_id, institute_id, as_of_date, account_type):
    """
    Calculate the correct balance for an account as of a specific date.
    This properly handles the sign convention based on account type.
    """
    try:
        total_debits = 0
        total_credits = 0
        
        # 1. Check income_transactions (these are CREDITS for income accounts)
        try:
            response = supabase.table('income_transactions')\
                .select('amount')\
                .eq('account_id', account_id)\
                .eq('institute_id', institute_id)\
                .lte('transaction_date', as_of_date.isoformat())\
                .execute()
            
            for tx in (response.data or []):
                total_credits += float(tx['amount'])
        except Exception as e:
            print(f"Error getting income transactions: {e}")
        
        # 2. Check expense_transactions (these are DEBITS for expense accounts)
        try:
            response = supabase.table('expense_transactions')\
                .select('amount')\
                .eq('account_id', account_id)\
                .eq('institute_id', institute_id)\
                .lte('transaction_date', as_of_date.isoformat())\
                .execute()
            
            for tx in (response.data or []):
                total_debits += float(tx['amount'])
        except Exception as e:
            print(f"Error getting expense transactions: {e}")
        
        # 3. Check asset_transactions
        try:
            response = supabase.table('asset_transactions')\
                .select('amount, transaction_type')\
                .eq('account_id', account_id)\
                .eq('institute_id', institute_id)\
                .lte('transaction_date', as_of_date.isoformat())\
                .execute()
            
            for tx in (response.data or []):
                if tx['transaction_type'] == 'debit':
                    total_debits += float(tx['amount'])
                else:
                    total_credits += float(tx['amount'])
        except Exception as e:
            print(f"Error getting asset transactions: {e}")
        
        # 4. Check liability_transactions
        try:
            response = supabase.table('liability_transactions')\
                .select('amount, transaction_type')\
                .eq('account_id', account_id)\
                .eq('institute_id', institute_id)\
                .lte('transaction_date', as_of_date.isoformat())\
                .execute()
            
            for tx in (response.data or []):
                if tx['transaction_type'] == 'debit':
                    total_debits += float(tx['amount'])
                else:
                    total_credits += float(tx['amount'])
        except Exception as e:
            print(f"Error getting liability transactions: {e}")
        
        # 5. Check payments (these are CREDITS for income accounts, DEBITS for asset accounts)
        try:
            response = supabase.table('payments')\
                .select('amount')\
                .eq('institute_id', institute_id)\
                .lte('payment_date', as_of_date.isoformat())\
                .execute()
            
            for tx in (response.data or []):
                # Payments are income, so they are credits
                if account_type == 'asset':
                    total_debits += float(tx['amount'])
                else:
                    total_credits += float(tx['amount'])
        except Exception as e:
            print(f"Error getting payments: {e}")
        
        # Calculate the balance based on account type
        if account_type in ['asset', 'expense']:
            # Assets and Expenses: Debit - Credit (Debit balance normal)
            return total_debits - total_credits
        else:
            # Liabilities, Equity, Income: Credit - Debit (Credit balance normal)
            return total_credits - total_debits
        
    except Exception as e:
        print(f"Error in calculate_balance_correct: {e}")
        return 0
# ==========================================
# API ROUTES - ACCOUNT DETAIL
# ==========================================

@financial_reports_bp.route('/api/account-details/<account_id>', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def get_account_details(account_id):
    """Get detailed account transactions for drill-down"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        start_date_str = data.get('start_date')
        end_date_str = data.get('end_date')
        
        if not start_date_str or not end_date_str:
            today = datetime.now()
            start_date = datetime(today.year, 1, 1).date()
            end_date = today.date()
        else:
            start_date = parse_date(start_date_str)
            end_date = parse_date(end_date_str)
        
        if not start_date or not end_date:
            return jsonify({'success': False, 'message': 'Invalid date range'}), 400
        
        # Get account details
        account_response = supabase.table('chart_of_accounts')\
            .select('*')\
            .eq('id', account_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if not account_response.data:
            return jsonify({'success': False, 'message': 'Account not found'}), 404
        
        account = account_response.data[0]
        
        # Get transactions
        transactions = get_account_transactions_for_period(account_id, institute_id, start_date, end_date)
        
        # Calculate summary
        total_debits = sum(t['amount'] for t in transactions if t['type'] == 'debit')
        total_credits = sum(t['amount'] for t in transactions if t['type'] == 'credit')
        
        return jsonify({
            'success': True,
            'account': account,
            'transactions': transactions,
            'summary': {
                'total_debits': total_debits,
                'total_credits': total_credits,
                'total': sum(t['amount'] for t in transactions)
            },
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat()
        })
        
    except Exception as e:
        print(f"Error getting account details: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

# ==========================================
# API ROUTES - TRANSACTION DETAIL
# ==========================================

@financial_reports_bp.route('/api/transaction-detail/<entry_id>', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_transaction_detail(entry_id):
    """Get detailed transaction information for drill-down"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        source = request.args.get('source')
        if not source:
            return jsonify({'success': False, 'message': 'Source table is required'}), 400
        
        transaction = get_transaction_details(entry_id, source, institute_id)
        
        if not transaction:
            return jsonify({'success': False, 'message': 'Transaction not found'}), 404
        
        # Format the response based on source
        if source == 'payments':
            formatted = {
                'id': transaction['id'],
                'type': 'School Fees Payment',
                'student_name': transaction.get('students', {}).get('name', 'N/A'),
                'class': transaction.get('students', {}).get('class', 'N/A'),
                'amount': float(transaction['amount']),
                'date': transaction['payment_date'],
                'payment_method': transaction.get('payment_method', ''),
                'receipt_number': transaction.get('receipt_number', ''),
                'description': f"Fees payment from {transaction.get('students', {}).get('name', 'Student')}"
            }
        elif source == 'income_transactions':
            formatted = {
                'id': transaction['id'],
                'type': 'Other Income',
                'account_name': transaction.get('chart_of_accounts', {}).get('account_name', 'N/A'),
                'account_code': transaction.get('chart_of_accounts', {}).get('account_code', 'N/A'),
                'amount': float(transaction['amount']),
                'date': transaction['transaction_date'],
                'payment_method': transaction.get('payment_method', ''),
                'reference_number': transaction.get('reference_number', ''),
                'description': transaction.get('description', '')
            }
        elif source == 'expense_transactions':
            formatted = {
                'id': transaction['id'],
                'type': 'Expense',
                'account_name': transaction.get('chart_of_accounts', {}).get('account_name', 'N/A'),
                'account_code': transaction.get('chart_of_accounts', {}).get('account_code', 'N/A'),
                'amount': float(transaction['amount']),
                'date': transaction['transaction_date'],
                'payment_method': transaction.get('payment_method', ''),
                'reference_number': transaction.get('reference_number', ''),
                'description': transaction.get('description', ''),
                'vendor': transaction.get('vendor', '')
            }
        elif source == 'asset_transactions':
            formatted = {
                'id': transaction['id'],
                'type': 'Asset Transaction',
                'account_name': transaction.get('chart_of_accounts', {}).get('account_name', 'N/A'),
                'account_code': transaction.get('chart_of_accounts', {}).get('account_code', 'N/A'),
                'amount': float(transaction['amount']),
                'date': transaction['transaction_date'],
                'transaction_type': transaction.get('transaction_type', ''),
                'reference_number': transaction.get('reference_number', ''),
                'description': transaction.get('description', ''),
                'notes': transaction.get('notes', '')
            }
        elif source == 'liability_transactions':
            formatted = {
                'id': transaction['id'],
                'type': 'Liability Transaction',
                'account_name': transaction.get('chart_of_accounts', {}).get('account_name', 'N/A'),
                'account_code': transaction.get('chart_of_accounts', {}).get('account_code', 'N/A'),
                'amount': float(transaction['amount']),
                'date': transaction['transaction_date'],
                'transaction_type': transaction.get('transaction_type', ''),
                'reference_number': transaction.get('reference_number', ''),
                'description': transaction.get('description', ''),
                'notes': transaction.get('notes', '')
            }
        else:
            return jsonify({'success': False, 'message': 'Unsupported source table'}), 400
        
        return jsonify({
            'success': True,
            'transaction': formatted
        })
        
    except Exception as e:
        print(f"Error getting transaction detail: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

# ==========================================
# EXPORT ROUTES
# ==========================================

@financial_reports_bp.route('/api/export/profit-loss', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def export_profit_loss():
    """Export Profit & Loss statement to Excel or CSV"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        start_date_str = data.get('start_date')
        end_date_str = data.get('end_date')
        format_type = data.get('format', 'excel')
        
        if not start_date_str or not end_date_str:
            today = datetime.now()
            start_date = datetime(today.year, 1, 1).date()
            end_date = today.date()
        else:
            start_date = parse_date(start_date_str)
            end_date = parse_date(end_date_str)
        
        if not start_date or not end_date:
            return jsonify({'success': False, 'message': 'Invalid date range'}), 400
        
        # Get data
        revenue, total_revenue = get_revenue_data(institute_id, start_date, end_date)
        expenses, total_expenses = get_expense_data(institute_id, start_date, end_date)
        net_income = total_revenue - total_expenses
        
        # Create DataFrames
        revenue_df = pd.DataFrame(revenue) if revenue else pd.DataFrame(columns=['date', 'description', 'amount'])
        revenue_df['type'] = 'Revenue'
        
        expense_df = pd.DataFrame(expenses) if expenses else pd.DataFrame(columns=['date', 'description', 'amount'])
        expense_df['type'] = 'Expense'
        
        # Add summary rows
        revenue_summary = pd.DataFrame([{
            'date': '',
            'description': 'TOTAL REVENUE',
            'amount': total_revenue,
            'type': 'Summary'
        }])
        
        expense_summary = pd.DataFrame([{
            'date': '',
            'description': 'TOTAL EXPENSES',
            'amount': total_expenses,
            'type': 'Summary'
        }])
        
        net_summary = pd.DataFrame([{
            'date': '',
            'description': 'NET INCOME' + (' (LOSS)' if net_income < 0 else ''),
            'amount': net_income,
            'type': 'Summary'
        }])
        
        # Combine all
        all_data = pd.concat([revenue_df, revenue_summary, expense_df, expense_summary, net_summary], ignore_index=True)
        
        # Export
        output = io.BytesIO()
        
        if format_type == 'excel':
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                all_data.to_excel(writer, sheet_name='Profit_Loss', index=False)
                summary_data = {
                    'Metric': ['Start Date', 'End Date', 'Total Revenue', 'Total Expenses', 'Net Income'],
                    'Value': [start_date.isoformat(), end_date.isoformat(), total_revenue, total_expenses, net_income]
                }
                summary_df = pd.DataFrame(summary_data)
                summary_df.to_excel(writer, sheet_name='Summary', index=False)
            
            mimetype = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            filename = f"Profit_Loss_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}.xlsx"
        else:
            all_data.to_csv(output, index=False)
            mimetype = 'text/csv'
            filename = f"Profit_Loss_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}.csv"
        
        output.seek(0)
        
        return send_file(
            output,
            mimetype=mimetype,
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        print(f"Error exporting profit & loss: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@financial_reports_bp.route('/api/export/balance-sheet', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def export_balance_sheet():
    """Export Balance Sheet to Excel or CSV"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        as_of_date_str = data.get('as_of_date')
        format_type = data.get('format', 'excel')
        
        if not as_of_date_str:
            as_of_date = datetime.now().date()
        else:
            as_of_date = parse_date(as_of_date_str)
        
        if not as_of_date:
            return jsonify({'success': False, 'message': 'Invalid date'}), 400
        
        # Get data
        assets, total_assets = get_asset_data(institute_id, as_of_date)
        liabilities, total_liabilities = get_liability_data(institute_id, as_of_date)
        equity, total_equity = get_equity_data(institute_id, as_of_date)
        
        # Create DataFrames
        assets_df = pd.DataFrame(assets) if assets else pd.DataFrame(columns=['account_name', 'balance'])
        assets_df['category'] = 'Assets'
        
        liabilities_df = pd.DataFrame(liabilities) if liabilities else pd.DataFrame(columns=['account_name', 'balance'])
        liabilities_df['category'] = 'Liabilities'
        
        equity_df = pd.DataFrame(equity) if equity else pd.DataFrame(columns=['account_name', 'balance'])
        equity_df['category'] = 'Equity'
        
        # Add summary rows
        assets_summary = pd.DataFrame([{
            'account_name': 'TOTAL ASSETS',
            'balance': total_assets,
            'category': 'Summary'
        }])
        
        liabilities_summary = pd.DataFrame([{
            'account_name': 'TOTAL LIABILITIES',
            'balance': total_liabilities,
            'category': 'Summary'
        }])
        
        equity_summary = pd.DataFrame([{
            'account_name': 'TOTAL EQUITY',
            'balance': total_equity,
            'category': 'Summary'
        }])
        
        # Combine all
        all_data = pd.concat([
            assets_df, assets_summary,
            liabilities_df, liabilities_summary,
            equity_df, equity_summary
        ], ignore_index=True)
        
        # Export
        output = io.BytesIO()
        
        if format_type == 'excel':
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                all_data.to_excel(writer, sheet_name='Balance_Sheet', index=False)
                summary_data = {
                    'Metric': ['As Of Date', 'Total Assets', 'Total Liabilities', 'Total Equity', 'Working Capital'],
                    'Value': [
                        as_of_date.isoformat(),
                        total_assets,
                        total_liabilities,
                        total_equity,
                        total_assets - total_liabilities
                    ]
                }
                summary_df = pd.DataFrame(summary_data)
                summary_df.to_excel(writer, sheet_name='Summary', index=False)
            
            mimetype = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            filename = f"Balance_Sheet_{as_of_date.strftime('%Y%m%d')}.xlsx"
        else:
            all_data.to_csv(output, index=False)
            mimetype = 'text/csv'
            filename = f"Balance_Sheet_{as_of_date.strftime('%Y%m%d')}.csv"
        
        output.seek(0)
        
        return send_file(
            output,
            mimetype=mimetype,
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        print(f"Error exporting balance sheet: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

# ==========================================
# SUMMARY API
# ==========================================

@financial_reports_bp.route('/api/summary', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_financial_summary():
    """Get a quick financial summary for the dashboard"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        today = datetime.now()
        start_date = datetime(today.year, 1, 1).date()
        end_date = today.date()
        
        # Get revenue and expenses for the year
        revenue, total_revenue = get_revenue_data(institute_id, start_date, end_date)
        expenses, total_expenses = get_expense_data(institute_id, start_date, end_date)
        
        # Get current assets and liabilities as of today
        assets, total_assets = get_asset_data(institute_id, today.date())
        liabilities, total_liabilities = get_liability_data(institute_id, today.date())
        
        return jsonify({
            'success': True,
            'data': {
                'year_to_date': {
                    'revenue': total_revenue,
                    'expenses': total_expenses,
                    'net_income': total_revenue - total_expenses,
                    'revenue_formatted': format_currency(total_revenue),
                    'expenses_formatted': format_currency(total_expenses),
                    'net_income_formatted': format_currency(total_revenue - total_expenses)
                },
                'balance_sheet': {
                    'total_assets': total_assets,
                    'total_liabilities': total_liabilities,
                    'total_equity': total_assets - total_liabilities,
                    'assets_formatted': format_currency(total_assets),
                    'liabilities_formatted': format_currency(total_liabilities),
                    'equity_formatted': format_currency(total_assets - total_liabilities)
                }
            }
        })
        
    except Exception as e:
        print(f"Error getting financial summary: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500