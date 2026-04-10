# sms_settings.py - SMS Integration Blueprint
from flask import Blueprint, render_template, request, jsonify, session
from supabase import create_client, Client
import os
import json
from functools import wraps
from dotenv import load_dotenv

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

sms_settings_bp = Blueprint('sms_settings', __name__, url_prefix='/sms-settings')

def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Please login'}), 401
        return f(*args, **kwargs)
    return decorated_function

def get_institute_id(user_id):
    """Get institute for the current user"""
    try:
        response = supabase.table('institutes')\
            .select('*')\
            .eq('user_id', user_id)\
            .execute()
        
        if response.data and len(response.data) > 0:
            return response.data[0]
        return None
    except Exception as e:
        print(f"Error getting institute: {e}")
        return None

@sms_settings_bp.route('/')
@login_required
def index():
    """SMS Settings Page"""
    user = session.get('user')
    institute = get_institute_id(user['id'])
    
    if not institute:
        return render_template('sms/settings.html', settings=None, institute=None)
    
    try:
        # Get SMS settings for this institute
        response = supabase.table('sms_settings')\
            .select('*')\
            .eq('institute_id', institute['id'])\
            .execute()
        
        settings = response.data[0] if response.data else None
        
        return render_template('sms/settings.html', settings=settings, institute=institute)
        
    except Exception as e:
        print(f"Error loading SMS settings: {e}")
        return render_template('sms/settings.html', settings=None, institute=institute)

@sms_settings_bp.route('/save', methods=['POST'])
@login_required
def save_settings():
    """Save SMS API settings"""
    user = session.get('user')
    institute = get_institute_id(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        
        settings_data = {
            'institute_id': institute['id'],
            'api_username': data.get('api_username', '').strip(),
            'api_key': data.get('api_key', '').strip(),
            'sender_id': data.get('sender_id', 'SCHOOL').strip(),
            'enabled': data.get('enabled', False),
            'send_on_payment': data.get('send_on_payment', True),
            'updated_at': 'now()'
        }
        
        # Check if settings already exist
        existing = supabase.table('sms_settings')\
            .select('id')\
            .eq('institute_id', institute['id'])\
            .execute()
        
        if existing.data:
            # Update existing
            result = supabase.table('sms_settings')\
                .update(settings_data)\
                .eq('institute_id', institute['id'])\
                .execute()
        else:
            # Insert new
            settings_data['created_at'] = 'now()'
            result = supabase.table('sms_settings').insert(settings_data).execute()
        
        if result.data:
            return jsonify({'success': True, 'message': 'SMS settings saved successfully'})
        else:
            return jsonify({'success': False, 'message': 'Failed to save settings'}), 500
            
    except Exception as e:
        print(f"Error saving SMS settings: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@sms_settings_bp.route('/test', methods=['POST'])
@login_required
def test_sms():
    """Test SMS sending with current settings"""
    user = session.get('user')
    institute = get_institute_id(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        test_phone = data.get('phone', '').strip()
        
        if not test_phone:
            return jsonify({'success': False, 'message': 'Please enter a test phone number'}), 400
        
        # Get SMS settings
        response = supabase.table('sms_settings')\
            .select('*')\
            .eq('institute_id', institute['id'])\
            .execute()
        
        if not response.data:
            return jsonify({'success': False, 'message': 'SMS settings not configured'}), 400
        
        settings = response.data[0]
        
        if not settings.get('enabled'):
            return jsonify({'success': False, 'message': 'SMS is disabled. Please enable it first.'}), 400
        
        # Import CommsSDK
        try:
            from comms_sdk import CommsSDK, MessagePriority
            
            sdk = CommsSDK.authenticate(
                settings['api_username'], 
                settings['api_key']
            )
            
            test_message = f"Test SMS from {institute.get('institute_name', 'School')}. Your SMS integration is working correctly!"
            
            response = sdk.send_sms(
                [test_phone],
                test_message,
                sender_id=settings.get('sender_id', 'SCHOOL'),
                priority=MessagePriority.HIGHEST
            )
            
            return jsonify({'success': True, 'message': 'Test SMS sent successfully!'})
            
        except ImportError:
            return jsonify({'success': False, 'message': 'CommsSDK not installed. Please install it first.'}), 500
        except Exception as e:
            return jsonify({'success': False, 'message': f'SMS sending failed: {str(e)}'}), 500
            
    except Exception as e:
        print(f"Error testing SMS: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500