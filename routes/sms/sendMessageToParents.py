# sendMessageToParents.py - Fixed with proper table creation and query fixes
from flask import Blueprint, render_template, request, jsonify, session
from supabase import create_client, Client
import os
import uuid
from datetime import datetime
from functools import wraps
from dotenv import load_dotenv

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

message_bp = Blueprint('message', __name__, url_prefix='/send-message')

def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Please login'}), 401
        return f(*args, **kwargs)
    return decorated_function

def get_institute(user_id):
    """Get institute for the current user"""
    try:
        response = supabase.table('institutes')\
            .select('*')\
            .eq('user_id', user_id)\
            .execute()
        
        if response.data and len(response.data) > 0:
            return response.data[0]
        return None
    except Exception as e:
        print(f"Error getting institute: {e}")
        return None

def get_sms_settings(institute_id):
    """Get SMS settings for the institute"""
    try:
        response = supabase.table('sms_settings')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .execute()
        
        if response.data and len(response.data) > 0:
            return response.data[0]
        return None
    except Exception as e:
        print(f"Error getting SMS settings: {e}")
        return None

@message_bp.route('/')
@login_required
def index():
    """Send Message to Parents Page"""
    user = session.get('user')
    institute = get_institute(user['id'])
    
    if not institute:
        return render_template('message/index.html', classes=[], students=[], institute=None)
    
    try:
        # Get all classes
        classes_response = supabase.table('classes')\
            .select('*')\
            .eq('institute_id', institute['id'])\
            .order('name')\
            .execute()
        
        classes = classes_response.data if classes_response.data else []
        
        # Get all students with their contact numbers
        students_response = supabase.table('students')\
            .select('id, name, student_id, class_id, classes(name), contact_number, father_name, mother_name')\
            .eq('institute_id', institute['id'])\
            .eq('status', 'active')\
            .order('name')\
            .execute()
        
        students = students_response.data if students_response.data else []
        
        # Get SMS settings
        sms_settings = get_sms_settings(institute['id'])
        
        return render_template('message/index.html', classes=classes, students=students, institute=institute, sms_settings=sms_settings)
        
    except Exception as e:
        print(f"Error loading message page: {e}")
        return render_template('message/index.html', classes=[], students=[], institute=institute, sms_settings=None)

@message_bp.route('/api/get-recipients', methods=['POST'])
@login_required
def get_recipients():
    """Get recipients based on selected criteria"""
    user = session.get('user')
    institute = get_institute(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        apply_to = data.get('apply_to')  # 'all', 'class', 'student'
        class_id = data.get('class_id')
        student_ids = data.get('student_ids', [])
        
        recipients = []
        
        if apply_to == 'all':
            # Get all students with valid contact numbers
            response = supabase.table('students')\
                .select('id, name, student_id, contact_number, father_name, mother_name')\
                .eq('institute_id', institute['id'])\
                .eq('status', 'active')\
                .neq('contact_number', '')\
                .execute()
            
            # Filter out empty contact numbers
            for student in response.data if response.data else []:
                if student.get('contact_number') and student['contact_number'].strip():
                    recipients.append({
                        'id': student['id'],
                        'name': student['name'],
                        'student_id': student['student_id'],
                        'phone': student['contact_number']
                    })
                    
        elif apply_to == 'class' and class_id:
            # Get students in specific class with valid contact numbers
            response = supabase.table('students')\
                .select('id, name, student_id, contact_number, father_name, mother_name')\
                .eq('institute_id', institute['id'])\
                .eq('class_id', class_id)\
                .eq('status', 'active')\
                .neq('contact_number', '')\
                .execute()
            
            for student in response.data if response.data else []:
                if student.get('contact_number') and student['contact_number'].strip():
                    recipients.append({
                        'id': student['id'],
                        'name': student['name'],
                        'student_id': student['student_id'],
                        'phone': student['contact_number']
                    })
                    
        elif apply_to == 'student' and student_ids:
            # Get selected students
            response = supabase.table('students')\
                .select('id, name, student_id, contact_number, father_name, mother_name')\
                .eq('institute_id', institute['id'])\
                .in_('id', student_ids)\
                .neq('contact_number', '')\
                .execute()
            
            for student in response.data if response.data else []:
                if student.get('contact_number') and student['contact_number'].strip():
                    recipients.append({
                        'id': student['id'],
                        'name': student['name'],
                        'student_id': student['student_id'],
                        'phone': student['contact_number']
                    })
        
        return jsonify({
            'success': True,
            'recipients': recipients,
            'count': len(recipients)
        })
        
    except Exception as e:
        print(f"Error getting recipients: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@message_bp.route('/api/search-students', methods=['GET'])
@login_required
def search_students():
    """Fast live search for students"""
    user = session.get('user')
    institute = get_institute(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        search_term = request.args.get('q', '').strip()
        class_id = request.args.get('class_id', '')
        
        # Don't search for terms less than 2 characters
        if len(search_term) < 2:
            return jsonify({'success': True, 'students': [], 'count': 0})
        
        # Build query
        query = supabase.table('students')\
            .select('id, name, student_id, class_id, classes(name), contact_number, father_name, mother_name')\
            .eq('institute_id', institute['id'])\
            .eq('status', 'active')
        
        # Apply class filter if provided
        if class_id:
            query = query.eq('class_id', class_id)
        
        # Apply search
        query = query.or_(f"name.ilike.%{search_term}%,student_id.ilike.%{search_term}%")
        
        # Limit results for performance
        response = query.limit(50).execute()
        
        students = []
        for student in response.data if response.data else []:
            # Only include students with phone numbers
            if student.get('contact_number') and student['contact_number'].strip():
                students.append({
                    'id': student['id'],
                    'name': student['name'],
                    'student_id': student['student_id'],
                    'class_name': student['classes']['name'] if student.get('classes') else 'N/A',
                    'phone': student.get('contact_number', ''),
                    'father_name': student.get('father_name', ''),
                    'mother_name': student.get('mother_name', '')
                })
        
        return jsonify({
            'success': True,
            'students': students,
            'count': len(students)
        })
        
    except Exception as e:
        print(f"Error searching students: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@message_bp.route('/api/send', methods=['POST'])
@login_required
def send_message():
    """Send SMS messages to selected recipients"""
    user = session.get('user')
    institute = get_institute(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        recipients = data.get('recipients', [])
        message = data.get('message', '').strip()
        sender_id = data.get('sender_id', 'SCHOOL')
        
        if not recipients:
            return jsonify({'success': False, 'message': 'No recipients selected'}), 400
        
        if not message:
            return jsonify({'success': False, 'message': 'Message cannot be empty'}), 400
        
        # Get SMS settings
        sms_settings = get_sms_settings(institute['id'])
        
        if not sms_settings or not sms_settings.get('enabled'):
            return jsonify({'success': False, 'message': 'SMS is not enabled. Please configure SMS settings first.'}), 400
        
        if not sms_settings.get('api_username') or not sms_settings.get('api_key'):
            return jsonify({'success': False, 'message': 'SMS API credentials not configured. Please update SMS settings.'}), 400
        
        # Prepare message with institute branding
        full_message = f"{message}\n\n{institute.get('institute_name', 'School')}\nThank you."
        
        # Send SMS using CommsSDK
        try:
            from comms_sdk import CommsSDK, MessagePriority
            
            sdk = CommsSDK.authenticate(
                sms_settings['api_username'], 
                sms_settings['api_key']
            )
            
            # Collect phone numbers
            phone_numbers = []
            for recipient in recipients:
                phone = recipient.get('phone', '').strip()
                if phone:
                    # Format phone number
                    phone = phone.replace(' ', '').replace('-', '')
                    if not phone.startswith('+'):
                        if phone.startswith('0'):
                            phone = '+256' + phone[1:]
                        elif phone.startswith('256'):
                            phone = '+' + phone
                        else:
                            phone = '+256' + phone
                    phone_numbers.append(phone)
            
            if not phone_numbers:
                return jsonify({'success': False, 'message': 'No valid phone numbers found'}), 400
            
            # Send SMS in batches (max 100 per batch)
            batch_size = 100
            success_count = 0
            
            for i in range(0, len(phone_numbers), batch_size):
                batch = phone_numbers[i:i+batch_size]
                response = sdk.send_sms(
                    batch,
                    full_message,
                    sender_id=sender_id[:11],  # Max 11 characters
                    priority=MessagePriority.HIGHEST
                )
                success_count += len(batch)
            
            # Log the message (only if table exists)
            try:
                message_log_id = str(uuid.uuid4())
                log_data = {
                    'id': message_log_id,
                    'institute_id': institute['id'],
                    'sender_id': sender_id,
                    'message': full_message[:500],
                    'recipient_count': len(phone_numbers),
                    'status': 'sent',
                    'created_at': datetime.now().isoformat()
                }
                supabase.table('message_logs').insert(log_data).execute()
            except Exception as log_error:
                print(f"Error logging message: {log_error}")
                # Continue even if logging fails
            
            return jsonify({
                'success': True,
                'message': f'Message sent successfully to {success_count} recipient(s)',
                'recipient_count': success_count
            })
            
        except ImportError:
            return jsonify({'success': False, 'message': 'CommsSDK not installed. Please install it first.'}), 500
        except Exception as e:
            return jsonify({'success': False, 'message': f'SMS sending failed: {str(e)}'}), 500
            
    except Exception as e:
        print(f"Error sending message: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@message_bp.route('/api/message-history', methods=['GET'])
@login_required
def get_message_history():
    """Get message sending history"""
    user = session.get('user')
    institute = get_institute(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Try to get from message_logs table
        response = supabase.table('message_logs')\
            .select('*')\
            .eq('institute_id', institute['id'])\
            .order('created_at', desc=True)\
            .limit(50)\
            .execute()
        
        logs = response.data if response.data else []
        
        return jsonify({'success': True, 'logs': logs})
        
    except Exception as e:
        # Table might not exist yet, return empty array
        print(f"Error getting message history (table may not exist): {e}")
        return jsonify({'success': True, 'logs': []})