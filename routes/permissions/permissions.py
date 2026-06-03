# permissions.py - Fixed get_current_employee_id to return UUID
from functools import wraps
from flask import session, request, redirect, url_for, flash, current_app
from supabase import create_client, Client
import os
import re
from datetime import datetime
import uuid
import json

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def get_institute_id(user_id):
    """Get institute ID for the current user - can accept either user_id or employee_id"""
    try:
        # First, check if this is an employee UUID
        employee_response = supabase.table('employees')\
            .select('institute_id')\
            .eq('id', user_id)\
            .execute()
        
        if employee_response.data:
            return employee_response.data[0]['institute_id']
        
        # Check if this is an employee by employee_id string
        emp_by_code = supabase.table('employees')\
            .select('institute_id')\
            .eq('employee_id', user_id)\
            .execute()
        
        if emp_by_code.data:
            return emp_by_code.data[0]['institute_id']
        
        # Otherwise, treat as user_id from auth
        response = supabase.table('institutes')\
            .select('id')\
            .eq('user_id', user_id)\
            .execute()
        
        if response.data and len(response.data) > 0:
            return response.data[0]['id']
        return None
    except Exception:
        return None


def get_current_employee_id():
    """Get employee UUID for the currently logged in user"""
    try:
        user = session.get('user', {})
        
        # If user already has employee_uuid in session, use it directly
        if 'employee_uuid' in user and user['employee_uuid']:
            return user['employee_uuid']
        
        # For institute owners (no employee record)
        is_employee = user.get('is_employee', False)
        if not is_employee:
            return None
        
        # Get institute_id first
        institute_id = get_institute_id(user.get('id'))
        if not institute_id:
            return None
        
        # For employees, try to find by email
        user_email = user.get('email', '')
        if user_email:
            response = supabase.table('employees')\
                .select('id')\
                .eq('institute_id', institute_id)\
                .eq('email', user_email)\
                .eq('status', 'active')\
                .execute()
            
            if response.data and len(response.data) > 0:
                employee_uuid = response.data[0]['id']
                # Store in session for future use
                session['user']['employee_uuid'] = employee_uuid
                return employee_uuid
        
        # Try to find by name (fallback)
        user_name = user.get('name', '')
        if user_name:
            response = supabase.table('employees')\
                .select('id')\
                .eq('institute_id', institute_id)\
                .ilike('name', user_name)\
                .eq('status', 'active')\
                .execute()
            
            if response.data and len(response.data) > 0:
                employee_uuid = response.data[0]['id']
                session['user']['employee_uuid'] = employee_uuid
                return employee_uuid
        
        return None
    except Exception as e:
        print(f"Error getting employee ID: {e}")
        return None


def get_route_category(route_name):
    """Categorize route by its blueprint prefix"""
    categories = {
        'students': 'Student Management',
        'employees': 'Employee Management', 
        'fees': 'Fee Management',
        'collect': 'Fee Collection',
        'exams': 'Exam Management',
        'attendance': 'Student Attendance',
        'staff_attendance': 'Staff Attendance',
        'library': 'Library Management',
        'inventory': 'Inventory Management',
        'attendance_report': 'Attendance Reports',
        'staff_attendance_report': 'Staff Attendance Reports',
        'payroll': 'Payroll Management',
        'results': 'Results Card',
        'houses': 'Student Houses',
        'accounts': 'Accounts Management',
        'grading': 'Grading Settings',
        'sms_settings': 'SMS Settings',
        'requirements': 'Requirements Management',
        'promote': 'Student Promotion',
        'employee_id': 'Employee ID Cards',
        'id': 'Student ID Cards',
        'billing': 'Billing',
        'admin': 'Admin Panel',
        'agent': 'Agent Management',
        'edit_invoice': 'Invoice Editing',
        'schoolpay': 'SchoolPay Integration',
        'sync_schoolpay': 'SchoolPay Sync'
        
        
    }
    
    for prefix, category in categories.items():
        if route_name.startswith(prefix):
            return category
    
    return 'Other Modules'


def get_all_routes():
    """Get all registered routes in the application"""
    routes = []
    seen_endpoints = set()
    
    for rule in current_app.url_map.iter_rules():
        endpoint = rule.endpoint
        
        # Skip static files and debug routes
        if endpoint in seen_endpoints or endpoint == 'static' or endpoint.startswith('_'):
            continue
        
        # Skip admin routes if not needed
        if endpoint.startswith('admin'):
            continue
        
        seen_endpoints.add(endpoint)
        
        # Determine HTTP methods
        methods = list(rule.methods - {'HEAD', 'OPTIONS'})
        
        routes.append({
            'endpoint': endpoint,
            'url': rule.rule,
            'methods': methods,
            'category': get_route_category(endpoint),
            'description': endpoint.replace('_', ' ').title()
        })
    
    # Sort by category then endpoint
    routes.sort(key=lambda x: (x['category'], x['endpoint']))
    
    return routes


def get_employee_permissions(employee_id):
    """Get permissions for a specific employee from the database"""
    try:
        if not employee_id:
            return {}
        
        # Validate that employee_id is a UUID
        try:
            uuid.UUID(str(employee_id))
        except ValueError:
            print(f"Invalid UUID format for employee_id: {employee_id}")
            return {}
        
        response = supabase.table('employee_permissions')\
            .select('permissions')\
            .eq('employee_id', employee_id)\
            .execute()
        
        if response.data and response.data[0].get('permissions'):
            permissions = response.data[0]['permissions']
            if isinstance(permissions, str):
                permissions = json.loads(permissions)
            return permissions
        
        return {}
        
    except Exception as e:
        print(f"Error getting employee permissions: {e}")
        return {}


def check_route_permission(employee_id, endpoint):
    """
    Check if employee has explicit permission for a specific route.
    Returns: True (allowed), False (denied), None (not configured - use role)
    """
    if not employee_id:
        return None
    
    permissions = get_employee_permissions(employee_id)
    
    # Check for explicit route permission (both true and false)
    if endpoint in permissions:
        # Return the exact value (True for allow, False for deny)
        return permissions[endpoint] is True
    
    # Check for category-level permission
    category = get_route_category(endpoint)
    category_key = f"category:{category}"
    
    if category_key in permissions:
        return permissions[category_key] is True
    
    # No explicit configuration - fall back to role-based access
    return None


def role_required(allowed_roles):
    """
    Enhanced decorator that checks explicit database permissions first,
    then falls back to role-based access control for unconfigured routes.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Check if user is logged in
            if 'user' not in session:
                flash('Please login to access this page', 'warning')
                return redirect(url_for('auth.login'))
            
            user = session.get('user', {})
            is_employee = user.get('is_employee', False)
            user_role = user.get('role')
            endpoint = request.endpoint
            
            # Get employee_id for permission check (returns UUID)
            employee_id = get_current_employee_id()
            
            # =============================================
            # STEP 1: CHECK EXPLICIT DATABASE PERMISSIONS
            # =============================================
            if employee_id:
                permissions = get_employee_permissions(employee_id)
                
                # Check specific route permission
                if endpoint in permissions:
                    if permissions[endpoint] is True:
                        return f(*args, **kwargs)
                    else:
                        flash(f'Access denied. This action has been disabled for your account.', 'error')
                        return redirect(url_for('dashboard.index'))
                
                # Check for category-level permission
                category = get_route_category(endpoint)
                category_key = f"category:{category}"
                
                if category_key in permissions:
                    if permissions[category_key] is True:
                        return f(*args, **kwargs)
                    else:
                        flash(f'Access denied. The {category} module has been disabled for your account.', 'error')
                        return redirect(url_for('dashboard.index'))
            
            # =============================================
            # STEP 2: FALLBACK TO ROLE-BASED ACCESS
            # =============================================
            # Check if user is institute owner (highest privilege)
            if not is_employee and 'owner' in allowed_roles:
                return f(*args, **kwargs)
            
            # Check if employee has required role
            if is_employee and user_role in allowed_roles:
                return f(*args, **kwargs)
            
            # Access denied - no role match and no explicit permission
            flash('Access denied. Insufficient privileges.', 'error')
            return redirect(url_for('dashboard.index'))
        
        return decorated_function
    return decorator


class PermissionManager:
    """Manage employee permissions - stores BOTH allow and deny states"""
    
    @staticmethod
    def get_all_routes_grouped():
        """Get all routes grouped by category"""
        routes = get_all_routes()
        
        grouped = {}
        for route in routes:
            category = route['category']
            if category not in grouped:
                grouped[category] = []
            grouped[category].append(route)
        
        return grouped
    
    @staticmethod
    def get_employee_permissions(employee_id):
        """Get permissions for a specific employee"""
        try:
            if not employee_id:
                return {}
            
            # Validate UUID format
            try:
                uuid.UUID(str(employee_id))
            except ValueError:
                print(f"Invalid UUID format for employee_id: {employee_id}")
                return {}
            
            response = supabase.table('employee_permissions')\
                .select('permissions')\
                .eq('employee_id', employee_id)\
                .execute()
            
            if response.data and response.data[0].get('permissions'):
                permissions = response.data[0]['permissions']
                if isinstance(permissions, str):
                    permissions = json.loads(permissions)
                return permissions
            
            return {}
            
        except Exception as e:
            print(f"Error getting employee permissions: {e}")
            return {}
    
    @staticmethod
    def save_employee_permissions(employee_id, permissions):
        """Save permissions for an employee - stores explicit allow/deny"""
        try:
            if not employee_id:
                return False
            
            # Get institute_id for this employee
            employee_response = supabase.table('employees')\
                .select('institute_id')\
                .eq('id', employee_id)\
                .execute()
            
            if not employee_response.data:
                return False
            
            institute_id = employee_response.data[0]['institute_id']
            
            # Store permissions as-is (both true and false values)
            clean_permissions = {}
            for key, value in permissions.items():
                if value is not None:
                    clean_permissions[key] = value
            
            # Check if record exists
            existing = supabase.table('employee_permissions')\
                .select('id')\
                .eq('employee_id', employee_id)\
                .execute()
            
            if existing.data:
                # Update existing
                result = supabase.table('employee_permissions')\
                    .update({
                        'permissions': clean_permissions,
                        'updated_at': datetime.now().isoformat()
                    })\
                    .eq('employee_id', employee_id)\
                    .execute()
            else:
                # Create new
                perm_id = str(uuid.uuid4())
                result = supabase.table('employee_permissions')\
                    .insert({
                        'id': perm_id,
                        'employee_id': employee_id,
                        'institute_id': institute_id,
                        'permissions': clean_permissions,
                        'created_at': datetime.now().isoformat(),
                        'updated_at': datetime.now().isoformat()
                    })\
                    .execute()
            
            return result.data is not None
            
        except Exception as e:
            print(f"Error saving employee permissions: {e}")
            return False
    
    @staticmethod
    def reset_employee_permissions(employee_id):
        """Reset employee permissions to default (remove all overrides)"""
        try:
            if not employee_id:
                return False
            
            # Delete permissions record
            result = supabase.table('employee_permissions')\
                .delete()\
                .eq('employee_id', employee_id)\
                .execute()
            
            return True
            
        except Exception as e:
            print(f"Error resetting employee permissions: {e}")
            return False
    
    @staticmethod
    def get_permission_summary(employee_id):
        """Get summary of permissions for an employee"""
        permissions = PermissionManager.get_employee_permissions(employee_id)
        routes = get_all_routes()
        
        # Count configured routes
        total_configured = len(permissions)
        allowed_count = sum(1 for v in permissions.values() if v is True)
        denied_count = sum(1 for v in permissions.values() if v is False)
        
        return {
            'total_routes': len(routes),
            'total_configured': total_configured,
            'explicit_allowed': allowed_count,
            'explicit_denied': denied_count,
            'unconfigured': len(routes) - total_configured
        }