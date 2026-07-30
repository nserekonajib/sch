# registeredUserDetails.py - Admin route to view all registered users
from flask import Blueprint, render_template, request, jsonify, session
from supabase import create_client, Client
import os
from datetime import datetime, timedelta
from functools import wraps
from dotenv import load_dotenv

load_dotenv()

# Initialize Supabase client with service role key for admin operations
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_SERVICE_KEY = os.getenv('SUPABASE_SERVICE_KEY')  # This should be the service role key

# IMPORTANT: Use service key for admin operations
supabase_admin: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# Also keep regular client for non-admin operations if needed
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

registered_users_bp = Blueprint('registered_users', __name__, url_prefix='/admin/users')

def admin_required(f):
    """Decorator to require admin access"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Please login'}), 401
        user_email = session.get('user', {}).get('email', '')
        admin_emails = os.getenv('ADMIN_EMAILS', '').split(',')
        if user_email not in admin_emails:
            return jsonify({'success': False, 'message': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated_function

def get_all_users():
    """Fetch all users from Supabase Auth using admin client with service key"""
    try:
        # Use the admin client with service role key
        response = supabase_admin.auth.admin.list_users()
        
        # Check if response has users attribute
        if hasattr(response, 'users'):
            users = response.users
        elif isinstance(response, dict) and 'users' in response:
            users = response['users']
        elif isinstance(response, list):
            users = response
        else:
            # Try to access as attribute
            users = getattr(response, 'data', [])
            if not users:
                users = getattr(response, 'users', [])
        
        print(f"Found {len(users) if users else 0} users")
        return users if users else []
        
    except Exception as e:
        print(f"Error fetching users: {e}")
        import traceback
        traceback.print_exc()
        return []

def format_date(date_str):
    """Format date string for display"""
    if not date_str:
        return 'Never'
    try:
        # Handle different date formats
        if isinstance(date_str, datetime):
            return date_str.strftime('%b %d, %Y %I:%M %p')
        
        # Remove timezone info if present
        date_str = date_str.replace('Z', '+00:00')
        dt = datetime.fromisoformat(date_str)
        return dt.strftime('%b %d, %Y %I:%M %p')
    except Exception as e:
        print(f"Date formatting error: {e}")
        return str(date_str)

def get_user_status(user):
    """Determine user status based on metadata"""
    # Handle both dict and object access
    if hasattr(user, 'get'):
        metadata = user.get('user_metadata', {})
        banned_until = user.get('banned_until')
    else:
        # If it's an object with attributes
        metadata = getattr(user, 'user_metadata', {})
        banned_until = getattr(user, 'banned_until', None)
    
    if banned_until:
        try:
            ban_date = datetime.fromisoformat(str(banned_until).replace('Z', '+00:00'))
            if ban_date > datetime.now(ban_date.tzinfo):
                return 'banned'
        except:
            pass
    
    # Check if user has been confirmed
    if hasattr(user, 'get'):
        confirmed_at = user.get('confirmed_at')
    else:
        confirmed_at = getattr(user, 'confirmed_at', None)
    
    if not confirmed_at:
        return 'pending'
    
    return 'active'

def safe_get(user, key, default='Not set'):
    """Safely get value from user dict or object"""
    try:
        if hasattr(user, 'get'):
            return user.get(key, default)
        else:
            return getattr(user, key, default)
    except:
        return default

@registered_users_bp.route('/')
@admin_required
def index():
    """Display all registered users"""
    users = get_all_users()
    
    print(f"Processing {len(users) if users else 0} users for display")
    
    # Process user data for display
    user_list = []
    for user in users:
        # Handle both dict and object access
        try:
            if hasattr(user, 'get'):
                # Dict access
                user_id = user.get('id', '')
                email = user.get('email', '')
                metadata = user.get('user_metadata', {})
                created_at = user.get('created_at', '')
                last_sign_in_at = user.get('last_sign_in_at', '')
                confirmed_at = user.get('confirmed_at', '')
                banned_until = user.get('banned_until')
            else:
                # Object attribute access
                user_id = getattr(user, 'id', '')
                email = getattr(user, 'email', '')
                metadata = getattr(user, 'user_metadata', {})
                created_at = getattr(user, 'created_at', '')
                last_sign_in_at = getattr(user, 'last_sign_in_at', '')
                confirmed_at = getattr(user, 'confirmed_at', '')
                banned_until = getattr(user, 'banned_until', None)
            
            user_list.append({
                'id': user_id,
                'email': email or 'No email',
                'display_name': metadata.get('display_name', metadata.get('institute_name', 'Not set')),
                'institute_name': metadata.get('institute_name', 'Not set'),
                'phone': metadata.get('phone', 'Not set'),
                'role': metadata.get('role', 'user'),
                'status': get_user_status(user),
                'created_at': format_date(created_at),
                'last_sign_in': format_date(last_sign_in_at),
                'confirmed_at': format_date(confirmed_at),
                'providers': ['email'],
                'is_anonymous': False,
                'banned_until': banned_until
            })
        except Exception as e:
            print(f"Error processing user: {e}")
            continue
    
    # Sort by created_at (newest first)
    user_list.sort(key=lambda x: x['created_at'], reverse=True)
    
    # Statistics
    stats = {
        'total': len(user_list),
        'active': sum(1 for u in user_list if u['status'] == 'active'),
        'banned': sum(1 for u in user_list if u['status'] == 'banned'),
        'pending': sum(1 for u in user_list if u['status'] == 'pending'),
        'owners': sum(1 for u in user_list if u['role'] == 'owner'),
        'today': sum(1 for u in user_list if u['created_at'].startswith(datetime.now().strftime('%b %d, %Y')))
    }
    
    print(f"Stats: {stats}")
    
    return render_template('admin/users.html', users=user_list, stats=stats, datetime=datetime)

@registered_users_bp.route('/api/users')
@admin_required
def get_users_api():
    """API endpoint to get all users as JSON"""
    users = get_all_users()
    user_list = []
    for user in users:
        try:
            if hasattr(user, 'get'):
                metadata = user.get('user_metadata', {})
                user_list.append({
                    'id': user.get('id'),
                    'email': user.get('email'),
                    'display_name': metadata.get('display_name', metadata.get('institute_name', 'Not set')),
                    'institute_name': metadata.get('institute_name', 'Not set'),
                    'phone': metadata.get('phone', 'Not set'),
                    'role': metadata.get('role', 'user'),
                    'status': get_user_status(user),
                    'created_at': user.get('created_at'),
                    'last_sign_in': user.get('last_sign_in_at'),
                    'providers': user.get('providers', ['email'])
                })
            else:
                metadata = getattr(user, 'user_metadata', {})
                user_list.append({
                    'id': getattr(user, 'id', None),
                    'email': getattr(user, 'email', None),
                    'display_name': metadata.get('display_name', metadata.get('institute_name', 'Not set')),
                    'institute_name': metadata.get('institute_name', 'Not set'),
                    'phone': metadata.get('phone', 'Not set'),
                    'role': metadata.get('role', 'user'),
                    'status': get_user_status(user),
                    'created_at': getattr(user, 'created_at', None),
                    'last_sign_in': getattr(user, 'last_sign_in_at', None),
                    'providers': ['email']
                })
        except Exception as e:
            print(f"Error in API: {e}")
            continue
    return jsonify({'success': True, 'users': user_list, 'total': len(user_list)})

@registered_users_bp.route('/api/user/<user_id>/status', methods=['POST'])
@admin_required
def update_user_status(user_id):
    """Update user status (ban/unban)"""
    try:
        data = request.get_json()
        action = data.get('action')  # 'ban' or 'unban'
        
        if action == 'ban':
            # Ban user for 1 year
            ban_until = (datetime.now() + timedelta(days=365)).isoformat()
            response = supabase_admin.auth.admin.update_user_by_id(
                user_id,
                {"banned_until": ban_until}
            )
            message = "User banned successfully"
        elif action == 'unban':
            # Unban user
            response = supabase_admin.auth.admin.update_user_by_id(
                user_id,
                {"banned_until": None}
            )
            message = "User unbanned successfully"
        else:
            return jsonify({'success': False, 'message': 'Invalid action'}), 400
        
        return jsonify({'success': True, 'message': message})
        
    except Exception as e:
        print(f"Error updating user status: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@registered_users_bp.route('/api/user/<user_id>', methods=['DELETE'])
@admin_required
def delete_user(user_id):
    """Delete a user (admin only)"""
    try:
        response = supabase_admin.auth.admin.delete_user(user_id)
        return jsonify({'success': True, 'message': 'User deleted successfully'})
    except Exception as e:
        print(f"Error deleting user: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    
@registered_users_bp.route('/test')
@admin_required
def test():
    """Test route to check Supabase connection"""
    try:
        # Test if we can list users
        response = supabase_admin.auth.admin.list_users()
        
        # Check what type of response we get
        return jsonify({
            'success': True,
            'has_users': hasattr(response, 'users'),
            'has_data': hasattr(response, 'data'),
            'response_type': str(type(response)),
            'response_dir': dir(response) if hasattr(response, '__dir__') else [],
            'sample': str(response)[:500] if response else None
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'type': str(type(e))})