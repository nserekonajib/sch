# whatsappIntegrationSettings.py - Global WhatsApp Integration with All Routes

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

# MASTER USER CONFIGURATION
MASTER_EMAIL = "nserekonajib3@gmail.com"

# Fixed configuration
FIXED_NODEJS_API_URL = "http://d44cgg048cgckw4kwo4osw4k.195.200.15.127.sslip.io"
FIXED_API_KEY = "2343243"

whatsapp_bp = Blueprint('whatsapp', __name__, url_prefix='/whatsapp-integration')

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Please login'}), 401
        return f(*args, **kwargs)
    return decorated_function

def is_master_user(user_email):
    """Check if the current user is the master WhatsApp user"""
    return user_email.lower() == MASTER_EMAIL.lower()

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
            'master_connected': False,
            'master_email': MASTER_EMAIL,
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        result = supabase.table('whatsapp_settings_custom').insert(settings_data).execute()
        
        if result.data:
            return result.data[0]
        return None
            
    except Exception as e:
        print(f"Error getting/creating settings: {e}")
        return None


@whatsapp_bp.route('/')
@role_required(['admin', 'owner'])
def index():
    """WhatsApp Integration Page"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    user_email = user.get('email', '')
    
    if not institute_id:
        return render_template('whatsapp/index.html', 
                             settings=None, 
                             institute_id=None, 
                             fixed_url=FIXED_NODEJS_API_URL,
                             is_master=is_master_user(user_email),
                             master_connected=False)
    
    try:
        settings = get_or_create_settings(institute_id)
        master_connected = settings.get('master_connected', False) if settings else False
        
        return render_template('whatsapp/index.html', 
                             settings=settings, 
                             institute_id=institute_id,
                             fixed_url=FIXED_NODEJS_API_URL,
                             is_master=is_master_user(user_email),
                             master_connected=master_connected)
        
    except Exception as e:
        print(f"Error loading WhatsApp settings: {e}")
        return render_template('whatsapp/index.html', 
                             settings=None, 
                             institute_id=institute_id, 
                             fixed_url=FIXED_NODEJS_API_URL,
                             is_master=is_master_user(user_email),
                             master_connected=False)


@whatsapp_bp.route('/api/settings', methods=['GET'])
@role_required(['admin', 'owner'])
def get_settings():
    """Get WhatsApp settings"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    user_email = user.get('email', '')
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        settings = get_or_create_settings(institute_id)
        
        return jsonify({
            'success': True, 
            'settings': settings,
            'is_master': is_master_user(user_email),
            'master_email': MASTER_EMAIL,
            'master_connected': settings.get('master_connected', False) if settings else False
        })
        
    except Exception as e:
        print(f"Error getting settings: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@whatsapp_bp.route('/api/settings/update-enabled', methods=['POST'])
@role_required(['admin', 'owner'])
def update_enabled_status():
    """Update the enabled status"""
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
        
        # Update the enabled status
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
@role_required(['admin', 'owner', 'teacher'])
def get_status():
    """Get WhatsApp connection status - polls Node.js for current state"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        settings = get_or_create_settings(institute_id)
        nodejs_url = settings.get('nodejs_api_url', '').rstrip('/')
        
        response = requests.get(
            f"{nodejs_url}/api/status/{institute_id}",
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            return jsonify({
                'success': True,
                'status': data
            })
        else:
            return jsonify({'success': False, 'message': 'Failed to get status'}), 500
            
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    
@whatsapp_bp.route('/api/request-qr', methods=['POST'])
@role_required(['admin', 'owner'])
def request_qr():
    """Request QR code - ONLY MASTER USER"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    user_email = user.get('email', '')
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    if not is_master_user(user_email):
        return jsonify({
            'success': False, 
            'message': 'Only the administrator can connect WhatsApp.'
        }), 403
    
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
            return jsonify({
                'success': False, 
                'message': f'Failed to request QR: {response.status_code} - {response.text}'
            }), 500
            
    except requests.exceptions.ConnectionError:
        return jsonify({'success': False, 'message': 'WhatsApp server not reachable'}), 500
    except Exception as e:
        print(f"Error requesting QR: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@whatsapp_bp.route('/api/mark-master-connected', methods=['POST'])
@role_required(['admin', 'owner'])
def mark_master_connected():
    """Mark master as connected for this institute"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    user_email = user.get('email', '')
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    if not is_master_user(user_email):
        return jsonify({'success': False, 'message': 'Only the administrator can mark connection'}), 403
    
    try:
        # Update local settings
        update_data = {
            'master_connected': True,
            'master_connected_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        result = supabase.table('whatsapp_settings_custom')\
            .update(update_data)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if result.data:
            # Also try to notify Node.js
            try:
                settings = get_or_create_settings(institute_id)
                nodejs_url = settings.get('nodejs_api_url', '').rstrip('/')
                api_key = settings.get('api_key', '')
                
                if nodejs_url:
                    requests.post(
                        f"{nodejs_url}/api/mark-master-connected",
                        json={'instituteId': institute_id},
                        headers={'X-API-Key': api_key} if api_key else {},
                        timeout=5
                    )
            except:
                pass  # Ignore Node.js notification errors
            
            return jsonify({
                'success': True, 
                'message': 'WhatsApp connection is now permanent for all users'
            })
        else:
            return jsonify({'success': False, 'message': 'Failed to update'}), 500
            
    except Exception as e:
        print(f"Error marking master connected: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@whatsapp_bp.route('/api/logout', methods=['POST'])
@role_required(['admin', 'owner'])
def logout_whatsapp():
    """Logout WhatsApp - ONLY MASTER USER"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    user_email = user.get('email', '')
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    if not is_master_user(user_email):
        return jsonify({
            'success': False, 
            'message': 'Only the administrator can disconnect WhatsApp'
        }), 403
    
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
            # Don't clear master_connected - keep it permanent
            return jsonify({'success': True, 'message': 'Disconnected successfully'})
        else:
            return jsonify({'success': False, 'message': f'Failed to logout: {response.status_code}'}), 500
            
    except requests.exceptions.ConnectionError:
        return jsonify({'success': False, 'message': 'WhatsApp server not reachable'}), 500
    except Exception as e:
        print(f"Error logging out: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@whatsapp_bp.route('/api/send-message', methods=['POST'])
@role_required(['admin', 'owner', 'teacher'])
def send_message():
    """Send a WhatsApp message - ALL USERS CAN SEND in GLOBAL mode"""
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
        
        # GLOBAL MODE: Don't check master_connected - just check if enabled
        if not settings.get('is_enabled', True):
            return jsonify({
                'success': False, 
                'message': 'WhatsApp is disabled for this institute. Please enable it first.'
            }), 400
        
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
            timeout=120  # Increased timeout for large files
        )
        
        if response.status_code == 200:
            return jsonify({'success': True, 'message': 'Message sent successfully'})
        else:
            return jsonify({'success': False, 'message': f'Failed to send: {response.status_code} - {response.text}'}), 500
            
    except requests.exceptions.ConnectionError:
        return jsonify({'success': False, 'message': 'WhatsApp server not reachable'}), 500
    except requests.exceptions.Timeout:
        return jsonify({'success': False, 'message': 'Request timed out. Please try again.'}), 500
    except Exception as e:
        print(f"Error sending message: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@whatsapp_bp.route('/api/send-pdf', methods=['POST'])
@role_required(['admin', 'owner', 'teacher'])
def send_pdf():
    """Send a PDF via WhatsApp - ALL USERS CAN SEND in GLOBAL mode"""
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
        
        # GLOBAL MODE: Don't check master_connected - just check if enabled
        if not settings.get('is_enabled', True):
            return jsonify({
                'success': False, 
                'message': 'WhatsApp is disabled for this institute. Please enable it first.'
            }), 400
        
        nodejs_url = settings.get('nodejs_api_url', '').rstrip('/')
        api_key = settings.get('api_key', '')
        
        if not nodejs_url:
            return jsonify({'success': False, 'message': 'Node.js API URL not configured'}), 400
        
        # Log file size for debugging
        pdf_size = len(pdf_base64) / 1024 / 1024  # Size in MB
        print(f"📄 Sending PDF: {filename}, Size: {pdf_size:.2f} MB")
        
        # Increase timeout for large files
        timeout = 120 if pdf_size > 5 else 60
        
        response = requests.post(
            f"{nodejs_url}/api/send-pdf",
            json={
                'number': phone_number,
                'pdfBuffer': pdf_base64,
                'filename': filename,
                'instituteId': institute_id
            },
            headers={'X-API-Key': api_key} if api_key else {},
            timeout=timeout
        )
        
        if response.status_code == 200:
            return jsonify({'success': True, 'message': 'PDF sent successfully'})
        else:
            print(f"PDF send failed: {response.status_code} - {response.text}")
            return jsonify({'success': False, 'message': f'Failed to send PDF: {response.status_code}'}), 500
            
    except requests.exceptions.ConnectionError:
        return jsonify({'success': False, 'message': 'WhatsApp server not reachable'}), 500
    except requests.exceptions.Timeout:
        return jsonify({'success': False, 'message': 'Request timed out. The file might be too large.'}), 500
    except Exception as e:
        print(f"Error sending PDF: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@whatsapp_bp.route('/test')
@role_required(['admin', 'owner'])
def test_page():
    """WhatsApp API Test Page"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    user_email = user.get('email', '')
    
    return render_template('whatsapp/test.html', 
                         institute_id=institute_id,
                         is_master=is_master_user(user_email))


# ==================== ADDITIONAL HELPER ROUTES ====================

@whatsapp_bp.route('/api/check-master', methods=['GET'])
@role_required(['admin', 'owner'])
def check_master():
    """Check if current user is master"""
    user = session.get('user')
    user_email = user.get('email', '')
    
    return jsonify({
        'success': True,
        'is_master': is_master_user(user_email),
        'master_email': MASTER_EMAIL
    })


@whatsapp_bp.route('/api/force-enable', methods=['POST'])
@role_required(['admin', 'owner'])
def force_enable():
    """Force enable WhatsApp for an institute"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    user_email = user.get('email', '')
    
    if not is_master_user(user_email):
        return jsonify({'success': False, 'message': 'Only the administrator can force enable'}), 403
    
    try:
        result = supabase.table('whatsapp_settings_custom')\
            .update({
                'is_enabled': True,
                'master_connected': True,
                'updated_at': datetime.now().isoformat()
            })\
            .eq('institute_id', institute_id)\
            .execute()
        
        if result.data:
            return jsonify({
                'success': True,
                'message': 'WhatsApp force enabled successfully'
            })
        else:
            return jsonify({'success': False, 'message': 'Failed to force enable'}), 500
            
    except Exception as e:
        print(f"Error force enabling: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    
    
    
# Add this to whatsappIntegrationSettings.py

@whatsapp_bp.route('/api/connect', methods=['POST'])
@role_required(['admin', 'owner'])
def connect_whatsapp():
    """Connect WhatsApp using phone number pairing - MASTER ONLY"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    user_email = user.get('email', '')
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    if not is_master_user(user_email):
        return jsonify({
            'success': False, 
            'message': 'Only the administrator can connect WhatsApp.'
        }), 403
    
    try:
        data = request.get_json()
        phone_number = data.get('phoneNumber', '').strip()
        
        if not phone_number:
            return jsonify({'success': False, 'message': 'Phone number is required'}), 400
        
        # Format phone number
        phone_number = phone_number.replace('+', '').strip()
        if not phone_number.isdigit():
            return jsonify({'success': False, 'message': 'Invalid phone number format'}), 400
        
        settings = get_or_create_settings(institute_id)
        
        if not settings:
            return jsonify({'success': False, 'message': 'WhatsApp not configured'}), 400
        
        nodejs_url = settings.get('nodejs_api_url', '').rstrip('/')
        api_key = settings.get('api_key', '')
        
        if not nodejs_url:
            return jsonify({'success': False, 'message': 'Node.js API URL not configured'}), 400
        
        response = requests.post(
            f"{nodejs_url}/api/connect",
            json={
                'phoneNumber': phone_number,
                'instituteId': institute_id
            },
            headers={'X-API-Key': api_key} if api_key else {},
            timeout=60
        )
        
        if response.status_code == 200:
            result = response.json()
            return jsonify({'success': True, 'result': result})
        else:
            return jsonify({
                'success': False, 
                'message': f'Failed to connect: {response.status_code} - {response.text}'
            }), 500
            
    except requests.exceptions.ConnectionError:
        return jsonify({'success': False, 'message': 'WhatsApp server not reachable'}), 500
    except Exception as e:
        print(f"Error connecting: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500