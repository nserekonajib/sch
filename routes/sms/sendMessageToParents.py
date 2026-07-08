# sendMessageToParents.py - Complete rewrite with balance checking and SMS logging
from flask import Blueprint, render_template, request, jsonify, session
from supabase import create_client, Client
import os
import uuid
import re
from datetime import datetime
from functools import wraps
from dotenv import load_dotenv
from routes.accounts.accounts import get_institute_id as get_institute_id_func
from routes.permissions.permissions import role_required
load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Master API credentials from .env (for sending SMS)
MASTER_API_USERNAME = os.getenv('COMMS_API_USERNAME', '')
MASTER_API_KEY = os.getenv('COMMS_API_KEY', '')

message_bp = Blueprint('message', __name__, url_prefix='/send-message')

def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Please login'}), 401
        return f(*args, **kwargs)
    return decorated_function

def get_institute_details(institute_id):
    """Get full institute details by ID"""
    try:
        response = supabase.table('institutes')\
            .select('*')\
            .eq('id', institute_id)\
            .execute()
        
        if response.data and len(response.data) > 0:
            return response.data[0]
        return None
    except Exception as e:
        print(f"Error getting institute details: {e}")
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

def calculate_sms_cost(message, cost_per_sms=35):
    """Calculate SMS cost based on message length and encoding"""
    # Check for Unicode characters (emoji, special chars, non-ASCII)
    has_unicode = any(ord(c) > 127 for c in message)
    segment_size = 70 if has_unicode else 160
    segments = (len(message) + segment_size - 1) // segment_size
    total_cost = segments * cost_per_sms
    
    return {
        'length': len(message),
        'segments': segments,
        'cost': total_cost,
        'encoding': 'Unicode' if has_unicode else 'GSM',
        'cost_per_sms': cost_per_sms
    }

def format_phone_number(phone):
    """Format phone number to international format"""
    if not phone:
        return None
    
    phone = str(phone).strip().replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
    
    if not phone:
        return None
    
    # If already has +, return as is
    if phone.startswith('+'):
        return phone
    
    # Ugandan number formats
    if phone.startswith('0'):
        return '+256' + phone[1:]
    elif phone.startswith('256'):
        return '+' + phone
    elif len(phone) == 9 and phone.isdigit():
        return '+256' + phone
    elif len(phone) == 12 and phone.isdigit():
        return '+' + phone
    else:
        return '+256' + phone

def deduct_from_balance(institute_id, amount):
    """Deduct amount from institute balance"""
    try:
        response = supabase.table('institutes')\
            .select('balance, total_spent')\
            .eq('id', institute_id)\
            .execute()
        
        if not response.data:
            return False, "Institute not found"
        
        current_balance = response.data[0].get('balance', 0)
        current_total_spent = response.data[0].get('total_spent', 0)
        
        if current_balance < amount:
            return False, f"Insufficient balance. Available: UGX {current_balance:,.2f}, Required: UGX {amount:,.2f}"
        
        new_balance = current_balance - amount
        new_total_spent = current_total_spent + amount
        
        supabase.table('institutes')\
            .update({
                'balance': new_balance,
                'total_spent': new_total_spent,
                'last_balance_update': datetime.now().isoformat()
            })\
            .eq('id', institute_id)\
            .execute()
        
        return True, new_balance
    except Exception as e:
        print(f"Error deducting from balance: {e}")
        return False, str(e)

def log_sms_sent(institute_id, student_id, phone_number, message, segments, cost, status, error_message=None):
    """Log SMS to sms_log table"""
    try:
        log_id = str(uuid.uuid4())
        log_data = {
            'id': log_id,
            'institute_id': institute_id,
            'student_id': student_id,
            'phone_number': phone_number,
            'message': message[:500],  # Truncate to 500 chars
            'message_length': len(message),
            'segments': segments,
            'cost': cost,
            'status': status,
            'error_message': error_message[:500] if error_message else None,
            'sent_at': datetime.now().isoformat()
        }
        supabase.table('sms_log').insert(log_data).execute()
        return True
    except Exception as e:
        print(f"Error logging SMS: {e}")
        return False

def log_bulk_sms_sent(log_entries):
    """Log multiple SMS entries in batch"""
    try:
        if not log_entries:
            return True
        
        # Prepare batch data
        batch_data = []
        for entry in log_entries:
            batch_data.append({
                'id': str(uuid.uuid4()),
                'institute_id': entry.get('institute_id'),
                'student_id': entry.get('student_id'),
                'phone_number': entry.get('phone_number'),
                'message': entry.get('message', '')[:500],
                'message_length': entry.get('message_length', 0),
                'segments': entry.get('segments', 0),
                'cost': entry.get('cost', 0),
                'status': entry.get('status', 'sent'),
                'error_message': entry.get('error_message', '')[:500] if entry.get('error_message') else None,
                'sent_at': datetime.now().isoformat()
            })
        
        # Batch insert
        if batch_data:
            supabase.table('sms_log').insert(batch_data).execute()
        return True
    except Exception as e:
        print(f"Error batch logging SMS: {e}")
        return False

@message_bp.route('/')
@role_required(['owner', 'teacher', 'accountant'])
def index():
    """Send Message to Parents Page"""
    user = session.get('user')
    institute_id = get_institute_id_func(user['id'])
    
    if not institute_id:
        return render_template('message/index.html', classes=[], students=[], institute=None, sms_settings=None, balance=0)
    
    try:
        # Batch query for institute details
        institute = get_institute_details(institute_id)
        
        # Batch query for classes
        classes_response = supabase.table('classes')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('name')\
            .execute()
        
        classes = classes_response.data if classes_response.data else []
        
        # Batch query for students with class info - optimized with select
        students_response = supabase.table('students')\
            .select('id, name, student_id, class_id, classes(name), contact_number, father_name, mother_name')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')\
            .order('name')\
            .limit(500)\
            .execute()
        
        students = students_response.data if students_response.data else []
        
        # Batch query for SMS settings
        sms_settings = get_sms_settings(institute_id)
        
        # Get current balance
        current_balance = institute.get('balance', 0) if institute else 0
        
        return render_template('message/index.html', 
                             classes=classes, 
                             students=students, 
                             institute=institute, 
                             sms_settings=sms_settings,
                             balance=current_balance)
        
    except Exception as e:
        print(f"Error loading message page: {e}")
        return render_template('message/index.html', classes=[], students=[], institute=None, sms_settings=None, balance=0)

@message_bp.route('/api/get-recipients', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def get_recipients():
    """Get recipients based on selected criteria - optimized with batch queries"""
    user = session.get('user')
    institute_id = get_institute_id_func(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        apply_to = data.get('apply_to')  # 'all', 'class', 'student'
        class_id = data.get('class_id')
        student_ids = data.get('student_ids', [])
        
        # Build query based on selection
        query = supabase.table('students')\
            .select('id, name, student_id, contact_number')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')
        
        if apply_to == 'class' and class_id:
            query = query.eq('class_id', class_id)
        elif apply_to == 'student' and student_ids:
            query = query.in_('id', student_ids)
        # 'all' - no additional filters
        
        # Execute query
        response = query.execute()
        
        # Process results with batch formatting
        recipients = []
        for student in response.data if response.data else []:
            phone = format_phone_number(student.get('contact_number', ''))
            if phone:
                recipients.append({
                    'id': student['id'],
                    'name': student['name'],
                    'student_id': student['student_id'],
                    'phone': phone
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
@role_required(['owner', 'teacher', 'accountant'])
def search_students():
    """Fast live search for students - optimized with batch query"""
    user = session.get('user')
    institute_id = get_institute_id_func(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        search_term = request.args.get('q', '').strip()
        class_id = request.args.get('class_id', '')
        
        # Don't search for terms less than 2 characters
        if len(search_term) < 2:
            return jsonify({'success': True, 'students': [], 'count': 0})
        
        # Build query with optimized join
        query = supabase.table('students')\
            .select('id, name, student_id, class_id, classes(name), contact_number, father_name, mother_name')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')
        
        # Apply class filter if provided
        if class_id:
            query = query.eq('class_id', class_id)
        
        # Apply search with OR condition - optimized for performance
        query = query.or_(f"name.ilike.%{search_term}%,student_id.ilike.%{search_term}%")
        
        # Limit results for performance
        response = query.limit(50).execute()
        
        # Process results
        students = []
        for student in response.data if response.data else []:
            phone = format_phone_number(student.get('contact_number', ''))
            if phone:
                students.append({
                    'id': student['id'],
                    'name': student['name'],
                    'student_id': student['student_id'],
                    'class_name': student['classes']['name'] if student.get('classes') else 'N/A',
                    'phone': phone,
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

@message_bp.route('/api/calculate-cost', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def calculate_cost():
    """Calculate SMS cost before sending"""
    user = session.get('user')
    institute_id = get_institute_id_func(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        message = data.get('message', '')
        recipient_count = data.get('recipient_count', 1)
        
        # Get SMS settings
        sms_settings = get_sms_settings(institute_id)
        cost_per_sms = sms_settings.get('cost_per_sms', 35) if sms_settings else 35
        
        # Calculate cost for one message
        cost_info = calculate_sms_cost(message, cost_per_sms)
        
        # Calculate total cost (cost per message * number of recipients)
        total_cost = cost_info['cost'] * recipient_count
        
        # Get current balance
        institute = get_institute_details(institute_id)
        current_balance = institute.get('balance', 0) if institute else 0
        
        return jsonify({
            'success': True,
            'cost_info': {
                'per_message': cost_info,
                'recipient_count': recipient_count,
                'total_cost': total_cost,
                'current_balance': current_balance,
                'has_sufficient_balance': current_balance >= total_cost,
                'balance_after': current_balance - total_cost
            }
        })
        
    except Exception as e:
        print(f"Error calculating cost: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@message_bp.route('/api/send', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def send_message():
    """Send SMS messages to selected recipients with balance checking - optimized with batch processing"""
    user = session.get('user')
    institute_id = get_institute_id_func(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        recipients = data.get('recipients', [])
        message = data.get('message', '').strip()
        sender_id = data.get('sender_id', 'SCHOOL')
        personalization = data.get('personalization', True)  # Whether to replace {student_name}
        
        if not recipients:
            return jsonify({'success': False, 'message': 'No recipients selected'}), 400
        
        if not message:
            return jsonify({'success': False, 'message': 'Message cannot be empty'}), 400
        
        # Get institute details
        institute = get_institute_details(institute_id)
        
        if not institute:
            return jsonify({'success': False, 'message': 'Institute not found'}), 400
        
        # Get SMS settings
        sms_settings = get_sms_settings(institute_id)
        
        if not sms_settings:
            return jsonify({'success': False, 'message': 'SMS settings not configured. Please configure SMS settings first.'}), 400
        
        if not sms_settings.get('enabled'):
            return jsonify({'success': False, 'message': 'SMS is not enabled. Please enable SMS in settings.'}), 400
        
        # Get cost per SMS from settings
        cost_per_sms = sms_settings.get('cost_per_sms', 35)
        
        # Prepare institute branding
        institute_name = institute.get('institute_name', 'School')
        
        # Calculate cost for one message without personalization
        full_message = f"{message}\n\n{institute_name}"
        cost_info = calculate_sms_cost(full_message, cost_per_sms)
        
        # Calculate total cost
        total_recipients = len(recipients)
        total_cost = cost_info['cost'] * total_recipients
        
        # Check institute balance
        current_balance = institute.get('balance', 0)
        
        if current_balance < total_cost:
            return jsonify({
                'success': False, 
                'message': f'Insufficient balance. Available: UGX {current_balance:,.0f}, Required: UGX {total_cost:,.0f} (for {total_recipients} recipient(s) x {cost_info["segments"]} segment(s) @ UGX {cost_per_sms}/segment)',
                'insufficient_balance': True,
                'balance': current_balance,
                'required': total_cost
            }), 400
        
        # Check master API credentials
        if not MASTER_API_USERNAME or not MASTER_API_KEY:
            return jsonify({'success': False, 'message': 'SMS API credentials not configured. Please contact support.'}), 500
        
        # Send SMS using master credentials
        try:
            from comms_sdk import CommsSDK, MessagePriority
            
            sdk = CommsSDK.authenticate(MASTER_API_USERNAME, MASTER_API_KEY)
            
            # Prepare batch phone numbers and messages
            phone_numbers = []
            recipient_map = {}
            log_entries = []
            success_count = 0
            failed_recipients = []
            
            # Prepare personalized messages if needed
            for recipient in recipients:
                phone = recipient.get('phone', '').strip()
                if not phone:
                    continue
                
                formatted_phone = format_phone_number(phone)
                if not formatted_phone:
                    continue
                
                # Personalize message with student name
                student_name = recipient.get('name', 'Student')
                personalized_msg = full_message
                if personalization and '{student_name}' in personalized_msg:
                    personalized_msg = personalized_msg.replace('{student_name}', student_name)
                elif personalization:
                    # If no placeholder, still add student name at top
                    personalized_msg = f"Dear {student_name},\n\n{personalized_msg}"
                
                # Check if message exceeds limit for this recipient (due to name length)
                personalized_cost = calculate_sms_cost(personalized_msg, cost_per_sms)
                
                phone_numbers.append(formatted_phone)
                recipient_map[formatted_phone] = {
                    'recipient': recipient,
                    'message': personalized_msg,
                    'cost': personalized_cost
                }
            
            if not phone_numbers:
                return jsonify({'success': False, 'message': 'No valid phone numbers found'}), 400
            
            # Send in batches of 100 for faster processing
            batch_size = 100
            all_successful = True
            
            for i in range(0, len(phone_numbers), batch_size):
                batch_phones = phone_numbers[i:i+batch_size]
                
                # Prepare batch messages (all same since we personalize individually)
                # We'll send personalized messages one by one but in a batch
                try:
                    # For each phone in batch, send personalized message
                    for phone in batch_phones:
                        recipient_data = recipient_map.get(phone, {})
                        if not recipient_data:
                            continue
                        
                        personal_msg = recipient_data.get('message', full_message)
                        personal_cost = recipient_data.get('cost', cost_info)
                        
                        try:
                            response = sdk.send_sms(
                                [phone],
                                personal_msg,
                                sender_id=sender_id[:11],  # Max 11 characters
                                priority=MessagePriority.HIGHEST
                            )
                            
                            success_count += 1
                            
                            # Prepare log entry
                            log_entries.append({
                                'institute_id': institute_id,
                                'student_id': recipient_data['recipient'].get('id'),
                                'phone_number': phone,
                                'message': personal_msg,
                                'message_length': len(personal_msg),
                                'segments': personal_cost['segments'],
                                'cost': personal_cost['cost'],
                                'status': 'sent'
                            })
                            
                        except Exception as single_error:
                            all_successful = False
                            failed_recipients.append(phone)
                            log_entries.append({
                                'institute_id': institute_id,
                                'student_id': recipient_data['recipient'].get('id'),
                                'phone_number': phone,
                                'message': personal_msg,
                                'message_length': len(personal_msg),
                                'segments': personal_cost['segments'],
                                'cost': personal_cost['cost'],
                                'status': 'failed',
                                'error_message': str(single_error)
                            })
                            print(f"Error sending to {phone}: {single_error}")
                            
                except Exception as batch_error:
                    all_successful = False
                    print(f"Error processing batch: {batch_error}")
                    for phone in batch_phones:
                        recipient_data = recipient_map.get(phone, {})
                        if recipient_data:
                            failed_recipients.append(phone)
                            log_entries.append({
                                'institute_id': institute_id,
                                'student_id': recipient_data['recipient'].get('id'),
                                'phone_number': phone,
                                'message': recipient_data.get('message', full_message),
                                'message_length': len(recipient_data.get('message', full_message)),
                                'segments': cost_info['segments'],
                                'cost': cost_info['cost'],
                                'status': 'failed',
                                'error_message': str(batch_error)
                            })
            
            # Batch log all entries
            if log_entries:
                log_bulk_sms_sent(log_entries)
            
            # Only deduct balance if at least one message was sent successfully
            if success_count > 0:
                # Calculate actual cost based on successful sends
                actual_cost = 0
                for entry in log_entries:
                    if entry.get('status') == 'sent':
                        actual_cost += entry.get('cost', 0)
                
                # Deduct from balance
                deduct_success, result = deduct_from_balance(institute_id, actual_cost)
                
                if not deduct_success:
                    print(f"Warning: SMS sent but balance deduction failed: {result}")
                    return jsonify({
                        'success': True,
                        'message': f'Message sent to {success_count} recipient(s) but balance deduction failed. Please contact support.',
                        'recipient_count': success_count,
                        'balance_deduction_failed': True
                    })
                
                # Get updated balance for response
                updated_institute = get_institute_details(institute_id)
                new_balance = updated_institute.get('balance', 0) if updated_institute else 0
                
                response_message = f'Message sent successfully to {success_count} of {total_recipients} recipient(s).'
                if failed_recipients:
                    response_message += f' Failed: {len(failed_recipients)} recipient(s).'
                
                return jsonify({
                    'success': True,
                    'message': response_message,
                    'recipient_count': success_count,
                    'total_recipients': total_recipients,
                    'failed_count': len(failed_recipients),
                    'cost': actual_cost,
                    'new_balance': new_balance,
                    'segments_per_sms': cost_info['segments'],
                    'cost_per_sms': cost_info['cost']
                })
            else:
                return jsonify({
                    'success': False,
                    'message': f'Failed to send any messages. No messages were sent and no balance was deducted.',
                    'failed_count': len(failed_recipients)
                }), 500
            
        except ImportError:
            return jsonify({'success': False, 'message': 'CommsSDK not installed. Please install it first.'}), 500
        except Exception as e:
            error_msg = str(e)
            print(f"SMS sending error: {error_msg}")
            return jsonify({'success': False, 'message': f'SMS sending failed: {error_msg}'}), 500
            
    except Exception as e:
        print(f"Error sending message: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@message_bp.route('/api/message-history', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_message_history():
    """Get SMS sending history from sms_log table"""
    user = session.get('user')
    institute_id = get_institute_id_func(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        limit = request.args.get('limit', 100, type=int)
        
        # Get SMS history from sms_log table
        response = supabase.table('sms_log')\
            .select('*, students(name, student_id)')\
            .eq('institute_id', institute_id)\
            .order('sent_at', desc=True)\
            .limit(limit)\
            .execute()
        
        logs = response.data if response.data else []
        
        # Format the logs for display
        formatted_logs = []
        for log in logs:
            formatted_logs.append({
                'id': log.get('id'),
                'phone_number': log.get('phone_number'),
                'student_name': log.get('students', {}).get('name') if log.get('students') else None,
                'student_id': log.get('students', {}).get('student_id') if log.get('students') else None,
                'message': log.get('message'),
                'segments': log.get('segments'),
                'cost': log.get('cost'),
                'status': log.get('status'),
                'error_message': log.get('error_message'),
                'sent_at': log.get('sent_at')
            })
        
        # Get summary stats
        stats_response = supabase.table('sms_log')\
            .select('status', count='exact')\
            .eq('institute_id', institute_id)\
            .execute()
        
        total_sent = 0
        total_failed = 0
        total_cost = 0
        
        if stats_response.data:
            for log in stats_response.data:
                if log.get('status') == 'sent':
                    total_sent += 1
                elif log.get('status') == 'failed':
                    total_failed += 1
        
        # Get total cost
        cost_response = supabase.table('sms_log')\
            .select('cost')\
            .eq('institute_id', institute_id)\
            .eq('status', 'sent')\
            .execute()
        
        if cost_response.data:
            total_cost = sum(log.get('cost', 0) for log in cost_response.data)
        
        return jsonify({
            'success': True, 
            'logs': formatted_logs,
            'summary': {
                'total_sent': total_sent,
                'total_failed': total_failed,
                'total_cost': total_cost
            }
        })
        
    except Exception as e:
        print(f"Error getting message history: {e}")
        return jsonify({'success': True, 'logs': [], 'summary': {'total_sent': 0, 'total_failed': 0, 'total_cost': 0}})

@message_bp.route('/api/get-balance', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_balance():
    """Get current institute balance"""
    user = session.get('user')
    institute_id = get_institute_id_func(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'balance': 0}), 400
    
    institute = get_institute_details(institute_id)
    
    return jsonify({
        'success': True,
        'balance': institute.get('balance', 0) if institute else 0,
        'total_spent': institute.get('total_spent', 0) if institute else 0
    })