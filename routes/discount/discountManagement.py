# discountManagement.py - Fixed version with proper date handling
from flask import Blueprint, render_template, request, jsonify, session
from supabase import create_client, Client
import os
import uuid
from datetime import datetime
import json
from functools import wraps
from dotenv import load_dotenv

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

discount_bp = Blueprint('discount', __name__, url_prefix='/discounts')

def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Please login'}), 401
        return f(*args, **kwargs)
    return decorated_function

def get_institute_id(user_id):
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

@discount_bp.route('/')
@login_required
def index():
    """Discount Management Page"""
    user = session.get('user')
    institute = get_institute_id(user['id'])
    
    if not institute:
        return render_template('discounts/index.html', discounts=[], students=[], classes=[], institute=None, now=datetime.now())
    
    try:
        # Get all active discounts
        discounts_response = supabase.table('discounts')\
            .select('*')\
            .eq('institute_id', institute['id'])\
            .order('created_at', desc=True)\
            .execute()
        
        discounts = discounts_response.data if discounts_response.data else []
        
        # Get all students
        students_response = supabase.table('students')\
            .select('id, name, student_id, class_id, classes(name)')\
            .eq('institute_id', institute['id'])\
            .eq('status', 'active')\
            .order('name')\
            .execute()
        
        students = students_response.data if students_response.data else []
        
        # Get all classes
        classes_response = supabase.table('classes')\
            .select('*')\
            .eq('institute_id', institute['id'])\
            .order('name')\
            .execute()
        
        classes = classes_response.data if classes_response.data else []
        
        return render_template('discounts/index.html', 
                              discounts=discounts, 
                              students=students, 
                              classes=classes,
                              institute=institute,
                              now=datetime.now())
        
    except Exception as e:
        print(f"Error loading discounts: {e}")
        return render_template('discounts/index.html', discounts=[], students=[], classes=[], institute=institute, now=datetime.now())

@discount_bp.route('/create', methods=['POST'])
@login_required
def create_discount():
    """Create a new discount"""
    user = session.get('user')
    institute = get_institute_id(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        
        discount_type = data.get('discount_type')  # 'percentage', 'fixed'
        discount_value = float(data.get('discount_value', 0))
        apply_to = data.get('apply_to')  # 'all', 'class', 'student'
        target_id = data.get('target_id')
        reason = data.get('reason', '')
        valid_from = data.get('valid_from')
        valid_until = data.get('valid_until')
        
        # Handle empty date strings - convert None if empty
        if valid_from == '' or valid_from is None:
            valid_from = None
        if valid_until == '' or valid_until is None:
            valid_until = None
            
        if discount_value <= 0:
            return jsonify({'success': False, 'message': 'Invalid discount value'}), 400
        
        # Get target students
        students_list = []
        
        if apply_to == 'all':
            # Get all active students
            response = supabase.table('students')\
                .select('id, name, student_id')\
                .eq('institute_id', institute['id'])\
                .eq('status', 'active')\
                .execute()
            students_list = response.data if response.data else []
            
        elif apply_to == 'class':
            # Get students in specific class
            response = supabase.table('students')\
                .select('id, name, student_id')\
                .eq('institute_id', institute['id'])\
                .eq('class_id', target_id)\
                .eq('status', 'active')\
                .execute()
            students_list = response.data if response.data else []
            
        elif apply_to == 'student':
            # Get single student
            response = supabase.table('students')\
                .select('id, name, student_id')\
                .eq('id', target_id)\
                .eq('institute_id', institute['id'])\
                .execute()
            if response.data:
                students_list = [response.data[0]]
        
        if not students_list:
            return jsonify({'success': False, 'message': 'No students found for the selected criteria'}), 404
        
        # Create discount records for each student
        discounts_created = []
        
        for student in students_list:
            discount_id = str(uuid.uuid4())
            discount_data = {
                'id': discount_id,
                'institute_id': institute['id'],
                'student_id': student['id'],
                'student_name': student['name'],
                'discount_type': discount_type,
                'discount_value': discount_value,
                'apply_to': apply_to,
                'target_id': target_id if apply_to != 'all' else None,
                'reason': reason if reason else None,
                'valid_from': valid_from,
                'valid_until': valid_until,
                'is_active': True,
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }
            
            result = supabase.table('discounts').insert(discount_data).execute()
            
            if result.data:
                discounts_created.append({
                    'student_id': student['id'],
                    'student_name': student['name'],
                    'discount_id': discount_id
                })
        
        return jsonify({
            'success': True,
            'message': f'Discount applied to {len(discounts_created)} student(s)',
            'discounts': discounts_created
        })
        
    except Exception as e:
        print(f"Error creating discount: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@discount_bp.route('/apply-to-invoice', methods=['POST'])
@login_required
def apply_discount_to_invoice():
    """Apply discount to specific invoice"""
    user = session.get('user')
    institute = get_institute_id(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        invoice_id = data.get('invoice_id')
        discount_type = data.get('discount_type')
        discount_value = float(data.get('discount_value', 0))
        reason = data.get('reason', '')
        
        if not invoice_id or discount_value <= 0:
            return jsonify({'success': False, 'message': 'Invalid discount value'}), 400
        
        # Get invoice details
        invoice_response = supabase.table('invoices')\
            .select('*, students(name, student_id)')\
            .eq('id', invoice_id)\
            .eq('institute_id', institute['id'])\
            .execute()
        
        if not invoice_response.data:
            return jsonify({'success': False, 'message': 'Invoice not found'}), 404
        
        invoice = invoice_response.data[0]
        
        # Calculate discount amount
        if discount_type == 'percentage':
            discount_amount = (discount_value / 100) * invoice['total_amount']
        else:
            discount_amount = discount_value
        
        discount_amount = min(discount_amount, invoice['balance'])
        
        # Apply discount to invoice
        new_balance = invoice['balance'] - discount_amount
        
        supabase.table('invoices')\
            .update({
                'balance': new_balance,
                'discount_applied': discount_amount,
                'updated_at': datetime.now().isoformat()
            })\
            .eq('id', invoice_id)\
            .execute()
        
        # Create discount record
        discount_id = str(uuid.uuid4())
        discount_data = {
            'id': discount_id,
            'institute_id': institute['id'],
            'student_id': invoice['student_id'],
            'student_name': invoice['students']['name'],
            'invoice_id': invoice_id,
            'discount_type': discount_type,
            'discount_value': discount_value,
            'discount_amount': discount_amount,
            'reason': reason if reason else None,
            'apply_to': 'invoice',
            'is_active': True,
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        supabase.table('discounts').insert(discount_data).execute()
        
        return jsonify({
            'success': True,
            'message': f'Discount of UGX {discount_amount:,.0f} applied to invoice {invoice["invoice_number"]}',
            'new_balance': new_balance,
            'discount_amount': discount_amount
        })
        
    except Exception as e:
        print(f"Error applying discount: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@discount_bp.route('/<discount_id>/toggle', methods=['PUT'])
@login_required
def toggle_discount(discount_id):
    """Enable or disable a discount"""
    user = session.get('user')
    institute = get_institute_id(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        is_active = data.get('is_active', False)
        
        result = supabase.table('discounts')\
            .update({
                'is_active': is_active,
                'updated_at': datetime.now().isoformat()
            })\
            .eq('id', discount_id)\
            .eq('institute_id', institute['id'])\
            .execute()
        
        if result.data:
            status = 'activated' if is_active else 'deactivated'
            return jsonify({'success': True, 'message': f'Discount {status} successfully'})
        else:
            return jsonify({'success': False, 'message': 'Discount not found'}), 404
            
    except Exception as e:
        print(f"Error toggling discount: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@discount_bp.route('/<discount_id>', methods=['DELETE'])
@login_required
def delete_discount(discount_id):
    """Delete a discount"""
    user = session.get('user')
    institute = get_institute_id(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        result = supabase.table('discounts')\
            .delete()\
            .eq('id', discount_id)\
            .eq('institute_id', institute['id'])\
            .execute()
        
        if result.data:
            return jsonify({'success': True, 'message': 'Discount deleted successfully'})
        else:
            return jsonify({'success': False, 'message': 'Discount not found'}), 404
            
    except Exception as e:
        print(f"Error deleting discount: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500