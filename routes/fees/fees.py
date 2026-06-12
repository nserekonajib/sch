from routes.permissions.permissions import role_required
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
from routes.accounts.accounts import get_institute_id
from flask import send_file, make_response
import pandas as pd
from io import BytesIO
from datetime import datetime

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



@fees_bp.route('/')
@role_required(['owner', 'teacher', 'accountant'])
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
@role_required(['owner', 'teacher', 'accountant'])
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
@role_required(['owner', 'teacher', 'accountant'])
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
@role_required(['owner', 'teacher', 'accountant'])
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
@role_required(['owner', 'teacher', 'accountant'])
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
@role_required(['owner', 'teacher', 'accountant'])
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
@role_required(['owner', 'teacher', 'accountant'])
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
    
    
@fees_bp.route('/particulars/create-multiple-classes', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def create_particulars_multiple_classes():
    """Create fee particulars for multiple classes with category filtering"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        
        class_ids = data.get('class_ids', [])  # Array of class IDs
        fee_items = data.get('fee_items', [])
        category_filter = data.get('category', 'all')  # 'all', 'Boarding', 'Day'
        
        if not class_ids:
            return jsonify({'success': False, 'message': 'Please select at least one class'}), 400
        
        if not fee_items:
            return jsonify({'success': False, 'message': 'No fee items provided'}), 400
        
        # Get all students from selected classes with category filter
        all_students = []
        
        for class_id in class_ids:
            # Build query for each class
            query = supabase.table('students')\
                .select('id, name, student_id, class_id, category, classes(name)')\
                .eq('institute_id', institute_id)\
                .eq('class_id', class_id)\
                .eq('status', 'active')
            
            # Apply category filter
            if category_filter != 'all':
                query = query.eq('category', category_filter)
            
            response = query.execute()
            
            if response.data:
                # Add class name to each student
                class_name = response.data[0].get('classes', {}).get('name', 'Unknown') if response.data else 'Unknown'
                for student in response.data:
                    student['class_name'] = class_name
                all_students.extend(response.data)
        
        if not all_students:
            return jsonify({'success': False, 'message': 'No students found in selected classes with the specified category'}), 404
        
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
        
        for student in all_students:
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
                    'apply_to': 'multiple_classes',
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
                            'class': student.get('class_name', 'N/A'),
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
                'message': f'Successfully created {invoices_created} invoice(s) for {len(class_ids)} class(es)',
                'invoices': particulars_created,
                'errors': errors if errors else None,
                'summary': {
                    'total_students': len(all_students),
                    'total_invoices': invoices_created,
                    'classes_processed': len(class_ids)
                }
            })
        else:
            return jsonify({
                'success': False, 
                'message': 'Failed to create invoices',
                'errors': errors
            }), 500
        
    except Exception as e:
        print(f"Error creating fee particulars for multiple classes: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


@fees_bp.route('/classes', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_classes():
    """Get all classes for the institute"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        response = supabase.table('classes')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('name')\
            .execute()
        
        classes = response.data if response.data else []
        
        # Get student counts for each class with category breakdown
        for class_item in classes:
            # Get total active students
            total_response = supabase.table('students')\
                .select('id', count='exact')\
                .eq('institute_id', institute_id)\
                .eq('class_id', class_item['id'])\
                .eq('status', 'active')\
                .execute()
            
            class_item['total_students'] = total_response.count or 0
            
            # Get boarding students count
            boarding_response = supabase.table('students')\
                .select('id', count='exact')\
                .eq('institute_id', institute_id)\
                .eq('class_id', class_item['id'])\
                .eq('category', 'Boarding')\
                .eq('status', 'active')\
                .execute()
            
            class_item['boarding_students'] = boarding_response.count or 0
            
            # Get day students count
            day_response = supabase.table('students')\
                .select('id', count='exact')\
                .eq('institute_id', institute_id)\
                .eq('class_id', class_item['id'])\
                .eq('category', 'Day')\
                .eq('status', 'active')\
                .execute()
            
            class_item['day_students'] = day_response.count or 0
        
        return jsonify({'success': True, 'classes': classes})
        
    except Exception as e:
        print(f"Error getting classes: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    
@fees_bp.route('/invoiced-students', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_invoiced_students():
    """Get paginated list of students with invoices and their invoice details"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Get pagination parameters
        page = request.args.get('page', 1, type=int)
        per_page = 10
        offset = (page - 1) * per_page
        
        # Get filter parameters
        category = request.args.get('category', 'all')
        status = request.args.get('status', 'all')
        
        # First, get students with category filter if needed
        student_query = supabase.table('students')\
            .select('id')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')
        
        if category != 'all':
            student_query = student_query.eq('category', category)
        
        student_response = student_query.execute()
        student_ids = [s['id'] for s in (student_response.data or [])]
        
        if not student_ids and category != 'all':
            return jsonify({
                'success': True,
                'students': [],
                'pagination': {
                    'current_page': page,
                    'per_page': per_page,
                    'total_count': 0,
                    'total_pages': 0,
                    'has_prev': False,
                    'has_next': False
                }
            })
        
        # Build query for invoices with students
        query = supabase.table('invoices')\
            .select('''
                id,
                invoice_number,
                total_amount,
                paid_amount,
                balance,
                status,
                due_date,
                created_at,
                student_id,
                fee_particulars(fee_items),
                students!inner(
                    id,
                    name,
                    student_id,
                    category,
                    class_id,
                    classes!inner(name)
                )
            ''')\
            .eq('institute_id', institute_id)
        
        # Apply student ID filter if category was specified
        if student_ids:
            query = query.in_('student_id', student_ids)
        
        # Apply status filter
        if status != 'all':
            query = query.eq('status', status)
        
        # Get total count for pagination
        count_query = supabase.table('invoices')\
            .select('id', count='exact')\
            .eq('institute_id', institute_id)
        
        if student_ids:
            count_query = count_query.in_('student_id', student_ids)
        
        if status != 'all':
            count_query = count_query.eq('status', status)
        
        count_result = count_query.execute()
        total_count = count_result.count or 0
        
        # Get paginated results
        response = query.order('created_at', desc=True)\
            .range(offset, offset + per_page - 1)\
            .execute()
        
        invoices = response.data if response.data else []
        
        # Format the response
        invoiced_students = []
        invoice_map = {}
        
        for invoice in invoices:
            student = invoice.get('students', {})
            student_id = student.get('id')
            
            if not student_id:
                continue
            
            # Parse fee items
            fee_items = []
            if invoice.get('fee_particulars') and invoice['fee_particulars'].get('fee_items'):
                try:
                    fee_items = json.loads(invoice['fee_particulars']['fee_items'])
                except:
                    fee_items = []
            
            # Group invoices by student
            if student_id not in invoice_map:
                invoice_map[student_id] = {
                    'student': {
                        'id': student_id,
                        'name': student.get('name', 'N/A'),
                        'student_id': student.get('student_id', 'N/A'),
                        'category': student.get('category', 'N/A'),
                        'class_name': student.get('classes', {}).get('name', 'N/A') if student.get('classes') else 'N/A'
                    },
                    'invoices': []
                }
            
            invoice_map[student_id]['invoices'].append({
                'id': invoice.get('id'),
                'invoice_number': invoice.get('invoice_number'),
                'total_amount': invoice.get('total_amount', 0),
                'paid_amount': invoice.get('paid_amount', 0),
                'balance': invoice.get('balance', 0),
                'status': invoice.get('status', 'pending'),
                'due_date': invoice.get('due_date'),
                'created_at': invoice.get('created_at'),
                'fee_items': fee_items
            })
        
        # Convert to list
        invoiced_students = list(invoice_map.values())
        
        total_pages = (total_count + per_page - 1) // per_page if total_count > 0 else 0
        
        return jsonify({
            'success': True,
            'students': invoiced_students,
            'pagination': {
                'current_page': page,
                'per_page': per_page,
                'total_count': total_count,
                'total_pages': total_pages,
                'has_prev': page > 1,
                'has_next': page < total_pages
            }
        })
        
    except Exception as e:
        print(f"Error getting invoiced students: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@fees_bp.route('/invoice/<invoice_id>/details', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_invoice_details(invoice_id):
    """Get detailed invoice information for modal popup"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        response = supabase.table('invoices')\
            .select('''
                *,
                students(
                    id,
                    name,
                    student_id,
                    category,
                    class_id,
                    classes(name),
                    father_name,
                    mother_name,
                    all_parents,
                    contact_number,
                    address
                ),
                fee_particulars(fee_items),
                payments(
                    id,
                    amount,
                    payment_method,
                    receipt_number,
                    payment_date
                )
            ''')\
            .eq('id', invoice_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if not response.data:
            return jsonify({'success': False, 'message': 'Invoice not found'}), 404
        
        invoice = response.data[0]
        
        # Parse fee items
        fee_items = []
        if invoice.get('fee_particulars') and invoice['fee_particulars'].get('fee_items'):
            try:
                fee_items = json.loads(invoice['fee_particulars']['fee_items'])
            except:
                fee_items = []
        
        # Get student details
        student = invoice.get('students', {})
        
        # Get payment history
        payments = invoice.get('payments', [])
        
        # Sort payments by date
        payments = sorted(payments, key=lambda x: x.get('payment_date', ''), reverse=True)
        
        # Build parent name string from available fields
        parent_name = 'N/A'
        if student.get('father_name') and student.get('mother_name'):
            parent_name = f"Father: {student.get('father_name')}, Mother: {student.get('mother_name')}"
        elif student.get('father_name'):
            parent_name = f"Father: {student.get('father_name')}"
        elif student.get('mother_name'):
            parent_name = f"Mother: {student.get('mother_name')}"
        elif student.get('all_parents'):
            parent_name = student.get('all_parents')
        
        # Get parent phone
        parent_phone = student.get('contact_number', 'N/A')
        
        return jsonify({
            'success': True,
            'invoice': {
                'id': invoice.get('id'),
                'invoice_number': invoice.get('invoice_number'),
                'total_amount': invoice.get('total_amount', 0),
                'paid_amount': invoice.get('paid_amount', 0),
                'balance': invoice.get('balance', 0),
                'status': invoice.get('status', 'pending'),
                'due_date': invoice.get('due_date'),
                'created_at': invoice.get('created_at'),
                'updated_at': invoice.get('updated_at'),
                'fee_items': fee_items,
                'student': {
                    'id': student.get('id'),
                    'name': student.get('name', 'N/A'),
                    'student_id': student.get('student_id', 'N/A'),
                    'category': student.get('category', 'N/A'),
                    'class_name': student.get('classes', {}).get('name', 'N/A') if student.get('classes') else 'N/A',
                    'parent_name': parent_name,
                    'parent_phone': parent_phone,
                    'address': student.get('address', 'N/A')
                },
                'payments': payments
            }
        })
        
    except Exception as e:
        print(f"Error getting invoice details: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500
    
    


@fees_bp.route('/export-invoiced-students', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def export_invoiced_students():
    """Export invoiced students to Excel with date filtering"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Get filter parameters
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        category = request.args.get('category', 'all')
        status = request.args.get('status', 'all')
        
        # Build query for students with invoices
        student_query = supabase.table('students')\
            .select('id, name, student_id, category, class_id, classes!inner(name)')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')
        
        if category != 'all':
            student_query = student_query.eq('category', category)
        
        student_response = student_query.execute()
        students = student_response.data or []
        
        if not students:
            return jsonify({'success': False, 'message': 'No students found'}), 404
        
        student_ids = [s['id'] for s in students]
        
        # Build invoice query with date filtering
        invoice_query = supabase.table('invoices')\
            .select('''
                id,
                invoice_number,
                total_amount,
                paid_amount,
                balance,
                status,
                due_date,
                created_at,
                student_id,
                fee_particulars(fee_items)
            ''')\
            .eq('institute_id', institute_id)\
            .in_('student_id', student_ids)
        
        # Apply date filters
        if start_date:
            invoice_query = invoice_query.gte('created_at', start_date)
        if end_date:
            # Add one day to include the end date fully
            end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
            next_day = end_date_obj + timedelta(days=1)
            invoice_query = invoice_query.lt('created_at', next_day.strftime('%Y-%m-%d'))
        
        if status != 'all':
            invoice_query = invoice_query.eq('status', status)
        
        invoice_response = invoice_query.order('created_at', desc=False).execute()
        invoices = invoice_response.data or []
        
        # Create student mapping
        student_map = {s['id']: s for s in students}
        
        # Prepare data for Excel
        export_data = []
        
        for invoice in invoices:
            student = student_map.get(invoice['student_id'], {})
            
            # Parse fee items
            fee_items_str = ""
            if invoice.get('fee_particulars') and invoice['fee_particulars'].get('fee_items'):
                try:
                    fee_items = json.loads(invoice['fee_particulars']['fee_items'])
                    fee_items_str = ", ".join([f"{item.get('label', '')}: UGX {item.get('amount', 0):,}" for item in fee_items])
                except:
                    fee_items_str = ""
            
            # Calculate days overdue if due_date exists
            days_overdue = ""
            if invoice.get('due_date'):
                try:
                    due_date = datetime.strptime(invoice['due_date'], '%Y-%m-%d')
                    if due_date.date() < datetime.now().date() and invoice.get('balance', 0) > 0:
                        days_overdue = (datetime.now().date() - due_date.date()).days
                        days_overdue = f"{days_overdue} days"
                    else:
                        days_overdue = "Not overdue"
                except:
                    days_overdue = ""
            
            export_data.append({
                'Invoice Number': invoice.get('invoice_number', ''),
                'Student Name': student.get('name', ''),
                'Student ID': student.get('student_id', ''),
                'Class': student.get('classes', {}).get('name', '') if student.get('classes') else '',
                'Category': student.get('category', ''),
                'Status': invoice.get('status', '').title(),
                'Total Amount (UGX)': invoice.get('total_amount', 0),
                'Paid Amount (UGX)': invoice.get('paid_amount', 0),
                'Balance (UGX)': invoice.get('balance', 0),
                'Payment %': f"{(invoice.get('paid_amount', 0) / invoice.get('total_amount', 1) * 100):.1f}%" if invoice.get('total_amount', 0) > 0 else "0%",
                'Due Date': invoice.get('due_date', ''),
                'Days Overdue': days_overdue,
                'Invoice Date': invoice.get('created_at', ''),
                'Fee Items': fee_items_str
            })
        
        if not export_data:
            return jsonify({'success': False, 'message': 'No invoices found for the selected filters'}), 404
        
        # Create DataFrame
        df = pd.DataFrame(export_data)
        
        # Add summary sheet data
        summary_data = {
            'Metric': [
                'Report Generated On',
                'Total Invoices',
                'Total Amount (UGX)',
                'Total Paid Amount (UGX)',
                'Total Balance (UGX)',
                'Collection Rate',
                'Start Date',
                'End Date',
                'Categories Filter',
                'Status Filter'
            ],
            'Value': [
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                len(export_data),
                f"UGX {df['Total Amount (UGX)'].sum():,.2f}",
                f"UGX {df['Paid Amount (UGX)'].sum():,.2f}",
                f"UGX {df['Balance (UGX)'].sum():,.2f}",
                f"{(df['Paid Amount (UGX)'].sum() / df['Total Amount (UGX)'].sum() * 100):.1f}%" if df['Total Amount (UGX)'].sum() > 0 else "0%",
                start_date or 'All',
                end_date or 'All',
                category.title(),
                status.title()
            ]
        }
        df_summary = pd.DataFrame(summary_data)
        
        # Create Excel file with multiple sheets
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            # Write main data
            df.to_excel(writer, sheet_name='Invoiced Students', index=False)
            
            # Write summary
            df_summary.to_excel(writer, sheet_name='Summary', index=False)
            
            # Add status breakdown
            status_breakdown = df.groupby('Status').agg({
                'Total Amount (UGX)': 'sum',
                'Paid Amount (UGX)': 'sum',
                'Balance (UGX)': 'sum'
            }).reset_index()
            status_breakdown.to_excel(writer, sheet_name='Status Breakdown', index=False)
            
            # Add category breakdown
            category_breakdown = df.groupby('Category').agg({
                'Total Amount (UGX)': 'sum',
                'Paid Amount (UGX)': 'sum',
                'Balance (UGX)': 'sum'
            }).reset_index()
            category_breakdown.to_excel(writer, sheet_name='Category Breakdown', index=False)
        
        output.seek(0)
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"invoiced_students_{timestamp}.xlsx"
        
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        print(f"Error exporting invoiced students: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500
    
    
@fees_bp.route('/student-payable-summary/<student_id>', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_student_payable_summary(student_id):
    """
    Get student's total payable amount after discounts and collection percentage
    Returns: total_invoiced, total_discount, total_payable, total_paid, collection_percentage, remaining_balance
    """
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Get student details
        student_response = supabase.table('students')\
            .select('*, classes(name)')\
            .eq('id', student_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if not student_response.data:
            return jsonify({'success': False, 'message': 'Student not found'}), 404
        
        student = student_response.data[0]
        
        # Get all invoices for this student
        invoices_response = supabase.table('invoices')\
            .select('*')\
            .eq('student_id', student_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        invoices = invoices_response.data if invoices_response.data else []
        
        # Get all discounts applied to this student
        discounts_response = supabase.table('discounts')\
            .select('*')\
            .eq('student_id', student_id)\
            .eq('institute_id', institute_id)\
            .eq('is_active', True)\
            .execute()
        
        discounts = discounts_response.data if discounts_response.data else []
        
        # Calculate totals safely
        total_invoiced = 0
        total_paid = 0
        for inv in invoices:
            total_invoiced += float(inv.get('total_amount') or 0)
            total_paid += float(inv.get('paid_amount') or 0)
        
        # Calculate total discount applied safely
        total_discount_applied = 0
        for discount in discounts:
            discount_amount = discount.get('discount_amount')
            if discount_amount is not None:
                try:
                    total_discount_applied += float(discount_amount)
                except (ValueError, TypeError):
                    print(f"Invalid discount amount: {discount_amount}")
        
        # Total payable after discount = total_invoiced - total_discount_applied
        total_payable = total_invoiced - total_discount_applied
        
        # Calculate collection percentage
        if total_payable > 0:
            collection_percentage = (total_paid / total_payable) * 100
        else:
            collection_percentage = 100 if total_paid > 0 else 0
        
        # Calculate remaining balance (negative means credit/overpayment)
        remaining_balance = total_payable - total_paid
        
        # Get invoice breakdown with individual discounts
        invoice_breakdown = []
        for invoice in invoices:
            # Get discounts for this specific invoice
            invoice_discounts = [d for d in discounts if d.get('invoice_id') == invoice.get('id')]
            invoice_discount_amount = 0
            for d in invoice_discounts:
                discount_amount = d.get('discount_amount')
                if discount_amount is not None:
                    try:
                        invoice_discount_amount += float(discount_amount)
                    except (ValueError, TypeError):
                        pass
            
            invoice_breakdown.append({
                'invoice_id': invoice.get('id'),
                'invoice_number': invoice.get('invoice_number'),
                'total_amount': float(invoice.get('total_amount') or 0),
                'discount_applied': invoice_discount_amount,
                'payable_amount': (float(invoice.get('total_amount') or 0)) - invoice_discount_amount,
                'paid_amount': float(invoice.get('paid_amount') or 0),
                'balance': float(invoice.get('balance') or 0),
                'status': invoice.get('status'),
                'due_date': invoice.get('due_date')
            })
        
        return jsonify({
            'success': True,
            'student': {
                'id': student['id'],
                'name': student['name'],
                'student_id': student['student_id'],
                'class': student['classes']['name'] if student.get('classes') else 'N/A',
                'category': student.get('category', 'N/A')
            },
            'summary': {
                'total_invoiced': round(total_invoiced, 2),
                'total_discount': round(total_discount_applied, 2),
                'total_payable': round(total_payable, 2),
                'total_paid': round(total_paid, 2),
                'remaining_balance': round(remaining_balance, 2),
                'collection_percentage': round(collection_percentage, 2),
                'is_credit': remaining_balance < 0,
                'credit_amount': round(abs(remaining_balance), 2) if remaining_balance < 0 else 0
            },
            'invoice_breakdown': invoice_breakdown,
            'discounts_applied': [
                {
                    'discount_id': d.get('id'),
                    'invoice_id': d.get('invoice_id'),
                    'discount_type': d.get('discount_type'),
                    'discount_value': d.get('discount_value'),
                    'discount_amount': float(d.get('discount_amount') or 0),
                    'reason': d.get('reason'),
                    'applied_on': d.get('created_at')
                } for d in discounts
            ]
        })
        
    except Exception as e:
        print(f"Error getting student payable summary: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500
    
@fees_bp.route('/class-payable-summary/<class_id>', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_class_payable_summary(class_id):
    """
    Get class-wise summary of total payable amounts after discounts and collection percentages
    """
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Get all active students in the class
        students_response = supabase.table('students')\
            .select('id, name, student_id, category')\
            .eq('institute_id', institute_id)\
            .eq('class_id', class_id)\
            .eq('status', 'active')\
            .execute()
        
        students = students_response.data if students_response.data else []
        
        if not students:
            return jsonify({'success': False, 'message': 'No students found in this class'}), 404
        
        # Get class details
        class_response = supabase.table('classes')\
            .select('name')\
            .eq('id', class_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        class_name = class_response.data[0]['name'] if class_response.data else 'Unknown Class'
        
        # Initialize totals
        class_totals = {
            'total_students': len(students),
            'total_invoiced': 0,
            'total_discount': 0,
            'total_payable': 0,
            'total_paid': 0,
            'remaining_balance': 0,
            'average_collection_percentage': 0
        }
        
        student_summaries = []
        
        for student in students:
            # Get invoices for this student
            invoices_response = supabase.table('invoices')\
                .select('*')\
                .eq('student_id', student['id'])\
                .eq('institute_id', institute_id)\
                .execute()
            
            invoices = invoices_response.data if invoices_response.data else []
            
            # Get discounts for this student
            discounts_response = supabase.table('discounts')\
                .select('*')\
                .eq('student_id', student['id'])\
                .eq('institute_id', institute_id)\
                .eq('is_active', True)\
                .execute()
            
            discounts = discounts_response.data if discounts_response.data else []
            
            # Calculate totals safely
            total_invoiced = 0
            total_paid = 0
            for inv in invoices:
                total_invoiced += float(inv.get('total_amount') or 0)
                total_paid += float(inv.get('paid_amount') or 0)
            
            total_discount = 0
            for d in discounts:
                discount_amount = d.get('discount_amount')
                if discount_amount is not None:
                    try:
                        total_discount += float(discount_amount)
                    except (ValueError, TypeError):
                        pass
            
            total_payable = total_invoiced - total_discount
            
            if total_payable > 0:
                collection_percentage = (total_paid / total_payable) * 100
            else:
                collection_percentage = 100 if total_paid > 0 else 0
            
            remaining_balance = total_payable - total_paid
            
            # Add to class totals
            class_totals['total_invoiced'] += total_invoiced
            class_totals['total_discount'] += total_discount
            class_totals['total_payable'] += total_payable
            class_totals['total_paid'] += total_paid
            class_totals['remaining_balance'] += remaining_balance
            
            student_summaries.append({
                'student_id': student['id'],
                'student_name': student['name'],
                'student_code': student['student_id'],
                'category': student.get('category', 'N/A'),
                'total_invoiced': round(total_invoiced, 2),
                'total_discount': round(total_discount, 2),
                'total_payable': round(total_payable, 2),
                'total_paid': round(total_paid, 2),
                'remaining_balance': round(remaining_balance, 2),
                'collection_percentage': round(collection_percentage, 2),
                'status': 'Credit' if remaining_balance < 0 else ('Paid' if remaining_balance == 0 else 'Pending')
            })
        
        # Calculate average collection percentage
        if class_totals['total_payable'] > 0:
            class_totals['average_collection_percentage'] = round((class_totals['total_paid'] / class_totals['total_payable']) * 100, 2)
        
        return jsonify({
            'success': True,
            'class': {
                'id': class_id,
                'name': class_name
            },
            'summary': {
                **class_totals,
                'total_invoiced': round(class_totals['total_invoiced'], 2),
                'total_discount': round(class_totals['total_discount'], 2),
                'total_payable': round(class_totals['total_payable'], 2),
                'total_paid': round(class_totals['total_paid'], 2),
                'remaining_balance': round(class_totals['remaining_balance'], 2)
            },
            'students': student_summaries
        })
        
    except Exception as e:
        print(f"Error getting class payable summary: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500
@fees_bp.route('/overall-payable-summary', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_overall_payable_summary():
    """
    Get overall summary for the entire institute
    Returns total payable amounts after discounts and overall collection percentage
    """
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Get all active students
        students_response = supabase.table('students')\
            .select('id, name, student_id, class_id, category, classes(name)')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')\
            .execute()
        
        students = students_response.data if students_response.data else []
        
        # Get all invoices
        invoices_response = supabase.table('invoices')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .execute()
        
        invoices = invoices_response.data if invoices_response.data else []
        
        # Get all discounts
        discounts_response = supabase.table('discounts')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .eq('is_active', True)\
            .execute()
        
        discounts = discounts_response.data if discounts_response.data else []
        
        # Calculate totals - Handle None values safely
        total_invoiced = 0.0
        total_paid = 0.0
        for inv in invoices:
            try:
                total_amount = inv.get('total_amount')
                if total_amount is not None:
                    total_invoiced += float(total_amount)
                
                paid_amount = inv.get('paid_amount')
                if paid_amount is not None:
                    total_paid += float(paid_amount)
            except (ValueError, TypeError) as e:
                print(f"Error processing invoice amount: {e}")
                continue
        
        # Calculate total discount - Handle None values safely
        total_discount = 0.0
        for d in discounts:
            try:
                discount_amount = d.get('discount_amount')
                if discount_amount is not None and discount_amount != '':
                    total_discount += float(discount_amount)
            except (ValueError, TypeError) as e:
                print(f"Invalid discount_amount value: {discount_amount}, error: {e}")
                continue
        
        total_payable = total_invoiced - total_discount
        
        if total_payable > 0:
            overall_collection_percentage = (total_paid / total_payable) * 100
        else:
            overall_collection_percentage = 100.0 if total_paid > 0 else 0.0
        
        remaining_balance = total_payable - total_paid
        
        # Category-wise breakdown with safe number handling
        category_breakdown = {}
        for student in students:
            # Handle None category - default to 'Other'
            category = student.get('category')
            if category is None or category == '':
                category = 'Other'
            elif not isinstance(category, str):
                category = str(category)
            
            if category not in category_breakdown:
                category_breakdown[category] = {
                    'student_count': 0,
                    'total_invoiced': 0.0,
                    'total_paid': 0.0,
                    'total_discount': 0.0
                }
            
            category_breakdown[category]['student_count'] += 1
            
            # Get student's invoices
            student_invoices = [inv for inv in invoices if inv.get('student_id') == student['id']]
            student_discounts = [d for d in discounts if d.get('student_id') == student['id']]
            
            # Calculate student totals safely
            student_invoiced = 0.0
            student_paid = 0.0
            for inv in student_invoices:
                try:
                    total_amount = inv.get('total_amount')
                    if total_amount is not None:
                        student_invoiced += float(total_amount)
                    
                    paid_amount = inv.get('paid_amount')
                    if paid_amount is not None:
                        student_paid += float(paid_amount)
                except (ValueError, TypeError):
                    continue
            
            student_discount = 0.0
            for d in student_discounts:
                try:
                    discount_amount = d.get('discount_amount')
                    if discount_amount is not None and discount_amount != '':
                        student_discount += float(discount_amount)
                except (ValueError, TypeError):
                    continue
            
            category_breakdown[category]['total_invoiced'] += student_invoiced
            category_breakdown[category]['total_paid'] += student_paid
            category_breakdown[category]['total_discount'] += student_discount
        
        # Calculate category percentages safely and ensure no None values
        formatted_category_breakdown = {}
        for category, data in category_breakdown.items():
            cat_total_payable = data['total_invoiced'] - data['total_discount']
            
            if cat_total_payable > 0:
                collection_percentage = round((data['total_paid'] / cat_total_payable) * 100, 2)
            else:
                collection_percentage = 100.0 if data['total_paid'] > 0 else 0.0
            
            formatted_category_breakdown[category] = {
                'student_count': data['student_count'],
                'total_invoiced': round(data['total_invoiced'], 2),
                'total_discount': round(data['total_discount'], 2),
                'total_payable': round(cat_total_payable, 2),
                'total_paid': round(data['total_paid'], 2),
                'remaining_balance': round(cat_total_payable - data['total_paid'], 2),
                'collection_percentage': collection_percentage
            }
        
        # Prepare response with all safe values
        response_data = {
            'success': True,
            'institute_id': str(institute_id) if institute_id else '',
            'summary': {
                'total_students': len(students),
                'total_invoiced': round(total_invoiced, 2),
                'total_discount_applied': round(total_discount, 2),
                'total_payable': round(total_payable, 2),
                'total_collected': round(total_paid, 2),
                'total_remaining': round(remaining_balance, 2),
                'overall_collection_percentage': round(overall_collection_percentage, 2),
                'total_invoices': len(invoices),
                'total_discount_records': len(discounts),
                'is_overall_credit': remaining_balance < 0
            },
            'category_breakdown': formatted_category_breakdown
        }
        
        return jsonify(response_data)
        
    except Exception as e:
        print(f"Error getting overall payable summary: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False, 
            'message': f'Error processing data: {str(e)}'
        }), 500
        
@fees_bp.route('/payable-summary/<institute_id>', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def payable_summary_page(institute_id):
    """Render the payable summary page for a specific institute"""
    user = session.get('user')
    
    # Verify the user has access to this institute
    user_institute_id = get_institute_id(user['id'])
    
    if not user_institute_id or user_institute_id != institute_id:
        return render_template('errors/403.html', 
                             message="You don't have access to this institute's data"), 403
    
    try:
        # Get institute details
        institute_response = supabase.table('institutes')\
            .select('institute_name, id')\
            .eq('id', institute_id)\
            .execute()
        
        if not institute_response.data:
            return render_template('errors/404.html', 
                                 message="Institute not found"), 404
        
        institute = institute_response.data[0]
        
        return render_template('fees/payable_summary.html', 
                             institute=institute['institute_name'],
                             institute_id=institute_id)
        
    except Exception as e:
        print(f"Error loading payable summary page: {e}")
        return render_template('errors/500.html', 
                             message="Error loading fee collection summary"), 500
        
        
        
@fees_bp.route('/students-without-invoices', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_students_without_invoices():
    """
    Get students who have no invoices within the selected date range
    Query params: start_date, end_date, category (optional), class_id (optional)
    """
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Get query parameters
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        category = request.args.get('category', 'all')
        class_id = request.args.get('class_id', 'all')
        
        # Validate date range
        if not start_date or not end_date:
            return jsonify({'success': False, 'message': 'Start date and end date are required'}), 400
        
        # Get all active students with their details
        student_query = supabase.table('students')\
            .select('id, name, student_id, category, class_id, contact_number, address, classes(name)')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')
        
        # Apply category filter
        if category != 'all':
            student_query = student_query.eq('category', category)
        
        # Apply class filter
        if class_id != 'all':
            student_query = student_query.eq('class_id', class_id)
        
        student_response = student_query.execute()
        all_students = student_response.data if student_response.data else []
        
        if not all_students:
            return jsonify({
                'success': True,
                'students': [],
                'total_count': 0,
                'message': 'No students found with the selected filters'
            })
        
        # Get all invoices within the date range
        invoice_query = supabase.table('invoices')\
            .select('student_id')\
            .eq('institute_id', institute_id)\
            .gte('created_at', start_date)\
            .lte('created_at', end_date)
        
        invoice_response = invoice_query.execute()
        invoiced_student_ids = set()
        
        if invoice_response.data:
            invoiced_student_ids = {inv['student_id'] for inv in invoice_response.data}
        
        # Filter students who have NO invoices in the date range
        students_without_invoices = []
        for student in all_students:
            if student['id'] not in invoiced_student_ids:
                students_without_invoices.append({
                    'id': student['id'],
                    'name': student['name'],
                    'student_id': student['student_id'],
                    'category': student.get('category', 'N/A'),
                    'class_name': student.get('classes', {}).get('name', 'N/A') if student.get('classes') else 'N/A',
                    'class_id': student.get('class_id'),
                    'contact_number': student.get('contact_number', 'N/A'),
                    'address': student.get('address', 'N/A')
                })
        
        # Get class list for filter dropdown
        classes_response = supabase.table('classes')\
            .select('id, name')\
            .eq('institute_id', institute_id)\
            .order('name')\
            .execute()
        
        classes = classes_response.data if classes_response.data else []
        
        return jsonify({
            'success': True,
            'students': students_without_invoices,
            'total_count': len(students_without_invoices),
            'filters': {
                'start_date': start_date,
                'end_date': end_date,
                'category': category,
                'class_id': class_id
            },
            'classes': classes
        })
        
    except Exception as e:
        print(f"Error getting students without invoices: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


@fees_bp.route('/export-students-without-invoices', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def export_students_without_invoices():
    """Export students without invoices to Excel"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Get query parameters
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        category = request.args.get('category', 'all')
        class_id = request.args.get('class_id', 'all')
        
        if not start_date or not end_date:
            return jsonify({'success': False, 'message': 'Start date and end date are required'}), 400
        
        # Get all active students with their details
        student_query = supabase.table('students')\
            .select('id, name, student_id, category, class_id, contact_number, address, classes(name)')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')
        
        if category != 'all':
            student_query = student_query.eq('category', category)
        
        if class_id != 'all':
            student_query = student_query.eq('class_id', class_id)
        
        student_response = student_query.execute()
        all_students = student_response.data if student_response.data else []
        
        # Get all invoices within the date range
        invoice_query = supabase.table('invoices')\
            .select('student_id')\
            .eq('institute_id', institute_id)\
            .gte('created_at', start_date)\
            .lte('created_at', end_date)
        
        invoice_response = invoice_query.execute()
        invoiced_student_ids = {inv['student_id'] for inv in (invoice_response.data or [])}
        
        # Filter students without invoices
        students_without_invoices = []
        for student in all_students:
            if student['id'] not in invoiced_student_ids:
                students_without_invoices.append({
                    'Student Name': student['name'],
                    'Student ID': student['student_id'],
                    'Class': student.get('classes', {}).get('name', 'N/A') if student.get('classes') else 'N/A',
                    'Category': student.get('category', 'N/A'),
                    'Contact Number': student.get('contact_number', 'N/A'),
                    'Address': student.get('address', 'N/A')
                })
        
        if not students_without_invoices:
            return jsonify({'success': False, 'message': 'No students found without invoices in the selected date range'}), 404
        
        # Create DataFrame
        df = pd.DataFrame(students_without_invoices)
        
        # Add summary sheet
        summary_data = {
            'Metric': [
                'Report Generated On',
                'Date Range',
                'Start Date',
                'End Date',
                'Category Filter',
                'Class Filter',
                'Total Students Without Invoices',
                'Total Active Students',
                'Students With Invoices'
            ],
            'Value': [
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                f"{start_date} to {end_date}",
                start_date,
                end_date,
                category.title(),
                class_id if class_id != 'all' else 'All Classes',
                len(students_without_invoices),
                len(all_students),
                len(all_students) - len(students_without_invoices)
            ]
        }
        df_summary = pd.DataFrame(summary_data)
        
        # Create Excel file
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Students Without Invoices', index=False)
            df_summary.to_excel(writer, sheet_name='Summary', index=False)
            
            # Add category breakdown
            category_breakdown = df.groupby('Category').size().reset_index(name='Count')
            category_breakdown.to_excel(writer, sheet_name='Category Breakdown', index=False)
            
            # Add class breakdown
            class_breakdown = df.groupby('Class').size().reset_index(name='Count')
            class_breakdown.to_excel(writer, sheet_name='Class Breakdown', index=False)
        
        output.seek(0)
        
        # Generate filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"students_without_invoices_{start_date}_to_{end_date}_{timestamp}.xlsx"
        
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        print(f"Error exporting students without invoices: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500
    
    
@fees_bp.route('/students-without-invoices-page', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def students_without_invoices_page():
    """Render the students without invoices page"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return render_template('errors/404.html', message="Institute not found"), 404
    
    return render_template('fees/students_without_invoices.html', 
                         institute_id=institute_id)