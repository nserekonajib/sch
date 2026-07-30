# auth.py - Authentication Blueprint with Supabase & Separate Employee Login
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from supabase import create_client, Client
import os
from functools import wraps
from dotenv import load_dotenv
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

auth_bp = Blueprint('auth', __name__)

# ========== ROLE-BASED DECORATORS ==========

def login_required(f):
    """Decorator to require login for routes (any user type)"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            flash('Please login to access this page', 'warning')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

def owner_required(f):
    """Decorator to require institute owner login"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            flash('Please login to access this page', 'warning')
            return redirect(url_for('auth.login'))
        if session.get('user', {}).get('is_employee'):
            flash('Access denied. Institute owner access required.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function

def employee_required(f):
    """Decorator to require employee login (any role)"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            flash('Please login to access this page', 'warning')
            return redirect(url_for('auth.employee_login_page'))
        if not session.get('user', {}).get('is_employee'):
            flash('Access denied. Employee access required.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function

def teacher_required(f):
    """Decorator to require teacher role"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            flash('Please login to access this page', 'warning')
            return redirect(url_for('auth.employee_login_page'))
        user_role = session.get('user', {}).get('role')
        if not session.get('user', {}).get('is_employee') or user_role != 'teacher':
            flash('Access denied. Teacher privileges required.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function

def accountant_required(f):
    """Decorator to require accountant role"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            flash('Please login to access this page', 'warning')
            return redirect(url_for('auth.employee_login_page'))
        user_role = session.get('user', {}).get('role')
        if not session.get('user', {}).get('is_employee') or user_role != 'accountant':
            flash('Access denied. Accountant privileges required.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function

def librarian_required(f):
    """Decorator to require librarian role"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            flash('Please login to access this page', 'warning')
            return redirect(url_for('auth.employee_login_page'))
        user_role = session.get('user', {}).get('role')
        if not session.get('user', {}).get('is_employee') or user_role != 'librarian':
            flash('Access denied. Librarian privileges required.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function

def secretary_required(f):
    """Decorator to require secretary role"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            flash('Please login to access this page', 'warning')
            return redirect(url_for('auth.employee_login_page'))
        user_role = session.get('user', {}).get('role')
        if not session.get('user', {}).get('is_employee') or user_role != 'secretary':
            flash('Access denied. Secretary privileges required.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function

def support_staff_required(f):
    """Decorator to require support staff role"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            flash('Please login to access this page', 'warning')
            return redirect(url_for('auth.employee_login_page'))
        user_role = session.get('user', {}).get('role')
        if not session.get('user', {}).get('is_employee') or user_role != 'support_staff':
            flash('Access denied. Support staff privileges required.', 'error')
            return redirect(url_for('dashboard.index'))
        return f(*args, **kwargs)
    return decorated_function

def role_required(allowed_roles):
    """Generic role-based decorator - pass list of allowed roles"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user' not in session:
                flash('Please login to access this page', 'warning')
                return redirect(url_for('auth.login'))
            
            user = session.get('user', {})
            is_employee = user.get('is_employee', False)
            user_role = user.get('role')
            
            # For institute owners (not employees)
            if not is_employee and 'owner' in allowed_roles:
                return f(*args, **kwargs)
            
            # For employees with matching role
            if is_employee and user_role in allowed_roles:
                return f(*args, **kwargs)
            
            flash('Access denied. Insufficient privileges.', 'error')
            return redirect(url_for('dashboard.index'))
        return decorated_function
    return decorator

# ========== OWNER LOGIN ROUTE (Email + Password) ==========

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Owner login route - uses email and password"""
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        
        if not email or not password:
            flash('Please fill in all fields', 'error')
            return redirect(url_for('auth.login'))
        
        try:
            # Attempt to sign in with Supabase
            response = supabase.auth.sign_in_with_password({
                "email": email,
                "password": password
            })
            
            if response.user:
                # Get user metadata
                user_metadata = response.user.user_metadata or {}
                
                # Store user info in session from metadata only
                session['user'] = {
                    'id': response.user.id,
                    'email': response.user.email,
                    'is_employee': False,
                    'role': user_metadata.get('role', 'owner'),
                    'institute_name': user_metadata.get('display_name', user_metadata.get('institute_name', '')),
                    'display_name': user_metadata.get('display_name', user_metadata.get('institute_name', '')),
                    'phone': user_metadata.get('phone', ''),
                    'institute_id': user_metadata.get('institute_id'),
                    'institute_code': user_metadata.get('institute_code')
                }
                
                flash('Login successful! Welcome back!', 'success')
                return redirect(url_for('dashboard.index'))
            else:
                flash('Invalid email or password', 'error')
                
        except Exception as e:
            error_msg = str(e)
            if 'Invalid login credentials' in error_msg:
                flash('Invalid email or password', 'error')
            else:
                flash(f'Login failed: {error_msg}', 'error')
    
    return render_template('auth.html', mode='login')

# ========== EMPLOYEE LOGIN ROUTE (Employee ID + Password) ==========

@auth_bp.route('/employee-login', methods=['GET', 'POST'])
def employee_login():
    """Employee login route - uses Employee ID and password"""
    if request.method == 'POST':
        employee_id = request.form.get('employee_id', '').strip()
        password = request.form.get('password', '')
        
        if not employee_id or not password:
            flash('Please enter your Employee ID and password', 'error')
            return redirect(url_for('auth.employee_login'))
        
        try:
            # Find employee by employee_id (EMP-2024-0001 format)
            employee_response = supabase.table('employees')\
                .select('*')\
                .eq('employee_id', employee_id)\
                .eq('status', 'active')\
                .execute()
            
            if not employee_response.data:
                flash('Invalid Employee ID or password', 'error')
                return redirect(url_for('auth.employee_login'))
            
            employee = employee_response.data[0]
            
            # Verify password hash
            stored_hash = employee.get('password_hash', '')
            if not stored_hash or not check_password_hash(stored_hash, password):
                flash('Invalid Employee ID or password', 'error')
                return redirect(url_for('auth.employee_login'))
            
            # Remove password hash from session
            employee_for_session = {k: v for k, v in employee.items() if k != 'password_hash'}
            employee_for_session['is_employee'] = True
            
            session['user'] = employee_for_session
            
            flash(f'Welcome {employee.get("name", "Employee")}!', 'success')
            return redirect(url_for('dashboard.index'))
            
        except Exception as e:
            print(f"Employee login error: {e}")
            flash('Login failed. Please try again.', 'error')
    
    return render_template('employee_login.html')

# ========== REGISTER ROUTE - SIMPLIFIED (Only stores in user metadata) ==========

@auth_bp.route('/registe', methods=['GET', 'POST'])
def register():
    """Registration route - ONLY stores data in user metadata, no institutes table"""
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        institute_name = request.form.get('institute_name', '').strip()
        phone = request.form.get('phone', '').strip()
        
        # Validation
        if not email or not password or not institute_name:
            flash('Please fill in all required fields', 'error')
            return redirect(url_for('auth.register'))
        
        if password != confirm_password:
            flash('Passwords do not match', 'error')
            return redirect(url_for('auth.register'))
        
        if len(password) < 6:
            flash('Password must be at least 6 characters', 'error')
            return redirect(url_for('auth.register'))
        
        try:
            # Generate institute code
            import random
            import string
            date_str = datetime.now().strftime("%Y%m%d")
            random_suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            institute_code = f"INS{date_str}{random_suffix}"
            
            # Create Supabase auth user with ALL data in metadata
            response = supabase.auth.sign_up({
                "email": email,
                "password": password,
                "options": {
                    "data": {
                        "role": "owner",
                        "institute_name": institute_name,
                        "display_name": institute_name,  # Display name for reports
                        "institute_code": institute_code,
                        "phone": phone,
                        "email": email,
                        "registered_at": datetime.now().isoformat()
                    }
                }
            })
            
            if response.user:
                # Store user info in session
                user_metadata = response.user.user_metadata or {}
                session['user'] = {
                    'id': response.user.id,
                    'email': response.user.email,
                    'is_employee': False,
                    'role': 'owner',
                    'institute_name': user_metadata.get('display_name', institute_name),
                    'display_name': user_metadata.get('display_name', institute_name),
                    'phone': user_metadata.get('phone', phone),
                    'institute_code': user_metadata.get('institute_code', institute_code)
                }
                
                flash('Registration successful! Welcome to Lunserk ERP!', 'success')
                return redirect(url_for('dashboard.index'))
            else:
                flash('Registration failed. Could not create user account.', 'error')
                return redirect(url_for('auth.register'))
                
        except Exception as e:
            error_msg = str(e)
            if 'User already registered' in error_msg:
                flash('Email already registered. Please login instead.', 'warning')
                return redirect(url_for('auth.login'))
            else:
                print(f"Registration error: {e}")
                flash(f'Registration failed: {error_msg}', 'error')
    
    return render_template('auth.html', mode='register')

# ========== PROFILE ROUTE (Both Owner & Employee) ==========

@auth_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    """Update user profile - handles both owner and employee"""
    user = session.get('user')
    if not user:
        return redirect(url_for('auth.login'))
    
    is_employee = user.get('is_employee', False)
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'update_email':
            new_email = request.form.get('new_email', '').strip()
            password = request.form.get('password', '')
            
            if not new_email or not password:
                flash('Please provide new email and current password', 'error')
                return redirect(url_for('auth.profile'))
            
            if is_employee:
                # Employee email update
                try:
                    employee_response = supabase.table('employees')\
                        .select('password_hash')\
                        .eq('id', user['id'])\
                        .execute()
                    
                    if not employee_response.data or not check_password_hash(employee_response.data[0].get('password_hash', ''), password):
                        flash('Current password is incorrect', 'error')
                        return redirect(url_for('auth.profile'))
                    
                    supabase.table('employees')\
                        .update({'email': new_email, 'updated_at': datetime.now().isoformat()})\
                        .eq('id', user['id'])\
                        .execute()
                    
                    session['user']['email'] = new_email
                    flash('Email updated successfully!', 'success')
                    
                except Exception as e:
                    flash(f'Error updating email: {str(e)}', 'error')
            
            else:
                # Owner email update via Supabase Auth
                try:
                    auth_response = supabase.auth.sign_in_with_password({
                        "email": user['email'],
                        "password": password
                    })
                    
                    if not auth_response.user:
                        flash('Current password is incorrect', 'error')
                        return redirect(url_for('auth.profile'))
                    
                    update_response = supabase.auth.update_user({"email": new_email})
                    
                    if update_response and update_response.user:
                        session['user']['email'] = new_email
                        flash('Email updated successfully!', 'success')
                    else:
                        flash('Failed to update email', 'error')
                        
                except Exception as e:
                    error_msg = str(e)
                    if 'invalid password' in error_msg.lower():
                        flash('Current password is incorrect', 'error')
                    elif 'email already in use' in error_msg.lower():
                        flash('This email is already registered', 'error')
                    else:
                        flash(f'Error: {error_msg}', 'error')
        
        elif action == 'update_password':
            current_password = request.form.get('current_password', '')
            new_password = request.form.get('new_password', '')
            confirm_password = request.form.get('confirm_password', '')
            
            if not current_password or not new_password:
                flash('Please provide current and new password', 'error')
                return redirect(url_for('auth.profile'))
            
            if new_password != confirm_password:
                flash('New passwords do not match', 'error')
                return redirect(url_for('auth.profile'))
            
            if len(new_password) < 6:
                flash('Password must be at least 6 characters', 'error')
                return redirect(url_for('auth.profile'))
            
            if is_employee:
                # Employee password update
                try:
                    employee_response = supabase.table('employees')\
                        .select('password_hash')\
                        .eq('id', user['id'])\
                        .execute()
                    
                    if not employee_response.data or not check_password_hash(employee_response.data[0].get('password_hash', ''), current_password):
                        flash('Current password is incorrect', 'error')
                        return redirect(url_for('auth.profile'))
                    
                    new_hash = generate_password_hash(new_password)
                    
                    supabase.table('employees')\
                        .update({'password_hash': new_hash, 'updated_at': datetime.now().isoformat()})\
                        .eq('id', user['id'])\
                        .execute()
                    
                    flash('Password updated successfully!', 'success')
                    
                except Exception as e:
                    flash(f'Error updating password: {str(e)}', 'error')
            
            else:
                # Owner password update via Supabase Auth
                try:
                    auth_response = supabase.auth.sign_in_with_password({
                        "email": user['email'],
                        "password": current_password
                    })
                    
                    if not auth_response.user:
                        flash('Current password is incorrect', 'error')
                        return redirect(url_for('auth.profile'))
                    
                    update_response = supabase.auth.update_user({"password": new_password})
                    
                    if update_response and update_response.user:
                        flash('Password updated successfully!', 'success')
                    else:
                        flash('Failed to update password', 'error')
                        
                except Exception as e:
                    error_msg = str(e)
                    if 'invalid password' in error_msg.lower():
                        flash('Current password is incorrect', 'error')
                    else:
                        flash(f'Error: {error_msg}', 'error')
        
        elif action == 'update_display_name':
            new_display_name = request.form.get('display_name', '').strip()
            
            if not new_display_name:
                flash('Display name is required', 'error')
                return redirect(url_for('auth.profile'))
            
            if is_employee:
                # Employee - update employee record or institute display name
                try:
                    supabase.table('employees')\
                        .update({'display_name': new_display_name, 'updated_at': datetime.now().isoformat()})\
                        .eq('id', user['id'])\
                        .execute()
                    session['user']['display_name'] = new_display_name
                    flash('Display name updated successfully!', 'success')
                except Exception as e:
                    flash(f'Error updating display name: {str(e)}', 'error')
            else:
                # Owner - update user metadata
                try:
                    supabase.auth.update_user({
                        "data": {
                            "display_name": new_display_name,
                            "institute_name": new_display_name
                        }
                    })
                    
                    session['user']['display_name'] = new_display_name
                    session['user']['institute_name'] = new_display_name
                    flash('Display name updated successfully!', 'success')
                except Exception as e:
                    flash(f'Error updating display name: {str(e)}', 'error')
        
        elif action == 'update_phone':
            new_phone = request.form.get('phone', '').strip()
            
            if is_employee:
                try:
                    supabase.table('employees')\
                        .update({'phone': new_phone, 'updated_at': datetime.now().isoformat()})\
                        .eq('id', user['id'])\
                        .execute()
                    session['user']['phone'] = new_phone
                    flash('Phone number updated successfully!', 'success')
                except Exception as e:
                    flash(f'Error updating phone: {str(e)}', 'error')
            else:
                # Owner - update user metadata
                try:
                    supabase.auth.update_user({
                        "data": {
                            "phone": new_phone
                        }
                    })
                    session['user']['phone'] = new_phone
                    flash('Phone number updated successfully!', 'success')
                except Exception as e:
                    flash(f'Error updating phone: {str(e)}', 'error')
        
        return redirect(url_for('auth.profile'))
    
    # GET request - show profile form
    return render_template('profile.html', user=user, is_employee=is_employee)

# ========== LOGOUT ROUTE ==========

@auth_bp.route('/logout')
def logout():
    """Logout route - clears session for both user types"""
    try:
        if not session.get('user', {}).get('is_employee', False):
            supabase.auth.sign_out()
    except:
        pass
    session.clear()
    flash('You have been logged out successfully', 'info')
    return redirect(url_for('auth.login'))

# ========== HELPER ROUTES ==========

@auth_bp.route('/api/current-user', methods=['GET'])
@login_required
def get_current_user():
    """Get current logged in user info"""
    user = session.get('user', {})
    safe_user = {k: v for k, v in user.items() if k not in ['password_hash']}
    return jsonify({'success': True, 'user': safe_user})

@auth_bp.route('/api/user-role', methods=['GET'])
@login_required
def get_user_role():
    """Get current user's role"""
    user = session.get('user', {})
    return jsonify({
        'success': True,
        'is_employee': user.get('is_employee', False),
        'role': user.get('role', 'owner'),
        'employee_id': user.get('employee_id') if user.get('is_employee') else None
    })

# ========== DEMO LOGIN ==========

@auth_bp.route('/demo-login')
def demo_login():
    """Demo route for automatic login with predefined credentials"""
    email = "nserekonajib3@gmail.com"
    password = "Nabirah1@"
    
    try:
        response = supabase.auth.sign_in_with_password({
            "email": email,
            "password": password
        })
        
        if response.user:
            user_metadata = response.user.user_metadata or {}
            
            session['user'] = {
                'id': response.user.id,
                'email': response.user.email,
                'is_employee': False,
                'role': user_metadata.get('role', 'owner'),
                'institute_name': user_metadata.get('display_name', user_metadata.get('institute_name', '')),
                'display_name': user_metadata.get('display_name', user_metadata.get('institute_name', '')),
                'phone': user_metadata.get('phone', ''),
                'institute_id': user_metadata.get('institute_id'),
                'institute_code': user_metadata.get('institute_code')
            }
            
            flash('Demo login successful! Welcome back!', 'success')
            return redirect(url_for('dashboard.index'))
        else:
            flash('Demo login failed. Invalid credentials.', 'error')
            return redirect(url_for('auth.login'))
            
    except Exception as e:
        error_msg = str(e)
        if 'Invalid login credentials' in error_msg:
            flash('Demo login failed. Invalid email or password.', 'error')
        else:
            flash(f'Demo login failed: {error_msg}', 'error')
        return redirect(url_for('auth.login'))