# schoolPayIntegration.py - SchoolPay Payment Gateway Integration (Updated with MD5 hash)
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
        return render_template('schoolpay/index.html', settings=None, institute_id=None)
    
    try:
        # Get SchoolPay settings for this institute
        response = supabase.table('schoolpay_settings')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .execute()
        
        settings = response.data[0] if response.data else None
        
        return render_template('schoolpay/index.html', settings=settings, institute_id=institute_id)
        
    except Exception as e:
        print(f"Error loading SchoolPay settings: {e}")
        return render_template('schoolpay/index.html', settings=None, institute_id=institute_id)

@schoolpay_bp.route('/api/settings/save', methods=['POST'])
@login_required
def save_settings():
    """Save SchoolPay API credentials"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        
        settings_data = {
            'institute_id': institute_id,
            'school_code': data.get('school_code', '').strip(),
            'api_password': data.get('api_password', '').strip(),
            'environment': data.get('environment', 'sandbox'),
            'is_active': data.get('is_active', False),
            'updated_at': datetime.now().isoformat()
        }
        
        # Validate required fields
        if not settings_data['school_code']:
            return jsonify({'success': False, 'message': 'School code is required'}), 400
        
        if not settings_data['api_password']:
            return jsonify({'success': False, 'message': 'API password is required'}), 400
        
        # Check if settings already exist
        existing = supabase.table('schoolpay_settings')\
            .select('id')\
            .eq('institute_id', institute_id)\
            .execute()
        
        if existing.data:
            # Update existing
            result = supabase.table('schoolpay_settings')\
                .update(settings_data)\
                .eq('institute_id', institute_id)\
                .execute()
        else:
            # Insert new
            settings_data['id'] = str(uuid.uuid4())
            settings_data['created_at'] = datetime.now().isoformat()
            result = supabase.table('schoolpay_settings').insert(settings_data).execute()
        
        if result.data:
            return jsonify({'success': True, 'message': 'SchoolPay settings saved successfully'})
        else:
            return jsonify({'success': False, 'message': 'Failed to save settings'}), 500
            
    except Exception as e:
        print(f"Error saving SchoolPay settings: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@schoolpay_bp.route('/api/settings/test', methods=['POST'])
@login_required
def test_connection():
    """Test SchoolPay API connection using MD5 hash authentication"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        school_code = data.get('school_code', '').strip()
        api_password = data.get('api_password', '').strip()
        environment = data.get('environment', 'sandbox')
        
        if not school_code:
            return jsonify({'success': False, 'message': 'School code is required'}), 400
        
        if not api_password:
            return jsonify({'success': False, 'message': 'API password is required'}), 400
        
        # Use today's date for testing
        test_date = datetime.now().strftime('%Y-%m-%d')
        
        # Generate MD5 hash as per SchoolPay specification
        # MD5(SchoolCode + Date + Password)
        hash_input = school_code + test_date + api_password
        request_hash = hashlib.md5(hash_input.encode()).hexdigest().upper()
        
        # Determine API base URL
        if environment == 'production':
            base_url = "https://schoolpay.co.ug/paymentapi"
        else:
            base_url = "https://schoolpay.co.ug/paymentapi"  # Sandbox URL (same for now)
        
        # Test endpoint: Get transactions for a specific date
        test_url = f"{base_url}/AndroidRS/SyncSchoolTransactions/{school_code}/{test_date}/{request_hash}"
        
        print(f"Testing SchoolPay connection...")
        print(f"URL: {test_url}")
        print(f"Hash Input: {hash_input}")
        print(f"Generated Hash: {request_hash}")
        
        # Make test request
        response = requests.get(test_url, timeout=30)
        
        print(f"Response Status: {response.status_code}")
        print(f"Response Body: {response.text[:500] if response.text else 'Empty'}")
        
        if response.status_code == 200:
            try:
                response_data = response.json()
                # Check if the response indicates success
                if isinstance(response_data, dict):
                    if response_data.get('status') == 'success' or 'data' in response_data:
                        return jsonify({
                            'success': True, 
                            'message': 'Connection successful! API credentials are valid.',
                            'data': response_data
                        })
                    else:
                        return jsonify({
                            'success': True, 
                            'message': 'Connection successful! API responded.',
                            'data': response_data
                        })
                else:
                    return jsonify({
                        'success': True, 
                        'message': 'Connection successful! API credentials are valid.',
                        'data': response_data
                    })
            except json.JSONDecodeError:
                # If response is not JSON but status is 200, it might still be valid
                return jsonify({
                    'success': True, 
                    'message': 'Connection successful! API responded with status 200.'
                })
        elif response.status_code == 401:
            return jsonify({'success': False, 'message': 'Authentication failed. Invalid school code or password.'}), 400
        elif response.status_code == 404:
            return jsonify({'success': False, 'message': 'API endpoint not found. Please check your environment settings.'}), 400
        else:
            return jsonify({'success': False, 'message': f'Connection failed. Status code: {response.status_code}'}), 400
            
    except requests.exceptions.Timeout:
        return jsonify({'success': False, 'message': 'Connection timeout. Please check your network.'}), 400
    except requests.exceptions.ConnectionError:
        return jsonify({'success': False, 'message': 'Cannot connect to SchoolPay API. Please check your internet connection.'}), 400
    except Exception as e:
        print(f"Error testing connection: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@schoolpay_bp.route('/api/settings/test-range', methods=['POST'])
@login_required
def test_date_range():
    """Test SchoolPay API with date range"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        school_code = data.get('school_code', '').strip()
        api_password = data.get('api_password', '').strip()
        environment = data.get('environment', 'sandbox')
        from_date = data.get('from_date', '')
        to_date = data.get('to_date', '')
        
        if not school_code:
            return jsonify({'success': False, 'message': 'School code is required'}), 400
        
        if not api_password:
            return jsonify({'success': False, 'message': 'API password is required'}), 400
        
        if not from_date or not to_date:
            # Default to last 7 days
            to_date = datetime.now().strftime('%Y-%m-%d')
            from_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        
        # Generate MD5 hash for date range
        # MD5(SchoolCode + FromDate + Password)
        hash_input = school_code + from_date + api_password
        request_hash = hashlib.md5(hash_input.encode()).hexdigest().upper()
        
        # Determine API base URL
        if environment == 'production':
            base_url = "https://schoolpay.co.ug/paymentapi"
        else:
            base_url = "https://schoolpay.co.ug/paymentapi"
        
        # Test endpoint: Get transactions for date range
        test_url = f"{base_url}/AndroidRS/SchoolRangeTransactions/{school_code}/{from_date}/{to_date}/{request_hash}"
        
        print(f"Testing SchoolPay date range...")
        print(f"URL: {test_url}")
        
        response = requests.get(test_url, timeout=30)
        
        if response.status_code == 200:
            try:
                response_data = response.json()
                return jsonify({
                    'success': True,
                    'message': 'Date range test successful!',
                    'data': response_data
                })
            except json.JSONDecodeError:
                return jsonify({
                    'success': True,
                    'message': 'Date range test successful!'
                })
        else:
            return jsonify({'success': False, 'message': f'Test failed. Status code: {response.status_code}'}), 400
            
    except Exception as e:
        print(f"Error testing date range: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@schoolpay_bp.route('/api/settings/credentials', methods=['GET'])
@login_required
def get_credentials():
    """Get SchoolPay credentials (masked)"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        response = supabase.table('schoolpay_settings')\
            .select('school_code, environment, is_active')\
            .eq('institute_id', institute_id)\
            .execute()
        
        if response.data:
            settings = response.data[0]
            # Mask the password (don't send it back)
            settings['api_password'] = '••••••••'
            return jsonify({'success': True, 'settings': settings})
        else:
            return jsonify({'success': True, 'settings': None})
            
    except Exception as e:
        print(f"Error getting credentials: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500