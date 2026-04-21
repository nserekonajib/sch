# agent_system.py - Geo-Verified Field Agent System
from flask import Blueprint, render_template, request, jsonify, session
from supabase import create_client, Client
import os
import uuid
from datetime import datetime, timedelta
import json
import hashlib
import hmac
import requests
from functools import wraps
from dotenv import load_dotenv
import random
import string
from werkzeug.utils import secure_filename
import cloudinary
import cloudinary.uploader
from flask import *

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

# IP Quality Score API for VPN detection
IPQUALITY_API_KEY = os.getenv('IPQUALITY_API_KEY', '')

agent_bp = Blueprint('agent', __name__, url_prefix='/agent')

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Please login'}), 401
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
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

def generate_device_fingerprint(request_data):
    """Generate unique device fingerprint"""
    user_agent = request_data.get('user_agent', '')
    screen_resolution = request_data.get('screen_resolution', '')
    timezone = request_data.get('timezone', '')
    language = request_data.get('language', '')
    
    fingerprint_string = f"{user_agent}|{screen_resolution}|{timezone}|{language}"
    return hashlib.sha256(fingerprint_string.encode()).hexdigest()

def detect_vpn(ip_address):
    """Detect VPN/Proxy using IPQualityScore API"""
    if not IPQUALITY_API_KEY:
        return {'is_vpn': False, 'is_proxy': False, 'message': 'VPN detection not configured'}
    
    try:
        url = f"https://ipqualityscore.com/api/json/ip/{IPQUALITY_API_KEY}/{ip_address}"
        response = requests.get(url, timeout=10)
        data = response.json()
        
        return {
            'is_vpn': data.get('vpn', False),
            'is_proxy': data.get('proxy', False),
            'is_datacenter': data.get('is_datacenter', False),
            'fraud_score': data.get('fraud_score', 0),
            'message': 'VPN detection completed'
        }
    except Exception as e:
        print(f"VPN detection error: {e}")
        return {'is_vpn': False, 'is_proxy': False, 'message': 'Detection failed'}

def verify_location(gps_lat, gps_lon, ip_address):
    """Verify GPS location against IP location"""
    try:
        # Get IP geolocation
        ip_response = requests.get(f"https://ipapi.co/{ip_address}/json/", timeout=10)
        ip_data = ip_response.json()
        
        ip_lat = ip_data.get('latitude')
        ip_lon = ip_data.get('longitude')
        
        if not ip_lat or not ip_lon:
            return {'verified': False, 'message': 'Could not determine IP location'}
        
        # Calculate distance between GPS and IP locations (Haversine formula)
        from math import radians, sin, cos, sqrt, atan2
        
        R = 6371  # Earth's radius in km
        
        lat1, lon1 = radians(float(gps_lat)), radians(float(gps_lon))
        lat2, lon2 = radians(ip_lat), radians(ip_lon)
        
        dlon = lon2 - lon1
        dlat = lat2 - lat1
        
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        c = 2 * atan2(sqrt(a), sqrt(1-a))
        distance = R * c
        
        # Accept if within 50km (adjustable)
        is_match = distance <= 50
        
        return {
            'verified': is_match,
            'distance_km': round(distance, 2),
            'ip_location': f"{ip_data.get('city', 'Unknown')}, {ip_data.get('country_name', 'Unknown')}",
            'message': 'Location verified' if is_match else 'Location mismatch detected'
        }
    except Exception as e:
        print(f"Location verification error: {e}")
        return {'verified': False, 'message': 'Verification failed'}

# ==================== AGENT APPLICATION ====================

@agent_bp.route('/')
def landing():
    """Agent System Landing Page"""
    return render_template('agent/landing.html')

@agent_bp.route('/apply')
def apply():
    """Agent Application Page"""
    return render_template('agent/apply.html')

@agent_bp.route('/api/send-otp', methods=['POST'])
def send_otp():
    """Send OTP for phone verification"""
    try:
        data = request.get_json()
        phone = data.get('phone', '').strip()
        
        if not phone:
            return jsonify({'success': False, 'message': 'Phone number required'}), 400
        
        # Generate 6-digit OTP
        otp = ''.join(random.choices(string.digits, k=6))
        
        # Store OTP in session or database (in production, use SMS gateway)
        session['phone_otp'] = otp
        session['phone_otp_expiry'] = (datetime.now() + timedelta(minutes=5)).isoformat()
        
        # In production, send SMS via SMS gateway
        print(f"OTP for {phone}: {otp}")  # For development
        
        return jsonify({'success': True, 'message': 'OTP sent successfully'})
        
    except Exception as e:
        print(f"Error sending OTP: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@agent_bp.route('/api/verify-otp', methods=['POST'])
def verify_otp():
    """Verify OTP"""
    try:
        data = request.get_json()
        otp = data.get('otp', '').strip()
        
        stored_otp = session.get('phone_otp')
        expiry = session.get('phone_otp_expiry')
        
        if not stored_otp:
            return jsonify({'success': False, 'message': 'No OTP sent'}), 400
        
        if datetime.now() > datetime.fromisoformat(expiry):
            return jsonify({'success': False, 'message': 'OTP expired'}), 400
        
        if otp != stored_otp:
            return jsonify({'success': False, 'message': 'Invalid OTP'}), 400
        
        session['phone_verified'] = True
        return jsonify({'success': True, 'message': 'Phone verified successfully'})
        
    except Exception as e:
        print(f"Error verifying OTP: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
# Update the relevant sections in agent_system.py

# Remove send_otp and verify_otp endpoints entirely
# Update the submit_application endpoint:

@agent_bp.route('/api/submit-application', methods=['POST'])
def submit_application():
    """Submit agent application (no OTP required)"""
    try:
        data = request.get_json()
        
        # Generate device fingerprint
        device_fingerprint = generate_device_fingerprint(data.get('device_info', {}))
        
        # Check for existing application with same device fingerprint
        existing = supabase.table('agent_applications')\
            .select('id')\
            .eq('device_fingerprint', device_fingerprint)\
            .execute()
        
        if existing.data:
            return jsonify({'success': False, 'message': 'Multiple applications not allowed from same device'}), 400
        
        # Handle document upload (optional)
        document_url = None
        if data.get('document_base64'):
            try:
                import base64
                import tempfile
                
                doc_data = data['document_base64'].split(',')[1] if ',' in data['document_base64'] else data['document_base64']
                doc_bytes = base64.b64decode(doc_data)
                
                with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp_file:
                    tmp_file.write(doc_bytes)
                    tmp_path = tmp_file.name
                
                upload_result = cloudinary.uploader.upload(
                    tmp_path,
                    folder=f"agent_documents/{data['phone']}",
                    public_id=f"id_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                )
                
                document_url = upload_result['secure_url']
                os.unlink(tmp_path)
                
            except Exception as e:
                print(f"Document upload error: {e}")
        
        # Create application
        application_id = str(uuid.uuid4())
        application_data = {
            'id': application_id,
            'full_name': data.get('full_name'),
            'phone': data.get('phone'),
            'email': data.get('email'),
            'region': data.get('region'),
            'identification_document': document_url,
            'device_fingerprint': device_fingerprint,
            'status': 'pending',
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        result = supabase.table('agent_applications').insert(application_data).execute()
        
        return jsonify({'success': True, 'message': 'Application submitted successfully', 'application_id': application_id})
        
    except Exception as e:
        print(f"Error submitting application: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

# ==================== ADMIN ROUTES ====================

@agent_bp.route('/admin')
@admin_required
def admin_dashboard():
    """Admin Dashboard for Agent Management"""
    return render_template('agent/admin.html')

@agent_bp.route('/api/admin/applications', methods=['GET'])
@admin_required
def get_applications():
    """Get all applications"""
    try:
        status = request.args.get('status', 'pending')
        
        response = supabase.table('agent_applications')\
            .select('*')\
            .eq('status', status)\
            .order('created_at', desc=True)\
            .execute()
        
        return jsonify({'success': True, 'applications': response.data})
        
    except Exception as e:
        print(f"Error getting applications: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@agent_bp.route('/api/admin/applications/<app_id>/approve', methods=['POST'])
@admin_required
def approve_application(app_id):
    """Approve an application"""
    try:
        # Get application details
        app_response = supabase.table('agent_applications')\
            .select('*')\
            .eq('id', app_id)\
            .execute()
        
        if not app_response.data:
            return jsonify({'success': False, 'message': 'Application not found'}), 404
        
        application = app_response.data[0]
        
        # Update application status
        supabase.table('agent_applications')\
            .update({'status': 'approved', 'updated_at': datetime.now().isoformat()})\
            .eq('id', app_id)\
            .execute()
        
        # Create agent record
        agent_id = str(uuid.uuid4())
        agent_data = {
            'id': agent_id,
            'application_id': app_id,
            'full_name': application['full_name'],
            'phone': application['phone'],
            'email': application['email'],
            'region': application['region'],
            'status': 'active',
            'total_earnings': 0,
            'tasks_completed': 0,
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        supabase.table('agents').insert(agent_data).execute()
        
        return jsonify({'success': True, 'message': 'Application approved successfully'})
        
    except Exception as e:
        print(f"Error approving application: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@agent_bp.route('/api/admin/applications/<app_id>/reject', methods=['POST'])
@admin_required
def reject_application(app_id):
    """Reject an application"""
    try:
        data = request.get_json()
        reason = data.get('reason', '')
        
        supabase.table('agent_applications')\
            .update({
                'status': 'rejected',
                'rejection_reason': reason,
                'updated_at': datetime.now().isoformat()
            })\
            .eq('id', app_id)\
            .execute()
        
        return jsonify({'success': True, 'message': 'Application rejected'})
        
    except Exception as e:
        print(f"Error rejecting application: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@agent_bp.route('/api/admin/agents', methods=['GET'])
@admin_required
def get_agents():
    """Get all agents"""
    try:
        response = supabase.table('agents')\
            .select('*')\
            .order('created_at', desc=True)\
            .execute()
        
        return jsonify({'success': True, 'agents': response.data})
        
    except Exception as e:
        print(f"Error getting agents: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

# ==================== TASK MANAGEMENT ====================

@agent_bp.route('/api/admin/tasks', methods=['GET'])
@admin_required
def get_tasks():
    """Get all tasks"""
    try:
        response = supabase.table('agent_tasks')\
            .select('*')\
            .order('created_at', desc=True)\
            .execute()
        
        return jsonify({'success': True, 'tasks': response.data})
        
    except Exception as e:
        print(f"Error getting tasks: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@agent_bp.route('/api/admin/tasks/create', methods=['POST'])
@admin_required
def create_task():
    """Create a new task"""
    try:
        data = request.get_json()
        
        task_id = str(uuid.uuid4())
        task_data = {
            'id': task_id,
            'title': data.get('title'),
            'description': data.get('description'),
            'region': data.get('region'),
            'payment_amount': float(data.get('payment_amount', 0)),
            'deadline': data.get('deadline'),
            'status': 'active',
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        result = supabase.table('agent_tasks').insert(task_data).execute()
        
        return jsonify({'success': True, 'message': 'Task created successfully', 'task': result.data[0]})
        
    except Exception as e:
        print(f"Error creating task: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

# ==================== AGENT DASHBOARD ====================

@agent_bp.route('/dashboard')
@login_required
def agent_dashboard():
    """Agent Dashboard Page"""
    # Get agent record for logged-in user
    user = session.get('user')
    
    agent_response = supabase.table('agents')\
        .select('*')\
        .eq('email', user['email'])\
        .execute()
    
    if not agent_response.data:
        flash('You are not registered as an agent', 'error')
        return redirect(url_for('agent.landing'))
    
    agent = agent_response.data[0]
    return render_template('agent/dashboard.html', agent=agent)

@agent_bp.route('/api/agent/tasks', methods=['GET'])
@login_required
def get_agent_tasks():
    """Get tasks assigned to the agent based on region"""
    try:
        user = session.get('user')
        
        # Get agent's region
        agent_response = supabase.table('agents')\
            .select('region')\
            .eq('email', user['email'])\
            .execute()
        
        if not agent_response.data:
            return jsonify({'success': False, 'message': 'Agent not found'}), 404
        
        agent_region = agent_response.data[0]['region']
        
        # Get tasks for agent's region
        response = supabase.table('agent_tasks')\
            .select('*')\
            .eq('region', agent_region)\
            .eq('status', 'active')\
            .gte('deadline', datetime.now().date().isoformat())\
            .order('created_at', desc=True)\
            .execute()
        
        # Get completed tasks
        completed_response = supabase.table('agent_submissions')\
            .select('task_id')\
            .eq('agent_id', agent_response.data[0]['id'])\
            .eq('status', 'approved')\
            .execute()
        
        completed_task_ids = [s['task_id'] for s in completed_response.data] if completed_response.data else []
        
        tasks = []
        for task in response.data:
            tasks.append({
                **task,
                'is_completed': task['id'] in completed_task_ids
            })
        
        return jsonify({'success': True, 'tasks': tasks})
        
    except Exception as e:
        print(f"Error getting agent tasks: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@agent_bp.route('/api/agent/submit-task', methods=['POST'])
@login_required
def submit_task():
    """Submit a task with location verification"""
    try:
        data = request.get_json()
        user = session.get('user')
        
        # Get agent details
        agent_response = supabase.table('agents')\
            .select('*')\
            .eq('email', user['email'])\
            .execute()
        
        if not agent_response.data:
            return jsonify({'success': False, 'message': 'Agent not found'}), 404
        
        agent = agent_response.data[0]
        
        # Get task details
        task_response = supabase.table('agent_tasks')\
            .select('*')\
            .eq('id', data.get('task_id'))\
            .execute()
        
        if not task_response.data:
            return jsonify({'success': False, 'message': 'Task not found'}), 404
        
        task = task_response.data[0]
        
        # Extract submission data
        gps_lat = data.get('gps_lat')
        gps_lon = data.get('gps_lon')
        gps_accuracy = data.get('gps_accuracy', 0)
        ip_address = data.get('ip_address', request.remote_addr)
        device_info = data.get('device_info', {})
        device_fingerprint = generate_device_fingerprint(device_info)
        proof_url = data.get('proof_url')
        notes = data.get('notes', '')
        
        # Validate GPS accuracy
        if gps_accuracy > 100:
            return jsonify({'success': False, 'message': 'GPS accuracy too low. Please enable high accuracy mode.'}), 400
        
        # Detect VPN/Proxy
        vpn_check = detect_vpn(ip_address)
        if vpn_check.get('is_vpn') or vpn_check.get('is_proxy'):
            return jsonify({'success': False, 'message': 'VPN/Proxy detected. Please disable and try again.'}), 400
        
        # Verify location
        location_check = verify_location(gps_lat, gps_lon, ip_address)
        if not location_check.get('verified'):
            return jsonify({
                'success': False, 
                'message': f"Location mismatch detected. {location_check.get('message')}",
                'details': location_check
            }), 400
        
        # Check if already submitted
        existing = supabase.table('agent_submissions')\
            .select('id')\
            .eq('task_id', task['id'])\
            .eq('agent_id', agent['id'])\
            .execute()
        
        if existing.data:
            return jsonify({'success': False, 'message': 'Task already submitted'}), 400
        
        # Create submission
        submission_id = str(uuid.uuid4())
        submission_data = {
            'id': submission_id,
            'task_id': task['id'],
            'agent_id': agent['id'],
            'gps_latitude': gps_lat,
            'gps_longitude': gps_lon,
            'gps_accuracy': gps_accuracy,
            'ip_address': ip_address,
            'device_fingerprint': device_fingerprint,
            'proof_url': proof_url,
            'notes': notes,
            'location_verified': location_check.get('verified'),
            'distance_from_ip': location_check.get('distance_km'),
            'vpn_detected': vpn_check.get('is_vpn'),
            'status': 'pending',
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        result = supabase.table('agent_submissions').insert(submission_data).execute()
        
        return jsonify({
            'success': True, 
            'message': 'Task submitted successfully. Awaiting approval.',
            'submission_id': submission_id,
            'verification_details': location_check
        })
        
    except Exception as e:
        print(f"Error submitting task: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@agent_bp.route('/api/agent/submissions', methods=['GET'])
@login_required
def get_agent_submissions():
    """Get agent's submission history"""
    try:
        user = session.get('user')
        
        agent_response = supabase.table('agents')\
            .select('id')\
            .eq('email', user['email'])\
            .execute()
        
        if not agent_response.data:
            return jsonify({'success': False, 'message': 'Agent not found'}), 404
        
        agent_id = agent_response.data[0]['id']
        
        response = supabase.table('agent_submissions')\
            .select('*, agent_tasks(title, payment_amount)')\
            .eq('agent_id', agent_id)\
            .order('created_at', desc=True)\
            .execute()
        
        return jsonify({'success': True, 'submissions': response.data})
        
    except Exception as e:
        print(f"Error getting submissions: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@agent_bp.route('/api/agent/earnings', methods=['GET'])
@login_required
def get_agent_earnings():
    """Get agent's earnings summary"""
    try:
        user = session.get('user')
        
        agent_response = supabase.table('agents')\
            .select('id, total_earnings, tasks_completed')\
            .eq('email', user['email'])\
            .execute()
        
        if not agent_response.data:
            return jsonify({'success': False, 'message': 'Agent not found'}), 404
        
        agent = agent_response.data[0]
        
        # Get pending earnings
        pending_response = supabase.table('agent_submissions')\
            .select('agent_tasks(payment_amount)')\
            .eq('agent_id', agent['id'])\
            .eq('status', 'pending')\
            .execute()
        
        pending_earnings = sum(s.get('agent_tasks', {}).get('payment_amount', 0) for s in pending_response.data) if pending_response.data else 0
        
        return jsonify({
            'success': True,
            'earnings': {
                'total_earned': agent['total_earnings'] or 0,
                'pending_earnings': pending_earnings,
                'tasks_completed': agent['tasks_completed'] or 0
            }
        })
        
    except Exception as e:
        print(f"Error getting earnings: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

# ==================== ADMIN SUBMISSION MANAGEMENT ====================

@agent_bp.route('/api/admin/submissions', methods=['GET'])
@admin_required
def get_submissions():
    """Get all task submissions"""
    try:
        status = request.args.get('status', 'pending')
        
        response = supabase.table('agent_submissions')\
            .select('*, agent_tasks(title, payment_amount, region), agents(full_name, phone)')\
            .eq('status', status)\
            .order('created_at', desc=True)\
            .execute()
        
        return jsonify({'success': True, 'submissions': response.data})
        
    except Exception as e:
        print(f"Error getting submissions: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@agent_bp.route('/api/admin/submissions/<sub_id>/approve', methods=['POST'])
@admin_required
def approve_submission(sub_id):
    """Approve a task submission and release payment"""
    try:
        # Get submission details
        sub_response = supabase.table('agent_submissions')\
            .select('*, agent_tasks(payment_amount), agents(id)')\
            .eq('id', sub_id)\
            .execute()
        
        if not sub_response.data:
            return jsonify({'success': False, 'message': 'Submission not found'}), 404
        
        submission = sub_response.data[0]
        payment_amount = submission.get('agent_tasks', {}).get('payment_amount', 0)
        agent_id = submission.get('agents', {}).get('id')
        
        # Update submission status
        supabase.table('agent_submissions')\
            .update({
                'status': 'approved',
                'approved_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            })\
            .eq('id', sub_id)\
            .execute()
        
        # Update agent's earnings
        supabase.table('agents')\
            .update({
                'total_earnings': supabase.table('agents').select('total_earnings').eq('id', agent_id).execute().data[0].get('total_earnings', 0) + payment_amount,
                'tasks_completed': supabase.table('agents').select('tasks_completed').eq('id', agent_id).execute().data[0].get('tasks_completed', 0) + 1,
                'updated_at': datetime.now().isoformat()
            })\
            .eq('id', agent_id)\
            .execute()
        
        return jsonify({'success': True, 'message': 'Submission approved and payment released'})
        
    except Exception as e:
        print(f"Error approving submission: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@agent_bp.route('/api/admin/submissions/<sub_id>/reject', methods=['POST'])
@admin_required
def reject_submission(sub_id):
    """Reject a task submission"""
    try:
        data = request.get_json()
        reason = data.get('reason', '')
        
        supabase.table('agent_submissions')\
            .update({
                'status': 'rejected',
                'rejection_reason': reason,
                'updated_at': datetime.now().isoformat()
            })\
            .eq('id', sub_id)\
            .execute()
        
        return jsonify({'success': True, 'message': 'Submission rejected'})
        
    except Exception as e:
        print(f"Error rejecting submission: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500