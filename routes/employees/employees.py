# employees.py - Employee Management Blueprint
from flask import Blueprint, render_template, request, jsonify, session, send_file
from supabase import create_client, Client
import os
import uuid
import random
import string
from datetime import datetime
import json
import io
from functools import wraps
from dotenv import load_dotenv
import cloudinary
import cloudinary.uploader
from werkzeug.security import generate_password_hash

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Configure Cloudinary
cloudinary.config(
    cloud_name=os.getenv('CLOUDINARY_CLOUD_NAME'),
    api_key=os.getenv('CLOUDINARY_API_KEY'),
    api_secret=os.getenv('CLOUDINARY_API_SECRET'),
    secure=True
)

employees_bp = Blueprint('employees', __name__, url_prefix='/employees')

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

def generate_employee_id(institute_id):
    """Generate unique employee ID"""
    try:
        year = datetime.now().strftime('%Y')
        
        # Get count of employees this year
        response = supabase.table('employees')\
            .select('id', count='exact')\
            .eq('institute_id', institute_id)\
            .gte('created_at', f"{year}-01-01")\
            .execute()
        
        count = (response.count or 0) + 1
        return f"EMP-{year}-{str(count).zfill(4)}"
    except:
        return f"EMP-{datetime.now().strftime('%Y%m%d%H%M%S')}"

@employees_bp.route('/')
@login_required
def index():
    """Employees Management Page"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return render_template('employees/index.html', institute=None)
    
    return render_template('employees/index.html', institute_id=institute_id)

@employees_bp.route('/api/employees', methods=['GET'])
@login_required
def get_employees():
    """Get all employees via API"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        response = supabase.table('employees')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('created_at', desc=True)\
            .execute()
        
        employees = response.data if response.data else []
        
        return jsonify({'success': True, 'employees': employees})
        
    except Exception as e:
        print(f"Error fetching employees: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@employees_bp.route('/api/employees/<employee_id>', methods=['GET'])
@login_required
def get_employee(employee_id):
    """Get single employee details"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        response = supabase.table('employees')\
            .select('*')\
            .eq('id', employee_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if response.data:
            return jsonify({'success': True, 'employee': response.data[0]})
        else:
            return jsonify({'success': False, 'message': 'Employee not found'}), 404
            
    except Exception as e:
        print(f"Error fetching employee: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@employees_bp.route('/api/employees/create', methods=['POST'])
@login_required
def create_employee():
    """Create new employee"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        
        # Generate employee ID
        employee_id = generate_employee_id(institute_id)
        
        # Default password (will be hashed when creating user account)
        default_password = "123"
        
        # Prepare employee data
        employee_data = {
            'id': str(uuid.uuid4()),
            'institute_id': institute_id,
            'employee_id': employee_id,
            'name': data.get('name', '').strip(),
            'gender': data.get('gender'),
            'date_of_birth': data.get('date_of_birth'),
            'date_of_joining': data.get('date_of_joining'),
            'father_husband_name': data.get('father_husband_name', '').strip(),
            'national_id': data.get('national_id', '').strip(),
            'education': data.get('education', '').strip(),
            'home_address': data.get('home_address', '').strip(),
            'experience': data.get('experience', '').strip(),
            'email': data.get('email', '').strip(),
            'phone': data.get('phone', '').strip(),
            'monthly_salary': float(data.get('monthly_salary', 0)),
            'role': data.get('role'),  # teacher, accountant, librarian, secretary, support_staff, other
            'status': 'active',
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        # Handle photo upload
        if data.get('photo_data'):
            try:
                import base64
                import tempfile
                
                photo_data = data['photo_data'].split(',')[1] if ',' in data['photo_data'] else data['photo_data']
                image_bytes = base64.b64decode(photo_data)
                
                with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp_file:
                    tmp_file.write(image_bytes)
                    tmp_path = tmp_file.name
                
                upload_result = cloudinary.uploader.upload(
                    tmp_path,
                    folder=f"employee_photos/{institute_id}",
                    public_id=f"{employee_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                    overwrite=True
                )
                
                employee_data['photo_url'] = upload_result['secure_url']
                employee_data['photo_public_id'] = upload_result['public_id']
                
                os.unlink(tmp_path)
                
            except Exception as e:
                print(f"Photo upload error: {e}")
        
        # Insert employee
        result = supabase.table('employees').insert(employee_data).execute()
        
        if result.data:
            # Create user account for employee
            try:
                # Check if user already exists with this email
                existing_user = supabase.table('users')\
                    .select('id')\
                    .eq('email', employee_data['email'])\
                    .execute()
                
                if not existing_user.data:
                    # Create user account with role-based permissions
                    user_id = str(uuid.uuid4())
                    user_data = {
                        'id': user_id,
                        'email': employee_data['email'],
                        'password_hash': generate_password_hash(default_password),
                        'role': employee_data['role'],
                        'employee_id': result.data[0]['id'],
                        'institute_id': institute_id,
                        'is_active': True,
                        'created_at': datetime.now().isoformat()
                    }
                    
                    supabase.table('users').insert(user_data).execute()
            except Exception as e:
                print(f"Error creating user account: {e}")
                # Don't fail the employee creation if user account fails
            
            return jsonify({
                'success': True,
                'message': f'Employee created successfully. Employee ID: {employee_id}, Default Password: {default_password}',
                'employee': result.data[0]
            })
        else:
            return jsonify({'success': False, 'message': 'Failed to create employee'}), 500
            
    except Exception as e:
        print(f"Error creating employee: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@employees_bp.route('/api/employees/update/<employee_id>', methods=['PUT'])
@login_required
def update_employee(employee_id):
    """Update employee details"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        
        # Prepare update data
        update_data = {
            'name': data.get('name', '').strip(),
            'gender': data.get('gender'),
            'date_of_birth': data.get('date_of_birth'),
            'date_of_joining': data.get('date_of_joining'),
            'father_husband_name': data.get('father_husband_name', '').strip(),
            'national_id': data.get('national_id', '').strip(),
            'education': data.get('education', '').strip(),
            'home_address': data.get('home_address', '').strip(),
            'experience': data.get('experience', '').strip(),
            'email': data.get('email', '').strip(),
            'phone': data.get('phone', '').strip(),
            'monthly_salary': float(data.get('monthly_salary', 0)),
            'role': data.get('role'),
            'updated_at': datetime.now().isoformat()
        }
        
        # Handle photo upload
        if data.get('photo_data') and not data.get('photo_data').startswith('http'):
            try:
                import base64
                import tempfile
                
                photo_data = data['photo_data'].split(',')[1] if ',' in data['photo_data'] else data['photo_data']
                image_bytes = base64.b64decode(photo_data)
                
                with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp_file:
                    tmp_file.write(image_bytes)
                    tmp_path = tmp_file.name
                
                # Delete old photo if exists
                old_employee = supabase.table('employees').select('photo_public_id').eq('id', employee_id).execute()
                if old_employee.data and old_employee.data[0].get('photo_public_id'):
                    try:
                        cloudinary.uploader.destroy(old_employee.data[0]['photo_public_id'])
                    except:
                        pass
                
                upload_result = cloudinary.uploader.upload(
                    tmp_path,
                    folder=f"employee_photos/{institute_id}",
                    public_id=f"{employee_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                    overwrite=True
                )
                
                update_data['photo_url'] = upload_result['secure_url']
                update_data['photo_public_id'] = upload_result['public_id']
                
                os.unlink(tmp_path)
                
            except Exception as e:
                print(f"Photo upload error: {e}")
        
        # Update employee
        result = supabase.table('employees')\
            .update(update_data)\
            .eq('id', employee_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if result.data:
            return jsonify({
                'success': True,
                'message': 'Employee updated successfully',
                'employee': result.data[0]
            })
        else:
            return jsonify({'success': False, 'message': 'Employee not found'}), 404
            
    except Exception as e:
        print(f"Error updating employee: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@employees_bp.route('/api/employees/delete/<employee_id>', methods=['DELETE'])
@login_required
def delete_employee(employee_id):
    """Delete employee"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Delete employee photo from Cloudinary if exists
        employee_response = supabase.table('employees')\
            .select('photo_public_id')\
            .eq('id', employee_id)\
            .execute()
        
        if employee_response.data and employee_response.data[0].get('photo_public_id'):
            try:
                cloudinary.uploader.destroy(employee_response.data[0]['photo_public_id'])
            except:
                pass
        
        # Delete employee
        result = supabase.table('employees')\
            .delete()\
            .eq('id', employee_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if result.data:
            return jsonify({'success': True, 'message': 'Employee deleted successfully'})
        else:
            return jsonify({'success': False, 'message': 'Employee not found'}), 404
            
    except Exception as e:
        print(f"Error deleting employee: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@employees_bp.route('/api/employees/toggle-status/<employee_id>', methods=['PUT'])
@login_required
def toggle_status(employee_id):
    """Toggle employee status (active/inactive)"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        status = data.get('status')
        
        result = supabase.table('employees')\
            .update({'status': status, 'updated_at': datetime.now().isoformat()})\
            .eq('id', employee_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if result.data:
            return jsonify({'success': True, 'message': f'Employee marked as {status}'})
        else:
            return jsonify({'success': False, 'message': 'Employee not found'}), 404
            
    except Exception as e:
        print(f"Error toggling status: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@employees_bp.route('/api/stats', methods=['GET'])
@login_required
def get_stats():
    """Get employee statistics"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        response = supabase.table('employees')\
            .select('status, role')\
            .eq('institute_id', institute_id)\
            .execute()
        
        employees = response.data if response.data else []
        
        total = len(employees)
        active = sum(1 for e in employees if e.get('status') == 'active')
        inactive = total - active
        
        # Count by role
        teachers = sum(1 for e in employees if e.get('role') == 'teacher')
        accountants = sum(1 for e in employees if e.get('role') == 'accountant')
        librarians = sum(1 for e in employees if e.get('role') == 'librarian')
        secretaries = sum(1 for e in employees if e.get('role') == 'secretary')
        support_staff = sum(1 for e in employees if e.get('role') == 'support_staff')
        other = sum(1 for e in employees if e.get('role') == 'other')
        
        return jsonify({
            'success': True,
            'stats': {
                'total': total,
                'active': active,
                'inactive': inactive,
                'teachers': teachers,
                'accountants': accountants,
                'librarians': librarians,
                'secretaries': secretaries,
                'support_staff': support_staff,
                'other': other
            }
        })
        
    except Exception as e:
        print(f"Error getting stats: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500