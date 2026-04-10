# collectFees.py - Simplified with negative balance only (no credit invoices)
from flask import Blueprint, render_template, request, jsonify, session, send_file
from supabase import create_client, Client
import os
import uuid
import random
import string
from datetime import datetime, timedelta
import json
import io
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, mm
from reportlab.pdfgen import canvas
from functools import wraps
from dotenv import load_dotenv

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
domain = os.getenv('domain')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

collect_bp = Blueprint('collect', __name__, url_prefix='/fee-collection')

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
            .select('*')\
            .eq('user_id', user_id)\
            .execute()
        
        if response.data and len(response.data) > 0:
            return response.data[0]
        return None
    except Exception as e:
        print(f"Error getting institute ID: {e}")
        return None

def send_payment_sms(institute, student, amount_paid, balance, receipt_number, payment_method, notes=""):
    """Send SMS notification for payment"""
    try:
        sms_response = supabase.table('sms_settings')\
            .select('*')\
            .eq('institute_id', institute['id'])\
            .eq('enabled', True)\
            .execute()
        
        if not sms_response.data:
            print("SMS not enabled or no settings found")
            return False
        
        settings = sms_response.data[0]
        
        if not settings.get('send_on_payment', True):
            print("SMS on payment is disabled")
            return False
        
        phone = student.get('contact_number', '')
        if not phone:
            print(f"No phone number for student: {student['name']}")
            return False
        
        phone = phone.strip().replace(' ', '').replace('-', '')
        if not phone.startswith('+'):
            phone = '+' + phone if phone.startswith('256') else phone
        
        # Show credit balance if negative
        balance_display = f"Credit: UGX {abs(balance):,.0f}" if balance < 0 else f"Due: UGX {balance:,.0f}"
        
        message = f"""Payment Received! 🎓

Student: {student['name']}
Amount: UGX {amount_paid:,.0f}
{balance_display}
Method: {payment_method.upper()}
Receipt: {receipt_number}

{institute.get('institute_name', 'School')}
Thank you for your payment!"""

        if notes:
            message += f"\nNote: {notes}"
        
        try:
            from comms_sdk import CommsSDK, MessagePriority
            
            sdk = CommsSDK.authenticate(
                settings['api_username'], 
                settings['api_key']
            )
            
            response = sdk.send_sms(
                [phone],
                message,
                sender_id=settings.get('sender_id', 'SCHOOL'),
                priority=MessagePriority.HIGHEST
            )
            
            print(f"SMS sent successfully to {phone}")
            return True
            
        except ImportError:
            print("CommsSDK not installed")
            return False
        except Exception as e:
            print(f"SMS sending error: {e}")
            return False
            
    except Exception as e:
        print(f"Error in send_payment_sms: {e}")
        return False
    
@collect_bp.route('/')
@login_required
def index():
    """Fee Collection Page"""
    user = session.get('user')
    institute = get_institute_id(user['id'])
    
    if not institute:
        return render_template('fees/collection.html', institute=None, now=datetime.now())
    
    return render_template('fees/collection.html', institute=institute, now=datetime.now())

@collect_bp.route('/search-student', methods=['POST'])
@login_required
def search_student():
    """Search for student by name or ID"""
    user = session.get('user')
    institute = get_institute_id(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        search_term = data.get('search_term', '').strip()
        
        if not search_term:
            return jsonify({'success': False, 'message': 'Please enter search term'}), 400
        
        response = supabase.table('students')\
            .select('*, classes(name)')\
            .eq('institute_id', institute['id'])\
            .eq('status', 'active')\
            .ilike('name', f'%{search_term}%')\
            .execute()
        
        if not response.data:
            response = supabase.table('students')\
                .select('*, classes(name)')\
                .eq('institute_id', institute['id'])\
                .eq('status', 'active')\
                .ilike('student_id', f'%{search_term}%')\
                .execute()
        
        students = response.data if response.data else []
        
        return jsonify({'success': True, 'students': students})
        
    except Exception as e:
        print(f"Error searching student: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@collect_bp.route('/get-student-fees/<student_id>', methods=['GET'])
@login_required
def get_student_fees(student_id):
    """Get fee details and invoices for a student"""
    user = session.get('user')
    institute = get_institute_id(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Get student details
        student_response = supabase.table('students')\
            .select('*, classes(name)')\
            .eq('id', student_id)\
            .eq('institute_id', institute['id'])\
            .execute()
        
        if not student_response.data:
            return jsonify({'success': False, 'message': 'Student not found'}), 404
        
        student = student_response.data[0]
        
        # Get all invoices for this student (only invoices with balance != 0 or recent)
        invoices_response = supabase.table('invoices')\
            .select('*, fee_particulars(fee_items)')\
            .eq('student_id', student_id)\
            .eq('institute_id', institute['id'])\
            .neq('balance', 0)\
            .order('created_at', desc=True)\
            .execute()
        
        invoices = invoices_response.data if invoices_response.data else []
        
        # Calculate total due (sum of all balances - negative means credit)
        total_due = sum(inv['balance'] for inv in invoices)
        
        # Prepare invoices for display
        invoice_list = []
        for inv in invoices:
            invoice_list.append({
                'id': inv['id'],
                'invoice_number': inv['invoice_number'],
                'total_amount': float(inv['total_amount']),
                'paid_amount': float(inv['paid_amount']),
                'balance': float(inv['balance']),
                'status': inv['status'],
                'due_date': inv['due_date'],
                'created_at': inv['created_at'],
                'discount_applied': float(inv.get('discount_applied', 0))
            })
        
        return jsonify({
            'success': True,
            'student': {
                'id': student['id'],
                'name': student['name'],
                'student_id': student['student_id'],
                'class': student['classes']['name'] if student.get('classes') else 'N/A',
                'contact': student.get('contact_number', 'N/A')
            },
            'invoices': invoice_list,
            'total_due': total_due
        })
        
    except Exception as e:
        print(f"Error getting student fees: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
# Update the process_payment function in collectFees.py

@collect_bp.route('/process-payment', methods=['POST'])
@login_required
def process_payment():
    """Process fee payment - balance becomes negative if payment exceeds due"""
    user = session.get('user')
    institute = get_institute_id(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        student_id = data.get('student_id')
        invoice_id = data.get('invoice_id')
        amount_paid = float(data.get('amount', 0))
        payment_method = data.get('payment_method', 'cash')
        fee_month = data.get('fee_month')
        notes = data.get('notes', '')
        
        if not student_id or amount_paid <= 0:
            return jsonify({'success': False, 'message': 'Invalid payment amount'}), 400
        
        # Handle fee_month - convert from YYYY-MM to first day of month for date field
        if fee_month:
            # If fee_month is in YYYY-MM format, convert to first day of month
            if len(fee_month) == 7 and '-' in fee_month:
                fee_month_date = f"{fee_month}-01"
            else:
                fee_month_date = fee_month
        else:
            fee_month_date = datetime.now().date().isoformat()
        
        # Get student details
        student_response = supabase.table('students')\
            .select('*, classes(name)')\
            .eq('id', student_id)\
            .eq('institute_id', institute['id'])\
            .execute()
        
        if not student_response.data:
            return jsonify({'success': False, 'message': 'Student not found'}), 404
        
        student = student_response.data[0]
        
        # Get all existing receipt numbers
        existing_receipts_response = supabase.table('payments')\
            .select('receipt_number')\
            .eq('institute_id', institute['id'])\
            .execute()
        
        existing_numbers = set()
        if existing_receipts_response.data:
            for receipt in existing_receipts_response.data:
                existing_numbers.add(receipt['receipt_number'])
        
        payments_made = []
        remaining_amount = amount_paid
        
        if invoice_id:
            # Pay specific invoice - allow negative balance
            invoice_response = supabase.table('invoices')\
                .select('*')\
                .eq('id', invoice_id)\
                .eq('student_id', student_id)\
                .eq('institute_id', institute['id'])\
                .execute()
            
            if not invoice_response.data:
                return jsonify({'success': False, 'message': 'Invoice not found'}), 404
            
            invoice = invoice_response.data[0]
            
            # Apply payment - balance can go negative
            new_paid = invoice['paid_amount'] + remaining_amount
            new_balance = invoice['total_amount'] - new_paid
            
            # Determine status
            if new_balance == 0:
                new_status = 'paid'
            elif new_balance < 0:
                new_status = 'credit'
            elif new_paid > 0:
                new_status = 'partial'
            else:
                new_status = 'pending'
            
            supabase.table('invoices')\
                .update({
                    'paid_amount': new_paid,
                    'balance': new_balance,
                    'status': new_status,
                    'updated_at': datetime.now().isoformat()
                })\
                .eq('id', invoice_id)\
                .eq('institute_id', institute['id'])\
                .execute()
            
            payments_made.append({
                'invoice_id': invoice['id'],
                'invoice_number': invoice['invoice_number'],
                'amount': remaining_amount,
                'new_balance': new_balance
            })
            
            remaining_amount = 0
            
        else:
            # General payment - distribute to oldest invoices with balance > 0 first
            invoices_response = supabase.table('invoices')\
                .select('*')\
                .eq('student_id', student_id)\
                .eq('institute_id', institute['id'])\
                .gt('balance', 0)\
                .order('created_at', desc=False)\
                .execute()
            
            invoices = invoices_response.data if invoices_response.data else []
            
            for invoice in invoices:
                if remaining_amount <= 0:
                    break
                
                payment_for_invoice = min(remaining_amount, invoice['balance'])
                
                if payment_for_invoice > 0:
                    new_paid = invoice['paid_amount'] + payment_for_invoice
                    new_balance = invoice['total_amount'] - new_paid
                    new_status = 'paid' if new_balance == 0 else 'partial'
                    
                    supabase.table('invoices')\
                        .update({
                            'paid_amount': new_paid,
                            'balance': new_balance,
                            'status': new_status,
                            'updated_at': datetime.now().isoformat()
                        })\
                        .eq('id', invoice['id'])\
                        .eq('institute_id', institute['id'])\
                        .execute()
                    
                    payments_made.append({
                        'invoice_id': invoice['id'],
                        'invoice_number': invoice['invoice_number'],
                        'amount': payment_for_invoice,
                        'new_balance': new_balance
                    })
                    
                    remaining_amount -= payment_for_invoice
            
            # If there's remaining amount, find the most recent invoice to apply negative balance
            if remaining_amount > 0:
                # Get the most recent invoice (could be any, we'll apply negative to the newest)
                recent_invoice_response = supabase.table('invoices')\
                    .select('*')\
                    .eq('student_id', student_id)\
                    .eq('institute_id', institute['id'])\
                    .order('created_at', desc=True)\
                    .limit(1)\
                    .execute()
                
                if recent_invoice_response.data:
                    invoice = recent_invoice_response.data[0]
                    new_paid = invoice['paid_amount'] + remaining_amount
                    new_balance = invoice['total_amount'] - new_paid
                    new_status = 'credit' if new_balance < 0 else invoice['status']
                    
                    supabase.table('invoices')\
                        .update({
                            'paid_amount': new_paid,
                            'balance': new_balance,
                            'status': new_status,
                            'updated_at': datetime.now().isoformat()
                        })\
                        .eq('id', invoice['id'])\
                        .eq('institute_id', institute['id'])\
                        .execute()
                    
                    payments_made.append({
                        'invoice_id': invoice['id'],
                        'invoice_number': invoice['invoice_number'],
                        'amount': remaining_amount,
                        'new_balance': new_balance,
                        'note': 'Overpayment - Credit balance'
                    })
                else:
                    # No invoices exist, create a new invoice with negative balance
                    new_invoice_id = str(uuid.uuid4())
                    new_invoice_number = f"CREDIT-{datetime.now().strftime('%Y%m%d%H%M%S')}"
                    
                    invoice_data = {
                        'id': new_invoice_id,
                        'institute_id': institute['id'],
                        'student_id': student_id,
                        'invoice_number': new_invoice_number,
                        'total_amount': -remaining_amount,
                        'paid_amount': remaining_amount,
                        'balance': -remaining_amount,
                        'status': 'credit',
                        'due_date': (datetime.now() + timedelta(days=365)).date().isoformat(),
                        'created_at': datetime.now().isoformat(),
                        'updated_at': datetime.now().isoformat()
                    }
                    
                    supabase.table('invoices').insert(invoice_data).execute()
                    
                    payments_made.append({
                        'invoice_number': new_invoice_number,
                        'amount': remaining_amount,
                        'new_balance': -remaining_amount,
                        'note': 'Credit balance from overpayment'
                    })
        
        # Generate unique receipt number
        receipt_number = generate_unique_receipt_number(institute['id'], existing_numbers)
        
        # Create payment record
        payment_id = str(uuid.uuid4())
        payment_data = {
            'id': payment_id,
            'institute_id': institute['id'],
            'student_id': student_id,
            'invoice_id': invoice_id,
            'amount': amount_paid,
            'payment_method': payment_method,
            'receipt_number': receipt_number,
            'payment_date': datetime.now().date().isoformat(),
            'fee_month': fee_month_date,  # Use the converted date
            'notes': notes,
            'created_at': datetime.now().isoformat()
        }
        
        supabase.table('payments').insert(payment_data).execute()
        
        # Get updated totals
        updated_invoices = supabase.table('invoices')\
            .select('*')\
            .eq('student_id', student_id)\
            .eq('institute_id', institute['id'])\
            .execute()
        
        total_due = sum(inv['balance'] for inv in updated_invoices.data)
        
        # Send SMS notification
        try:
            send_payment_sms(
                institute=institute,
                student=student,
                amount_paid=amount_paid,
                balance=total_due,
                receipt_number=receipt_number,
                payment_method=payment_method,
                notes=notes
            )
        except Exception as e:
            print(f"SMS notification error (non-critical): {e}")
            
        return jsonify({
            'success': True,
            'message': f'Payment of UGX {amount_paid:,.0f} processed successfully',
            'receipt_number': receipt_number,
            'amount_paid': amount_paid,
            'total_due': total_due,
            'payment_method': payment_method,
            'notes': notes,
            'student_name': student['name'],
            'student_id': student['student_id'],
            'class': student['classes']['name'] if student.get('classes') else 'N/A',
            'payments_made': payments_made,
            'institute': institute
        })
        
    except Exception as e:
        print(f"Error processing payment: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    
    
@collect_bp.route('/apply-discount', methods=['POST'])
@login_required
def apply_discount():
    """Apply discount to an invoice"""
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
            .select('*')\
            .eq('id', invoice_id)\
            .eq('institute_id', institute['id'])\
            .execute()
        
        if not invoice_response.data:
            return jsonify({'success': False, 'message': 'Invoice not found'}), 404
        
        invoice = invoice_response.data[0]
        
        # Calculate discount amount based on current balance
        if discount_type == 'percentage':
            discount_amount = (discount_value / 100) * invoice['balance']
        else:
            discount_amount = min(discount_value, abs(invoice['balance']))
        
        # Apply discount to invoice - only update balance, not discount_applied
        new_balance = invoice['balance'] - discount_amount
        
        # Update status
        if new_balance == 0:
            new_status = 'paid'
        elif new_balance < 0:
            new_status = 'credit'
        else:
            new_status = 'partial' if invoice['paid_amount'] > 0 else 'pending'
        
        # Update invoice - remove discount_applied from update
        supabase.table('invoices')\
            .update({
                'balance': new_balance,
                'status': new_status,
                'updated_at': datetime.now().isoformat()
            })\
            .eq('id', invoice_id)\
            .eq('institute_id', institute['id'])\
            .execute()
        
        # Get student details
        student_response = supabase.table('students')\
            .select('name, student_id')\
            .eq('id', invoice['student_id'])\
            .execute()
        
        student_name = student_response.data[0]['name'] if student_response.data else 'Unknown'
        
        # Create discount record for tracking
        discount_id = str(uuid.uuid4())
        discount_data = {
            'id': discount_id,
            'institute_id': institute['id'],
            'student_id': invoice['student_id'],
            'student_name': student_name,
            'invoice_id': invoice_id,
            'discount_type': discount_type,
            'discount_value': discount_value,
            'discount_amount': discount_amount,
            'reason': reason,
            'apply_to': 'invoice',
            'is_active': True,
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        supabase.table('discounts').insert(discount_data).execute()
        
        return jsonify({
            'success': True,
            'message': f'Discount of UGX {discount_amount:,.0f} applied successfully',
            'new_balance': new_balance,
            'discount_amount': discount_amount,
            'invoice_balance': new_balance
        })
        
    except Exception as e:
        print(f"Error applying discount: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@collect_bp.route('/receipt/<receipt_number>', methods=['GET'])
@login_required
def get_receipt(receipt_number):
    """Get receipt details for printing"""
    user = session.get('user')
    institute = get_institute_id(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        payment_response = supabase.table('payments')\
            .select('*, students(name, student_id, classes(name))')\
            .eq('receipt_number', receipt_number)\
            .eq('institute_id', institute['id'])\
            .execute()
        
        if not payment_response.data:
            return jsonify({'success': False, 'message': 'Receipt not found'}), 404
        
        payment = payment_response.data[0]
        
        return jsonify({
            'success': True,
            'receipt': {
                'receipt_number': payment['receipt_number'],
                'date': payment['payment_date'],
                'student_name': payment['students']['name'],
                'student_id': payment['students']['student_id'],
                'class': payment['students']['classes']['name'] if payment['students'].get('classes') else 'N/A',
                'amount': payment['amount'],
                'payment_method': payment['payment_method'],
                'fee_month': payment.get('fee_month', 'N/A'),
                'notes': payment.get('notes', ''),
                'institute': institute
            }
        })
        
    except Exception as e:
        print(f"Error getting receipt: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@collect_bp.route('/print-receipt/<receipt_number>', methods=['GET'])
@login_required
def print_receipt(receipt_number):
    """Generate thermal receipt PDF for printing"""
    user = session.get('user')
    institute = get_institute_id(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        payment_response = supabase.table('payments')\
            .select('*, students(name, student_id, classes(name))')\
            .eq('receipt_number', receipt_number)\
            .eq('institute_id', institute['id'])\
            .execute()
        
        if not payment_response.data:
            return jsonify({'success': False, 'message': 'Receipt not found'}), 404
        
        payment = payment_response.data[0]
        
        # Get current balance including credits
        invoices_response = supabase.table('invoices')\
            .select('balance')\
            .eq('student_id', payment['student_id'])\
            .eq('institute_id', institute['id'])\
            .execute()
        
        current_balance = sum(inv['balance'] for inv in invoices_response.data) if invoices_response.data else 0
        
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=(80*mm, 180*mm),
                                rightMargin=5*mm, leftMargin=5*mm,
                                topMargin=5*mm, bottomMargin=5*mm)
        
        story = []
        styles = getSampleStyleSheet()
        
        title_style = ParagraphStyle(
            'Title',
            parent=styles['Normal'],
            fontSize=12,
            alignment=1,
            spaceAfter=5,
            fontName='Helvetica-Bold'
        )
        
        normal_style = ParagraphStyle(
            'Normal',
            parent=styles['Normal'],
            fontSize=9,
            alignment=0,
            spaceAfter=3
        )
        
        center_style = ParagraphStyle(
            'Center',
            parent=styles['Normal'],
            fontSize=9,
            alignment=1,
            spaceAfter=3
        )
        
        # Institute Header
        story.append(Paragraph(institute.get('institute_name', 'School Name'), title_style))
        story.append(Paragraph(institute.get('target_line', ''), center_style))
        story.append(Paragraph(institute.get('address', ''), center_style))
        story.append(Paragraph(f"Tel: {institute.get('phone_number', '')}", center_style))
        story.append(Spacer(1, 5))
        
        # Receipt Title
        story.append(Paragraph("=" * 35, normal_style))
        story.append(Paragraph("FEE PAYMENT RECEIPT", title_style))
        story.append(Paragraph("=" * 35, normal_style))
        story.append(Spacer(1, 5))
        
        # Receipt Details
        receipt_data = [
            ['Receipt No:', payment['receipt_number']],
            ['Date:', payment['payment_date']],
            ['', ''],
            ['Student Name:', payment['students']['name']],
            ['Student ID:', payment['students']['student_id']],
            ['Class:', payment['students']['classes']['name'] if payment['students'].get('classes') else 'N/A'],
            ['Fee Month:', payment.get('fee_month', 'N/A')],
        ]
        
        t = Table(receipt_data, colWidths=[30*mm, 40*mm])
        t.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        story.append(t)
        story.append(Spacer(1, 5))
        
        # Amount
        story.append(Paragraph("-" * 35, normal_style))
        
        balance_text = f"Credit: UGX {abs(current_balance):,.0f}" if current_balance < 0 else f"Balance Due: UGX {current_balance:,.0f}"
        
        amount_data = [
            ['Amount Paid:', f"UGX {payment['amount']:,.0f}"],
            ['Payment Method:', payment['payment_method'].upper()],
            [balance_text, '']
        ]
        
        t2 = Table(amount_data, colWidths=[30*mm, 40*mm])
        t2.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        story.append(t2)
        
        # Notes
        if payment.get('notes'):
            story.append(Spacer(1, 5))
            story.append(Paragraph(f"Notes: {payment['notes']}", normal_style))
        
        story.append(Paragraph("-" * 35, normal_style))
        
        # Footer
        story.append(Spacer(1, 8))
        story.append(Paragraph("Thank you for your payment!", center_style))
        story.append(Paragraph("This is a computer generated receipt", center_style))
        story.append(Paragraph("No signature required", center_style))
        
        doc.build(story)
        buffer.seek(0)
        
        return send_file(
            buffer,
            as_attachment=False,
            download_name=f"receipt_{receipt_number}.pdf",
            mimetype='application/pdf'
        )
        
    except Exception as e:
        print(f"Error generating receipt: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

def generate_unique_receipt_number(institute_id, existing_numbers):
    """Generate unique receipt number with retry logic"""
    max_attempts = 10
    attempts = 0
    
    while attempts < max_attempts:
        try:
            year = datetime.now().strftime('%Y')
            month = datetime.now().strftime('%m')
            
            random_component = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
            
            response = supabase.table('payments')\
                .select('id', count='exact')\
                .eq('institute_id', institute_id)\
                .gte('created_at', f"{year}-{month}-01")\
                .execute()
            
            count = (response.count or 0) + 1
            receipt_number = f"RCP-{year}{month}-{random_component}-{str(count).zfill(3)}"
            
            if receipt_number not in existing_numbers:
                return receipt_number
                
        except Exception as e:
            print(f"Error generating receipt number (attempt {attempts + 1}): {e}")
        
        attempts += 1
        import time
        time.sleep(0.1)
    
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S%f')
    fallback_number = f"RCP-{timestamp}"
    
    if fallback_number in existing_numbers:
        fallback_number = f"RCP-{timestamp}-{random.randint(1000, 9999)}"
    
    return fallback_number

def generate_receipt_number(institute_id):
    """Legacy function - kept for compatibility"""
    return generate_unique_receipt_number(institute_id, set())