# budget.py - Fixed to include school fees in income

from flask import Blueprint, render_template, request, jsonify, session
from supabase import create_client, Client
import os
import uuid
from datetime import datetime, timedelta
from functools import wraps
from dotenv import load_dotenv
import pandas as pd
import numpy as np

from routes.accounts.accounts import get_institute_from_session, role_required

load_dotenv()

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

budget_bp = Blueprint('budget', __name__, url_prefix='/budget')


# ============================================================
# ROUTES
# ============================================================

@budget_bp.route('/')
@role_required(['owner', 'teacher', 'accountant'])
def index():
    """Budget Dashboard - Advanced Version"""
    institute = get_institute_from_session()
    
    if not institute:
        return render_template('budget/index.html', institute=None)
    
    # Get fiscal years available
    years = get_available_fiscal_years(institute['id'])
    
    return render_template('budget/index.html', 
                         institute=institute,
                         years=years,
                         current_year=datetime.now().year)


@budget_bp.route('/api/dashboard-stats', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_dashboard_stats():
    """Get dashboard statistics for the budget overview"""
    institute = get_institute_from_session()
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        year = request.args.get('year', datetime.now().year)
        
        # Get all budgets for this year
        headers_resp = supabase.table('budget_headers')\
            .select('id, name, status')\
            .eq('institute_id', institute['id'])\
            .eq('fiscal_year', year)\
            .execute()
        
        headers = headers_resp.data or []
        
        # Get actual totals
        start_date = f"{year}-01-01"
        end_date = f"{year}-12-31"
        
        # FIXED: Include school fees from payments table
        # Income from payments (school fees)
        payments_resp = supabase.table('payments')\
            .select('amount')\
            .eq('institute_id', institute['id'])\
            .gte('payment_date', start_date)\
            .lte('payment_date', end_date)\
            .execute()
        
        school_fees_income = sum(float(t['amount']) for t in (payments_resp.data or []))
        
        # Income from income_transactions (other income)
        inc_resp = supabase.table('income_transactions')\
            .select('amount')\
            .eq('institute_id', institute['id'])\
            .gte('transaction_date', start_date)\
            .lte('transaction_date', end_date)\
            .execute()
        
        other_income = sum(float(t['amount']) for t in (inc_resp.data or []))
        
        # Total income = school fees + other income
        total_income = school_fees_income + other_income
        
        # Expense actuals from expense_transactions
        exp_resp = supabase.table('expense_transactions')\
            .select('amount')\
            .eq('institute_id', institute['id'])\
            .gte('transaction_date', start_date)\
            .lte('transaction_date', end_date)\
            .execute()
        
        total_expenses = sum(float(t['amount']) for t in (exp_resp.data or []))
        
        net_actual = total_income - total_expenses
        
        # Count active budgets
        active_budgets = len([h for h in headers if h.get('status') == 'active'])
        draft_budgets = len([h for h in headers if h.get('status') == 'draft'])
        
        return jsonify({
            'success': True,
            'stats': {
                'total_budgets': len(headers),
                'active_budgets': active_budgets,
                'draft_budgets': draft_budgets,
                'total_income': total_income,
                'school_fees_income': school_fees_income,
                'other_income': other_income,
                'total_expenses': total_expenses,
                'net_actual': net_actual,
                'year': year
            }
        })
        
    except Exception as e:
        print(f"Error in dashboard stats: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@budget_bp.route('/api/headers', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_budget_headers():
    """Get all budget headers with advanced filtering"""
    institute = get_institute_from_session()
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
        
    try:
        year = request.args.get('year', datetime.now().year)
        status = request.args.get('status', 'all')
        
        query = supabase.table('budget_headers')\
            .select('id, name, period_type, fiscal_year, status, start_date, end_date, created_at')\
            .eq('institute_id', institute['id'])\
            .eq('fiscal_year', year)
        
        if status != 'all':
            query = query.eq('status', status)
        
        resp = query.order('created_at', desc=True).execute()
        
        return jsonify({'success': True, 'headers': resp.data})
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@budget_bp.route('/api/headers/create', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def create_budget_header():
    """Create a new budget header with comprehensive validation"""
    institute = get_institute_from_session()
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
        
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['name', 'start_date', 'end_date']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'success': False, 'message': f'{field} is required'}), 400
        
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        
        # Validate dates
        if start_date >= end_date:
            return jsonify({'success': False, 'message': 'End date must be after start date'}), 400
        
        # Calculate fiscal year from start date
        fiscal_year = datetime.strptime(start_date, '%Y-%m-%d').year
        
        # Check for duplicate budget name in same year
        check_resp = supabase.table('budget_headers')\
            .select('id')\
            .eq('institute_id', institute['id'])\
            .eq('fiscal_year', fiscal_year)\
            .eq('name', data.get('name'))\
            .execute()
        
        if check_resp.data:
            return jsonify({'success': False, 'message': 'A budget with this name already exists for this fiscal year'}), 400
        
        header_data = {
            'id': str(uuid.uuid4()),
            'institute_id': institute['id'],
            'name': data.get('name'),
            'fiscal_year': fiscal_year,
            'period_type': data.get('period_type', 'monthly'),
            'start_date': start_date,
            'end_date': end_date,
            'status': 'draft',
            'description': data.get('description', ''),
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        result = supabase.table('budget_headers').insert(header_data).execute()
        
        return jsonify({'success': True, 'header': result.data[0]})
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@budget_bp.route('/api/headers/<header_id>', methods=['PUT'])
@role_required(['owner', 'teacher', 'accountant'])
def update_budget_header(header_id):
    """Update budget header (name, status, dates)"""
    institute = get_institute_from_session()
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        
        # Verify ownership
        check_resp = supabase.table('budget_headers')\
            .select('id')\
            .eq('id', header_id)\
            .eq('institute_id', institute['id'])\
            .execute()
        
        if not check_resp.data:
            return jsonify({'success': False, 'message': 'Budget not found'}), 404
        
        update_data = {}
        allowed_fields = ['name', 'status', 'description', 'start_date', 'end_date']
        for field in allowed_fields:
            if field in data:
                update_data[field] = data[field]
        
        update_data['updated_at'] = datetime.now().isoformat()
        
        result = supabase.table('budget_headers')\
            .update(update_data)\
            .eq('id', header_id)\
            .execute()
        
        return jsonify({'success': True, 'header': result.data[0]})
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@budget_bp.route('/api/headers/<header_id>', methods=['DELETE'])
@role_required(['owner', 'teacher', 'accountant'])
def delete_budget_header(header_id):
    """Delete a budget header and all its lines"""
    institute = get_institute_from_session()
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Verify ownership
        check_resp = supabase.table('budget_headers')\
            .select('id')\
            .eq('id', header_id)\
            .eq('institute_id', institute['id'])\
            .execute()
        
        if not check_resp.data:
            return jsonify({'success': False, 'message': 'Budget not found'}), 404
        
        # Delete budget lines first
        supabase.table('budget_lines')\
            .delete()\
            .eq('budget_header_id', header_id)\
            .execute()
        
        # Delete header
        supabase.table('budget_headers')\
            .delete()\
            .eq('id', header_id)\
            .execute()
        
        return jsonify({'success': True, 'message': 'Budget deleted successfully'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@budget_bp.route('/api/budgets/<header_id>', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_budget_detail(header_id):
    """Get detailed budget with variance analysis and forecasting - FIXED: includes school fees"""
    institute = get_institute_from_session()
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400

    try:
        # Get header
        header_resp = supabase.table('budget_headers')\
            .select('*')\
            .eq('id', header_id)\
            .eq('institute_id', institute['id'])\
            .execute()
        
        if not header_resp.data:
            return jsonify({'success': False, 'message': 'Budget not found'}), 404
            
        header = header_resp.data[0]
        
        # Get accounts
        acc_resp = supabase.table('chart_of_accounts')\
            .select('id, account_code, account_name, account_type, description')\
            .eq('institute_id', institute['id'])\
            .eq('is_active', True)\
            .in_('account_type', ['income', 'expense'])\
            .execute()
        
        accounts = {a['id']: a for a in (acc_resp.data or [])}
        
        # Get budget lines
        lines_resp = supabase.table('budget_lines')\
            .select('*')\
            .eq('budget_header_id', header_id)\
            .execute()
        
        lines_map = {}
        for line in (lines_resp.data or []):
            if line['account_id'] not in lines_map:
                lines_map[line['account_id']] = {}
            lines_map[line['account_id']][line['period_index']] = float(line['budgeted_amount'])
        
        # Get actuals based on budget date range
        start_date = header.get('start_date', f"{header['fiscal_year']}-01-01")
        end_date = header.get('end_date', f"{header['fiscal_year']}-12-31")
        
        all_tx = []
        
        # FIXED: Include school fees from payments table as income
        # Get school fees payments
        payments_resp = supabase.table('payments')\
            .select('amount, payment_date')\
            .eq('institute_id', institute['id'])\
            .gte('payment_date', start_date)\
            .lte('payment_date', end_date)\
            .execute()
        
        # Add school fees as income transactions (mapped to a generic "School Fees" account)
        for p in (payments_resp.data or []):
            all_tx.append({
                'account_id': 'school_fees',  # Special ID for school fees
                'amount': float(p['amount']),
                'date': p.get('payment_date', '')
            })
        
        # Income transactions (other income)
        inc_resp = supabase.table('income_transactions')\
            .select('account_id, amount, transaction_date')\
            .eq('institute_id', institute['id'])\
            .gte('transaction_date', start_date)\
            .lte('transaction_date', end_date)\
            .execute()
        for tx in (inc_resp.data or []):
            all_tx.append({
                'account_id': tx['account_id'], 
                'amount': float(tx['amount']),
                'date': tx.get('transaction_date', '')
            })

        # Expense transactions
        exp_resp = supabase.table('expense_transactions')\
            .select('account_id, amount, transaction_date')\
            .eq('institute_id', institute['id'])\
            .gte('transaction_date', start_date)\
            .lte('transaction_date', end_date)\
            .execute()
        for tx in (exp_resp.data or []):
            all_tx.append({
                'account_id': tx['account_id'], 
                'amount': float(tx['amount']),
                'date': tx.get('transaction_date', '')
            })
        
        df = pd.DataFrame(all_tx) if all_tx else pd.DataFrame(columns=['account_id', 'amount', 'date'])
        
        if not df.empty:
            yearly_actuals = df.groupby('account_id')['amount'].sum().to_dict()
        else:
            yearly_actuals = {}
        
        # Determine number of periods
        num_periods = 1 if header['period_type'] == 'yearly' else 4 if header['period_type'] == 'quarterly' else 12
        
        # Add a special "School Fees" account to the accounts dict if it doesn't exist
        if 'school_fees' not in accounts:
            accounts['school_fees'] = {
                'id': 'school_fees',
                'account_code': 'INC-SCHOOL-FEES',
                'account_name': 'School Fees',
                'account_type': 'income',
                'description': 'School fees collected from students'
            }
        
        # Compile budget data
        budget_data = []
        totals = {
            'budgeted_income': 0.0, 'actual_income': 0.0,
            'budgeted_expenses': 0.0, 'actual_expenses': 0.0,
            'variance_total': 0.0,
            'school_fees_actual': yearly_actuals.get('school_fees', 0.0),
            'other_income_actual': 0.0
        }
        
        # Get all account IDs that have budget lines OR actuals
        all_account_ids = set(lines_map.keys()) | set(yearly_actuals.keys())
        
        for acc_id in all_account_ids:
            account = accounts.get(acc_id)
            if not account:
                continue
                
            account_lines = lines_map.get(acc_id, {})
            budgeted_total = sum(account_lines.values())
            actual_total = yearly_actuals.get(acc_id, 0.0)
            
            variance = actual_total - budgeted_total
            
            # Calculate variance percentage
            var_percent = round((variance / budgeted_total * 100), 2) if budgeted_total > 0 else 0
            
            # Determine status
            if account['account_type'] == 'expense':
                is_bad = variance > 0
            else:
                is_bad = variance < 0
            
            status = 'over_budget' if is_bad and abs(variance) > 0 else 'on_track'
            
            # Calculate utilization
            utilization = round((actual_total / budgeted_total * 100), 1) if budgeted_total > 0 else 0
            
            period_values = [account_lines.get(i, 0.0) for i in range(num_periods)]
            
            # Add to totals
            if account['account_type'] == 'income':
                totals['budgeted_income'] += budgeted_total
                totals['actual_income'] += actual_total
                if acc_id != 'school_fees':
                    totals['other_income_actual'] += actual_total
            else:
                totals['budgeted_expenses'] += budgeted_total
                totals['actual_expenses'] += actual_total

            budget_data.append({
                'account_id': acc_id,
                'code': account['account_code'],
                'name': account['account_name'],
                'type': account['account_type'],
                'budgeted': round(budgeted_total, 0),
                'actual': round(actual_total, 0),
                'variance': round(variance, 0),
                'variance_percent': var_percent,
                'status': status,
                'utilization': utilization,
                'period_values': period_values,
                'has_budget': len(account_lines) > 0,
                'has_actuals': actual_total > 0,
                'is_school_fees': acc_id == 'school_fees'
            })
        
        # Sort: income first, then expenses
        budget_data.sort(key=lambda x: (0 if x['type'] == 'income' else 1, x['name']))
        
        # Calculate net totals
        totals['net_actual'] = totals['actual_income'] - totals['actual_expenses']
        totals['net_budgeted'] = totals['budgeted_income'] - totals['budgeted_expenses']
        totals['net_variance'] = totals['net_actual'] - totals['net_budgeted']
        
        # Generate forecast
        forecast = generate_forecast(header, budget_data)
        
        return jsonify({
            'success': True,
            'header': header,
            'budgets': budget_data,
            'totals': totals,
            'forecast': forecast,
            'summary': {
                'total_accounts': len(budget_data),
                'accounts_with_budget': len([b for b in budget_data if b['has_budget']]),
                'accounts_with_actuals': len([b for b in budget_data if b['has_actuals']]),
                'school_fees_actual': totals['school_fees_actual'],
                'other_income_actual': totals['other_income_actual']
            }
        })
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


@budget_bp.route('/api/budgets/save/<header_id>', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def save_budget_lines(header_id):
    """Save budget lines with upsert support"""
    institute = get_institute_from_session()
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
        
    try:
        data = request.get_json()
        lines_to_save = data.get('lines', [])
        
        if not lines_to_save:
            return jsonify({'success': False, 'message': 'No data to save'}), 400
        
        # Delete existing lines for this header
        supabase.table('budget_lines')\
            .delete()\
            .eq('budget_header_id', header_id)\
            .execute()
        
        # Prepare bulk insert
        bulk_data = []
        for item in lines_to_save:
            account_id = item['account_id']
            period_values = item['period_values']
            for index, amount in enumerate(period_values):
                if amount > 0:  # Only save non-zero values
                    bulk_data.append({
                        'id': str(uuid.uuid4()),
                        'budget_header_id': header_id,
                        'account_id': account_id,
                        'period_index': index,
                        'budgeted_amount': float(amount)
                    })
        
        if bulk_data:
            # Insert in batches for performance
            batch_size = 100
            for i in range(0, len(bulk_data), batch_size):
                batch = bulk_data[i:i+batch_size]
                supabase.table('budget_lines').insert(batch).execute()
        
        # Update header status to 'active' if it was draft
        supabase.table('budget_headers')\
            .update({'status': 'active', 'updated_at': datetime.now().isoformat()})\
            .eq('id', header_id)\
            .execute()
        
        return jsonify({
            'success': True, 
            'message': f'Successfully saved {len(bulk_data)} budget lines.',
            'lines_saved': len(bulk_data)
        })
        
    except Exception as e:
        print(f"Error saving budget: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


@budget_bp.route('/api/forecast/<header_id>', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_forecast(header_id):
    """Get budget forecast with trend analysis"""
    institute = get_institute_from_session()
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Get budget data
        budget_data = get_budget_detail_data(header_id, institute['id'])
        
        if not budget_data:
            return jsonify({'success': False, 'message': 'Budget not found'}), 404
        
        forecast = generate_forecast(budget_data['header'], budget_data['budgets'])
        
        return jsonify({
            'success': True,
            'forecast': forecast
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@budget_bp.route('/api/accounts', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_budget_accounts():
    """Get accounts available for budgeting"""
    institute = get_institute_from_session()
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        acc_resp = supabase.table('chart_of_accounts')\
            .select('id, account_code, account_name, account_type, description')\
            .eq('institute_id', institute['id'])\
            .eq('is_active', True)\
            .in_('account_type', ['income', 'expense'])\
            .order('account_type')\
            .order('account_name')\
            .execute()
        
        return jsonify({
            'success': True,
            'accounts': acc_resp.data or []
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@budget_bp.route('/api/available-years', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_available_years():
    """Get available fiscal years with budget data"""
    institute = get_institute_from_session()
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        years = get_available_fiscal_years(institute['id'])
        return jsonify({'success': True, 'years': years})
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def get_available_fiscal_years(institute_id):
    """
    Get all fiscal years that have budget data or transactions.
    """
    years = set()
    
    # Get years from budget headers
    try:
        resp = supabase.table('budget_headers')\
            .select('fiscal_year')\
            .eq('institute_id', institute_id)\
            .execute()
        
        for item in (resp.data or []):
            if item.get('fiscal_year'):
                years.add(item['fiscal_year'])
    except Exception as e:
        print(f"Error fetching budget headers years: {e}")
    
    # Get years from income_transactions
    try:
        resp = supabase.table('income_transactions')\
            .select('transaction_date')\
            .eq('institute_id', institute_id)\
            .limit(1)\
            .execute()
        
        for item in (resp.data or []):
            date_str = item.get('transaction_date', '')
            if date_str:
                try:
                    if isinstance(date_str, str):
                        year = datetime.strptime(date_str[:10], '%Y-%m-%d').year
                    else:
                        year = date_str.year if hasattr(date_str, 'year') else datetime.now().year
                    years.add(year)
                except:
                    pass
    except Exception as e:
        print(f"Error fetching income transactions years: {e}")
    
    # Get years from expense_transactions
    try:
        resp = supabase.table('expense_transactions')\
            .select('transaction_date')\
            .eq('institute_id', institute_id)\
            .limit(1)\
            .execute()
        
        for item in (resp.data or []):
            date_str = item.get('transaction_date', '')
            if date_str:
                try:
                    if isinstance(date_str, str):
                        year = datetime.strptime(date_str[:10], '%Y-%m-%d').year
                    else:
                        year = date_str.year if hasattr(date_str, 'year') else datetime.now().year
                    years.add(year)
                except:
                    pass
    except Exception as e:
        print(f"Error fetching expense transactions years: {e}")
    
    # Get years from payments
    try:
        resp = supabase.table('payments')\
            .select('payment_date')\
            .eq('institute_id', institute_id)\
            .limit(1)\
            .execute()
        
        for item in (resp.data or []):
            date_str = item.get('payment_date', '')
            if date_str:
                try:
                    if isinstance(date_str, str):
                        year = datetime.strptime(date_str[:10], '%Y-%m-%d').year
                    else:
                        year = date_str.year if hasattr(date_str, 'year') else datetime.now().year
                    years.add(year)
                except:
                    pass
    except Exception as e:
        print(f"Error fetching payments years: {e}")
    
    # Add current year and previous year if no data found
    current_year = datetime.now().year
    if not years:
        years.add(current_year)
        years.add(current_year - 1)
    else:
        years.add(current_year)
    
    return sorted(list(years), reverse=True)


def get_budget_detail_data(header_id, institute_id):
    """Helper to get budget detail data"""
    try:
        header_resp = supabase.table('budget_headers')\
            .select('*')\
            .eq('id', header_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if not header_resp.data:
            return None
        
        header = header_resp.data[0]
        
        # Get accounts
        acc_resp = supabase.table('chart_of_accounts')\
            .select('id, account_code, account_name, account_type')\
            .eq('institute_id', institute_id)\
            .eq('is_active', True)\
            .in_('account_type', ['income', 'expense'])\
            .execute()
        
        accounts = {a['id']: a for a in (acc_resp.data or [])}
        
        # Get budget lines
        lines_resp = supabase.table('budget_lines')\
            .select('*')\
            .eq('budget_header_id', header_id)\
            .execute()
        
        lines_map = {}
        for line in (lines_resp.data or []):
            if line['account_id'] not in lines_map:
                lines_map[line['account_id']] = {}
            lines_map[line['account_id']][line['period_index']] = float(line['budgeted_amount'])
        
        # Get actuals
        start_date = header.get('start_date', f"{header['fiscal_year']}-01-01")
        end_date = header.get('end_date', f"{header['fiscal_year']}-12-31")
        
        all_tx = []
        
        # School fees from payments
        payments_resp = supabase.table('payments')\
            .select('amount')\
            .eq('institute_id', institute_id)\
            .gte('payment_date', start_date)\
            .lte('payment_date', end_date)\
            .execute()
        for p in (payments_resp.data or []):
            all_tx.append({
                'account_id': 'school_fees',
                'amount': float(p['amount'])
            })
        
        # Income transactions
        resp = supabase.table('income_transactions')\
            .select('account_id, amount')\
            .eq('institute_id', institute_id)\
            .gte('transaction_date', start_date)\
            .lte('transaction_date', end_date)\
            .execute()
        for tx in (resp.data or []):
            all_tx.append({
                'account_id': tx['account_id'],
                'amount': float(tx['amount'])
            })
        
        # Expense transactions
        resp = supabase.table('expense_transactions')\
            .select('account_id, amount')\
            .eq('institute_id', institute_id)\
            .gte('transaction_date', start_date)\
            .lte('transaction_date', end_date)\
            .execute()
        for tx in (resp.data or []):
            all_tx.append({
                'account_id': tx['account_id'],
                'amount': float(tx['amount'])
            })
        
        df = pd.DataFrame(all_tx) if all_tx else pd.DataFrame(columns=['account_id', 'amount'])
        yearly_actuals = df.groupby('account_id')['amount'].sum().to_dict() if not df.empty else {}
        
        # Add school fees account
        if 'school_fees' not in accounts:
            accounts['school_fees'] = {
                'id': 'school_fees',
                'account_code': 'INC-SCHOOL-FEES',
                'account_name': 'School Fees',
                'account_type': 'income'
            }
        
        num_periods = 1 if header['period_type'] == 'yearly' else 4 if header['period_type'] == 'quarterly' else 12
        
        budget_data = []
        all_account_ids = set(lines_map.keys()) | set(yearly_actuals.keys())
        
        for acc_id in all_account_ids:
            account = accounts.get(acc_id)
            if not account:
                continue
            
            account_lines = lines_map.get(acc_id, {})
            budgeted_total = sum(account_lines.values())
            actual_total = yearly_actuals.get(acc_id, 0.0)
            
            variance = actual_total - budgeted_total
            var_percent = round((variance / budgeted_total * 100), 2) if budgeted_total > 0 else 0
            
            if account['account_type'] == 'expense':
                is_bad = variance > 0
            else:
                is_bad = variance < 0
            
            status = 'over_budget' if is_bad and abs(variance) > 0 else 'on_track'
            
            period_values = [account_lines.get(i, 0.0) for i in range(num_periods)]
            
            budget_data.append({
                'account_id': acc_id,
                'code': account['account_code'],
                'name': account['account_name'],
                'type': account['account_type'],
                'budgeted': round(budgeted_total, 0),
                'actual': round(actual_total, 0),
                'variance': round(variance, 0),
                'variance_percent': var_percent,
                'status': status,
                'period_values': period_values,
                'has_budget': len(account_lines) > 0,
                'has_actuals': actual_total > 0
            })
        
        return {'header': header, 'budgets': budget_data}
        
    except Exception as e:
        print(f"Error in get_budget_detail_data: {e}")
        return None


def generate_forecast(header, budget_data):
    """Generate budget forecast based on current trends"""
    forecast = {
        'income': {'projected': 0, 'trend': 0, 'confidence': 0},
        'expenses': {'projected': 0, 'trend': 0, 'confidence': 0},
        'net': {'projected': 0, 'trend': 0, 'confidence': 0}
    }
    
    # Separate income and expense
    income_items = [b for b in budget_data if b['type'] == 'income']
    expense_items = [b for b in budget_data if b['type'] == 'expense']
    
    # Calculate projected totals based on actual/budget ratios
    if income_items:
        total_budgeted_income = sum(b['budgeted'] for b in income_items)
        total_actual_income = sum(b['actual'] for b in income_items)
        
        if total_budgeted_income > 0:
            forecast['income']['projected'] = total_actual_income
            forecast['income']['trend'] = round((total_actual_income / total_budgeted_income * 100), 1)
            forecast['income']['confidence'] = min(round((total_actual_income / total_budgeted_income) * 50, 0), 95)
    
    if expense_items:
        total_budgeted_expenses = sum(b['budgeted'] for b in expense_items)
        total_actual_expenses = sum(b['actual'] for b in expense_items)
        
        if total_budgeted_expenses > 0:
            forecast['expenses']['projected'] = total_actual_expenses
            forecast['expenses']['trend'] = round((total_actual_expenses / total_budgeted_expenses * 100), 1)
            forecast['expenses']['confidence'] = min(round((total_actual_expenses / total_budgeted_expenses) * 50, 0), 95)
    
    # Net forecast
    forecast['net']['projected'] = forecast['income']['projected'] - forecast['expenses']['projected']
    forecast['net']['trend'] = forecast['income']['trend'] - forecast['expenses']['trend']
    forecast['net']['confidence'] = min(forecast['income']['confidence'], forecast['expenses']['confidence'])
    
    return forecast