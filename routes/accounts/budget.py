from flask import Blueprint, render_template, request, jsonify, session
from supabase import create_client, Client
import os
import uuid
from datetime import datetime
from functools import wraps
from dotenv import load_dotenv
import pandas as pd

from routes.accounts.accounts import get_institute_from_session, role_required

load_dotenv()

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

budget_bp = Blueprint('budget', __name__, url_prefix='/budget')


@budget_bp.route('/')
@role_required(['owner', 'teacher', 'accountant'])
def index():
    institute = get_institute_from_session()
    return render_template('budget/index.html', institute=institute)


@budget_bp.route('/api/headers', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_budget_headers():
    institute = get_institute_from_session()
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
        
    try:
        year = request.args.get('year', datetime.now().year)
        resp = supabase.table('budget_headers')\
            .select('id, name, period_type, fiscal_year, status, start_date, end_date')\
            .eq('institute_id', institute['id'])\
            .eq('fiscal_year', year)\
            .order('created_at', desc=True)\
            .execute()
        return jsonify({'success': True, 'headers': resp.data})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@budget_bp.route('/api/headers/create', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def create_budget_header():
    institute = get_institute_from_session()
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
        
    try:
        data = request.get_json()
        
        # Parse dates
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        
        # Validate dates
        if not start_date or not end_date:
            return jsonify({'success': False, 'message': 'Start date and end date are required'}), 400
            
        # Calculate fiscal year from start date
        fiscal_year = datetime.strptime(start_date, '%Y-%m-%d').year
        
        header_data = {
            'id': str(uuid.uuid4()),
            'institute_id': institute['id'],
            'name': data.get('name'),
            'fiscal_year': fiscal_year,
            'period_type': data.get('period_type', 'monthly'),
            'start_date': start_date,
            'end_date': end_date,
            'status': 'draft'
        }
        result = supabase.table('budget_headers').insert(header_data).execute()
        return jsonify({'success': True, 'header': result.data[0]})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@budget_bp.route('/api/budgets/<header_id>', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_budget_detail(header_id):
    institute = get_institute_from_session()
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400

    try:
        header_resp = supabase.table('budget_headers')\
            .select('*')\
            .eq('id', header_id)\
            .eq('institute_id', institute['id'])\
            .execute()
        
        if not header_resp.data:
            return jsonify({'success': False, 'message': 'Budget not found'}), 404
            
        header = header_resp.data[0]
        year = header['fiscal_year']
        num_periods = 1 if header['period_type'] == 'yearly' else 4 if header['period_type'] == 'quarterly' else 12

        # Accounts
        acc_resp = supabase.table('chart_of_accounts')\
            .select('id, account_code, account_name, account_type')\
            .eq('institute_id', institute['id'])\
            .eq('is_active', True)\
            .in_('account_type', ['income', 'expense'])\
            .execute()
        accounts = {a['id']: a for a in (acc_resp.data or [])}

        # Budget Lines
        lines_resp = supabase.table('budget_lines')\
            .select('*')\
            .eq('budget_header_id', header_id)\
            .execute()
            
        lines_map = {}
        for line in (lines_resp.data or []):
            if line['account_id'] not in lines_map:
                lines_map[line['account_id']] = {}
            lines_map[line['account_id']][line['period_index']] = float(line['budgeted_amount'])

        # Actuals using the budget date range
        start_date = header.get('start_date', f"{year}-01-01")
        end_date = header.get('end_date', f"{year}-12-31")
        
        all_tx = []
        
        # Get income transactions within date range
        inc_resp = supabase.table('income_transactions')\
            .select('account_id, amount')\
            .eq('institute_id', institute['id'])\
            .gte('transaction_date', start_date)\
            .lte('transaction_date', end_date)\
            .execute()
        for tx in (inc_resp.data or []):
            all_tx.append({'account_id': tx['account_id'], 'amount': float(tx['amount'])})

        # Get expense transactions within date range
        exp_resp = supabase.table('expense_transactions')\
            .select('account_id, amount')\
            .eq('institute_id', institute['id'])\
            .gte('transaction_date', start_date)\
            .lte('transaction_date', end_date)\
            .execute()
        for tx in (exp_resp.data or []):
            all_tx.append({'account_id': tx['account_id'], 'amount': float(tx['amount'])})

        df = pd.DataFrame(all_tx)
        yearly_actuals = df.groupby('account_id')['amount'].sum().to_dict() if not df.empty else {}

        # Compile
        budget_data = []
        totals = {
            'budgeted_income': 0.0, 'actual_income': 0.0, 
            'budgeted_expenses': 0.0, 'actual_expenses': 0.0
        }
        
        for acc_id, account in accounts.items():
            account_lines = lines_map.get(acc_id, {})
            budgeted_total = sum(account_lines.values())
            actual_total = yearly_actuals.get(acc_id, 0.0)
            
            variance = actual_total - budgeted_total
            var_percent = round((variance / budgeted_total * 100), 2) if budgeted_total > 0 else 0
            
            # Determine status based on account type
            if account['account_type'] == 'expense':
                is_bad = variance > 0  # Over budget for expenses is bad
            else:  # income
                is_bad = variance < 0  # Under budget for income is bad
            
            status = 'over_budget' if is_bad else 'on_track'

            period_values = [account_lines.get(i, 0.0) for i in range(num_periods)]

            if account['account_type'] == 'income':
                totals['budgeted_income'] += budgeted_total
                totals['actual_income'] += actual_total
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
                'period_values': period_values
            })

        # Calculate net income
        totals['net_actual'] = totals['actual_income'] - totals['actual_expenses']
        totals['net_budgeted'] = totals['budgeted_income'] - totals['budgeted_expenses']

        return jsonify({
            'success': True,
            'header': header,
            'budgets': budget_data,
            'totals': totals
        })
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@budget_bp.route('/api/budgets/save/<header_id>', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def save_budget_lines(header_id):
    institute = get_institute_from_session()
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
        
    try:
        data = request.get_json()
        lines_to_save = data.get('lines', [])
        
        # PREPARE BULK DATA FOR UPSERT
        bulk_data = []
        for item in lines_to_save:
            account_id = item['account_id']
            period_values = item['period_values']
            for index, amount in enumerate(period_values):
                bulk_data.append({
                    'budget_header_id': header_id,
                    'account_id': account_id,
                    'period_index': index,
                    'budgeted_amount': float(amount)
                })

        if bulk_data:
            # Supabase UPSERT
            supabase.table('budget_lines')\
                .upsert(bulk_data, on_conflict='budget_header_id, account_id, period_index')\
                .execute()
                
        return jsonify({'success': True, 'message': f'Successfully saved {len(bulk_data)} budget lines.'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500