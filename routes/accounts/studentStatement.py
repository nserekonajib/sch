# studentStatements.py - Student Statements Blueprint with Employee Support
from flask import Blueprint, render_template, request, jsonify, session, send_file
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

statement_bp = Blueprint('statements', __name__, url_prefix='/student-statements')

def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Please login'}), 401
        return f(*args, **kwargs)
    return decorated_function

def get_institute_from_session():
    """Get institute details from current session - handles both owners and employees"""
    user = session.get('user')
    if not user:
        print("No user in session")
        return None
    
    print(f"Getting institute for user: {user.get('id')}, is_employee: {user.get('is_employee')}")
    print(f"User institute_id from session: {user.get('institute_id')}")
    
    institute_id = None
    
    # CASE 1: Employee - has institute_id directly in session
    if user.get('is_employee') and user.get('institute_id'):
        institute_id = user.get('institute_id')
        print(f"Using employee institute_id from session: {institute_id}")
    
    # CASE 2: Owner - need to look up by user_id
    elif not user.get('is_employee') and user.get('id'):
        try:
            response = supabase.table('institutes')\
                .select('id')\
                .eq('user_id', user['id'])\
                .execute()
            
            if response.data and len(response.data) > 0:
                institute_id = response.data[0]['id']
                print(f"Found owner institute_id: {institute_id}")
            else:
                print(f"No institute found for owner user_id: {user['id']}")
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
                print(f"Found employee institute_id from lookup: {institute_id}")
        except Exception as e:
            print(f"Error looking up employee institute: {e}")
    
    if not institute_id:
        print("No institute_id found")
        return None
    
    # Fetch full institute details
    try:
        response = supabase.table('institutes')\
            .select('*')\
            .eq('id', institute_id)\
            .execute()
        
        if response.data and len(response.data) > 0:
            print(f"Found institute: {response.data[0].get('institute_name')}")
            return response.data[0]
        else:
            print(f"No institute found with id: {institute_id}")
            return None
    except Exception as e:
        print(f"Error fetching institute details: {e}")
        return None

@statement_bp.route('/')
@login_required
def index():
    """Student Statements Page"""
    institute = get_institute_from_session()
    
    if not institute:
        return render_template('statements/index.html', institute=None)
    
    return render_template('statements/index.html', institute=institute)

@statement_bp.route('/search-student', methods=['POST'])
@login_required
def search_student():
    """Live search for students"""
    institute = get_institute_from_session()
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        search_term = data.get('search_term', '').strip()
        
        if not search_term:
            return jsonify({'success': False, 'message': 'Please enter search term'}), 400
        
        # Search by name or student_id
        response = supabase.table('students')\
            .select('*, classes(name)')\
            .eq('institute_id', institute['id'])\
            .eq('status', 'active')\
            .ilike('name', f'%{search_term}%')\
            .limit(20)\
            .execute()
        
        if not response.data:
            response = supabase.table('students')\
                .select('*, classes(name)')\
                .eq('institute_id', institute['id'])\
                .eq('status', 'active')\
                .ilike('student_id', f'%{search_term}%')\
                .limit(20)\
                .execute()
        
        students = response.data if response.data else []
        
        return jsonify({'success': True, 'students': students})
        
    except Exception as e:
        print(f"Error searching student: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@statement_bp.route('/get-statement', methods=['POST'])
@login_required
def get_statement():
    """Get student statement with date filtering - includes all transactions with proper chronological order"""
    institute = get_institute_from_session()
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        student_id = data.get('student_id')
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        
        if not student_id:
            return jsonify({'success': False, 'message': 'Student not selected'}), 400
        
        # Get student details
        student_response = supabase.table('students')\
            .select('*, classes(name)')\
            .eq('id', student_id)\
            .eq('institute_id', institute['id'])\
            .execute()
        
        if not student_response.data:
            return jsonify({'success': False, 'message': 'Student not found'}), 404
        
        student = student_response.data[0]
        
        # Get ALL invoices for this student (including credit invoices)
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
        
        # Build transactions list with proper timestamps
        transactions = []
        
        # Add invoices as transactions (including credit invoices)
        for invoice in invoices:
            # Get the full timestamp for proper sorting
            timestamp = invoice['created_at']
            date_only = timestamp[:10]
            
            # For credit invoices (negative total_amount), show as a credit transaction
            if invoice['total_amount'] < 0:
                transactions.append({
                    'timestamp': timestamp,
                    'date': date_only,
                    'type': 'credit_invoice',
                    'description': f"Credit Note {invoice['invoice_number']} - Overpayment Credit",
                    'debit': 0,
                    'credit': abs(invoice['total_amount']),
                    'reference': invoice['invoice_number'],
                    'invoice_id': invoice['id']
                })
            else:
                # Regular invoice - money owed BY the student
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
                    'reference': invoice['invoice_number'],
                    'invoice_id': invoice['id']
                })
        
        # Add payments as credit transactions with proper timestamp
        for payment in payments:
            # Use payment_date + created_at time for proper ordering
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
                'invoice_ref': invoice_ref,
                'payment_id': payment['id']
            })
        
        # Add discounts as credit transactions
        for discount in discounts:
            if discount.get('discount_amount', 0) > 0:
                timestamp = discount.get('created_at', datetime.now().isoformat())
                date_only = timestamp[:10]
                
                # Only include if within date range
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
        
        # Sort transactions by timestamp (chronological order)
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
        
        # Calculate summary - sum of all invoice totals (positive and negative)
        total_debits = sum(inv['total_amount'] for inv in invoices if inv['total_amount'] > 0)
        total_credits = sum(p['amount'] for p in payments) + sum(d.get('discount_amount', 0) for d in discounts)
        
        # For credit invoices (negative totals), they should be counted as credits
        total_credits += sum(abs(inv['total_amount']) for inv in invoices if inv['total_amount'] < 0)
        
        current_balance = running_balance
        
        return jsonify({
            'success': True,
            'student': {
                'id': student['id'],
                'name': student['name'],
                'student_id': student['student_id'],
                'class': student['classes']['name'] if student.get('classes') else 'N/A',
                'contact': student.get('contact_number', 'N/A')
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
    
@statement_bp.route('/export-pdf', methods=['POST'])
@login_required
def export_pdf():
    """Export student statement as PDF with minimal professional spacing"""
    institute = get_institute_from_session()
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        student = data.get('student')
        statement = data.get('statement')
        summary = data.get('summary')
        date_range = data.get('date_range')
        
        if not student or not statement:
            return jsonify({'success': False, 'message': 'No data to export'}), 400
        
        # Create PDF with tighter margins
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4,
                                rightMargin=15*mm, leftMargin=15*mm,
                                topMargin=15*mm, bottomMargin=15*mm)
        
        story = []
        styles = getSampleStyleSheet()
        
        # Compact custom styles
        title_style = ParagraphStyle(
            'Title',
            parent=styles['Normal'],
            fontSize=14,
            textColor=colors.HexColor('#ffa500'),
            alignment=TA_CENTER,
            spaceAfter=2,
            fontName='Helvetica-Bold'
        )
        
        subtitle_style = ParagraphStyle(
            'Subtitle',
            parent=styles['Normal'],
            fontSize=9,
            textColor=colors.grey,
            alignment=TA_CENTER,
            spaceAfter=1
        )
        
        section_title = ParagraphStyle(
            'SectionTitle',
            parent=styles['Normal'],
            fontSize=11,
            textColor=colors.HexColor('#1e2a3a'),
            spaceAfter=3,
            fontName='Helvetica-Bold'
        )
        
        info_label = ParagraphStyle(
            'InfoLabel',
            parent=styles['Normal'],
            fontSize=9,
            fontName='Helvetica-Bold',
            textColor=colors.HexColor('#4b5563')
        )
        
        info_value = ParagraphStyle(
            'InfoValue',
            parent=styles['Normal'],
            fontSize=9,
            textColor=colors.HexColor('#1f2937')
        )
        
        # Institute Header (compact)
        header_data = []
        
        if institute.get('logo_url'):
            try:
                from reportlab.lib.utils import ImageReader
                import requests
                img_data = requests.get(institute['logo_url']).content
                img_buffer = io.BytesIO(img_data)
                logo = Image(img_buffer, width=25*mm, height=25*mm)
                logo.hAlign = 'CENTER'
                story.append(logo)
                story.append(Spacer(1, 2))
            except:
                pass
        
        story.append(Paragraph(institute.get('institute_name', 'School Name'), title_style))
        if institute.get('target_line'):
            story.append(Paragraph(institute.get('target_line'), subtitle_style))
        story.append(Paragraph(institute.get('address', ''), subtitle_style))
        if institute.get('phone_number'):
            story.append(Paragraph(f"Tel: {institute.get('phone_number')}", subtitle_style))
        story.append(Spacer(1, 6))
        
        # Divider
        story.append(Paragraph("-" * 80, subtitle_style))
        story.append(Spacer(1, 4))
        
        # Report Title
        story.append(Paragraph("FEE STATEMENT", title_style))
        story.append(Spacer(1, 4))
        
        # Date Range (inline)
        if date_range.get('start_date') or date_range.get('end_date'):
            date_text = f"Period: {date_range.get('start_date', 'Start')} - {date_range.get('end_date', 'End')}"
        else:
            date_text = "Period: All Transactions"
        story.append(Paragraph(date_text, subtitle_style))
        story.append(Spacer(1, 6))
        
        # Student Information in 2-column grid
        story.append(Paragraph("STUDENT DETAILS", section_title))
        story.append(Spacer(1, 2))
        
        # Create compact student info table
        student_info = [
            [Paragraph("<b>Name:</b>", info_label), Paragraph(student['name'], info_value),
             Paragraph("<b>ID:</b>", info_label), Paragraph(student['student_id'], info_value)],
            [Paragraph("<b>Class:</b>", info_label), Paragraph(student['class'], info_value),
             Paragraph("<b>Contact:</b>", info_label), Paragraph(student.get('contact', 'N/A'), info_value)]
        ]
        
        info_table = Table(student_info, colWidths=[25*mm, 55*mm, 25*mm, 55*mm])
        info_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))
        story.append(info_table)
        story.append(Spacer(1, 8))
        
        # Statement Table
        story.append(Paragraph("TRANSACTION HISTORY", section_title))
        story.append(Spacer(1, 3))
        
        # Prepare table data with compact formatting
        table_data = [
            ['Date', 'Description', 'Debit', 'Credit', 'Balance']
        ]
        
        # Add only last 30 transactions for compactness, or all if less
        display_statement = statement[-30:] if len(statement) > 30 else statement
        
        for entry in display_statement:
            # Format date to show MM-DD only
            date_display = entry['date'][5:10] if len(entry['date']) > 10 else entry['date']
            # Truncate description if too long
            desc_display = entry['description'][:40] + '...' if len(entry['description']) > 40 else entry['description']
            
            table_data.append([
                date_display,
                desc_display,
                f"{entry['debit']:,.0f}" if entry['debit'] > 0 else '-',
                f"{entry['credit']:,.0f}" if entry['credit'] > 0 else '-',
                f"{entry['balance']:,.0f}"
            ])
        
        # Add summary rows
        table_data.append(['', '', '', '', ''])
        table_data.append([
            'TOTALS', '',
            f"{summary['total_debits']:,.0f}",
            f"{summary['total_credits']:,.0f}",
            ''
        ])
        table_data.append([
            'BALANCE', '',
            '',
            '',
            f"{summary['current_balance']:,.0f}"
        ])
        
        # Create compact table
        statement_table = Table(table_data, colWidths=[22*mm, 60*mm, 28*mm, 28*mm, 28*mm])
        statement_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('ALIGN', (0, 0), (0, -1), 'CENTER'),
            ('ALIGN', (1, 0), (1, -1), 'LEFT'),
            ('ALIGN', (2, 0), (4, -1), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#ffa500')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('GRID', (0, 1), (-1, -3), 0.3, colors.lightgrey),
            ('BACKGROUND', (0, -2), (-1, -2), colors.HexColor('#fef3c7')),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#ffedd5')),
            ('FONTNAME', (0, -2), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, -2), (-1, -1), 9),
            ('SPAN', (0, -2), (1, -2)),
            ('SPAN', (0, -1), (1, -1)),
            ('ALIGN', (0, -2), (1, -2), 'RIGHT'),
            ('ALIGN', (0, -1), (1, -1), 'RIGHT'),
        ]))
        
        story.append(statement_table)
        story.append(Spacer(1, 8))
        
        # Footer
        story.append(Paragraph("-" * 80, subtitle_style))
        story.append(Spacer(1, 3))
        story.append(Paragraph("Computer Generated Statement", subtitle_style))
        story.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", subtitle_style))
        
        doc.build(story)
        buffer.seek(0)
        
        return send_file(
            buffer,
            as_attachment=True,
            download_name=f"statement_{student['student_id']}_{datetime.now().strftime('%Y%m%d')}.pdf",
            mimetype='application/pdf'
        )
        
    except Exception as e:
        print(f"Error generating PDF: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500