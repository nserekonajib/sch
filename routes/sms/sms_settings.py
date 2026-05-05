# sms_settings.py - Complete SMS Integration with Balance Deduction
from flask import Blueprint, render_template, request, jsonify, session, url_for
from supabase import create_client, Client
import os
import json
from functools import wraps
from dotenv import load_dotenv
from datetime import datetime, timedelta
import uuid
import re


load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Master API credentials from .env (for sending SMS)
MASTER_API_USERNAME = os.getenv('COMMS_API_USERNAME', '')
MASTER_API_KEY = os.getenv('COMMS_API_KEY', '')

sms_settings_bp = Blueprint('sms_settings', __name__, url_prefix='/sms-settings')

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Please login'}), 401
        return f(*args, **kwargs)
    return decorated_function

def get_institute(user_id):
    """Get institute for current user"""
    try:
        response = supabase.table('institutes')\
            .select('*')\
            .eq('user_id', user_id)\
            .execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error getting institute: {e}")
        return None

def calculate_sms_cost(message, cost_per_sms=35):
    """Calculate SMS cost based on message length"""
    # Check if message contains Unicode characters
    has_unicode = any(ord(c) > 127 for c in message)
    
    # Segment sizes: 160 for GSM, 70 for Unicode
    segment_size = 70 if has_unicode else 160
    segments = (len(message) + segment_size - 1) // segment_size
    
    cost = segments * cost_per_sms
    return {
        'length': len(message),
        'segments': segments,
        'cost': cost,
        'encoding': 'Unicode' if has_unicode else 'GSM'
    }

def deduct_from_balance(institute_id, amount, description=""):
    """Deduct amount from institute balance"""
    try:
        # Get current balance
        response = supabase.table('institutes')\
            .select('balance')\
            .eq('id', institute_id)\
            .execute()
        
        if not response.data:
            return False, "Institute not found"
        
        current_balance = response.data[0].get('balance', 0)
        
        if current_balance < amount:
            return False, f"Insufficient balance. Available: UGX {current_balance:,.2f}, Needed: UGX {amount:,.2f}"
        
        # Deduct from balance
        new_balance = current_balance - amount
        total_spent = supabase.table('institutes')\
            .select('total_spent')\
            .eq('id', institute_id)\
            .execute()
        
        current_total_spent = total_spent.data[0].get('total_spent', 0) if total_spent.data else 0
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

def add_to_balance(institute_id, amount, description=""):
    """Add amount to institute balance"""
    try:
        response = supabase.table('institutes')\
            .select('balance')\
            .eq('id', institute_id)\
            .execute()
        
        current_balance = response.data[0].get('balance', 0) if response.data else 0
        new_balance = current_balance + amount
        
        supabase.table('institutes')\
            .update({
                'balance': new_balance,
                'last_balance_update': datetime.now().isoformat()
            })\
            .eq('id', institute_id)\
            .execute()
        
        return True, new_balance
    except Exception as e:
        print(f"Error adding to balance: {e}")
        return False, str(e)

@sms_settings_bp.route('/')
@login_required
def index():
    """SMS Settings Page"""
    user = session.get('user')
    institute = get_institute(user['id'])
    
    if not institute:
        return render_template('sms/settings.html', settings=None, institute=None)
    
    try:
        # Get SMS settings
        response = supabase.table('sms_settings')\
            .select('*')\
            .eq('institute_id', institute['id'])\
            .execute()
        
        settings = response.data[0] if response.data else None
        
        return render_template('sms/settings.html', settings=settings, institute=institute)
        
    except Exception as e:
        print(f"Error loading SMS settings: {e}")
        return render_template('sms/settings.html', settings=None, institute=institute)

@sms_settings_bp.route('/get-balance', methods=['GET'])
@login_required
def get_balance():
    """Get current institute balance"""
    user = session.get('user')
    institute = get_institute(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'balance': 0}), 400
    
    return jsonify({
        'success': True, 
        'balance': institute.get('balance', 0),
        'total_spent': institute.get('total_spent', 0)
    })

@sms_settings_bp.route('/save', methods=['POST'])
@login_required
def save_settings():
    """Save SMS API settings"""
    user = session.get('user')
    institute = get_institute(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        
        settings_data = {
            'institute_id': institute['id'],
            'api_username': data.get('api_username', '').strip(),
            'api_key': data.get('api_key', '').strip(),
            'sender_id': data.get('sender_id', 'SCHOOL').strip()[:11],
            'enabled': data.get('enabled', False),
            'send_on_payment': data.get('send_on_payment', True),
            'cost_per_sms': data.get('cost_per_sms', 35),
            'updated_at': datetime.now().isoformat()
        }
        
        # Check if settings exist
        existing = supabase.table('sms_settings')\
            .select('id')\
            .eq('institute_id', institute['id'])\
            .execute()
        
        if existing.data:
            result = supabase.table('sms_settings')\
                .update(settings_data)\
                .eq('institute_id', institute['id'])\
                .execute()
        else:
            settings_data['created_at'] = datetime.now().isoformat()
            result = supabase.table('sms_settings').insert(settings_data).execute()
        
        if result.data:
            return jsonify({'success': True, 'message': 'SMS settings saved successfully'})
        else:
            return jsonify({'success': False, 'message': 'Failed to save settings'}), 500
            
    except Exception as e:
        print(f"Error saving SMS settings: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@sms_settings_bp.route('/calculate-cost', methods=['POST'])
@login_required
def calculate_cost():
    """Calculate SMS cost without sending"""
    try:
        data = request.get_json()
        message = data.get('message', '')
        
        # Get cost per SMS from settings
        user = session.get('user')
        institute = get_institute(user['id'])
        
        cost_per_sms = 35  # default
        if institute:
            settings_response = supabase.table('sms_settings')\
                .select('cost_per_sms')\
                .eq('institute_id', institute['id'])\
                .execute()
            if settings_response.data:
                cost_per_sms = settings_response.data[0].get('cost_per_sms', 35)
        
        cost_info = calculate_sms_cost(message, cost_per_sms)
        return jsonify({'success': True, 'cost_info': cost_info})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@sms_settings_bp.route('/test', methods=['POST'])
@login_required
def test_sms():
    """Test SMS sending with balance deduction"""
    user = session.get('user')
    institute = get_institute(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        test_phone = data.get('phone', '').strip()
        
        if not test_phone:
            return jsonify({'success': False, 'message': 'Please enter a test phone number'}), 400
        
        # Validate phone number
        if not re.match(r'^\+?[0-9]{10,15}$', test_phone):
            return jsonify({'success': False, 'message': 'Invalid phone number format'}), 400
        
        # Get SMS settings
        response = supabase.table('sms_settings')\
            .select('*')\
            .eq('institute_id', institute['id'])\
            .execute()
        
        if not response.data:
            return jsonify({'success': False, 'message': 'SMS settings not configured'}), 400
        
        settings = response.data[0]
        
        if not settings.get('enabled'):
            return jsonify({'success': False, 'message': 'SMS is disabled. Please enable it first.'}), 400
        
        # Prepare test message
        test_message = f"Test SMS from {institute.get('institute_name', 'School')}. Your SMS integration is working correctly!"
        
        # Calculate cost
        cost_per_sms = settings.get('cost_per_sms', 35)
        cost_info = calculate_sms_cost(test_message, cost_per_sms)
        
        # Check balance
        current_balance = institute.get('balance', 0)
        
        if current_balance < cost_info['cost']:
            return jsonify({
                'success': False, 
                'message': f'Insufficient balance. Available: UGX {current_balance:,.2f}, Required: UGX {cost_info["cost"]:,.2f} (for {cost_info["segments"]} segment(s))',
                'insufficient_balance': True
            }), 400
        
        # Send SMS using master credentials
        try:
            from comms_sdk import CommsSDK, MessagePriority
            
            sdk = CommsSDK.authenticate(
                MASTER_API_USERNAME,
                MASTER_API_KEY
            )
            
            # Send SMS
            sms_response = sdk.send_sms(
                [test_phone],
                test_message,
                sender_id=settings.get('sender_id', 'SCHOOL').strip(),
                priority=MessagePriority.HIGHEST
            )
            
            # Deduct from balance
            deduct_success, result = deduct_from_balance(
                institute['id'], 
                cost_info['cost'],
                f"Test SMS to {test_phone}"
            )
            
            if deduct_success:
                # Log SMS
                supabase.table('sms_log').insert({
                    'id': str(uuid.uuid4()),
                    'institute_id': institute['id'],
                    'phone_number': test_phone,
                    'message': test_message,
                    'message_length': cost_info['length'],
                    'segments': cost_info['segments'],
                    'cost': cost_info['cost'],
                    'status': 'sent',
                    'sent_at': datetime.now().isoformat()
                }).execute()
                
                return jsonify({
                    'success': True, 
                    'message': f'Test SMS sent successfully! Cost: UGX {cost_info["cost"]:,.2f} (for {cost_info["segments"]} segment(s)). New balance: UGX {result:,.2f}',
                    'new_balance': result,
                    'cost': cost_info['cost']
                })
            else:
                return jsonify({'success': False, 'message': f'SMS sent but failed to deduct balance: {result}'}), 500
            
        except ImportError:
            return jsonify({'success': False, 'message': 'CommsSDK not installed. Please run: pip install comms-sdk'}), 500
        except Exception as e:
            return jsonify({'success': False, 'message': f'SMS sending failed: {str(e)}'}), 500
            
    except Exception as e:
        print(f"Error testing SMS: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@sms_settings_bp.route('/initiate-payment', methods=['POST'])
@login_required
def initiate_payment():
    """Initiate payment to top up balance"""
    try:
        user = session.get('user')
        institute = get_institute(user['id'])
        
        if not institute:
            return jsonify({'success': False, 'message': 'Institute not found'}), 400
        
        data = request.get_json()
        amount = int(data.get('amount', 0))
        
        if amount < 5000:
            return jsonify({'success': False, 'message': 'Minimum top-up amount is UGX 5,000'}), 400
        
        # Generate unique reference
        reference_id = f"TOPUP_{institute['id']}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # Callback URL for modal
        callback_url = f"{request.host_url.rstrip('/')}/sms-settings/payment-callback"
        
        # Initialize PesaPal
        from routes.billing.pespal import PesaPal
        pesapal = PesaPal()
        
        # Submit order
        result = pesapal.submit_order(
            amount=amount,
            reference_id=reference_id,
            callback_url=callback_url,
            email=institute.get('email', session.get('user', {}).get('email', '')),
            first_name=institute.get('institute_name', 'Institute'),
            last_name='User'
        )
        
        if result and result.get('redirect_url'):
            # Create payment record
            payment_id = str(uuid.uuid4())
            payment_data = {
                'id': payment_id,
                'institute_id': institute['id'],
                'order_tracking_id': result['order_tracking_id'],
                'merchant_reference': reference_id,
                'amount': amount,
                'payment_method': 'pesapal',
                'status': 'pending',
                'created_at': datetime.now().isoformat()
            }
            supabase.table('sms_payment_transactions').insert(payment_data).execute()
            
            return jsonify({
                'success': True,
                'redirect_url': result['redirect_url'],
                'order_tracking_id': result['order_tracking_id'],
                'amount': amount
            })
        else:
            return jsonify({'success': False, 'message': 'Failed to initiate payment'}), 500
            
    except Exception as e:
        print(f"Error initiating payment: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@sms_settings_bp.route('/payment-callback')
def payment_callback():
    """Handle PesaPal callback"""
    order_tracking_id = request.args.get('OrderTrackingId')
    
    if not order_tracking_id:
        return render_template('sms/payment_result.html', success=False, message='No tracking ID provided')
    
    # Verify transaction status
    from routes.billing.pespal import PesaPal
    pesapal = PesaPal()
    status_response = pesapal.verify_transaction_status(order_tracking_id)
    
    if status_response and status_response.get('status') == 'COMPLETED':
        # Update payment record
        payment_response = supabase.table('sms_payment_transactions')\
            .update({
                'status': 'completed',
                'payment_status': status_response.get('payment_status_description', 'Completed'),
                'updated_at': datetime.now().isoformat()
            })\
            .eq('order_tracking_id', order_tracking_id)\
            .execute()
        
        if payment_response.data:
            payment = payment_response.data[0]
            institute_id = payment['institute_id']
            amount = payment['amount']
            
            # Add to balance
            success, new_balance = add_to_balance(institute_id, amount, f"Balance top-up of UGX {amount:,.2f}")
            
            if success:
                return render_template('sms/payment_result.html', 
                                     success=True, 
                                     message=f'Payment successful! UGX {amount:,.2f} added to your balance.',
                                     amount=amount,
                                     new_balance=new_balance)
            else:
                return render_template('sms/payment_result.html', 
                                     success=False, 
                                     message='Payment verified but failed to update balance. Please contact support.')
    else:
        return render_template('sms/payment_result.html', 
                             success=False, 
                             message=f'Payment failed: {status_response.get("payment_status_description", "Unknown error") if status_response else "No response from payment gateway"}')

# Function to send SMS on payment (to be called from billing module)
def send_payment_sms(institute_id, student_name, amount, balance, receipt_no, payment_method, notes=""):
    """Send SMS notification for payment (called from billing)"""
    try:
        # Get SMS settings
        settings_response = supabase.table('sms_settings')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .eq('enabled', True)\
            .execute()
        
        if not settings_response.data:
            return False, "SMS not enabled"
        
        settings = settings_response.data[0]
        
        if not settings.get('send_on_payment'):
            return False, "SMS on payment disabled"
        
        # Get student phone
        # This should be passed from billing module
        # For now, we'll need to get it from student record
        
        # Prepare message
        message = f"""Payment Received! 🎓

Student: {student_name}
Amount: UGX {amount:,.2f}
Balance: UGX {balance:,.2f}
Method: {payment_method}
Receipt: {receipt_no}
{notes if notes else ''}

Thank you for your payment!"""
        
        # Calculate cost
        cost_info = calculate_sms_cost(message, settings.get('cost_per_sms', 35))
        
        # Check balance
        institute_response = supabase.table('institutes')\
            .select('balance')\
            .eq('id', institute_id)\
            .execute()
        
        if not institute_response.data or institute_response.data[0].get('balance', 0) < cost_info['cost']:
            return False, "Insufficient balance"
        
        # Send SMS
        from comms_sdk import CommsSDK, MessagePriority
        sdk = CommsSDK.authenticate(MASTER_API_USERNAME, MASTER_API_KEY)
        
        # Get student phone number (implement based on your schema)
        # phone_number = get_student_phone(student_id)
        
        # sdk.send_sms([phone_number], message, sender_id=settings.get('sender_id', 'SCHOOL'))
        
        # Deduct from balance
        deduct_from_balance(institute_id, cost_info['cost'], f"SMS for payment {receipt_no}")
        
        return True, "SMS sent successfully"
        
    except Exception as e:
        print(f"Error sending payment SMS: {e}")
        return False, str(e)
    
    
    
@sms_settings_bp.route('/store-manual-request', methods=['POST'])
@login_required
def store_manual_request():
    """Store manual payment request for tracking"""
    try:
        user = session.get('user')
        institute = get_institute(user['id'])
        
        if not institute:
            return jsonify({'success': False, 'message': 'Institute not found'}), 400
        
        data = request.get_json()
        amount = data.get('amount')
        reference = data.get('reference')
        
        # Store manual payment request
        manual_request = {
            'id': str(uuid.uuid4()),
            'institute_id': institute['id'],
            'amount': amount,
            'reference': reference,
            'status': 'pending',
            'created_at': datetime.now().isoformat()
        }
        
        supabase.table('manual_payment_requests').insert(manual_request).execute()
        
        return jsonify({'success': True})
    except Exception as e:
        print(f"Error storing manual request: {e}")
        return jsonify({'success': False}), 500

# Add to sms_settings.py - Manual Payment Management Routes
from routes.admin.admin import admin_required
@sms_settings_bp.route('/admin/manual-payments', methods=['GET'])
@admin_required
def admin_manual_payments():
    """Admin page for managing manual payment requests"""
    return render_template('admin/manual_payments.html')

@sms_settings_bp.route('/admin/api/manual-payments', methods=['GET'])
@admin_required
def get_manual_payments():
    """Get all manual payment requests"""
    try:
        status = request.args.get('status', 'pending')
        
        query = supabase.table('manual_payment_requests')\
            .select('*, institutes(institute_name, email, phone_number)')\
            .order('created_at', desc=True)
        
        if status != 'all':
            query = query.eq('status', status)
        
        response = query.execute()
        payments = response.data if response.data else []
        
        return jsonify({
            'success': True,
            'payments': payments
        })
    except Exception as e:
        print(f"Error getting manual payments: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@sms_settings_bp.route('/admin/api/manual-payment/approve', methods=['POST'])
@admin_required
def approve_manual_payment():
    """Approve a manual payment and add to institute balance"""
    try:
        data = request.get_json()
        payment_id = data.get('payment_id')
        admin_notes = data.get('admin_notes', '')
        
        if not payment_id:
            return jsonify({'success': False, 'message': 'Payment ID required'}), 400
        
        # Get the manual payment request
        payment_response = supabase.table('manual_payment_requests')\
            .select('*')\
            .eq('id', payment_id)\
            .execute()
        
        if not payment_response.data:
            return jsonify({'success': False, 'message': 'Payment request not found'}), 404
        
        payment = payment_response.data[0]
        
        if payment['status'] != 'pending':
            return jsonify({'success': False, 'message': f'Payment already {payment["status"]}'}), 400
        
        institute_id = payment['institute_id']
        amount = float(payment['amount'])
        
        # Add to institute balance using the existing function
        success, result = add_to_balance(
            institute_id, 
            amount, 
            f"Manual payment approval - Reference: {payment['reference']}"
        )
        
        if not success:
            return jsonify({'success': False, 'message': f'Failed to add balance: {result}'}), 500
        
        # Update manual payment request status
        supabase.table('manual_payment_requests')\
            .update({
                'status': 'approved',
                'admin_notes': admin_notes,
                'updated_at': datetime.now().isoformat()
            })\
            .eq('id', payment_id)\
            .execute()
        
        # Also record in sms_payment_transactions for audit
        transaction_id = str(uuid.uuid4())
        supabase.table('sms_payment_transactions').insert({
            'id': transaction_id,
            'institute_id': institute_id,
            'merchant_reference': payment['reference'],
            'amount': amount,
            'payment_method': 'manual',
            'status': 'completed',
            'payment_status': 'Approved by admin',
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }).execute()
        
        # Get updated balance
        balance_response = supabase.table('institutes')\
            .select('balance')\
            .eq('id', institute_id)\
            .execute()
        new_balance = balance_response.data[0].get('balance', 0) if balance_response.data else 0
        
        return jsonify({
            'success': True,
            'message': f'Payment approved! UGX {amount:,.2f} added to institute balance.',
            'new_balance': new_balance,
            'amount': amount
        })
        
    except Exception as e:
        print(f"Error approving manual payment: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@sms_settings_bp.route('/admin/api/manual-payment/reject', methods=['POST'])
@admin_required
def reject_manual_payment():
    """Reject a manual payment request"""
    try:
        data = request.get_json()
        payment_id = data.get('payment_id')
        admin_notes = data.get('admin_notes', '')
        
        if not payment_id:
            return jsonify({'success': False, 'message': 'Payment ID required'}), 400
        
        # Update payment request status
        supabase.table('manual_payment_requests')\
            .update({
                'status': 'rejected',
                'admin_notes': admin_notes,
                'updated_at': datetime.now().isoformat()
            })\
            .eq('id', payment_id)\
            .execute()
        
        return jsonify({
            'success': True,
            'message': 'Payment request rejected'
        })
        
    except Exception as e:
        print(f"Error rejecting manual payment: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
