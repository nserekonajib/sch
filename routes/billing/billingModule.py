# billingModule.py - Updated with dynamic pricing and discounts
from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
from supabase import create_client, Client
import os
import uuid
from datetime import datetime, timedelta
import json
from functools import wraps
from dotenv import load_dotenv
from routes.accounts.accounts import get_institute_from_session
from routes.billing.pespal import PesaPal
from routes.auth.auth import owner_required

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Get pricing from environment variables
BASE_PRICE = float(os.getenv('SUBSCRIPTION_PRICE', 50000))  # Default 50,000 UGX
DISCOUNT_6_MONTHS = float(os.getenv('DISCOUNT_6_MONTHS', 0.10))  # 10% discount
DISCOUNT_12_MONTHS = float(os.getenv('DISCOUNT_12_MONTHS', 0.15))  # 15% discount

def calculate_price(months):
    """Calculate price based on months with discounts"""
    if months == 6:
        return BASE_PRICE * months * (1 - DISCOUNT_6_MONTHS)
    elif months == 12:
        return BASE_PRICE * months * (1 - DISCOUNT_12_MONTHS)
    else:
        return BASE_PRICE * months

billing_bp = Blueprint('billing', __name__, url_prefix='/billing')

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            if request.is_json:
                return jsonify({'success': False, 'message': 'Please login'}), 401
            flash('Please login to access this page', 'warning')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

@billing_bp.route('/')
@owner_required
def index():
    """Billing Dashboard"""
    try:
        # Get institute object (returns full institute dict)
        institute = get_institute_from_session()
        
        # Calculate discounted prices for display
        price_per_month = BASE_PRICE
        price_6_months = calculate_price(6)
        price_12_months = calculate_price(12)
        
        # Extract institute_id correctly
        institute_id = None
        if institute and isinstance(institute, dict):
            institute_id = institute.get('id')
            print(f"Institute found: {institute.get('institute_name')} with ID: {institute_id}")
        else:
            print(f"No institute found, institute object: {institute}")
        
        if not institute_id:
            return render_template('billing/index.html', 
                                  subscription=None, 
                                  payments=[],
                                  is_active=False,
                                  days_remaining=0,
                                  price_per_month=price_per_month,
                                  price_6_months=price_6_months,
                                  price_12_months=price_12_months,
                                  discount_6_months=DISCOUNT_6_MONTHS,
                                  discount_12_months=DISCOUNT_12_MONTHS)
        
        # Get subscription from organization_billing
        sub_response = supabase.table('organization_billing')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .execute()
        
        subscription = sub_response.data[0] if sub_response.data else None
        
        # Get payment history from payment_transactions
        payments_response = supabase.table('payment_transactions')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('created_at', desc=True)\
            .limit(10)\
            .execute()
        
        payments = payments_response.data if payments_response.data else []
        
        # Calculate subscription status
        today = datetime.now().date()
        is_active = False
        days_remaining = 0
        
        if subscription:
            expiry_date_str = subscription.get('expiry_date')
            if expiry_date_str:
                # Handle both string and date formats
                if isinstance(expiry_date_str, str):
                    expiry_date = datetime.strptime(expiry_date_str, '%Y-%m-%d').date()
                else:
                    expiry_date = expiry_date_str
                is_active = expiry_date >= today
                days_remaining = (expiry_date - today).days if expiry_date >= today else 0
        
        return render_template('billing/index.html', 
                              subscription=subscription, 
                              payments=payments,
                              is_active=is_active,
                              days_remaining=days_remaining,
                              price_per_month=price_per_month,
                              price_6_months=price_6_months,
                              price_12_months=price_12_months,
                              discount_6_months=DISCOUNT_6_MONTHS,
                              discount_12_months=DISCOUNT_12_MONTHS)
        
    except Exception as e:
        print(f"Error loading billing page: {e}")
        import traceback
        traceback.print_exc()
        
        price_per_month = BASE_PRICE
        price_6_months = calculate_price(6)
        price_12_months = calculate_price(12)
        
        return render_template('billing/index.html', 
                              subscription=None, 
                              payments=[], 
                              is_active=False, 
                              days_remaining=0,
                              price_per_month=price_per_month,
                              price_6_months=price_6_months,
                              price_12_months=price_12_months,
                              discount_6_months=DISCOUNT_6_MONTHS,
                              discount_12_months=DISCOUNT_12_MONTHS)

@billing_bp.route('/initiate-payment', methods=['POST'])
@login_required
def initiate_payment():
    """Initiate payment with PesaPal"""
    try:
        # Get institute object and extract ID
        institute = get_institute_from_session()
        
        if not institute or not isinstance(institute, dict):
            return jsonify({'success': False, 'message': 'Institute not found'}), 400
        
        institute_id = institute.get('id')
        
        if not institute_id:
            return jsonify({'success': False, 'message': 'Institute ID not found'}), 400
        
        data = request.get_json()
        months = int(data.get('months', 1))
        
        # Only allow 1, 6, or 12 months
        if months not in [1, 6, 12]:
            return jsonify({'success': False, 'message': 'Invalid subscription period'}), 400
        
        # Calculate amount with discount
        amount = calculate_price(months)
        
        # Get institute details
        institute_response = supabase.table('institutes')\
            .select('institute_name, email, phone_number')\
            .eq('id', institute_id)\
            .execute()
        
        inst_data = institute_response.data[0] if institute_response.data else {}
        
        # Generate unique reference
        reference_id = f"SUB_{institute_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # Callback URL
        callback_url = f"{request.host_url.rstrip('/')}/billing/payment-callback"
        
        # Initialize PesaPal
        pesapal = PesaPal()
        
        # Submit order
        result = pesapal.submit_order(
            amount=amount,
            reference_id=reference_id,
            callback_url=callback_url,
            email=inst_data.get('email', session.get('user', {}).get('email', '')),
            first_name=inst_data.get('institute_name', 'Institute'),
            last_name='User'
        )
        
        if result and result.get('redirect_url'):
            # Create payment record in payment_transactions
            payment_id = str(uuid.uuid4())
            payment_data = {
                'id': payment_id,
                'institute_id': institute_id,
                'order_tracking_id': result['order_tracking_id'],
                'merchant_reference': reference_id,
                'amount': amount,
                'months': months,
                'status': 'pending',
                'payment_method': 'pesapal',
                'created_at': datetime.now().isoformat()
            }
            supabase.table('payment_transactions').insert(payment_data).execute()
            
            return jsonify({
                'success': True,
                'redirect_url': result['redirect_url'],
                'order_tracking_id': result['order_tracking_id']
            })
        else:
            print(f"Failed to initiate payment. PesaPal response: {result}")
            return jsonify({'success': False, 'message': 'Failed to initiate payment'}), 500
            
    except Exception as e:
        print(f"Error initiating payment: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@billing_bp.route('/payment-callback')
def payment_callback():
    """Handle PesaPal callback"""
    order_tracking_id = request.args.get('OrderTrackingId')
    order_merchant_reference = request.args.get('OrderMerchantReference')
    
    print(f"Callback received - OrderTrackingId: {order_tracking_id}")
    print(f"Callback received - OrderMerchantReference: {order_merchant_reference}")
    
    if not order_tracking_id:
        return redirect(url_for('billing.index'))
    
    # Verify transaction status
    pesapal = PesaPal()
    status_response = pesapal.verify_transaction_status(order_tracking_id)
    
    print(f"Verification response: {status_response}")
    
    # Check if payment was successful
    if status_response and status_response.get('status') == 'COMPLETED':
        # Update payment record
        payment_response = supabase.table('payment_transactions')\
            .update({
                'status': 'completed',
                'payment_status': status_response.get('payment_status_description', 'Completed'),
                'updated_at': datetime.now().isoformat()
            })\
            .eq('order_tracking_id', order_tracking_id)\
            .execute()
        
        print(f"Payment update response: {payment_response.data}")
        
        if payment_response.data:
            payment = payment_response.data[0]
            institute_id = payment['institute_id']
            months = payment['months']
            
            # Update or create subscription in organization_billing
            current_date = datetime.now().date()
            expiry_date = current_date + timedelta(days=30 * months)
            
            # Check if subscription exists
            sub_response = supabase.table('organization_billing')\
                .select('*')\
                .eq('institute_id', institute_id)\
                .execute()
            
            if sub_response.data:
                # Extend existing subscription
                existing_expiry_str = sub_response.data[0].get('expiry_date')
                if existing_expiry_str:
                    if isinstance(existing_expiry_str, str):
                        existing_expiry = datetime.strptime(existing_expiry_str, '%Y-%m-%d').date()
                    else:
                        existing_expiry = existing_expiry_str
                    
                    if existing_expiry > current_date:
                        new_expiry = existing_expiry + timedelta(days=30 * months)
                    else:
                        new_expiry = expiry_date
                else:
                    new_expiry = expiry_date
                
                supabase.table('organization_billing')\
                    .update({
                        'expiry_date': new_expiry.isoformat(),
                        'status': 'active',
                        'updated_at': datetime.now().isoformat()
                    })\
                    .eq('institute_id', institute_id)\
                    .execute()
                print(f"Subscription extended to: {new_expiry}")
            else:
                # Create new subscription
                sub_data = {
                    'id': str(uuid.uuid4()),
                    'institute_id': institute_id,
                    'start_date': current_date.isoformat(),
                    'expiry_date': expiry_date.isoformat(),
                    'status': 'active',
                    'created_at': datetime.now().isoformat()
                }
                supabase.table('organization_billing').insert(sub_data).execute()
                print(f"New subscription created until: {expiry_date}")
    else:
        print(f"Payment verification failed. Status: {status_response.get('status') if status_response else 'No response'}")
        # Update payment as failed
        supabase.table('payment_transactions')\
            .update({
                'status': 'failed',
                'payment_status': status_response.get('payment_status_description', 'Payment failed') if status_response else 'Verification failed',
                'updated_at': datetime.now().isoformat()
            })\
            .eq('order_tracking_id', order_tracking_id)\
            .execute()
    
    return redirect(url_for('billing.index'))

@billing_bp.route('/ipn', methods=['GET', 'POST'])
def ipn_handler():
    """Handle PesaPal IPN (Instant Payment Notification)"""
    print(f"IPN received: {request.args}")
    print(f"IPN data: {request.get_json() if request.is_json else request.form}")
    
    # IPN can be GET or POST
    if request.method == 'GET':
        order_tracking_id = request.args.get('OrderTrackingId')
        order_merchant_reference = request.args.get('OrderMerchantReference')
    else:
        data = request.get_json() or request.form
        order_tracking_id = data.get('OrderTrackingId')
        order_merchant_reference = data.get('OrderMerchantReference')
    
    if not order_tracking_id:
        return jsonify({'status': 'error', 'message': 'No tracking ID'}), 400
    
    # Verify and update payment
    pesapal = PesaPal()
    status_response = pesapal.verify_transaction_status(order_tracking_id)
    
    if status_response and status_response.get('status') == 'COMPLETED':
        # Update payment record
        payment_response = supabase.table('payment_transactions')\
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
            months = payment['months']
            
            # Update subscription
            current_date = datetime.now().date()
            expiry_date = current_date + timedelta(days=30 * months)
            
            sub_response = supabase.table('organization_billing')\
                .select('*')\
                .eq('institute_id', institute_id)\
                .execute()
            
            if sub_response.data:
                existing_expiry_str = sub_response.data[0].get('expiry_date')
                if existing_expiry_str:
                    if isinstance(existing_expiry_str, str):
                        existing_expiry = datetime.strptime(existing_expiry_str, '%Y-%m-%d').date()
                    else:
                        existing_expiry = existing_expiry_str
                    
                    if existing_expiry > current_date:
                        new_expiry = existing_expiry + timedelta(days=30 * months)
                    else:
                        new_expiry = expiry_date
                else:
                    new_expiry = expiry_date
                
                supabase.table('organization_billing')\
                    .update({
                        'expiry_date': new_expiry.isoformat(),
                        'status': 'active',
                        'updated_at': datetime.now().isoformat()
                    })\
                    .eq('institute_id', institute_id)\
                    .execute()
            else:
                sub_data = {
                    'id': str(uuid.uuid4()),
                    'institute_id': institute_id,
                    'start_date': current_date.isoformat(),
                    'expiry_date': expiry_date.isoformat(),
                    'status': 'active',
                    'created_at': datetime.now().isoformat()
                }
                supabase.table('organization_billing').insert(sub_data).execute()
    
    return jsonify({'status': 'success'})

@billing_bp.route('/check-subscription', methods=['GET'])
@login_required
def check_subscription():
    """Check subscription status via API"""
    try:
        institute = get_institute_from_session()
        
        if not institute or not isinstance(institute, dict):
            return jsonify({'success': False, 'message': 'Institute not found'}), 400
        
        institute_id = institute.get('id')
        
        if not institute_id:
            return jsonify({'success': False, 'message': 'Institute ID not found'}), 400
        
        sub_response = supabase.table('organization_billing')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .execute()
        
        subscription = sub_response.data[0] if sub_response.data else None
        
        if subscription:
            expiry_date_str = subscription.get('expiry_date')
            if expiry_date_str:
                if isinstance(expiry_date_str, str):
                    expiry_date = datetime.strptime(expiry_date_str, '%Y-%m-%d').date()
                else:
                    expiry_date = expiry_date_str
                today = datetime.now().date()
                is_active = expiry_date >= today
                days_remaining = (expiry_date - today).days if is_active else 0
                
                return jsonify({
                    'success': True,
                    'is_active': is_active,
                    'expiry_date': subscription['expiry_date'],
                    'days_remaining': days_remaining
                })
        
        return jsonify({
            'success': True,
            'is_active': False,
            'expiry_date': None,
            'days_remaining': 0
        })
            
    except Exception as e:
        print(f"Error checking subscription: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500