# whatsappIntegrationSettings.py - Auto-configured WhatsApp Integration
from flask import Blueprint, render_template, request, jsonify, session
from supabase import create_client, Client
import os
import uuid
import json
import requests
from datetime import datetime
from functools import wraps
from dotenv import load_dotenv
from routes.auth.auth import role_required
from routes.accounts.accounts import get_institute_id

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Fixed configuration - not editable by institutes
FIXED_NODEJS_API_URL = "https://whatsappconnection-2h64.onrender.com"
FIXED_API_KEY = "2343243"

whatsapp_bp = Blueprint('whatsapp', __name__, url_prefix='/whatsapp-integration')

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Please login'}), 401
        return f(*args, **kwargs)
    return decorated_function

def get_or_create_settings(institute_id):
    """Get existing settings or create default ones"""
    try:
        # Try to get existing settings
        response = supabase.table('whatsapp_settings_custom')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .execute()
        
        if response.data:
            return response.data[0]
        
        # Create new settings with fixed values
        settings_data = {
            'id': str(uuid.uuid4()),
            'institute_id': institute_id,
            'nodejs_api_url': FIXED_NODEJS_API_URL,
            'api_key': FIXED_API_KEY,
            'is_enabled': True,
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        result = supabase.table('whatsapp_settings_custom').insert(settings_data).execute()
        
        if result.data:
            return result.data[0]
        else:
            return None
            
    except Exception as e:
        print(f"Error getting/creating settings: {e}")
        return None


@whatsapp_bp.route('/')
@role_required(['admin', 'owner'])
def index():
    """WhatsApp Integration Page - Auto-configured"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return render_template('whatsapp/index.html', settings=None, institute_id=None, fixed_url=FIXED_NODEJS_API_URL)
    
    try:
        # Auto-create or get settings
        settings = get_or_create_settings(institute_id)
        
        return render_template('whatsapp/index.html', 
                             settings=settings, 
                             institute_id=institute_id,
                             fixed_url=FIXED_NODEJS_API_URL,
                             fixed_api_key=FIXED_API_KEY)
        
    except Exception as e:
        print(f"Error loading WhatsApp settings: {e}")
        return render_template('whatsapp/index.html', settings=None, institute_id=institute_id, fixed_url=FIXED_NODEJS_API_URL)


@whatsapp_bp.route('/api/settings', methods=['GET'])
@role_required(['admin', 'owner'])
def get_settings():
    """Get WhatsApp settings"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        settings = get_or_create_settings(institute_id)
        
        return jsonify({'success': True, 'settings': settings})
        
    except Exception as e:
        print(f"Error getting settings: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@whatsapp_bp.route('/api/settings/update-enabled', methods=['POST'])
@role_required(['admin', 'owner'])
def update_enabled_status():
    """Update only the enabled status"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        is_enabled = data.get('is_enabled', False)
        
        # Get existing settings
        settings = get_or_create_settings(institute_id)
        
        if not settings:
            return jsonify({'success': False, 'message': 'Settings not found'}), 404
        
        # Update only the enabled status
        update_data = {
            'is_enabled': is_enabled,
            'updated_at': datetime.now().isoformat()
        }
        
        result = supabase.table('whatsapp_settings_custom')\
            .update(update_data)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if result.data:
            return jsonify({'success': True, 'message': 'Status updated successfully'})
        else:
            return jsonify({'success': False, 'message': 'Failed to update status'}), 500
            
    except Exception as e:
        print(f"Error updating status: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@whatsapp_bp.route('/api/status', methods=['GET'])
@role_required(['admin', 'owner'])
def get_status():
    """Get WhatsApp connection status"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        settings = get_or_create_settings(institute_id)
        
        if not settings:
            return jsonify({'success': False, 'message': 'WhatsApp not configured'}), 400
        
        nodejs_url = settings.get('nodejs_api_url', '').rstrip('/')
        api_key = settings.get('api_key', '')
        
        if not nodejs_url:
            return jsonify({'success': False, 'message': 'Node.js API URL not configured'}), 400
        
        response = requests.get(
            f"{nodejs_url}/api/status/{institute_id}",
            headers={'X-API-Key': api_key} if api_key else {},
            timeout=60
        )
        
        if response.status_code == 200:
            status_data = response.json()
            return jsonify({
                'success': True,
                'status': status_data
            })
        else:
            return jsonify({'success': False, 'message': 'Failed to get status from Node.js API'}), 500
            
    except requests.exceptions.ConnectionError:
        return jsonify({'success': False, 'message': 'Node.js API not reachable'}), 500
    except Exception as e:
        print(f"Error getting status: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@whatsapp_bp.route('/api/request-qr', methods=['POST'])
@role_required(['admin', 'owner'])
def request_qr():
    """Request QR code for WhatsApp connection"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        settings = get_or_create_settings(institute_id)
        
        if not settings:
            return jsonify({'success': False, 'message': 'WhatsApp not configured'}), 400
        
        nodejs_url = settings.get('nodejs_api_url', '').rstrip('/')
        api_key = settings.get('api_key', '')
        
        if not nodejs_url:
            return jsonify({'success': False, 'message': 'Node.js API URL not configured'}), 400
        
        response = requests.post(
            f"{nodejs_url}/api/request-qr/{institute_id}",
            headers={'X-API-Key': api_key} if api_key else {},
            timeout=60
        )
        
        if response.status_code == 200:
            result = response.json()
            return jsonify({'success': True, 'result': result})
        else:
            return jsonify({'success': False, 'message': f'Failed to request QR: {response.status_code}'}), 500
            
    except requests.exceptions.ConnectionError:
        return jsonify({'success': False, 'message': 'Node.js API not reachable'}), 500
    except Exception as e:
        print(f"Error requesting QR: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@whatsapp_bp.route('/api/logout', methods=['POST'])
@role_required(['admin', 'owner'])
def logout_whatsapp():
    """Logout WhatsApp session"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        settings = get_or_create_settings(institute_id)
        
        if not settings:
            return jsonify({'success': False, 'message': 'WhatsApp not configured'}), 400
        
        nodejs_url = settings.get('nodejs_api_url', '').rstrip('/')
        api_key = settings.get('api_key', '')
        
        if not nodejs_url:
            return jsonify({'success': False, 'message': 'Node.js API URL not configured'}), 400
        
        response = requests.post(
            f"{nodejs_url}/api/logout/{institute_id}",
            headers={'X-API-Key': api_key} if api_key else {},
            timeout=60
        )
        
        if response.status_code == 200:
            result = response.json()
            return jsonify({'success': True, 'result': result})
        else:
            return jsonify({'success': False, 'message': f'Failed to logout: {response.status_code}'}), 500
            
    except requests.exceptions.ConnectionError:
        return jsonify({'success': False, 'message': 'Node.js API not reachable'}), 500
    except Exception as e:
        print(f"Error logging out: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@whatsapp_bp.route('/api/send-message', methods=['POST'])
@role_required(['admin', 'owner', 'teacher'])
def send_message():
    """Send a WhatsApp message"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        phone_number = data.get('phone_number', '').strip()
        message = data.get('message', '').strip()
        
        if not phone_number:
            return jsonify({'success': False, 'message': 'Phone number is required'}), 400
        
        if not message:
            return jsonify({'success': False, 'message': 'Message is required'}), 400
        
        settings = get_or_create_settings(institute_id)
        
        if not settings:
            return jsonify({'success': False, 'message': 'WhatsApp not configured'}), 400
        
        nodejs_url = settings.get('nodejs_api_url', '').rstrip('/')
        api_key = settings.get('api_key', '')
        
        if not nodejs_url:
            return jsonify({'success': False, 'message': 'Node.js API URL not configured'}), 400
        
        response = requests.post(
            f"{nodejs_url}/api/send",
            json={
                'number': phone_number,
                'message': message,
                'instituteId': institute_id
            },
            headers={'X-API-Key': api_key} if api_key else {},
            timeout=60
        )
        
        if response.status_code == 200:
            result = response.json()
            return jsonify({'success': True, 'result': result})
        else:
            print(f"Failed to send message: {response.status_code} - {response.text}")
            return jsonify({'success': False, 'message': f'Failed to send message: {response.status_code}'}), 500
            
    except requests.exceptions.ConnectionError:
        return jsonify({'success': False, 'message': 'Node.js API not reachable'}), 500
    except Exception as e:
        print(f"Error sending message: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@whatsapp_bp.route('/api/send-pdf', methods=['POST'])
@role_required(['admin', 'owner', 'teacher'])
def send_pdf():
    """Send a PDF document via WhatsApp"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        phone_number = data.get('phone_number', '').strip()
        pdf_base64 = data.get('pdf_base64', '').strip()
        filename = data.get('filename', 'document.pdf')
        
        if not phone_number:
            return jsonify({'success': False, 'message': 'Phone number is required'}), 400
        
        if not pdf_base64:
            return jsonify({'success': False, 'message': 'PDF data is required'}), 400
        
        settings = get_or_create_settings(institute_id)
        
        if not settings:
            return jsonify({'success': False, 'message': 'WhatsApp not configured'}), 400
        
        nodejs_url = settings.get('nodejs_api_url', '').rstrip('/')
        api_key = settings.get('api_key', '')
        
        if not nodejs_url:
            return jsonify({'success': False, 'message': 'Node.js API URL not configured'}), 400
        
        response = requests.post(
            f"{nodejs_url}/api/send-pdf",
            json={
                'number': phone_number,
                'pdfBuffer': pdf_base64,
                'filename': filename,
                'instituteId': institute_id
            },
            headers={'X-API-Key': api_key} if api_key else {},
            timeout=60
        )
        
        if response.status_code == 200:
            result = response.json()
            return jsonify({'success': True, 'result': result})
        else:
            print(f"Failed to send PDF: {response.status_code} - {response.text}")
            return jsonify({'success': False, 'message': f'Failed to send PDF: {response.status_code}'}), 500
            
    except requests.exceptions.ConnectionError:
        return jsonify({'success': False, 'message': 'Node.js API not reachable'}), 500
    except Exception as e:
        print(f"Error sending PDF: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@whatsapp_bp.route('/test')
@role_required(['admin', 'owner'])
def test_page():
    """WhatsApp API Test Page"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    return render_template('whatsapp/test.html', institute_id=institute_id)