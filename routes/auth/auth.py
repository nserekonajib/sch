# auth.py - Authentication Blueprint with Supabase
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from supabase import create_client, Client
import os
from functools import wraps
from dotenv import load_dotenv

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

auth_bp = Blueprint('auth', __name__)

def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            flash('Please login to access this page', 'warning')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Login route - handles both GET and POST"""
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
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
                # Store user info in session
                session['user'] = {
                    'id': response.user.id,
                    'email': response.user.email
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

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """Registration route - handles both GET and POST"""
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        # Validation
        if not email or not password:
            flash('Please fill in all fields', 'error')
            return redirect(url_for('auth.register'))
        
        if password != confirm_password:
            flash('Passwords do not match', 'error')
            return redirect(url_for('auth.register'))
        
        if len(password) < 6:
            flash('Password must be at least 6 characters', 'error')
            return redirect(url_for('auth.register'))
        
        try:
            # Attempt to sign up with Supabase
            response = supabase.auth.sign_up({
                "email": email,
                "password": password,
                "options": {
                    "data": {
                        "created_at": "now()"
                    }
                }
            })
            
            if response.user:
                flash('Registration successful! Please login with your credentials.', 'success')
                return redirect(url_for('auth.login'))
            else:
                flash('Registration failed. Please try again.', 'error')
                
        except Exception as e:
            error_msg = str(e)
            if 'User already registered' in error_msg:
                flash('Email already registered. Please login instead.', 'warning')
                return redirect(url_for('auth.login'))
            else:
                flash(f'Registration failed: {error_msg}', 'error')
    
    return render_template('auth.html', mode='register')

# @auth_bp.route('/dashboard')
# @login_required
# def dashboard():
#     """Protected dashboard route"""
#     user = session.get('user')
#     return render_template('dashboard.html', user=user)

@auth_bp.route('/logout')
def logout():
    """Logout route - clears session"""
    try:
        supabase.auth.sign_out()
    except:
        pass
    session.clear()
    flash('You have been logged out successfully', 'info')
    return redirect(url_for('landing'))


# Add to auth.py (after existing imports)
# Add to auth.py (after existing imports)
# Updated auth.py with proper email and password update
# auth.py - Fixed profile update with proper session handling

# Alternative: Simpler approach using direct Supabase Admin API
# Add this to your .env file: SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
# auth.py - Fixed profile update without ClientOptions issues

@auth_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    """Update user email and password"""
    user = session.get('user')
    if not user:
        return redirect(url_for('auth.login'))
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'update_email':
            new_email = request.form.get('new_email', '').strip()
            password = request.form.get('password', '')
            
            if not new_email or not password:
                flash('Please provide new email and current password', 'error')
                return redirect(url_for('auth.profile'))
            
            try:
                # First verify the password
                auth_response = supabase.auth.sign_in_with_password({
                    "email": user['email'],
                    "password": password
                })
                
                if not auth_response.user:
                    flash('Current password is incorrect', 'error')
                    return redirect(url_for('auth.profile'))
                
                # Update the email using the authenticated session
                update_response = supabase.auth.update_user({
                    "email": new_email
                })
                
                if update_response and update_response.user:
                    # Update the institutes table
                    try:
                        supabase.table('institutes')\
                            .update({'email': new_email})\
                            .eq('user_id', user['id'])\
                            .execute()
                    except Exception as inst_error:
                        print(f"Institute update error: {inst_error}")
                    
                    # Update session with new email
                    session['user']['email'] = new_email
                    
                    flash('Email updated successfully!', 'success')
                else:
                    flash('Failed to update email. Please try again.', 'error')
                    
            except Exception as e:
                error_msg = str(e)
                print(f"Email update error: {error_msg}")
                
                if 'invalid password' in error_msg.lower():
                    flash('Current password is incorrect', 'error')
                elif 'email already in use' in error_msg.lower():
                    flash('This email is already registered', 'error')
                elif 'Email confirmation required' in error_msg:
                    flash('Email confirmation is required. Please check your inbox.', 'warning')
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
            
            try:
                # First verify current password
                auth_response = supabase.auth.sign_in_with_password({
                    "email": user['email'],
                    "password": current_password
                })
                
                if not auth_response.user:
                    flash('Current password is incorrect', 'error')
                    return redirect(url_for('auth.profile'))
                
                # Update password
                update_response = supabase.auth.update_user({
                    "password": new_password
                })
                
                if update_response and update_response.user:
                    flash('Password updated successfully!', 'success')
                else:
                    flash('Failed to update password', 'error')
                    
            except Exception as e:
                error_msg = str(e)
                print(f"Password update error: {error_msg}")
                
                if 'invalid password' in error_msg.lower():
                    flash('Current password is incorrect', 'error')
                else:
                    flash(f'Error: {error_msg}', 'error')
        
        return redirect(url_for('auth.profile'))
    
    # GET request - show profile form
    return render_template('profile.html', user=user)