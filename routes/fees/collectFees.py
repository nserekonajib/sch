# collectFees.py - Updated with WhatsApp PDF receipt sending and CORRECT balance calculation
from flask import Blueprint, render_template, request, jsonify, session, send_file
from supabase import create_client, Client
import os
import uuid
import random
import string
from datetime import datetime, timedelta
import json
import io
import requests
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, mm
from reportlab.pdfgen import canvas
from functools import wraps
from dotenv import load_dotenv
from routes.accounts.accounts import get_institute_id
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

MASTER_API_USERNAME = os.getenv('COMMS_API_USERNAME', '')
MASTER_API_KEY = os.getenv('COMMS_API_KEY', '')


# ==================== HELPER FUNCTION: Calculate Student Balance ====================
def calculate_student_balance(student_id, institute_id):
    """
    Calculate student's actual balance including ALL payments (SchoolPay + Manual)
    Balance = Total Invoiced - Total Paid (all payments) - Total Discounts
    """
    total_invoiced = 0.0
    total_paid = 0.0
    total_discount = 0.0
    
    try:
        # Get ALL invoices for this student
        invoices_response = supabase.table('invoices')\
            .select('total_amount')\
            .eq('student_id', student_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        for inv in (invoices_response.data or []):
            try:
                amount = float(inv.get('total_amount', 0))
                if amount > 0:  # Only count positive invoices (debits)
                    total_invoiced += amount
            except (ValueError, TypeError):
                continue
        
        # Get ALL payments for this student (including SchoolPay)
        payments_response = supabase.table('payments')\
            .select('amount')\
            .eq('student_id', student_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        for p in (payments_response.data or []):
            try:
                amount = float(p.get('amount', 0))
                if amount > 0:
                    total_paid += amount
            except (ValueError, TypeError):
                continue
        
        # Get ALL discounts for this student
        discounts_response = supabase.table('discounts')\
            .select('discount_amount')\
            .eq('student_id', student_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        for d in (discounts_response.data or []):
            try:
                amount = float(d.get('discount_amount', 0))
                if amount > 0:
                    total_discount += amount
            except (ValueError, TypeError):
                continue
        
        # Calculate balance
        balance = total_invoiced - total_paid - total_discount
        
        # Don't show negative balance (overpayment)
        if balance < 0:
            balance = 0
            
        return balance
        
    except Exception as e:
        print(f"Error calculating balance for student {student_id}: {e}")
        return 0


def send_payment_sms(institute, student, amount_paid, balance, receipt_number, payment_method, notes=""):
    """Send SMS notification for payment"""
    try:
        # Get SMS settings
        sms_response = supabase.table('sms_settings')\
            .select('*')\
            .eq('institute_id', institute['id'])\
            .eq('enabled', True)\
            .execute()
        
        if not sms_response.data:
            return False
        
        settings = sms_response.data[0]
        
        if not settings.get('send_on_payment', True):
            return False
        
        phone = student.get('contact_number') or student.get('phone') or student.get('phone_number') or ''
        
        if not phone:
            return False
        
        # Format phone
        phone = phone.strip().replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
        if not phone.startswith('+'):
            if phone.startswith('0'):
                phone = '+256' + phone[1:]
            elif phone.startswith('256'):
                phone = '+' + phone
            elif len(phone) == 9 and phone.isdigit():
                phone = '+256' + phone
        
        # Prepare message
        if balance < 0:
            balance_display = f"Credit: UGX {abs(balance):,.0f}"
        else:
            balance_display = f"Due: UGX {balance:,.0f}"
        
        message = f"""Payment Received! 🎓

Student: {student.get('name', 'Student')}
Amount: UGX {amount_paid:,.0f}
{balance_display}
Method: {payment_method.upper()}
Receipt: {receipt_number}

{institute.get('institute_name', 'School')}
Thank you for your payment!"""

        if notes:
            message += f"\n\nNote: {notes}"
        
        # Check master credentials
        if not MASTER_API_USERNAME or not MASTER_API_KEY:
            return False
        
        try:
            from comms_sdk import CommsSDK, MessagePriority
            
            sdk = CommsSDK.authenticate(MASTER_API_USERNAME, MASTER_API_KEY)
            
            response = sdk.send_sms(
                [phone],
                message,
                sender_id=settings.get('sender_id', 'SCHOOL')[:11],
                priority=MessagePriority.HIGHEST
            )
            
            print(f"SMS sent to {phone}")
            return True
            
        except Exception as e:
            print(f"SMS error: {e}")
            return False
            
    except Exception as e:
        print(f"Unexpected error in send_payment_sms: {e}")
        return False

def send_whatsapp_pdf(institute, student, pdf_buffer, filename, phone_number):
    """
    Send PDF receipt via WhatsApp using the WhatsApp integration API
    
    Args:
        institute (dict): Institute object
        student (dict): Student object
        pdf_buffer (BytesIO): PDF buffer to send
        filename (str): Filename for the PDF
        phone_number (str): Recipient phone number
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Get WhatsApp settings
        whatsapp_response = supabase.table('whatsapp_settings_custom')\
            .select('*')\
            .eq('institute_id', institute['id'])\
            .eq('is_enabled', True)\
            .execute()
        
        if not whatsapp_response.data:
            print(f"WhatsApp not enabled for institute {institute['id']}")
            return False
        
        settings = whatsapp_response.data[0]
        nodejs_url = settings.get('nodejs_api_url', '').rstrip('/')
        api_key = settings.get('api_key', '')
        
        if not nodejs_url:
            print("Node.js API URL not configured")
            return False
        
        # Format phone number
        phone = phone_number.strip().replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
        if not phone.startswith('+'):
            if phone.startswith('0'):
                phone = '256' + phone[1:]
            elif phone.startswith('256'):
                phone = phone
            elif len(phone) == 9 and phone.isdigit():
                phone = '256' + phone
            else:
                # Remove any non-digit characters
                phone = ''.join(filter(str.isdigit, phone))
                if len(phone) == 9:
                    phone = '256' + phone
                elif len(phone) == 10 and phone.startswith('0'):
                    phone = '256' + phone[1:]
        
        # Convert PDF to base64
        pdf_bytes = pdf_buffer.getvalue()
        import base64
        pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')
        
        # Prepare headers
        headers = {}
        if api_key:
            headers['X-API-Key'] = api_key
        
        # Send PDF via WhatsApp API
        response = requests.post(
            f"{nodejs_url}/api/send-pdf",
            json={
                'number': phone,
                'pdfBuffer': pdf_base64,
                'filename': filename,
                'instituteId': institute['id']
            },
            headers=headers,
            timeout=60
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"WhatsApp PDF sent successfully to {phone}")
            return True
        else:
            print(f"WhatsApp PDF send failed: {response.status_code} - {response.text}")
            return False
            
    except requests.exceptions.ConnectionError:
        print(f"Node.js API not reachable for institute {institute['id']}")
        return False
    except Exception as e:
        print(f"Error sending WhatsApp PDF: {e}")
        import traceback
        traceback.print_exc()
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
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        search_term = data.get('search_term', '').strip()
        
        if not search_term:
            return jsonify({'success': False, 'message': 'Please enter search term'}), 400
        
        # Search by name
        response = supabase.table('students')\
            .select('*, classes(name)')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')\
            .ilike('name', f'%{search_term}%')\
            .execute()
        
        # If no results, search by student_id
        if not response.data:
            response = supabase.table('students')\
                .select('*, classes(name)')\
                .eq('institute_id', institute_id)\
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
    """Get fee details and invoices for a student - ALWAYS RECALCULATE from payments"""
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
        
        # Get ALL invoices for this student
        invoices_response = supabase.table('invoices')\
            .select('*')\
            .eq('student_id', student_id)\
            .eq('institute_id', institute_id)\
            .order('created_at', desc=True)\
            .execute()
        
        all_invoices = invoices_response.data if invoices_response.data else []
        
        # Get ALL payments for this student (including SchoolPay)
        payments_response = supabase.table('payments')\
            .select('*')\
            .eq('student_id', student_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        all_payments = payments_response.data if payments_response.data else []
        
        # Get ALL discounts for this student
        discounts_response = supabase.table('discounts')\
            .select('*')\
            .eq('student_id', student_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        all_discounts = discounts_response.data if discounts_response.data else []
        
        # 🔥 FIX: If there are unlinked payments, distribute them to invoices
        # This is the key fix - find payments without invoice_id and link them
        
        # Get invoice IDs
        invoice_ids = [inv['id'] for inv in all_invoices]
        
        # Find payments not linked to any invoice
        unlinked_payments = [p for p in all_payments if p.get('invoice_id') is None or p.get('invoice_id') == '']
        
        if unlinked_payments and all_invoices:
            print(f"Found {len(unlinked_payments)} unlinked payments. Distributing to invoices...")
            
            # Distribute unlinked payments to invoices with positive balance
            for payment in unlinked_payments:
                amount = float(payment['amount'])
                remaining = amount
                
                # Find invoices with balance > 0
                for inv in all_invoices:
                    if remaining <= 0:
                        break
                    
                    inv_balance = float(inv['balance'])
                    if inv_balance > 0:
                        # Link this payment to the invoice
                        payment_for_invoice = min(remaining, inv_balance)
                        
                        # Update payment
                        supabase.table('payments')\
                            .update({'invoice_id': inv['id']})\
                            .eq('id', payment['id'])\
                            .execute()
                        
                        # Update invoice balance
                        new_balance = inv_balance - payment_for_invoice
                        new_paid = float(inv['paid_amount']) + payment_for_invoice
                        
                        if new_balance < 0:
                            new_balance = 0
                        
                        status = 'paid' if new_balance == 0 else 'partial'
                        
                        supabase.table('invoices')\
                            .update({
                                'paid_amount': new_paid,
                                'balance': new_balance,
                                'status': status
                            })\
                            .eq('id', inv['id'])\
                            .execute()
                        
                        remaining -= payment_for_invoice
                        print(f"  Linked {payment_for_invoice} to {inv['invoice_number']}")
        
        # Now recalculate everything from scratch
        invoice_list = []
        total_due = 0
        
        for inv in all_invoices:
            # Calculate total paid for this invoice from payments
            inv_payments = [p for p in all_payments if p.get('invoice_id') == inv['id']]
            total_paid = sum(float(p['amount']) for p in inv_payments)
            
            # Calculate total discount for this invoice
            inv_discounts = [d for d in all_discounts if d.get('invoice_id') == inv['id']]
            total_discount = sum(float(d.get('discount_amount', 0)) for d in inv_discounts)
            
            # Calculate correct balance
            invoice_total = float(inv['total_amount'])
            correct_balance = invoice_total - total_paid - total_discount
            
            if correct_balance < 0:
                correct_balance = 0
            
            # Determine status
            if invoice_total == 0:
                status = 'paid'
            elif correct_balance == 0 and total_paid > 0:
                status = 'paid'
            elif correct_balance < invoice_total and total_paid > 0:
                status = 'partial'
            elif correct_balance == invoice_total and invoice_total > 0:
                status = 'pending'
            else:
                status = 'pending'
            
            if invoice_total > 0 or total_paid > 0:
                invoice_list.append({
                    'id': inv['id'],
                    'invoice_number': inv['invoice_number'],
                    'total_amount': invoice_total,
                    'paid_amount': total_paid,
                    'balance': correct_balance,
                    'status': status,
                    'due_date': inv.get('due_date', 'N/A'),
                    'created_at': inv.get('created_at', ''),
                    'discount_applied': total_discount
                })
                
                if correct_balance > 0:
                    total_due += correct_balance
        
        # Also calculate total due from ALL payments using helper
        total_due_calculated = calculate_student_balance(student_id, institute_id)
        
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
            'total_due': total_due_calculated
        })
        
    except Exception as e:
        print(f"Error getting student fees: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500
    
    
@collect_bp.route('/process-payment', methods=['POST'])
@login_required
def process_payment():
    """Process fee payment and send receipt via WhatsApp"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        student_id = data.get('student_id')
        invoice_id = data.get('invoice_id')
        amount_paid = float(data.get('amount', 0))
        payment_method = data.get('payment_method', 'cash')
        fee_month = data.get('fee_month')
        notes = data.get('notes', '')
        whatsapp_enabled = data.get('whatsapp_enabled', True)  # New flag
        
        if not student_id or amount_paid <= 0:
            return jsonify({'success': False, 'message': 'Invalid payment amount'}), 400
        
        # Get institute details
        institute_response = supabase.table('institutes')\
            .select('*')\
            .eq('id', institute_id)\
            .execute()
        
        institute = institute_response.data[0] if institute_response.data else {}
        
        # Handle fee_month
        if fee_month:
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
            .eq('institute_id', institute_id)\
            .execute()
        
        if not student_response.data:
            return jsonify({'success': False, 'message': 'Student not found'}), 404
        
        student = student_response.data[0]
        
        # Get existing receipt numbers
        existing_receipts_response = supabase.table('payments')\
            .select('receipt_number')\
            .eq('institute_id', institute_id)\
            .execute()
        
        existing_numbers = set()
        if existing_receipts_response.data:
            for receipt in existing_receipts_response.data:
                existing_numbers.add(receipt['receipt_number'])
        
        payments_made = []
        remaining_amount = amount_paid
        
        # Process payment (same as before)
        if invoice_id:
            # Pay specific invoice
            invoice_response = supabase.table('invoices')\
                .select('*')\
                .eq('id', invoice_id)\
                .eq('student_id', student_id)\
                .eq('institute_id', institute_id)\
                .execute()
            
            if not invoice_response.data:
                return jsonify({'success': False, 'message': 'Invoice not found'}), 404
            
            invoice = invoice_response.data[0]
            
            new_paid = invoice['paid_amount'] + remaining_amount
            new_balance = invoice['total_amount'] - new_paid
            
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
                .eq('institute_id', institute_id)\
                .execute()
            
            payments_made.append({
                'invoice_id': invoice['id'],
                'invoice_number': invoice['invoice_number'],
                'amount': remaining_amount,
                'new_balance': new_balance
            })
            
            remaining_amount = 0
            
        else:
            # General payment - distribute to invoices
            invoices_response = supabase.table('invoices')\
                .select('*')\
                .eq('student_id', student_id)\
                .eq('institute_id', institute_id)\
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
                        .eq('institute_id', institute_id)\
                        .execute()
                    
                    payments_made.append({
                        'invoice_id': invoice['id'],
                        'invoice_number': invoice['invoice_number'],
                        'amount': payment_for_invoice,
                        'new_balance': new_balance
                    })
                    
                    remaining_amount -= payment_for_invoice
            
            # Handle remaining amount (overpayment)
            if remaining_amount > 0:
                recent_invoice_response = supabase.table('invoices')\
                    .select('*')\
                    .eq('student_id', student_id)\
                    .eq('institute_id', institute_id)\
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
                        .eq('institute_id', institute_id)\
                        .execute()
                    
                    payments_made.append({
                        'invoice_id': invoice['id'],
                        'invoice_number': invoice['invoice_number'],
                        'amount': remaining_amount,
                        'new_balance': new_balance,
                        'note': 'Overpayment - Credit balance'
                    })
                else:
                    # Create credit invoice
                    new_invoice_id = str(uuid.uuid4())
                    new_invoice_number = f"CREDIT-{datetime.now().strftime('%Y%m%d%H%M%S')}"
                    
                    invoice_data = {
                        'id': new_invoice_id,
                        'institute_id': institute_id,
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
        
        # Generate receipt number
        receipt_number = generate_unique_receipt_number(institute_id, existing_numbers)
        
        # Create payment record
        payment_id = str(uuid.uuid4())
        payment_data = {
            'id': payment_id,
            'institute_id': institute_id,
            'student_id': student_id,
            'invoice_id': invoice_id,
            'amount': amount_paid,
            'payment_method': payment_method,
            'receipt_number': receipt_number,
            'payment_date': datetime.now().date().isoformat(),
            'fee_month': fee_month_date,
            'notes': notes,
            'created_at': datetime.now().isoformat()
        }
        
        supabase.table('payments').insert(payment_data).execute()
        
        # 🔥 FIX: Get updated total due using ALL payments
        total_due = calculate_student_balance(student_id, institute_id)
        
        # ==================== SEND SMS ====================
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
            print(f"SMS notification error: {e}")
        
        # ==================== SEND WHATSAPP PDF RECEIPT ====================
        whatsapp_sent = False
        if whatsapp_enabled:
            try:
                # Generate PDF receipt buffer
                pdf_buffer = generate_receipt_pdf(institute, student, payment_data, total_due)
                
                if pdf_buffer:
                    # Send via WhatsApp
                    filename = f"Receipt_{receipt_number}.pdf"
                    phone = student.get('contact_number') or student.get('phone') or student.get('phone_number') or ''
                    
                    if phone:
                        whatsapp_sent = send_whatsapp_pdf(
                            institute=institute,
                            student=student,
                            pdf_buffer=pdf_buffer,
                            filename=filename,
                            phone_number=phone
                        )
            except Exception as e:
                print(f"WhatsApp PDF send error: {e}")
                import traceback
                traceback.print_exc()
        
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
            'institute': institute,
            'whatsapp_sent': whatsapp_sent
        })
        
    except Exception as e:
        print(f"Error processing payment: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


# ==================== FIXED: generate_receipt_pdf with CORRECT balance ====================
def generate_receipt_pdf(institute, student, payment, total_due):
    """
    Generate PDF receipt for WhatsApp sending - FIXED balance calculation
    
    Args:
        institute (dict): Institute details
        student (dict): Student details
        payment (dict): Payment details
        total_due (float): Correct total balance (calculated with ALL payments)
    
    Returns:
        BytesIO: PDF buffer
    """
    try:
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
        
        # Helper function to safely get string values
        def safe_str(value, default=''):
            """Safely convert value to string, handling None"""
            if value is None:
                return default
            return str(value)
        
        # Institute Header - FIXED: ensure all values are strings
        story.append(Paragraph(safe_str(institute.get('institute_name', 'School Name')), title_style))
        story.append(Paragraph(safe_str(institute.get('target_line', '')), center_style))
        story.append(Paragraph(safe_str(institute.get('address', '')), center_style))
        story.append(Paragraph(f"Tel: {safe_str(institute.get('phone_number', ''))}", center_style))
        story.append(Spacer(1, 5))
        
        # Receipt Title
        story.append(Paragraph("=" * 35, normal_style))
        story.append(Paragraph("FEE PAYMENT RECEIPT", title_style))
        story.append(Paragraph("=" * 35, normal_style))
        story.append(Spacer(1, 5))
        
        # Receipt Details - FIXED: ensure all values are strings
        student_name = safe_str(student.get('name', 'N/A'))
        student_id = safe_str(student.get('student_id', 'N/A'))
        class_name = student.get('classes', {}).get('name', 'N/A') if student.get('classes') else 'N/A'
        class_name = safe_str(class_name)
        fee_month = safe_str(payment.get('fee_month', 'N/A'))
        receipt_number = safe_str(payment.get('receipt_number', 'N/A'))
        payment_date = safe_str(payment.get('payment_date', 'N/A'))
        
        receipt_data = [
            ['Receipt No:', receipt_number],
            ['Date:', payment_date],
            ['', ''],
            ['Student Name:', student_name],
            ['Student ID:', student_id],
            ['Class:', class_name],
            ['Fee Month:', fee_month],
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
        
        # Amount - 🔥 FIXED: Use total_due passed from caller
        story.append(Paragraph("-" * 35, normal_style))
        
        # Format balance display
        amount_paid = float(payment.get('amount', 0))
        payment_method = safe_str(payment.get('payment_method', 'CASH')).upper()
        
        if total_due < 0:
            balance_display = f"Credit: UGX {abs(total_due):,.0f}"
        elif total_due == 0:
            balance_display = "Balance: FULLY PAID"
        else:
            balance_display = f"Balance Due: UGX {total_due:,.0f}"
        
        amount_data = [
            ['Amount Paid:', f"UGX {amount_paid:,.0f}"],
            ['Payment Method:', payment_method],
            [balance_display, '']
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
        
        # Notes - FIXED: ensure notes is a string
        notes = payment.get('notes')
        if notes:
            story.append(Spacer(1, 5))
            story.append(Paragraph(f"Notes: {safe_str(notes)}", normal_style))
        
        story.append(Paragraph("-" * 35, normal_style))
        
        # Footer
        story.append(Spacer(1, 8))
        story.append(Paragraph("Thank you for your payment!", center_style))
        story.append(Paragraph("This is a computer generated receipt", center_style))
        story.append(Paragraph("No signature required", center_style))
        
        doc.build(story)
        buffer.seek(0)
        return buffer
        
    except Exception as e:
        print(f"Error generating PDF: {e}")
        import traceback
        traceback.print_exc()
        return None

@collect_bp.route('/apply-discount', methods=['POST'])
@login_required
def apply_discount():
    """Apply discount to an invoice"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
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
            .eq('institute_id', institute_id)\
            .execute()
        
        if not invoice_response.data:
            return jsonify({'success': False, 'message': 'Invoice not found'}), 404
        
        invoice = invoice_response.data[0]
        
        # Calculate discount amount based on current balance
        if discount_type == 'percentage':
            discount_amount = (discount_value / 100) * invoice['balance']
        else:
            discount_amount = min(discount_value, abs(invoice['balance']))
        
        # Apply discount to invoice
        new_balance = invoice['balance'] - discount_amount
        
        # Update status
        if new_balance == 0:
            new_status = 'paid'
        elif new_balance < 0:
            new_status = 'credit'
        else:
            new_status = 'partial' if invoice['paid_amount'] > 0 else 'pending'
        
        # Update invoice
        supabase.table('invoices')\
            .update({
                'balance': new_balance,
                'status': new_status,
                'updated_at': datetime.now().isoformat()
            })\
            .eq('id', invoice_id)\
            .eq('institute_id', institute_id)\
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
            'institute_id': institute_id,
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
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Get institute details
        institute_response = supabase.table('institutes')\
            .select('*')\
            .eq('id', institute_id)\
            .execute()
        
        institute = institute_response.data[0] if institute_response.data else {}
        
        payment_response = supabase.table('payments')\
            .select('*, students(name, student_id, classes(name))')\
            .eq('receipt_number', receipt_number)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if not payment_response.data:
            return jsonify({'success': False, 'message': 'Receipt not found'}), 404
        
        payment = payment_response.data[0]
        
        # 🔥 FIX: Calculate correct balance
        student_id = payment.get('student_id')
        current_balance = calculate_student_balance(student_id, institute_id)
        
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
                'balance': current_balance,
                'institute': institute
            }
        })
        
    except Exception as e:
        print(f"Error getting receipt: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@collect_bp.route('/print-receipt/<receipt_number>', methods=['GET'])
@login_required
def print_receipt(receipt_number):
    """Generate thermal receipt PDF for printing - FIXED balance"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Get institute details
        institute_response = supabase.table('institutes')\
            .select('*')\
            .eq('id', institute_id)\
            .execute()
        
        institute = institute_response.data[0] if institute_response.data else {}
        
        payment_response = supabase.table('payments')\
            .select('*, students(name, student_id, classes(name))')\
            .eq('receipt_number', receipt_number)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if not payment_response.data:
            return jsonify({'success': False, 'message': 'Receipt not found'}), 404
        
        payment = payment_response.data[0]
        student = payment['students']
        student_id = payment.get('student_id')
        
        # 🔥 FIX: Calculate correct balance using ALL payments
        current_balance = calculate_student_balance(student_id, institute_id)
        
        buffer = generate_receipt_pdf(institute, student, payment, current_balance)
        
        if buffer:
            return send_file(
                buffer,
                as_attachment=False,
                download_name=f"receipt_{receipt_number}.pdf",
                mimetype='application/pdf'
            )
        else:
            return jsonify({'success': False, 'message': 'Failed to generate receipt'}), 500
        
    except Exception as e:
        print(f"Error generating receipt: {e}")
        import traceback
        traceback.print_exc()
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

@collect_bp.route('/resend-receipt/<receipt_number>', methods=['POST'])
@login_required
def resend_receipt(receipt_number):
    """Resend receipt PDF via WhatsApp for an existing payment - FIXED balance"""
    user = session.get('user')
    
    if not user:
        return jsonify({'success': False, 'message': 'User not logged in'}), 401
    
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Get the payment details
        payment_response = supabase.table('payments')\
            .select('*, students(name, student_id, contact_number, classes(name))')\
            .eq('receipt_number', receipt_number)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if not payment_response.data:
            return jsonify({'success': False, 'message': 'Receipt not found'}), 404
        
        payment = payment_response.data[0]
        student = payment.get('students')
        
        if not student:
            return jsonify({'success': False, 'message': 'Student not found'}), 404
        
        # Get institute details
        institute_response = supabase.table('institutes')\
            .select('*')\
            .eq('id', institute_id)\
            .execute()
        
        institute = institute_response.data[0] if institute_response.data else {}
        
        if not institute:
            return jsonify({'success': False, 'message': 'Institute not found'}), 404
        
        # 🔥 FIX: Calculate correct balance using ALL payments
        student_id = payment.get('student_id')
        current_balance = calculate_student_balance(student_id, institute_id)
        
        # Generate PDF receipt
        pdf_buffer = generate_receipt_pdf(institute, student, payment, current_balance)
        
        if not pdf_buffer:
            return jsonify({'success': False, 'message': 'Failed to generate receipt PDF'}), 500
        
        # Get phone number
        data = request.get_json() or {}
        custom_phone = data.get('phone_number')
        phone = custom_phone or student.get('contact_number') or student.get('phone_number') or ''
        
        if not phone:
            return jsonify({'success': False, 'message': 'No phone number available'}), 400
        
        # Send WhatsApp PDF
        filename = f"Receipt_{receipt_number}.pdf"
        whatsapp_sent = send_whatsapp_pdf(
            institute=institute,
            student=student,
            pdf_buffer=pdf_buffer,
            filename=filename,
            phone_number=phone
        )
        
        if whatsapp_sent:
            # Update WhatsApp status
            supabase.table('payments')\
                .update({
                    'whatsapp_status': 'sent',
                    'whatsapp_sent_at': datetime.now().isoformat()
                })\
                .eq('receipt_number', receipt_number)\
                .eq('institute_id', institute_id)\
                .execute()
            
            return jsonify({
                'success': True,
                'message': f'Receipt {receipt_number} resent successfully via WhatsApp',
                'receipt_number': receipt_number,
                'phone_number': phone,
                'student_name': student.get('name'),
                'current_balance': current_balance
            })
        else:
            return jsonify({'success': False, 'message': 'Failed to send WhatsApp message'}), 500
            
    except Exception as e:
        print(f"Error resending receipt: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500