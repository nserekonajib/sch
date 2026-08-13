# admin.py - Complete rewrite with institute status, manual date updates, batch operations, and upsert logic
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
import time

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

# Get base subscription price from environment variable (in UGX)
BASE_PRICE = float(os.getenv('SUBSCRIPTION_PRICE', 50000))

# Discount rates
DISCOUNT_6_MONTHS = float(os.getenv('DISCOUNT_6_MONTHS', 0.10))
DISCOUNT_12_MONTHS = float(os.getenv('DISCOUNT_12_MONTHS', 0.15))

# Retry configuration
MAX_RETRIES = 4
RETRY_DELAY = 1  # seconds

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

def retry_on_failure(func, *args, **kwargs):
    """Retry a function up to MAX_RETRIES times on failure"""
    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES:
                print(f"Attempt {attempt + 1} failed: {e}. Retrying in {RETRY_DELAY}s...")
                time.sleep(RETRY_DELAY)
            else:
                raise last_error
    return None

def batch_upsert(table, records, conflict_key='id'):
    """
    Batch upsert records with retry logic.
    Splits records into batches of 50 for performance.
    """
    if not records:
        return []
    
    batch_size = 50
    results = []
    
    for i in range(0, len(records), batch_size):
        batch = records[i:i+batch_size]
        
        def upsert_batch():
            result = supabase.table(table).upsert(batch, on_conflict=conflict_key).execute()
            return result.data
        
        batch_results = retry_on_failure(upsert_batch)
        if batch_results:
            results.extend(batch_results)
    
    return results

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
        def fetch_stats():
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
            
            return {
                'total_institutions': total_institutions,
                'total_users': total_users,
                'total_payments': total_payments_count,
                'total_revenue': total_revenue,
                'active_subscriptions': active_subs,
                'month_revenue': month_revenue,
                'price_per_month': BASE_PRICE
            }
        
        stats = retry_on_failure(fetch_stats)
        return jsonify({'success': True, 'stats': stats})
        
    except Exception as e:
        print(f"Error getting admin stats: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@admin_bp.route('/api/institutions', methods=['GET'])
@admin_required
def get_institutions():
    """Get all institutions with filtering - includes status column"""
    try:
        search = request.args.get('search', '')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        status_filter = request.args.get('status', 'active')
        
        def fetch_institutions():
            query = supabase.table('institutes')\
                .select('*')\
                .order('created_at', desc=True)
            
            if search:
                query = query.or_(f"institute_name.ilike.%{search}%,email.ilike.%{search}%,phone_number.ilike.%{search}%")
            
            if start_date:
                query = query.gte('created_at', start_date)
            if end_date:
                query = query.lte('created_at', end_date)
            
            if status_filter == 'active':
                query = query.eq('status', 'active')
            elif status_filter == 'inactive':
                query = query.eq('status', 'inactive')
            elif status_filter == 'suspended':
                query = query.eq('status', 'suspended')
            
            response = query.execute()
            return response.data if response.data else []
        
        institutions = retry_on_failure(fetch_institutions)
        
        # Get subscription info for each institution (batch query for performance)
        if institutions:
            institute_ids = [inst['id'] for inst in institutions]
            
            def fetch_subscriptions():
                sub_response = supabase.table('organization_billing')\
                    .select('*')\
                    .in_('institute_id', institute_ids)\
                    .order('created_at', desc=True)\
                    .execute()
                return sub_response.data if sub_response.data else []
            
            subscriptions = retry_on_failure(fetch_subscriptions)
            
            # Map subscriptions by institute_id
            sub_map = {}
            for sub in subscriptions:
                if sub['institute_id'] not in sub_map:
                    sub_map[sub['institute_id']] = sub
            
            for inst in institutions:
                sub = sub_map.get(inst['id'])
                if sub:
                    inst['subscription'] = sub
                    start_date = datetime.strptime(sub['start_date'], '%Y-%m-%d').date()
                    expiry_date = datetime.strptime(sub['expiry_date'], '%Y-%m-%d').date()
                    months = round((expiry_date - start_date).days / 30)
                    inst['subscription_months'] = months
                    inst['subscription_amount'] = calculate_price(months)
                else:
                    inst['subscription'] = None
        
        return jsonify({'success': True, 'institutions': institutions})
        
    except Exception as e:
        print(f"Error getting institutions: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@admin_bp.route('/api/institution/update-status', methods=['POST'])
@admin_required
def update_institution_status():
    """Update institution status (active, inactive, suspended)"""
    try:
        data = request.get_json()
        institute_id = data.get('institute_id')
        status = data.get('status')
        
        if not institute_id:
            return jsonify({'success': False, 'message': 'Institute ID required'}), 400
        
        if status not in ['active', 'inactive', 'suspended']:
            return jsonify({'success': False, 'message': 'Invalid status'}), 400
        
        def update_status():
            result = supabase.table('institutes')\
                .update({
                    'status': status,
                    'updated_at': datetime.now().isoformat()
                })\
                .eq('id', institute_id)\
                .execute()
            return result.data
        
        result = retry_on_failure(update_status)
        
        if result:
            return jsonify({
                'success': True,
                'message': f'Institute status updated to {status}',
                'status': status
            })
        else:
            return jsonify({'success': False, 'message': 'Failed to update status'}), 500
        
    except Exception as e:
        print(f"Error updating institution status: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@admin_bp.route('/api/institution/add-payment', methods=['POST'])
@admin_required
def add_institution_payment():
    """Add subscription to an institution with custom dates and discount logic - FIXED: uses upsert"""
    try:
        data = request.get_json()
        institute_id = data.get('institute_id')
        months = int(data.get('months', 1))
        notes = data.get('notes', '')
        custom_start_date = data.get('start_date')
        custom_expiry_date = data.get('expiry_date')
        
        # Only allow 1, 6, or 12 months
        if months not in [1, 6, 12]:
            return jsonify({'success': False, 'message': 'Only 1, 6, or 12 month subscriptions are allowed'}), 400
        
        if not institute_id:
            return jsonify({'success': False, 'message': 'Institute ID required'}), 400
        
        def fetch_institute():
            inst_response = supabase.table('institutes')\
                .select('*')\
                .eq('id', institute_id)\
                .execute()
            return inst_response.data[0] if inst_response.data else None
        
        institute = retry_on_failure(fetch_institute)
        
        if not institute:
            return jsonify({'success': False, 'message': 'Institute not found'}), 404
        
        # Calculate price with discount
        amount = calculate_price(months)
        
        # Calculate dates
        current_date = datetime.now().date()
        
        if custom_start_date:
            start_date = datetime.strptime(custom_start_date, '%Y-%m-%d').date()
        else:
            start_date = current_date
        
        if custom_expiry_date:
            expiry_date = datetime.strptime(custom_expiry_date, '%Y-%m-%d').date()
        else:
            expiry_date = start_date + timedelta(days=30 * months)
        
        # Check if subscription exists for this institute
        def check_existing():
            existing_sub = supabase.table('organization_billing')\
                .select('*')\
                .eq('institute_id', institute_id)\
                .execute()
            return existing_sub.data[0] if existing_sub.data else None
        
        existing_sub = retry_on_failure(check_existing)
        
        if existing_sub:
            # UPDATE existing subscription
            current_expiry = datetime.strptime(existing_sub['expiry_date'], '%Y-%m-%d').date()
            current_start = datetime.strptime(existing_sub['start_date'], '%Y-%m-%d').date()
            
            # If the new expiry is after the current expiry, extend
            if expiry_date > current_expiry:
                new_expiry = expiry_date
            else:
                # Otherwise, add the months to the current expiry
                new_expiry = current_expiry + timedelta(days=30 * months)
            
            # Keep the original start date if it's earlier
            if start_date < current_start:
                new_start = start_date
            else:
                new_start = current_start
            
            def update_sub():
                result = supabase.table('organization_billing')\
                    .update({
                        'start_date': new_start.isoformat(),
                        'expiry_date': new_expiry.isoformat(),
                        'status': 'active',
                        'updated_at': datetime.now().isoformat()
                    })\
                    .eq('institute_id', institute_id)\
                    .execute()
                return result.data
            
            retry_on_failure(update_sub)
            final_start = new_start
            final_expiry = new_expiry
        else:
            # CREATE new subscription record
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
            
            def create_sub():
                result = supabase.table('organization_billing').insert(sub_data).execute()
                return result.data
            
            retry_on_failure(create_sub)
            final_start = start_date
            final_expiry = expiry_date
        
        # Also ensure institute status is active
        def update_institute_status():
            supabase.table('institutes')\
                .update({
                    'status': 'active',
                    'updated_at': datetime.now().isoformat()
                })\
                .eq('id', institute_id)\
                .execute()
        
        retry_on_failure(update_institute_status)
        
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
            'start_date': final_start.isoformat(),
            'expiry_date': final_expiry.isoformat(),
            'amount': amount,
            'months': months,
            'discount_percent': discount_percent
        })
        
    except Exception as e:
        print(f"Error adding payment: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@admin_bp.route('/api/institution/update-subscription', methods=['POST'])
@admin_required
def update_subscription():
    """Update existing subscription start and expiry dates"""
    try:
        data = request.get_json()
        subscription_id = data.get('subscription_id')
        institute_id = data.get('institute_id')
        start_date = data.get('start_date')
        expiry_date = data.get('expiry_date')
        
        if not subscription_id and not institute_id:
            return jsonify({'success': False, 'message': 'Subscription ID or Institute ID required'}), 400
        
        update_data = {
            'updated_at': datetime.now().isoformat()
        }
        
        if start_date:
            update_data['start_date'] = datetime.strptime(start_date, '%Y-%m-%d').date().isoformat()
        
        if expiry_date:
            update_data['expiry_date'] = datetime.strptime(expiry_date, '%Y-%m-%d').date().isoformat()
        
        def perform_update():
            if subscription_id:
                result = supabase.table('organization_billing')\
                    .update(update_data)\
                    .eq('id', subscription_id)\
                    .execute()
                return result.data
            else:
                # Get the subscription for the institute
                sub_response = supabase.table('organization_billing')\
                    .select('*')\
                    .eq('institute_id', institute_id)\
                    .execute()
                
                if sub_response.data:
                    result = supabase.table('organization_billing')\
                        .update(update_data)\
                        .eq('id', sub_response.data[0]['id'])\
                        .execute()
                    return result.data
                else:
                    # Create new subscription if none exists
                    sub_id = str(uuid.uuid4())
                    new_data = {
                        'id': sub_id,
                        'institute_id': institute_id,
                        'start_date': update_data.get('start_date', datetime.now().date().isoformat()),
                        'expiry_date': update_data.get('expiry_date', (datetime.now().date() + timedelta(days=30)).isoformat()),
                        'status': 'active',
                        'created_at': datetime.now().isoformat(),
                        'updated_at': datetime.now().isoformat()
                    }
                    result = supabase.table('organization_billing').insert(new_data).execute()
                    return result.data
        
        result = retry_on_failure(perform_update)
        
        return jsonify({
            'success': True,
            'message': 'Subscription dates updated successfully'
        })
        
    except Exception as e:
        print(f"Error updating subscription: {e}")
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
        
        def fetch_report():
            query = supabase.table('organization_billing')\
                .select('*, institutes(institute_name, email, phone_number, status)')\
                .order('created_at', desc=True)
            
            if start_date:
                query = query.gte('created_at', start_date)
            if end_date:
                query = query.lte('created_at', end_date)
            if institute_id:
                query = query.eq('institute_id', institute_id)
            
            response = query.execute()
            return response.data if response.data else []
        
        subscriptions = retry_on_failure(fetch_report)
        
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
            
            institute_data = sub.get('institutes', {})
            subscription_details.append({
                'id': sub['id'],
                'institute_name': institute_data.get('institute_name', 'Unknown'),
                'email': institute_data.get('email', 'N/A'),
                'status': institute_data.get('status', 'unknown'),
                'start_date': sub['start_date'],
                'expiry_date': sub['expiry_date'],
                'months': months,
                'amount': amount,
                'discount_percent': discount_percent,
                'subscription_status': sub['status'],
                'created_at': sub['created_at']
            })
        
        # Group by month
        monthly_data = {}
        for sub in subscription_details:
            created_at = sub['created_at'][:7]
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
                institute_data[inst_name] = {'amount': 0, 'status': sub['status']}
            institute_data[inst_name]['amount'] += sub['amount']
        
        institute_report = [{'institute': i, 'amount': d['amount'], 'status': d['status']} 
                          for i, d in institute_data.items()]
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
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365)
        
        def fetch_chart_data():
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
            
            return {
                'monthly_revenue': monthly_revenue,
                'institutions_growth': institutions_growth,
                'price_per_month': BASE_PRICE
            }
        
        data = retry_on_failure(fetch_chart_data)
        
        return jsonify({
            'success': True,
            'monthly_revenue': data['monthly_revenue'],
            'institutions_growth': data['institutions_growth'],
            'price_per_month': data['price_per_month']
        })
        
    except Exception as e:
        print(f"Error getting chart data: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@admin_bp.route('/api/export-revenue-excel', methods=['POST'])
@admin_required
def export_revenue_excel():
    """Export revenue report to Excel"""
    try:
        data = request.get_json()
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        institute_id = data.get('institute_id')
        
        def fetch_data():
            query = supabase.table('organization_billing')\
                .select('*, institutes(institute_name, email, phone_number, status)')\
                .order('created_at', desc=True)
            
            if start_date:
                query = query.gte('created_at', start_date)
            if end_date:
                query = query.lte('created_at', end_date)
            if institute_id:
                query = query.eq('institute_id', institute_id)
            
            response = query.execute()
            return response.data if response.data else []
        
        subscriptions = retry_on_failure(fetch_data)
        
        # Prepare data for Excel
        rows = []
        for sub in subscriptions:
            start_date_obj = datetime.strptime(sub['start_date'], '%Y-%m-%d').date()
            expiry_date_obj = datetime.strptime(sub['expiry_date'], '%Y-%m-%d').date()
            months = round((expiry_date_obj - start_date_obj).days / 30)
            amount = calculate_price(months)
            
            institute = sub.get('institutes', {})
            rows.append({
                'Institute': institute.get('institute_name', 'Unknown'),
                'Email': institute.get('email', 'N/A'),
                'Phone': institute.get('phone_number', 'N/A'),
                'Status': institute.get('status', 'unknown'),
                'Start Date': sub['start_date'],
                'Expiry Date': sub['expiry_date'],
                'Months': months,
                'Amount': amount,
                'Subscription Status': sub['status'],
                'Created At': sub['created_at']
            })
        
        df = pd.DataFrame(rows)
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Revenue Report', index=False)
            
            # Auto-adjust column widths
            worksheet = writer.sheets['Revenue Report']
            for column in worksheet.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = min(max_length + 2, 50)
                worksheet.column_dimensions[column_letter].width = adjusted_width
        
        output.seek(0)
        filename = f"revenue_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        
        return send_file(
            output,
            as_attachment=True,
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        
    except Exception as e:
        print(f"Error exporting revenue report: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

# ============================================================
# MANUAL PAYMENTS
# ============================================================

@admin_bp.route('/manual-payments')
@admin_required
def manual_payments_page():
    """Manual payments management page"""
    return render_template('admin/manual_payments.html')

@admin_bp.route('/api/manual-payments', methods=['GET'])
@admin_required
def get_manual_payments():
    """Get all manual payment requests"""
    try:
        status = request.args.get('status', 'all')
        
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

@admin_bp.route('/api/manual-payment/approve', methods=['POST'])
@admin_required
def approve_manual_payment():
    """Approve manual payment and add to balance"""
    try:
        data = request.get_json()
        payment_id = data.get('payment_id')
        admin_notes = data.get('admin_notes', '')
        
        if not payment_id:
            return jsonify({'success': False, 'message': 'Payment ID required'}), 400
        
        # Get payment request
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
        
        # Add to balance using the function from sms_settings
        from routes.sms.sms_settings import add_to_balance
        success, result = add_to_balance(institute_id, amount, f"Manual payment - {payment['reference']}")
        
        if not success:
            return jsonify({'success': False, 'message': f'Failed to add balance: {result}'}), 500
        
        # Update payment status
        supabase.table('manual_payment_requests')\
            .update({
                'status': 'approved',
                'admin_notes': admin_notes,
                'updated_at': datetime.now().isoformat()
            })\
            .eq('id', payment_id)\
            .execute()
        
        return jsonify({
            'success': True,
            'message': f'Payment approved! UGX {amount:,.2f} added to balance.'
        })
        
    except Exception as e:
        print(f"Error approving manual payment: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@admin_bp.route('/api/manual-payment/reject', methods=['POST'])
@admin_required
def reject_manual_payment():
    """Reject manual payment request"""
    try:
        data = request.get_json()
        payment_id = data.get('payment_id')
        admin_notes = data.get('admin_notes', '')
        
        if not payment_id:
            return jsonify({'success': False, 'message': 'Payment ID required'}), 400
        
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