# fees.py - Updated with category filtering and proper student selection
from flask import Blueprint, render_template, request, jsonify, session, send_file
from supabase import create_client, Client
import os
import uuid
import random
import string
from datetime import datetime, timedelta
import json
import io
import pandas as pd
from functools import wraps
from dotenv import load_dotenv
import cloudinary
import cloudinary.uploader

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

fees_bp = Blueprint('fees', __name__, url_prefix='/fees')

def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Please login'}), 401
        return f(*args, **kwargs)
    return decorated_function

def get_institute_id(user_id):
    """Get institute ID for the current user"""
    try:
        response = supabase.table('institutes')\
            .select('id')\
            .eq('user_id', user_id)\
            .execute()
        
        if response.data and len(response.data) > 0:
            return response.data[0]['id']
        return None
    except Exception as e:
        print(f"Error getting institute ID: {e}")
        return None

@fees_bp.route('/')
@login_required
def index():
    """Fees Management Dashboard"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return render_template('fees/index.html', classes=[], students=[], fee_particulars=[])
    
    try:
        # Get all classes
        classes_response = supabase.table('classes')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('name')\
            .execute()
        
        classes = classes_response.data if classes_response.data else []
        
        # Get all active students with their details
        students_response = supabase.table('students')\
            .select('id, name, student_id, class_id, category, classes(name)')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')\
            .order('name')\
            .execute()
        
        students = students_response.data if students_response.data else []
        
        # Get fee particulars
        particulars_response = supabase.table('fee_particulars')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('created_at', desc=True)\
            .execute()
        
        fee_particulars = particulars_response.data if particulars_response.data else []
        
        return render_template('fees/index.html', 
                              classes=classes, 
                              students=students, 
                              fee_particulars=fee_particulars)
        
    except Exception as e:
        print(f"Error loading fees page: {e}")
        return render_template('fees/index.html', classes=[], students=[], fee_particulars=[])

@fees_bp.route('/particulars', methods=['GET'])
@login_required
def get_particulars():
    """Get fee particulars for a class or student"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        apply_to = request.args.get('apply_to')
        target_id = request.args.get('target_id')
        
        query = supabase.table('fee_particulars')\
            .select('*')\
            .eq('institute_id', institute_id)
        
        if apply_to == 'class' and target_id:
            query = query.eq('class_id', target_id)
        elif apply_to == 'student' and target_id:
            query = query.eq('student_id', target_id)
        else:
            query = query.is_('class_id', 'null').is_('student_id', 'null')
        
        response = query.order('created_at', desc=True).execute()
        
        return jsonify({'success': True, 'particulars': response.data or []})
        
    except Exception as e:
        print(f"Error getting particulars: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    
    
@fees_bp.route('/search-students', methods=['GET'])
@login_required
def search_students():
    """Search students by name or ID with category filter"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        search_term = request.args.get('q', '').strip()
        category = request.args.get('category', 'all')
        
        # Build query
        query = supabase.table('students')\
            .select('id, name, student_id, category, class_id, classes(name)')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')
        
        # Apply category filter
        if category != 'all':
            query = query.eq('category', category)
        
        # Apply search filter
        if search_term and len(search_term) >= 2:
            query = query.or_(f"name.ilike.%{search_term}%,student_id.ilike.%{search_term}%")
        
        response = query.limit(20).execute()
        #debuggin response
        print(f'response: {response}')
        
        students = response.data if response.data else []
        print(students)
        
        # Format the response to match what frontend expects
        formatted_students = []
        for student in students:
            formatted_students.append({
                'id': student['id'],
                'name': student['name'],
                'student_id': student['student_id'],
                'category': student.get('category', 'N/A'),
                'classes': {  # Frontend expects a 'classes' object with 'name' property
                    'name': student['classes']['name'] if student.get('classes') else 'N/A'
                }
            })
        
        return jsonify({'success': True, 'students': formatted_students})
        
    except Exception as e:
        print(f"Error searching students: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@fees_bp.route('/particulars/create', methods=['POST'])
@login_required
def create_particulars():
    """Create fee particulars and generate invoices with category filtering"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        
        apply_to = data.get('apply_to')  # 'all', 'class', 'student'
        target_id = data.get('target_id')
        fee_items = data.get('fee_items', [])
        category_filter = data.get('category', 'all')  # 'all', 'Boarding', 'Day'
        
        if not fee_items:
            return jsonify({'success': False, 'message': 'No fee items provided'}), 400
        
        # Get target students with category filter
        students = []
        
        # Base query
        query = supabase.table('students')\
            .select('id, name, student_id, class_id, category')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')
        
        # Apply category filter
        if category_filter != 'all':
            query = query.eq('category', category_filter)
        
        # Apply apply_to filter
        if apply_to == 'class':
            if not target_id:
                return jsonify({'success': False, 'message': 'Please select a class'}), 400
            query = query.eq('class_id', target_id)
        elif apply_to == 'student':
            if not target_id:
                return jsonify({'success': False, 'message': 'Please select a student'}), 400
            query = query.eq('id', target_id)
        
        response = query.execute()
        students = response.data if response.data else []
        
        if not students:
            if apply_to == 'class':
                return jsonify({'success': False, 'message': 'No students found in this class with the selected category'}), 404
            elif apply_to == 'student':
                return jsonify({'success': False, 'message': 'Student not found or does not match category filter'}), 404
            else:
                return jsonify({'success': False, 'message': 'No students found with the selected category'}), 404
        
        # Create fee particulars and generate invoices
        invoices_created = 0
        particulars_created = []
        errors = []
        
        # Get all existing invoice numbers
        existing_invoices_response = supabase.table('invoices')\
            .select('invoice_number')\
            .eq('institute_id', institute_id)\
            .execute()
        
        existing_numbers = set()
        if existing_invoices_response.data:
            for inv in existing_invoices_response.data:
                existing_numbers.add(inv['invoice_number'])
        
        for student in students:
            try:
                # Calculate total amount from fee items
                total_amount = sum(item.get('amount', 0) for item in fee_items)
                
                # Create fee particulars record
                particulars_id = str(uuid.uuid4())
                particulars_data = {
                    'id': particulars_id,
                    'institute_id': institute_id,
                    'student_id': student['id'],
                    'class_id': student.get('class_id'),
                    'apply_to': apply_to,
                    'fee_items': json.dumps(fee_items),
                    'total_amount': total_amount,
                    'created_at': datetime.now().isoformat(),
                    'updated_at': datetime.now().isoformat()
                }
                
                particulars_result = supabase.table('fee_particulars').insert(particulars_data).execute()
                
                if particulars_result.data:
                    # Generate unique invoice number
                    invoice_number = generate_unique_invoice_number(institute_id, existing_numbers)
                    existing_numbers.add(invoice_number)
                    
                    invoice_id = str(uuid.uuid4())
                    due_date = datetime.now() + timedelta(days=30)
                    
                    invoice_data = {
                        'id': invoice_id,
                        'institute_id': institute_id,
                        'student_id': student['id'],
                        'particulars_id': particulars_id,
                        'invoice_number': invoice_number,
                        'total_amount': total_amount,
                        'paid_amount': 0,
                        'balance': total_amount,
                        'status': 'pending',
                        'due_date': due_date.date().isoformat(),
                        'created_at': datetime.now().isoformat(),
                        'updated_at': datetime.now().isoformat()
                    }
                    
                    invoice_result = supabase.table('invoices').insert(invoice_data).execute()
                    
                    if invoice_result.data:
                        invoices_created += 1
                        particulars_created.append({
                            'student': student['name'],
                            'student_id': student['student_id'],
                            'category': student.get('category', 'N/A'),
                            'invoice_number': invoice_number,
                            'total_amount': total_amount,
                            'type': 'invoice'
                        })
                    else:
                        errors.append(f"Failed to create invoice for {student['name']}")
                else:
                    errors.append(f"Failed to create fee particulars for {student['name']}")
                    
            except Exception as e:
                errors.append(f"Error processing {student['name']}: {str(e)}")
                print(f"Error processing student {student['name']}: {e}")
        
        if invoices_created > 0:
            return jsonify({
                'success': True,
                'message': f'Successfully created {invoices_created} invoice(s)',
                'invoices': particulars_created,
                'errors': errors if errors else None
            })
        else:
            return jsonify({
                'success': False, 
                'message': 'Failed to create invoices',
                'errors': errors
            }), 500
        
    except Exception as e:
        print(f"Error creating fee particulars: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

def generate_unique_invoice_number(institute_id, existing_numbers):
    """Generate unique invoice number with retry logic"""
    max_attempts = 10
    attempts = 0
    
    while attempts < max_attempts:
        try:
            year = datetime.now().strftime('%Y')
            month = datetime.now().strftime('%m')
            
            random_component = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
            
            response = supabase.table('invoices')\
                .select('id', count='exact')\
                .eq('institute_id', institute_id)\
                .gte('created_at', f"{year}-{month}-01")\
                .execute()
            
            count = (response.count or 0) + 1
            invoice_number = f"INV-{year}{month}-{random_component}-{str(count).zfill(3)}"
            
            if invoice_number not in existing_numbers:
                return invoice_number
                
        except Exception as e:
            print(f"Error generating invoice number (attempt {attempts + 1}): {e}")
        
        attempts += 1
        import time
        time.sleep(0.1)
    
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S%f')
    fallback_number = f"INV-{timestamp}"
    
    if fallback_number in existing_numbers:
        fallback_number = f"INV-{timestamp}-{random.randint(1000, 9999)}"
    
    return fallback_number

@fees_bp.route('/invoices', methods=['GET'])
@login_required
def get_invoices():
    """Get all invoices"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        status = request.args.get('status')
        
        query = supabase.table('invoices')\
            .select('*, students(name, student_id, category), fee_particulars(fee_items)')\
            .eq('institute_id', institute_id)\
            .order('created_at', desc=True)
        
        if status:
            query = query.eq('status', status)
        
        response = query.execute()
        
        invoices = response.data if response.data else []
        
        for invoice in invoices:
            if invoice.get('fee_particulars') and invoice['fee_particulars'].get('fee_items'):
                try:
                    invoice['fee_items'] = json.loads(invoice['fee_particulars']['fee_items'])
                except:
                    invoice['fee_items'] = []
        
        return jsonify({'success': True, 'invoices': invoices})
        
    except Exception as e:
        print(f"Error getting invoices: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@fees_bp.route('/invoices/<invoice_id>/pay', methods=['POST'])
@login_required
def pay_invoice(invoice_id):
    """Process invoice payment"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        amount_paid = float(data.get('amount', 0))
        payment_method = data.get('payment_method', 'cash')
        
        invoice_response = supabase.table('invoices')\
            .select('*')\
            .eq('id', invoice_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if not invoice_response.data:
            return jsonify({'success': False, 'message': 'Invoice not found'}), 404
        
        invoice = invoice_response.data[0]
        
        if invoice['status'] == 'paid':
            return jsonify({'success': False, 'message': 'Invoice already paid'}), 400
        
        new_paid = invoice['paid_amount'] + amount_paid
        new_balance = invoice['total_amount'] - new_paid
        new_status = 'paid' if new_balance <= 0 else 'partial'
        
        update_data = {
            'paid_amount': new_paid,
            'balance': new_balance,
            'status': new_status,
            'updated_at': datetime.now().isoformat()
        }
        
        result = supabase.table('invoices')\
            .update(update_data)\
            .eq('id', invoice_id)\
            .execute()
        
        if result.data:
            payment_id = str(uuid.uuid4())
            payment_data = {
                'id': payment_id,
                'institute_id': institute_id,
                'invoice_id': invoice_id,
                'student_id': invoice['student_id'],
                'amount': amount_paid,
                'payment_method': payment_method,
                'receipt_number': generate_receipt_number(institute_id),
                'payment_date': datetime.now().date().isoformat(),
                'created_at': datetime.now().isoformat()
            }
            
            supabase.table('payments').insert(payment_data).execute()
            
            return jsonify({
                'success': True,
                'message': f'Payment of UGX {amount_paid:,.0f} received',
                'invoice': {
                    'paid': new_paid,
                    'balance': new_balance,
                    'status': new_status
                }
            })
        else:
            return jsonify({'success': False, 'message': 'Payment failed'}), 500
            
    except Exception as e:
        print(f"Error processing payment: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@fees_bp.route('/students/<student_id>/invoices', methods=['GET'])
@login_required
def get_student_invoices(student_id):
    """Get invoices for a specific student"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        response = supabase.table('invoices')\
            .select('*, fee_particulars(fee_items)')\
            .eq('institute_id', institute_id)\
            .eq('student_id', student_id)\
            .order('created_at', desc=True)\
            .execute()
        
        invoices = response.data if response.data else []
        
        for invoice in invoices:
            if invoice.get('fee_particulars') and invoice['fee_particulars'].get('fee_items'):
                try:
                    invoice['fee_items'] = json.loads(invoice['fee_particulars']['fee_items'])
                except:
                    invoice['fee_items'] = []
        
        return jsonify({'success': True, 'invoices': invoices})
        
    except Exception as e:
        print(f"Error getting student invoices: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

def generate_invoice_number(institute_id):
    """Generate unique invoice number (legacy)"""
    return generate_unique_invoice_number(institute_id, set())

def generate_receipt_number(institute_id):
    """Generate unique receipt number"""
    try:
        year = datetime.now().strftime('%Y')
        month = datetime.now().strftime('%m')
        
        random_component = ''.join(random.choices(string.ascii_uppercase + string.digits, k=3))
        
        response = supabase.table('payments')\
            .select('id', count='exact')\
            .eq('institute_id', institute_id)\
            .gte('created_at', f"{year}-{month}-01")\
            .execute()
        
        count = (response.count or 0) + 1
        return f"RCP-{year}{month}-{random_component}-{str(count).zfill(3)}"
    except Exception as e:
        print(f"Error generating receipt number: {e}")
        return f"RCP-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(1000, 9999)}"