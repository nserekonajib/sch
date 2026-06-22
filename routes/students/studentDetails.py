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
    """API to get student statement with date filtering and carry-forward balance"""
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
        
        # ---------- GET ALL INVOICES (for carry-forward calculation) ----------
        all_invoices_query = supabase.table('invoices')\
            .select('*')\
            .eq('student_id', student_id)\
            .eq('institute_id', institute['id'])
        
        all_invoices_response = all_invoices_query.execute()
        all_invoices = all_invoices_response.data if all_invoices_response.data else []
        
        # ---------- GET ALL PAYMENTS (for carry-forward calculation) ----------
        all_payments_query = supabase.table('payments')\
            .select('*')\
            .eq('student_id', student_id)\
            .eq('institute_id', institute['id'])
        
        all_payments_response = all_payments_query.execute()
        all_payments = all_payments_response.data if all_payments_response.data else []
        
        # ---------- GET ALL DISCOUNTS ----------
        all_discounts_response = supabase.table('discounts')\
            .select('*')\
            .eq('student_id', student_id)\
            .eq('institute_id', institute['id'])\
            .execute()
        
        all_discounts = all_discounts_response.data if all_discounts_response.data else []
        
        # ---------- CALCULATE CARRY-FORWARD BALANCE (BEFORE START DATE) ----------
        carry_forward_balance = 0
        
        if start_date:
            # Get all transactions BEFORE the start date
            # Process invoices before start date
            for inv in all_invoices:
                inv_date = inv.get('created_at', '').split('T')[0] if inv.get('created_at') else ''
                if inv_date < start_date:
                    # Add invoice amount to carry-forward
                    if inv['total_amount'] > 0:
                        carry_forward_balance += inv['total_amount']
                    elif inv['total_amount'] < 0:
                        # Credit note reduces balance
                        carry_forward_balance += inv['total_amount']  # negative amount
            
            # Process payments before start date
            for pay in all_payments:
                pay_date = pay.get('payment_date', '')
                if pay_date < start_date:
                    carry_forward_balance -= pay['amount']
            
            # Process discounts before start date
            for disc in all_discounts:
                disc_date = disc.get('created_at', '').split('T')[0] if disc.get('created_at') else ''
                if disc_date < start_date:
                    carry_forward_balance -= disc.get('discount_amount', 0)
        
        # ---------- GET TRANSACTIONS IN FILTERED DATE RANGE ----------
        transactions = []
        
        # Add invoices in date range
        for invoice in all_invoices:
            timestamp = invoice['created_at']
            date_only = timestamp[:10]
            
            # Skip if outside date range
            if start_date and date_only < start_date:
                continue
            if end_date and date_only > end_date:
                continue
            
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
        
        # Add payments in date range
        for payment in all_payments:
            date_only = payment['payment_date']
            
            if start_date and date_only < start_date:
                continue
            if end_date and date_only > end_date:
                continue
            
            timestamp = f"{payment['payment_date']}T{payment['created_at'][11:]}"
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
        
        # Add discounts in date range
        for discount in all_discounts:
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
        
        # Calculate running balance with carry-forward
        running_balance = carry_forward_balance
        statement_entries = []
        
        # Add carry-forward row if there's a balance before the start date
        if start_date and carry_forward_balance != 0:
            statement_entries.append({
                'date': f'Before {start_date}',
                'description': 'Balance Brought Forward',
                'debit': 0,
                'credit': 0,
                'balance': carry_forward_balance,
                'type': 'carry_forward',
                'is_carry_forward': True
            })
        
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
                'type': trans['type'],
                'is_carry_forward': False
            })
        
        # Calculate summary for the filtered period
        total_debits = sum(t['debit'] for t in statement_entries if not t.get('is_carry_forward'))
        total_credits = sum(t['credit'] for t in statement_entries if not t.get('is_carry_forward'))
        current_balance = running_balance
        
        # Overall balance (all-time)
        overall_invoiced = sum(inv['total_amount'] for inv in all_invoices if inv['total_amount'] > 0)
        overall_paid = sum(p['amount'] for p in all_payments)
        overall_discount = sum(d.get('discount_amount', 0) for d in all_discounts)
        overall_balance = overall_invoiced - overall_paid - overall_discount
        
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
                'current_balance': current_balance,
                'carry_forward_balance': carry_forward_balance,
                'overall_balance': overall_balance,
                'overall_invoiced': overall_invoiced,
                'overall_paid': overall_paid,
                'overall_discount': overall_discount
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
    
@student_detail_bp.route('/api/export-statement/<student_id>', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def api_export_statement(student_id):
    """Export student statement to Excel or PDF"""
    institute = get_institute_from_session()
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        format_type = request.args.get('format', 'excel')  # excel or pdf
        
        # Get student details
        student_response = supabase.table('students')\
            .select('*, classes(name)')\
            .eq('id', student_id)\
            .eq('institute_id', institute['id'])\
            .execute()
        
        if not student_response.data:
            return jsonify({'success': False, 'message': 'Student not found'}), 404
        
        student = student_response.data[0]
        
        # Get ALL invoices
        all_invoices_query = supabase.table('invoices')\
            .select('*')\
            .eq('student_id', student_id)\
            .eq('institute_id', institute['id'])
        
        all_invoices_response = all_invoices_query.execute()
        all_invoices = all_invoices_response.data if all_invoices_response.data else []
        
        # Get ALL payments
        all_payments_query = supabase.table('payments')\
            .select('*')\
            .eq('student_id', student_id)\
            .eq('institute_id', institute['id'])
        
        all_payments_response = all_payments_query.execute()
        all_payments = all_payments_response.data if all_payments_response.data else []
        
        # Get ALL discounts
        all_discounts_response = supabase.table('discounts')\
            .select('*')\
            .eq('student_id', student_id)\
            .eq('institute_id', institute['id'])\
            .execute()
        
        all_discounts = all_discounts_response.data if all_discounts_response.data else []
        
        # Calculate carry-forward balance
        carry_forward_balance = 0
        
        if start_date:
            for inv in all_invoices:
                inv_date = inv.get('created_at', '').split('T')[0] if inv.get('created_at') else ''
                if inv_date < start_date:
                    if inv['total_amount'] > 0:
                        carry_forward_balance += inv['total_amount']
                    elif inv['total_amount'] < 0:
                        carry_forward_balance += inv['total_amount']
            
            for pay in all_payments:
                pay_date = pay.get('payment_date', '')
                if pay_date < start_date:
                    carry_forward_balance -= pay['amount']
            
            for disc in all_discounts:
                disc_date = disc.get('created_at', '').split('T')[0] if disc.get('created_at') else ''
                if disc_date < start_date:
                    carry_forward_balance -= disc.get('discount_amount', 0)
        
        # Build transactions for the period
        transactions = []
        
        # Add invoices in date range
        for invoice in all_invoices:
            timestamp = invoice['created_at']
            date_only = timestamp[:10]
            
            if start_date and date_only < start_date:
                continue
            if end_date and date_only > end_date:
                continue
            
            if invoice['total_amount'] < 0:
                transactions.append({
                    'Date': date_only,
                    'Description': f"Credit Note {invoice['invoice_number']} - Overpayment Credit",
                    'Debit (UGX)': 0,
                    'Credit (UGX)': abs(invoice['total_amount']),
                    'Reference': invoice['invoice_number']
                })
            else:
                status_text = invoice['status'].upper()
                if invoice['balance'] == 0:
                    status_text = "PAID"
                elif invoice['balance'] < invoice['total_amount']:
                    status_text = "PARTIAL"
                
                transactions.append({
                    'Date': date_only,
                    'Description': f"Invoice {invoice['invoice_number']} - {status_text}",
                    'Debit (UGX)': invoice['total_amount'],
                    'Credit (UGX)': 0,
                    'Reference': invoice['invoice_number']
                })
        
        # Add payments in date range
        for payment in all_payments:
            date_only = payment['payment_date']
            
            if start_date and date_only < start_date:
                continue
            if end_date and date_only > end_date:
                continue
            
            transactions.append({
                'Date': date_only,
                'Description': f"Payment - {payment['receipt_number']} ({payment['payment_method'].upper()})",
                'Debit (UGX)': 0,
                'Credit (UGX)': payment['amount'],
                'Reference': payment['receipt_number']
            })
        
        # Add discounts in date range
        for discount in all_discounts:
            if discount.get('discount_amount', 0) > 0:
                timestamp = discount.get('created_at', datetime.now().isoformat())
                date_only = timestamp[:10]
                
                if start_date and date_only < start_date:
                    continue
                if end_date and date_only > end_date:
                    continue
                    
                transactions.append({
                    'Date': date_only,
                    'Description': f"Discount - {discount['discount_type'].upper()} {discount['discount_value']}{'%' if discount['discount_type'] == 'percentage' else ' UGX'}",
                    'Debit (UGX)': 0,
                    'Credit (UGX)': discount['discount_amount'],
                    'Reference': discount.get('reason', 'N/A')
                })
        
        # Sort transactions by date
        transactions.sort(key=lambda x: x['Date'])
        
        # Calculate running balance
        running_balance = carry_forward_balance
        for trans in transactions:
            running_balance += trans['Debit (UGX)'] - trans['Credit (UGX)']
            trans['Balance (UGX)'] = running_balance
        
        # Calculate totals
        total_debits = sum(t['Debit (UGX)'] for t in transactions)
        total_credits = sum(t['Credit (UGX)'] for t in transactions)
        final_balance = running_balance
        
        # Get institute name
        institute_name = institute.get('institute_name', 'School')
        
        # Get current date for filename
        current_date = datetime.now().strftime('%Y%m%d')
        filename_base = f"student_statement_{student['student_id']}_{current_date}"
        
        if format_type == 'pdf':
            # PDF export using reportlab with BytesIO
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4, landscape
            from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import inch, mm
            from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
            
            # Create BytesIO object for PDF
            pdf_buffer = io.BytesIO()
            
            doc = SimpleDocTemplate(pdf_buffer, pagesize=A4, 
                                   rightMargin=72, leftMargin=72, 
                                   topMargin=72, bottomMargin=72)
            
            styles = getSampleStyleSheet()
            title_style = ParagraphStyle(
                'CustomTitle',
                parent=styles['Heading1'],
                fontSize=16,
                textColor=colors.HexColor('#ff8c00'),
                alignment=TA_CENTER,
                spaceAfter=10
            )
            
            story = []
            
            # Title
            story.append(Paragraph(f"{institute_name}", title_style))
            story.append(Paragraph(f"Student Fee Statement", styles['Heading2']))
            story.append(Spacer(1, 12))
            
            # Student Info
            info_data = [
                ['Student Name:', student['name']],
                ['Student ID:', student['student_id']],
                ['Class:', student['classes']['name'] if student.get('classes') else 'N/A'],
                ['Period:', f"{start_date or 'All Time'} to {end_date or 'All Time'}"]
            ]
            
            info_table = Table(info_data, colWidths=[100, 300])
            info_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ]))
            story.append(info_table)
            story.append(Spacer(1, 12))
            
            # Transaction Table
            table_data = [['Date', 'Description', 'Debit (UGX)', 'Credit (UGX)', 'Balance (UGX)']]
            
            # Add carry-forward row if applicable
            if start_date and carry_forward_balance != 0:
                table_data.append([
                    f'Before {start_date}',
                    'Balance Brought Forward',
                    '',
                    '',
                    f'{carry_forward_balance:,.0f}'
                ])
            
            for trans in transactions:
                table_data.append([
                    trans['Date'],
                    trans['Description'],
                    f"{trans['Debit (UGX)']:,.0f}" if trans['Debit (UGX)'] > 0 else '',
                    f"{trans['Credit (UGX)']:,.0f}" if trans['Credit (UGX)'] > 0 else '',
                    f"{trans['Balance (UGX)']:,.0f}"
                ])
            
            # Add totals row
            table_data.append([
                '',
                'TOTALS',
                f"{total_debits:,.0f}",
                f"{total_credits:,.0f}",
                f"{final_balance:,.0f}"
            ])
            
            table = Table(table_data, colWidths=[80, 220, 80, 80, 80])
            table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#ffa500')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (0, -1), 'LEFT'),
                ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#f0f0f0')),
                ('FONTWEIGHT', (0, -1), (-1, -1), 'BOLD'),
            ]))
            
            story.append(table)
            story.append(Spacer(1, 12))
            
            # Summary
            summary_style = ParagraphStyle(
                'Summary',
                parent=styles['Normal'],
                fontSize=10,
                spaceAfter=6
            )
            
            summary_text = f"""
            <b>Summary:</b><br/>
            Total Debits: UGX {total_debits:,.0f}<br/>
            Total Credits: UGX {total_credits:,.0f}<br/>
            <b>Balance: UGX {final_balance:,.0f}</b><br/>
            Carry Forward: UGX {carry_forward_balance:,.0f}
            """
            story.append(Paragraph(summary_text, summary_style))
            
            # Build PDF
            doc.build(story)
            
            # Get PDF data from buffer
            pdf_buffer.seek(0)
            
            # Return PDF as download
            return send_file(
                pdf_buffer,
                as_attachment=True,
                download_name=f"{filename_base}.pdf",
                mimetype='application/pdf'
            )
            
        else:
            # Excel export
            import pandas as pd
            
            # Create DataFrame
            df_data = []
            
            # Add carry-forward row
            if start_date and carry_forward_balance != 0:
                df_data.append({
                    'Date': f'Before {start_date}',
                    'Description': 'Balance Brought Forward',
                    'Debit (UGX)': 0,
                    'Credit (UGX)': 0,
                    'Balance (UGX)': carry_forward_balance
                })
            
            for trans in transactions:
                df_data.append(trans)
            
            df = pd.DataFrame(df_data)
            
            output = io.BytesIO()
            
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                # Write main statement
                df.to_excel(writer, sheet_name='Statement', index=False)
                
                # Get workbook and worksheet
                workbook = writer.book
                worksheet = writer.sheets['Statement']
                
                # Format currency columns
                for col in ['Debit (UGX)', 'Credit (UGX)', 'Balance (UGX)']:
                    if col in df.columns:
                        col_idx = df.columns.get_loc(col) + 1
                        for row in range(2, len(df) + 2):
                            cell = worksheet.cell(row=row, column=col_idx)
                            if cell.value:
                                cell.number_format = '#,##0.00'
                
                # Add summary sheet
                summary_data = {
                    'Student Name': [student['name']],
                    'Student ID': [student['student_id']],
                    'Class': [student['classes']['name'] if student.get('classes') else 'N/A'],
                    'Period Start': [start_date or 'All Time'],
                    'Period End': [end_date or 'All Time'],
                    'Total Debits': [total_debits],
                    'Total Credits': [total_credits],
                    'Carry Forward Balance': [carry_forward_balance],
                    'Current Balance': [final_balance]
                }
                summary_df = pd.DataFrame(summary_data)
                summary_df.to_excel(writer, sheet_name='Summary', index=False)
                
                # Auto-adjust column widths
                for sheet_name in writer.sheets:
                    worksheet = writer.sheets[sheet_name]
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
            
            return send_file(
                output,
                as_attachment=True,
                download_name=f"{filename_base}.xlsx",
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
        
    except Exception as e:
        print(f"Error exporting statement: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500