# permissions_management.py - Fixed for your database schema
from flask import Blueprint, render_template, request, jsonify, session, current_app
from supabase import create_client, Client
import os
from functools import wraps
from dotenv import load_dotenv
from routes.permissions.permissions import PermissionManager, get_all_routes

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

permissions_bp = Blueprint('permissions', __name__, url_prefix='/permissions')

def admin_required(f):
    """Decorator for admin-only access"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Please login'}), 401
        
        user = session.get('user', {})
        user_role = user.get('role')
        
        # Only owner/admin can manage permissions
        if user.get('is_employee') or user_role not in ['owner', 'admin']:
            return jsonify({'success': False, 'message': 'Admin access required'}), 403
        
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
    except Exception:
        return None

@permissions_bp.route('/')
@admin_required
def index():
    """Permissions Management Page"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return render_template('permissions/index.html', employees=[], grouped_routes={})
    
    try:
        # Get all employees for this institute
        employees_response = supabase.table('employees')\
            .select('id, name, employee_id, role')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')\
            .order('name')\
            .execute()
        
        employees = employees_response.data if employees_response.data else []
        
        # Get all routes and group them by category
        routes = get_all_routes()
        grouped_routes = {}
        for route in routes:
            category = route['category']
            if category not in grouped_routes:
                grouped_routes[category] = []
            grouped_routes[category].append(route)
        
        return render_template('permissions/index.html', employees=employees, grouped_routes=grouped_routes)
        
    except Exception as e:
        print(f"Error loading permissions page: {e}")
        import traceback
        traceback.print_exc()
        return render_template('permissions/index.html', employees=[], grouped_routes={})

@permissions_bp.route('/api/employees', methods=['GET'])
@admin_required
def get_employees():
    """Get all employees for permissions management"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        response = supabase.table('employees')\
            .select('id, name, employee_id, role')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')\
            .order('name')\
            .execute()
        
        employees = response.data if response.data else []
        
        # Get permission summary for each employee
        for emp in employees:
            permissions = PermissionManager.get_employee_permissions(emp['id'])
            emp['has_custom_permissions'] = len(permissions) > 0
            emp['permissions_count'] = len(permissions)
        
        return jsonify({'success': True, 'employees': employees})
        
    except Exception as e:
        print(f"Error getting employees: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@permissions_bp.route('/api/routes', methods=['GET'])
@admin_required
def get_routes():
    """Get all available routes in the system"""
    routes = get_all_routes()
    return jsonify({'success': True, 'routes': routes})

@permissions_bp.route('/api/employee/<employee_id>/permissions', methods=['GET'])
@admin_required
def get_employee_permissions(employee_id):
    """Get permissions for a specific employee"""
    try:
        permissions = PermissionManager.get_employee_permissions(employee_id)
        routes = get_all_routes()
        
        return jsonify({
            'success': True, 
            'permissions': permissions,
            'routes': routes
        })
        
    except Exception as e:
        print(f"Error getting employee permissions: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@permissions_bp.route('/api/employee/<employee_id>/permissions', methods=['POST'])
@admin_required
def save_employee_permissions(employee_id):
    """Save permissions for an employee"""
    try:
        data = request.get_json()
        permissions = data.get('permissions', {})
        
        success = PermissionManager.save_employee_permissions(employee_id, permissions)
        
        if success:
            return jsonify({'success': True, 'message': 'Permissions saved successfully'})
        else:
            return jsonify({'success': False, 'message': 'Failed to save permissions'}), 500
            
    except Exception as e:
        print(f"Error saving employee permissions: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@permissions_bp.route('/api/employee/<employee_id>/permissions/reset', methods=['POST'])
@admin_required
def reset_employee_permissions(employee_id):
    """Reset employee permissions to default"""
    try:
        success = PermissionManager.reset_employee_permissions(employee_id)
        
        if success:
            return jsonify({'success': True, 'message': 'Permissions reset to default'})
        else:
            return jsonify({'success': False, 'message': 'Failed to reset permissions'}), 500
            
    except Exception as e:
        print(f"Error resetting employee permissions: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@permissions_bp.route('/api/employee/<employee_id>/summary', methods=['GET'])
@admin_required
def get_permission_summary(employee_id):
    """Get permission summary for an employee"""
    try:
        summary = PermissionManager.get_permission_summary(employee_id)
        return jsonify({'success': True, 'summary': summary})
        
    except Exception as e:
        print(f"Error getting permission summary: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500