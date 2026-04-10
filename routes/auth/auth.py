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
    return redirect(url_for('auth.login'))