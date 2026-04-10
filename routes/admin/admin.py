# admin.py - Fixed with discount logic for 6 and 12 months
from flask import Blueprint, render_template, request, jsonify, session, send_file
from supabase import create_client, Client
import os
import uuid
from datetime import datetime, timedelta
import json
import io
import pandas as pd
from functools import wraps
from dotenv import load_dotenv

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

# Get base subscription price from environment variable (in UGX)
BASE_PRICE = float(os.getenv('SUBSCRIPTION_PRICE'))

# Discount rates
DISCOUNT_6_MONTHS = float(os.getenv('DISCOUNT_6_MONTHS'))  # 10% discount
DISCOUNT_12_MONTHS = float(os.getenv('DISCOUNT_12_MONTHS'))  # 15% discount

def calculate_price(months):
    """Calculate price based on months with discounts for 6 and 12 months"""
    if months == 6:
        price = BASE_PRICE * months * (1 - DISCOUNT_6_MONTHS)
    elif months == 12:
        price = BASE_PRICE * months * (1 - DISCOUNT_12_MONTHS)
    else:
        price = BASE_PRICE * months
    return round(price, 2)

def admin_required(f):
    """Decorator to require admin access"""
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

@admin_bp.route('/')
@admin_required
def index():
    """Admin Dashboard Page"""
    return render_template('admin/index.html', 
                          subscription_price=BASE_PRICE,
                          discount_6_months=DISCOUNT_6_MONTHS * 100,
                          discount_12_months=DISCOUNT_12_MONTHS * 100)

@admin_bp.route('/api/stats', methods=['GET'])
@admin_required
def get_stats():
    """Get overall platform statistics"""
    try:
        # Get total institutions
        institutions_response = supabase.table('institutes')\
            .select('id', count='exact')\
            .execute()
        total_institutions = institutions_response.count or 0
        
        # Get total users from institutes
        users_response = supabase.table('institutes')\
            .select('user_id')\
            .execute()
        unique_users = set()
        for inst in (users_response.data or []):
            if inst.get('user_id'):
                unique_users.add(inst['user_id'])
        total_users = len(unique_users)
        
        # Get subscriptions from organization_billing
        subs_response = supabase.table('organization_billing')\
            .select('*')\
            .execute()
        subscriptions = subs_response.data if subs_response.data else []
        
        total_payments_count = len(subscriptions)
        
        # Calculate total revenue (sum of calculated prices)
        total_revenue = 0
        for sub in subscriptions:
            # Calculate months from start_date to expiry_date
            start_date = datetime.strptime(sub['start_date'], '%Y-%m-%d').date()
            expiry_date = datetime.strptime(sub['expiry_date'], '%Y-%m-%d').date()
            months = round((expiry_date - start_date).days / 30)
            total_revenue += calculate_price(months)
        
        # Get active subscriptions (expiry_date >= today)
        today = datetime.now().date().isoformat()
        active_subs = sum(1 for sub in subscriptions if sub.get('expiry_date', '') >= today)
        
        # Get this month's subscriptions
        month_start = datetime.now().replace(day=1).date().isoformat()
        month_end = datetime.now().date().isoformat()
        month_subs = [sub for sub in subscriptions 
                     if sub.get('created_at', '')[:10] >= month_start and sub.get('created_at', '')[:10] <= month_end]
        
        month_revenue = 0
        for sub in month_subs:
            start_date = datetime.strptime(sub['start_date'], '%Y-%m-%d').date()
            expiry_date = datetime.strptime(sub['expiry_date'], '%Y-%m-%d').date()
            months = round((expiry_date - start_date).days / 30)
            month_revenue += calculate_price(months)
        
        return jsonify({
            'success': True,
            'stats': {
                'total_institutions': total_institutions,
                'total_users': total_users,
                'total_payments': total_payments_count,
                'total_revenue': total_revenue,
                'active_subscriptions': active_subs,
                'month_revenue': month_revenue,
                'price_per_month': BASE_PRICE
            }
        })
        
    except Exception as e:
        print(f"Error getting admin stats: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@admin_bp.route('/api/institutions', methods=['GET'])
@admin_required
def get_institutions():
    """Get all institutions with filtering"""
    try:
        search = request.args.get('search', '')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        query = supabase.table('institutes')\
            .select('*')\
            .order('created_at', desc=True)
        
        if search:
            query = query.or_(f"institute_name.ilike.%{search}%,email.ilike.%{search}%,phone_number.ilike.%{search}%")
        
        if start_date:
            query = query.gte('created_at', start_date)
        if end_date:
            query = query.lte('created_at', end_date)
        
        response = query.execute()
        institutions = response.data if response.data else []
        
        # Get subscription info for each institution
        for inst in institutions:
            sub_response = supabase.table('organization_billing')\
                .select('*')\
                .eq('institute_id', inst['id'])\
                .order('created_at', desc=True)\
                .limit(1)\
                .execute()
            
            if sub_response.data:
                inst['subscription'] = sub_response.data[0]
                # Calculate months and price
                start_date = datetime.strptime(sub_response.data[0]['start_date'], '%Y-%m-%d').date()
                expiry_date = datetime.strptime(sub_response.data[0]['expiry_date'], '%Y-%m-%d').date()
                months = round((expiry_date - start_date).days / 30)
                inst['subscription_months'] = months
                inst['subscription_amount'] = calculate_price(months)
            else:
                inst['subscription'] = None
        
        return jsonify({'success': True, 'institutions': institutions})
        
    except Exception as e:
        print(f"Error getting institutions: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@admin_bp.route('/api/institution/add-payment', methods=['POST'])
@admin_required
def add_institution_payment():
    """Add subscription to an institution with discount logic"""
    try:
        data = request.get_json()
        institute_id = data.get('institute_id')
        months = int(data.get('months', 1))
        notes = data.get('notes', '')
        
        # Only allow 1, 6, or 12 months
        if months not in [1, 6, 12]:
            return jsonify({'success': False, 'message': 'Only 1, 6, or 12 month subscriptions are allowed'}), 400
        
        if not institute_id:
            return jsonify({'success': False, 'message': 'Institute ID required'}), 400
        
        # Get institute details
        inst_response = supabase.table('institutes')\
            .select('*')\
            .eq('id', institute_id)\
            .execute()
        
        if not inst_response.data:
            return jsonify({'success': False, 'message': 'Institute not found'}), 404
        
        # Calculate price with discount
        amount = calculate_price(months)
        
        # Calculate dates
        current_date = datetime.now().date()
        start_date = current_date
        expiry_date = current_date + timedelta(days=30 * months)
        
        # Check if there's an existing active subscription
        existing_sub = supabase.table('organization_billing')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .gte('expiry_date', current_date.isoformat())\
            .execute()
        
        if existing_sub.data:
            # Extend existing subscription
            current_expiry = datetime.strptime(existing_sub.data[0]['expiry_date'], '%Y-%m-%d').date()
            new_expiry = current_expiry + timedelta(days=30 * months)
            
            supabase.table('organization_billing')\
                .update({
                    'expiry_date': new_expiry.isoformat(),
                    'status': 'active',
                    'updated_at': datetime.now().isoformat()
                })\
                .eq('id', existing_sub.data[0]['id'])\
                .execute()
            
            expiry_date = new_expiry
        else:
            # Create new subscription record
            sub_id = str(uuid.uuid4())
            sub_data = {
                'id': sub_id,
                'institute_id': institute_id,
                'start_date': start_date.isoformat(),
                'expiry_date': expiry_date.isoformat(),
                'status': 'active',
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }
            supabase.table('organization_billing').insert(sub_data).execute()
        
        discount_percent = 0
        if months == 6:
            discount_percent = DISCOUNT_6_MONTHS * 100
        elif months == 12:
            discount_percent = DISCOUNT_12_MONTHS * 100
        
        message = f'Subscription added: {months} month(s) for UGX {amount:,.0f}'
        if discount_percent > 0:
            message += f' (includes {discount_percent:.0f}% discount)'
        
        return jsonify({
            'success': True,
            'message': message,
            'expiry_date': expiry_date.isoformat(),
            'amount': amount,
            'months': months,
            'discount_percent': discount_percent
        })
        
    except Exception as e:
        print(f"Error adding payment: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@admin_bp.route('/api/revenue-report', methods=['POST'])
@admin_required
def get_revenue_report():
    """Get revenue report from organization_billing table"""
    try:
        data = request.get_json()
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        institute_id = data.get('institute_id')
        
        query = supabase.table('organization_billing')\
            .select('*, institutes(institute_name, email, phone_number)')\
            .order('created_at', desc=True)
        
        if start_date:
            query = query.gte('created_at', start_date)
        if end_date:
            query = query.lte('created_at', end_date)
        if institute_id:
            query = query.eq('institute_id', institute_id)
        
        response = query.execute()
        subscriptions = response.data if response.data else []
        
        # Calculate details for each subscription
        subscription_details = []
        total_amount = 0
        
        for sub in subscriptions:
            start_date_obj = datetime.strptime(sub['start_date'], '%Y-%m-%d').date()
            expiry_date_obj = datetime.strptime(sub['expiry_date'], '%Y-%m-%d').date()
            months = round((expiry_date_obj - start_date_obj).days / 30)
            amount = calculate_price(months)
            total_amount += amount
            
            discount_percent = 0
            if months == 6:
                discount_percent = DISCOUNT_6_MONTHS * 100
            elif months == 12:
                discount_percent = DISCOUNT_12_MONTHS * 100
            
            subscription_details.append({
                'id': sub['id'],
                'institute_name': sub.get('institutes', {}).get('institute_name', 'Unknown'),
                'email': sub.get('institutes', {}).get('email', 'N/A'),
                'start_date': sub['start_date'],
                'expiry_date': sub['expiry_date'],
                'months': months,
                'amount': amount,
                'discount_percent': discount_percent,
                'status': sub['status'],
                'created_at': sub['created_at']
            })
        
        # Group by month
        monthly_data = {}
        for sub in subscription_details:
            created_at = sub['created_at'][:7]  # YYYY-MM
            if created_at not in monthly_data:
                monthly_data[created_at] = 0
            monthly_data[created_at] += sub['amount']
        
        monthly_report = [{'month': m, 'amount': a} for m, a in monthly_data.items()]
        monthly_report.sort(key=lambda x: x['month'])
        
        # Group by institute
        institute_data = {}
        for sub in subscription_details:
            inst_name = sub['institute_name']
            if inst_name not in institute_data:
                institute_data[inst_name] = 0
            institute_data[inst_name] += sub['amount']
        
        institute_report = [{'institute': i, 'amount': a} for i, a in institute_data.items()]
        institute_report.sort(key=lambda x: x['amount'], reverse=True)
        
        return jsonify({
            'success': True,
            'subscriptions': subscription_details,
            'summary': {
                'total_amount': total_amount,
                'total_count': len(subscriptions),
                'monthly': monthly_report,
                'by_institute': institute_report,
                'price_per_month': BASE_PRICE
            }
        })
        
    except Exception as e:
        print(f"Error generating revenue report: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@admin_bp.route('/api/dashboard-chart', methods=['GET'])
@admin_required
def get_dashboard_chart():
    """Get data for dashboard charts from organization_billing"""
    try:
        # Get last 12 months revenue
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365)
        
        monthly_revenue = []
        current = start_date.replace(day=1)
        
        while current <= end_date:
            month_start = current.date().isoformat()
            if current.month == 12:
                next_month = current.replace(year=current.year + 1, month=1)
            else:
                next_month = current.replace(month=current.month + 1)
            month_end = (next_month - timedelta(days=1)).date().isoformat()
            
            response = supabase.table('organization_billing')\
                .select('*')\
                .gte('created_at', month_start)\
                .lte('created_at', month_end)\
                .execute()
            
            total = 0
            for sub in (response.data or []):
                start_date_obj = datetime.strptime(sub['start_date'], '%Y-%m-%d').date()
                expiry_date_obj = datetime.strptime(sub['expiry_date'], '%Y-%m-%d').date()
                months = round((expiry_date_obj - start_date_obj).days / 30)
                total += calculate_price(months)
            
            monthly_revenue.append({
                'month': current.strftime('%b %Y'),
                'revenue': total
            })
            
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)
        
        # Get institution growth
        institutions_growth = []
        current = start_date.replace(day=1)
        
        while current <= end_date:
            month_end = current.date().isoformat()
            
            response = supabase.table('institutes')\
                .select('id', count='exact')\
                .lte('created_at', month_end)\
                .execute()
            
            institutions_growth.append({
                'month': current.strftime('%b %Y'),
                'count': response.count or 0
            })
            
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)
        
        return jsonify({
            'success': True,
            'monthly_revenue': monthly_revenue,
            'institutions_growth': institutions_growth,
            'price_per_month': BASE_PRICE
        })
        
    except Exception as e:
        print(f"Error getting chart data: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500