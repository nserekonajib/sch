# schoolPayIntegration.py - SchoolPay Payment Gateway Integration (Multi-Account Support)
from flask import Blueprint, render_template, request, jsonify, session
from supabase import create_client, Client
import os
import base64
import uuid
from datetime import datetime, timedelta
import json
import hashlib
import hmac
import requests
from functools import wraps
from dotenv import load_dotenv

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

schoolpay_bp = Blueprint('schoolpay', __name__, url_prefix='/schoolpay')

def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Please login'}), 401
        return f(*args, **kwargs)
    return decorated_function

def get_institute_id(user_id):
    """Get institute ID for the current user"""
    try:
        response = supabase.table('institutes')\
            .select('id')\
            .eq('user_id', user_id)\
            .execute()
        
        if response.data and len(response.data) > 0:
            return response.data[0]['id']
        return None
    except Exception as e:
        print(f"Error getting institute ID: {e}")
        return None

@schoolpay_bp.route('/')
@login_required
def index():
    """SchoolPay Integration Settings Page"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return render_template('schoolpay/index.html', accounts=[], institute_id=None)
    
    try:
        # Get all SchoolPay accounts for this institute
        response = supabase.table('schoolpay_accounts')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('created_at', desc=True)\
            .execute()
        
        accounts = response.data if response.data else []
        
        return render_template('schoolpay/index.html', accounts=accounts, institute_id=institute_id)
        
    except Exception as e:
        print(f"Error loading SchoolPay accounts: {e}")
        return render_template('schoolpay/index.html', accounts=[], institute_id=institute_id)

@schoolpay_bp.route('/api/accounts', methods=['GET'])
@login_required
def get_accounts():
    """Get all SchoolPay accounts for the institute"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        response = supabase.table('schoolpay_accounts')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('created_at', desc=True)\
            .execute()
        
        accounts = response.data if response.data else []
        
        # Mask sensitive data
        for account in accounts:
            if account.get('api_password'):
                account['api_password'] = '••••••••'
        
        return jsonify({'success': True, 'accounts': accounts})
        
    except Exception as e:
        print(f"Error getting accounts: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@schoolpay_bp.route('/api/accounts/create', methods=['POST'])
@login_required
def create_account():
    """Create a new SchoolPay account"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        
        account_data = {
            'id': str(uuid.uuid4()),
            'institute_id': institute_id,
            'account_name': data.get('account_name', '').strip(),
            'school_code': data.get('school_code', '').strip(),
            'api_password': data.get('api_password', '').strip(),
            'environment': data.get('environment', 'sandbox'),
            'is_active': data.get('is_active', False),
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        # Validate required fields
        if not account_data['account_name']:
            return jsonify({'success': False, 'message': 'Account name is required'}), 400
        
        if not account_data['school_code']:
            return jsonify({'success': False, 'message': 'School code is required'}), 400
        
        if not account_data['api_password']:
            return jsonify({'success': False, 'message': 'API password is required'}), 400
        
        # Check if account name already exists for this institute
        existing = supabase.table('schoolpay_accounts')\
            .select('id')\
            .eq('institute_id', institute_id)\
            .eq('account_name', account_data['account_name'])\
            .execute()
        
        if existing.data:
            return jsonify({'success': False, 'message': 'Account name already exists'}), 400
        
        result = supabase.table('schoolpay_accounts').insert(account_data).execute()
        
        if result.data:
            # Mask password in response
            result.data[0]['api_password'] = '••••••••'
            return jsonify({
                'success': True, 
                'message': 'SchoolPay account created successfully',
                'account': result.data[0]
            })
        else:
            return jsonify({'success': False, 'message': 'Failed to create account'}), 500
            
    except Exception as e:
        print(f"Error creating SchoolPay account: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@schoolpay_bp.route('/api/accounts/<account_id>', methods=['PUT'])
@login_required
def update_account(account_id):
    """Update a SchoolPay account"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        
        update_data = {
            'account_name': data.get('account_name', '').strip(),
            'school_code': data.get('school_code', '').strip(),
            'environment': data.get('environment', 'sandbox'),
            'is_active': data.get('is_active', False),
            'updated_at': datetime.now().isoformat()
        }
        
        # Only update password if provided
        if data.get('api_password') and data['api_password'] != '••••••••':
            update_data['api_password'] = data['api_password']
        
        # Validate required fields
        if not update_data['account_name']:
            return jsonify({'success': False, 'message': 'Account name is required'}), 400
        
        if not update_data['school_code']:
            return jsonify({'success': False, 'message': 'School code is required'}), 400
        
        # Check if account exists
        account_check = supabase.table('schoolpay_accounts')\
            .select('id')\
            .eq('id', account_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if not account_check.data:
            return jsonify({'success': False, 'message': 'Account not found'}), 404
        
        result = supabase.table('schoolpay_accounts')\
            .update(update_data)\
            .eq('id', account_id)\
            .execute()
        
        if result.data:
            # Mask password in response
            result.data[0]['api_password'] = '••••••••'
            return jsonify({
                'success': True, 
                'message': 'SchoolPay account updated successfully',
                'account': result.data[0]
            })
        else:
            return jsonify({'success': False, 'message': 'Failed to update account'}), 500
            
    except Exception as e:
        print(f"Error updating SchoolPay account: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@schoolpay_bp.route('/api/accounts/<account_id>', methods=['DELETE'])
@login_required
def delete_account(account_id):
    """Delete a SchoolPay account"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Check if account exists
        account_check = supabase.table('schoolpay_accounts')\
            .select('id')\
            .eq('id', account_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if not account_check.data:
            return jsonify({'success': False, 'message': 'Account not found'}), 404
        
        result = supabase.table('schoolpay_accounts')\
            .delete()\
            .eq('id', account_id)\
            .execute()
        
        if result.data:
            return jsonify({'success': True, 'message': 'Account deleted successfully'})
        else:
            return jsonify({'success': False, 'message': 'Failed to delete account'}), 500
            
    except Exception as e:
        print(f"Error deleting SchoolPay account: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@schoolpay_bp.route('/api/accounts/<account_id>/toggle', methods=['PUT'])
@login_required
def toggle_account(account_id):
    """Toggle account active status"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        is_active = data.get('is_active', False)
        
        result = supabase.table('schoolpay_accounts')\
            .update({
                'is_active': is_active,
                'updated_at': datetime.now().isoformat()
            })\
            .eq('id', account_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if result.data:
            status = 'activated' if is_active else 'deactivated'
            return jsonify({'success': True, 'message': f'Account {status} successfully'})
        else:
            return jsonify({'success': False, 'message': 'Account not found'}), 404
            
    except Exception as e:
        print(f"Error toggling account: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@schoolpay_bp.route('/api/accounts/test', methods=['POST'])
@login_required
def test_connection():
    """Test SchoolPay API connection for a specific account"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        account_id = data.get('account_id')
        
        if not account_id:
            return jsonify({'success': False, 'message': 'Account ID required'}), 400
        
        # Get account details
        account_response = supabase.table('schoolpay_accounts')\
            .select('*')\
            .eq('id', account_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if not account_response.data:
            return jsonify({'success': False, 'message': 'Account not found'}), 404
        
        account = account_response.data[0]
        
        # Use today's date for testing
        test_date = datetime.now().strftime('%Y-%m-%d')
        
        # Generate MD5 hash as per SchoolPay specification
        hash_input = account['school_code'] + test_date + account['api_password']
        request_hash = hashlib.md5(hash_input.encode()).hexdigest().upper()
        
        # Determine API base URL
        if account['environment'] == 'production':
            base_url = "https://schoolpay.co.ug/paymentapi"
        else:
            base_url = "https://schoolpay.co.ug/paymentapi"
        
        # Test endpoint: Get transactions for a specific date
        test_url = f"{base_url}/AndroidRS/SyncSchoolTransactions/{account['school_code']}/{test_date}/{request_hash}"
        
        print(f"Testing SchoolPay connection for account: {account['account_name']}")
        print(f"URL: {test_url}")
        
        response = requests.get(test_url, timeout=30)
        
        if response.status_code == 200:
            return jsonify({
                'success': True, 
                'message': f'Connection successful for account "{account["account_name"]}"!'
            })
        elif response.status_code == 401:
            return jsonify({'success': False, 'message': 'Authentication failed. Invalid school code or password.'}), 400
        else:
            return jsonify({'success': False, 'message': f'Connection failed. Status code: {response.status_code}'}), 400
            
    except requests.exceptions.Timeout:
        return jsonify({'success': False, 'message': 'Connection timeout. Please check your network.'}), 400
    except requests.exceptions.ConnectionError:
        return jsonify({'success': False, 'message': 'Cannot connect to SchoolPay API.'}), 400
    except Exception as e:
        print(f"Error testing connection: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500