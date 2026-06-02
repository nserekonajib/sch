# studentDetailPage.py - Student Details and Statement Blueprint with Card/List Views
from flask import Blueprint, render_template, request, jsonify, session, send_file, url_for
from supabase import create_client, Client
import os
import uuid
from datetime import datetime, timedelta
import json
import io
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, mm
from reportlab.pdfgen import canvas
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from functools import wraps
from dotenv import load_dotenv

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

student_detail_bp = Blueprint('student_detail', __name__, url_prefix='/student-details')

def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Please login'}), 401
        return f(*args, **kwargs)
    return decorated_function

def role_required(allowed_roles):
    """Decorator to require specific roles"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user' not in session:
                return jsonify({'success': False, 'message': 'Please login'}), 401
            
            user = session.get('user', {})
            is_employee = user.get('is_employee', False)
            user_role = user.get('role')
            
            # For institute owners (not employees)
            if not is_employee and 'owner' in allowed_roles:
                return f(*args, **kwargs)
            
            # For employees with matching role
            if is_employee and user_role in allowed_roles:
                return f(*args, **kwargs)
            
            return jsonify({'success': False, 'message': 'Access denied'}), 403
        return decorated_function
    return decorator

def get_institute_from_session():
    """Get institute details from current session - handles both owners and employees"""
    user = session.get('user')
    if not user:
        print("No user in session")
        return None
    
    institute_id = None
    
    # CASE 1: Employee - has institute_id directly in session
    if user.get('is_employee') and user.get('institute_id'):
        institute_id = user.get('institute_id')
    
    # CASE 2: Owner - need to look up by user_id
    elif not user.get('is_employee') and user.get('id'):
        try:
            response = supabase.table('institutes')\
                .select('id')\
                .eq('user_id', user['id'])\
                .execute()
            
            if response.data and len(response.data) > 0:
                institute_id = response.data[0]['id']
        except Exception as e:
            print(f"Error finding owner institute: {e}")
    
    # CASE 3: Employee but institute_id not in session - fallback to lookup
    elif user.get('is_employee') and not user.get('institute_id'):
        try:
            employee_response = supabase.table('employees')\
                .select('institute_id')\
                .eq('id', user['id'])\
                .execute()
            
            if employee_response.data and len(employee_response.data) > 0:
                institute_id = employee_response.data[0].get('institute_id')
        except Exception as e:
            print(f"Error looking up employee institute: {e}")
    
    if not institute_id:
        return None
    
    # Fetch full institute details
    try:
        response = supabase.table('institutes')\
            .select('*')\
            .eq('id', institute_id)\
            .execute()
        
        if response.data and len(response.data) > 0:
            return response.data[0]
        return None
    except Exception as e:
        print(f"Error fetching institute details: {e}")
        return None

@student_detail_bp.route('/')
@role_required(['owner', 'teacher', 'accountant'])
def index():
    """Student Dashboard - Card/List View"""
    institute = get_institute_from_session()
    
    if not institute:
        return render_template('student_details/index.html', institute=None, students=[], view_type='card')
    
    try:
        # Get all students for the institute
        response = supabase.table('students')\
            .select('*, classes(name)')\
            .eq('institute_id', institute['id'])\
            .order('name')\
            .execute()
        
        students = response.data if response.data else []
        
        # Get classes for filtering
        classes_response = supabase.table('classes')\
            .select('*')\
            .eq('institute_id', institute['id'])\
            .order('name')\
            .execute()
        
        classes = classes_response.data if classes_response.data else []
        
        return render_template('student_details/index.html', 
                             institute=institute, 
                             students=students, 
                             classes=classes,
                             view_type='card')
        
    except Exception as e:
        print(f"Error fetching students: {e}")
        return render_template('student_details/index.html', 
                             institute=institute, 
                             students=[], 
                             classes=[],
                             view_type='card')

@student_detail_bp.route('/api/students')
@role_required(['owner', 'teacher', 'accountant'])
def api_get_students():
    """API endpoint to get students with filtering"""
    institute = get_institute_from_session()
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        class_id = request.args.get('class_id')
        search_term = request.args.get('search', '').strip()
        
        query = supabase.table('students')\
            .select('*, classes(name)')\
            .eq('institute_id', institute['id'])
        
        if class_id and class_id != 'all':
            query = query.eq('class_id', class_id)
        
        if search_term:
            query = query.ilike('name', f'%{search_term}%')
        
        response = query.order('name').execute()
        
        students = response.data if response.data else []
        
        # Get current balance for each student
        for student in students:
            # Get total invoices
            invoices_response = supabase.table('invoices')\
                .select('total_amount, balance')\
                .eq('student_id', student['id'])\
                .eq('institute_id', institute['id'])\
                .execute()
            
            total_balance = 0
            if invoices_response.data:
                total_balance = sum(inv.get('balance', 0) for inv in invoices_response.data)
            
            student['current_balance'] = total_balance
        
        return jsonify({'success': True, 'students': students})
        
    except Exception as e:
        print(f"Error fetching students: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@student_detail_bp.route('/<student_id>')
@role_required(['owner', 'teacher', 'accountant'])
def student_details(student_id):
    """Student Details Page with Statement"""
    institute = get_institute_from_session()
    
    if not institute:
        return render_template('student_details/details.html', student=None, institute=None)
    
    try:
        # Get student details with class info
        student_response = supabase.table('students')\
            .select('*, classes(name)')\
            .eq('id', student_id)\
            .eq('institute_id', institute['id'])\
            .execute()
        
        if not student_response.data:
            return render_template('student_details/details.html', 
                                 student=None, 
                                 institute=institute,
                                 error="Student not found")
        
        student = student_response.data[0]
        
        # Get class info
        student_class = student.get('classes', {})
        
        # Get all classes for potential transfer
        classes_response = supabase.table('classes')\
            .select('*')\
            .eq('institute_id', institute['id'])\
            .order('name')\
            .execute()
        
        classes = classes_response.data if classes_response.data else []
        
        return render_template('student_details/details.html', 
                             student=student,
                             student_class=student_class,
                             classes=classes,
                             institute=institute)
        
    except Exception as e:
        print(f"Error fetching student details: {e}")
        return render_template('student_details/details.html', 
                             student=None, 
                             institute=institute,
                             error=str(e))

@student_detail_bp.route('/api/student-statement/<student_id>', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def api_get_student_statement(student_id):
    """API to get student statement with date filtering"""
    institute = get_institute_from_session()
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        # Get student details
        student_response = supabase.table('students')\
            .select('*, classes(name)')\
            .eq('id', student_id)\
            .eq('institute_id', institute['id'])\
            .execute()
        
        if not student_response.data:
            return jsonify({'success': False, 'message': 'Student not found'}), 404
        
        student = student_response.data[0]
        
        # Get ALL invoices for this student
        invoice_query = supabase.table('invoices')\
            .select('*')\
            .eq('student_id', student_id)\
            .eq('institute_id', institute['id'])
        
        if start_date:
            invoice_query = invoice_query.gte('created_at', f"{start_date}T00:00:00")
        if end_date:
            invoice_query = invoice_query.lte('created_at', f"{end_date}T23:59:59")
        
        invoices_response = invoice_query.order('created_at', desc=False).execute()
        invoices = invoices_response.data if invoices_response.data else []
        
        # Get all payments for this student
        payment_query = supabase.table('payments')\
            .select('*, invoices(invoice_number)')\
            .eq('student_id', student_id)\
            .eq('institute_id', institute['id'])
        
        if start_date:
            payment_query = payment_query.gte('payment_date', start_date)
        if end_date:
            payment_query = payment_query.lte('payment_date', end_date)
        
        payments_response = payment_query.order('payment_date', desc=False).order('created_at', desc=False).execute()
        payments = payments_response.data if payments_response.data else []
        
        # Get all discounts
        discounts_response = supabase.table('discounts')\
            .select('*')\
            .eq('student_id', student_id)\
            .eq('institute_id', institute['id'])\
            .execute()
        
        discounts = discounts_response.data if discounts_response.data else []
        
        # Build transactions list
        transactions = []
        
        # Add invoices as transactions
        for invoice in invoices:
            timestamp = invoice['created_at']
            date_only = timestamp[:10]
            
            if invoice['total_amount'] < 0:
                transactions.append({
                    'timestamp': timestamp,
                    'date': date_only,
                    'type': 'credit_invoice',
                    'description': f"Credit Note {invoice['invoice_number']} - Overpayment Credit",
                    'debit': 0,
                    'credit': abs(invoice['total_amount']),
                    'reference': invoice['invoice_number']
                })
            else:
                status_text = invoice['status'].upper()
                if invoice['balance'] == 0:
                    status_text = "PAID"
                elif invoice['balance'] < invoice['total_amount']:
                    status_text = "PARTIAL"
                
                transactions.append({
                    'timestamp': timestamp,
                    'date': date_only,
                    'type': 'invoice',
                    'description': f"Invoice {invoice['invoice_number']} - {status_text}",
                    'debit': invoice['total_amount'],
                    'credit': 0,
                    'reference': invoice['invoice_number']
                })
        
        # Add payments as credit transactions
        for payment in payments:
            timestamp = f"{payment['payment_date']}T{payment['created_at'][11:]}"
            date_only = payment['payment_date']
            
            invoice_ref = payment.get('invoices', {}).get('invoice_number', 'N/A') if payment.get('invoices') else 'N/A'
            transactions.append({
                'timestamp': timestamp,
                'date': date_only,
                'type': 'payment',
                'description': f"Payment - {payment['receipt_number']} ({payment['payment_method'].upper()})",
                'debit': 0,
                'credit': payment['amount'],
                'reference': payment['receipt_number'],
                'invoice_ref': invoice_ref
            })
        
        # Add discounts as credit transactions
        for discount in discounts:
            if discount.get('discount_amount', 0) > 0:
                timestamp = discount.get('created_at', datetime.now().isoformat())
                date_only = timestamp[:10]
                
                if start_date and date_only < start_date:
                    continue
                if end_date and date_only > end_date:
                    continue
                    
                transactions.append({
                    'timestamp': timestamp,
                    'date': date_only,
                    'type': 'discount',
                    'description': f"Discount - {discount['discount_type'].upper()} {discount['discount_value']}{'%' if discount['discount_type'] == 'percentage' else ' UGX'}",
                    'debit': 0,
                    'credit': discount['discount_amount'],
                    'reference': discount.get('reason', 'N/A')
                })
        
        # Sort transactions by timestamp
        transactions.sort(key=lambda x: x['timestamp'])
        
        # Calculate running balance
        running_balance = 0
        statement_entries = []
        
        for trans in transactions:
            if trans['debit'] > 0:
                running_balance += trans['debit']
            if trans['credit'] > 0:
                running_balance -= trans['credit']
            
            statement_entries.append({
                'date': trans['date'],
                'description': trans['description'],
                'debit': trans['debit'],
                'credit': trans['credit'],
                'balance': running_balance,
                'type': trans['type']
            })
        
        # Calculate summary
        total_debits = sum(inv['total_amount'] for inv in invoices if inv['total_amount'] > 0)
        total_credits = sum(p['amount'] for p in payments) + sum(d.get('discount_amount', 0) for d in discounts)
        total_credits += sum(abs(inv['total_amount']) for inv in invoices if inv['total_amount'] < 0)
        
        current_balance = running_balance
        
        return jsonify({
            'success': True,
            'student': {
                'id': student['id'],
                'name': student['name'],
                'student_id': student['student_id'],
                'class': student['classes']['name'] if student.get('classes') else 'N/A',
                'contact': student.get('contact_number', 'N/A'),
                'photo_url': student.get('photo_url'),
                'gender': student.get('gender'),
                'date_of_birth': student.get('date_of_birth'),
                'address': student.get('address'),
                'father_name': student.get('father_name'),
                'mother_name': student.get('mother_name'),
                'category': student.get('category'),
                'status': student.get('status')
            },
            'statement': statement_entries,
            'summary': {
                'total_debits': total_debits,
                'total_credits': total_credits,
                'current_balance': current_balance
            },
            'date_range': {
                'start_date': start_date,
                'end_date': end_date
            }
        })
        
    except Exception as e:
        print(f"Error getting statement: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@student_detail_bp.route('/api/student-basic-info/<student_id>', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def api_get_student_basic_info(student_id):
    """API to get basic student info for quick view"""
    institute = get_institute_from_session()
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        response = supabase.table('students')\
            .select('id, name, student_id, email, contact_number, photo_url, status, class_id, classes(name)')\
            .eq('id', student_id)\
            .eq('institute_id', institute['id'])\
            .execute()
        
        if not response.data:
            return jsonify({'success': False, 'message': 'Student not found'}), 404
        
        student = response.data[0]
        
        # Get current balance
        invoices_response = supabase.table('invoices')\
            .select('balance')\
            .eq('student_id', student_id)\
            .eq('institute_id', institute['id'])\
            .execute()
        
        total_balance = 0
        if invoices_response.data:
            total_balance = sum(inv.get('balance', 0) for inv in invoices_response.data)
        
        student['current_balance'] = total_balance
        
        return jsonify({'success': True, 'student': student})
        
    except Exception as e:
        print(f"Error fetching student info: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500