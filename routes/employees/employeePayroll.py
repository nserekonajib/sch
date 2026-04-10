# employeePayroll.py - Updated with PDF receipt-style payslip
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
from reportlab.lib.pagesizes import A4, landscape, portrait
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, mm
from reportlab.pdfgen import canvas
from functools import wraps
from dotenv import load_dotenv
import cloudinary
import cloudinary.uploader
import requests
from PIL import Image as PILImage
import tempfile

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

payroll_bp = Blueprint('payroll', __name__, url_prefix='/payroll')

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

def get_salary_expense_account(institute_id):
    """Get or create salary expense account"""
    try:
        response = supabase.table('chart_of_accounts')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .eq('account_name', 'SALARIES')\
            .eq('account_type', 'expense')\
            .execute()
        
        if response.data:
            return response.data[0]
        
        count_response = supabase.table('chart_of_accounts')\
            .select('id', count='exact')\
            .eq('institute_id', institute_id)\
            .eq('account_type', 'expense')\
            .execute()
        
        count = (count_response.count or 0) + 1
        account_code = f"EXP-{str(count).zfill(4)}"
        
        account_data = {
            'id': str(uuid.uuid4()),
            'institute_id': institute_id,
            'account_code': account_code,
            'account_name': 'SALARIES',
            'account_type': 'expense',
            'description': 'Employee salary expenses',
            'is_active': True,
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        result = supabase.table('chart_of_accounts').insert(account_data).execute()
        
        if result.data:
            return result.data[0]
        return None
        
    except Exception as e:
        print(f"Error getting salary account: {e}")
        return None

@payroll_bp.route('/')
@login_required
def index():
    """Payroll Management Page"""
    user = session.get('user')
    institute = get_institute_id(user['id'])
    
    if not institute:
        return render_template('payroll/index.html', institute=None, now=datetime.now())
    
    return render_template('payroll/index.html', institute=institute, now=datetime.now())

@payroll_bp.route('/api/employees', methods=['GET'])
@login_required
def get_employees():
    """Get all active employees for payroll"""
    user = session.get('user')
    institute = get_institute_id(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        response = supabase.table('employees')\
            .select('*')\
            .eq('institute_id', institute['id'])\
            .eq('status', 'active')\
            .order('name')\
            .execute()
        
        employees = response.data if response.data else []
        
        return jsonify({'success': True, 'employees': employees})
        
    except Exception as e:
        print(f"Error getting employees: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@payroll_bp.route('/api/salary-summary', methods=['GET'])
@login_required
def get_salary_summary():
    """Get salary summary for selected month"""
    user = session.get('user')
    institute = get_institute_id(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        month = request.args.get('month')
        
        if not month:
            return jsonify({'success': False, 'message': 'Month required'}), 400
        
        employees_response = supabase.table('employees')\
            .select('*')\
            .eq('institute_id', institute['id'])\
            .eq('status', 'active')\
            .execute()
        
        employees = employees_response.data if employees_response.data else []
        
        paid_response = supabase.table('salary_payments')\
            .select('employee_id')\
            .eq('institute_id', institute['id'])\
            .eq('payment_month', month)\
            .execute()
        
        paid_employee_ids = set(p['employee_id'] for p in paid_response.data) if paid_response.data else set()
        
        employees_data = []
        
        for emp in employees:
            salary = float(emp.get('monthly_salary', 0))
            employees_data.append({
                'id': emp['id'],
                'employee_id': emp['employee_id'],
                'name': emp['name'],
                'role': emp.get('role', 'Staff'),
                'monthly_salary': salary,
                'is_paid': emp['id'] in paid_employee_ids,
                'deductions': 0,
                'bonuses': 0,
                'net_pay': salary
            })
        
        return jsonify({
            'success': True,
            'employees': employees_data
        })
        
    except Exception as e:
        print(f"Error getting salary summary: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@payroll_bp.route('/api/process-payment', methods=['POST'])
@login_required
def process_payment():
    """Process salary payment for employees with deductions and bonuses"""
    user = session.get('user')
    institute = get_institute_id(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        payments_data = data.get('payments', [])
        payment_month = data.get('payment_month')
        payment_date = data.get('payment_date')
        
        if not payments_data:
            return jsonify({'success': False, 'message': 'No payment data provided'}), 400
        
        if not payment_month:
            return jsonify({'success': False, 'message': 'Payment month required'}), 400
        
        salary_account = get_salary_expense_account(institute['id'])
        
        if not salary_account:
            return jsonify({'success': False, 'message': 'Salary expense account not found. Please create a SALARIES expense account in Chart of Accounts first.'}), 400
        
        processed_count = 0
        total_amount = 0
        payments = []
        errors = []
        
        for payment_item in payments_data:
            try:
                employee_id = payment_item.get('employee_id')
                salary_amount = float(payment_item.get('monthly_salary', 0))
                deductions = float(payment_item.get('deductions', 0))
                bonuses = float(payment_item.get('bonuses', 0))
                
                net_pay = salary_amount - deductions + bonuses
                
                if net_pay <= 0:
                    errors.append(f"Net pay for {payment_item.get('name', 'Unknown')} is zero or negative")
                    continue
                
                existing = supabase.table('salary_payments')\
                    .select('id')\
                    .eq('employee_id', employee_id)\
                    .eq('payment_month', payment_month)\
                    .execute()
                
                if existing.data:
                    errors.append(f"{payment_item.get('name')} already paid for {payment_month}")
                    continue
                
                payment_id = str(uuid.uuid4())
                receipt_number = generate_salary_receipt_number(institute['id'])
                
                payment_data = {
                    'id': payment_id,
                    'institute_id': institute['id'],
                    'employee_id': employee_id,
                    'amount': net_pay,
                    'gross_salary': salary_amount,
                    'deductions': deductions,
                    'bonuses': bonuses,
                    'payment_month': payment_month,
                    'payment_date': payment_date,
                    'payment_method': payment_item.get('payment_method', 'cash'),
                    'receipt_number': receipt_number,
                    'notes': payment_item.get('notes', ''),
                    'status': 'paid',
                    'created_at': datetime.now().isoformat()
                }
                
                supabase.table('salary_payments').insert(payment_data).execute()
                
                expense_data = {
                    'id': str(uuid.uuid4()),
                    'institute_id': institute['id'],
                    'account_id': salary_account['id'],
                    'amount': net_pay,
                    'transaction_date': payment_date,
                    'payment_method': payment_item.get('payment_method', 'cash'),
                    'reference_number': receipt_number,
                    'description': f"Salary payment for {payment_item.get('name')} - {payment_month}",
                    'employee_id': employee_id,
                    'created_at': datetime.now().isoformat(),
                    'updated_at': datetime.now().isoformat()
                }
                
                supabase.table('expense_transactions').insert(expense_data).execute()
                
                processed_count += 1
                total_amount += net_pay
                payments.append({
                    'employee_name': payment_item.get('name'),
                    'employee_id': payment_item.get('employee_id_code'),
                    'gross_salary': salary_amount,
                    'deductions': deductions,
                    'bonuses': bonuses,
                    'net_pay': net_pay,
                    'receipt_number': receipt_number
                })
                
            except Exception as e:
                errors.append(f"Error processing {payment_item.get('name', 'Unknown')}: {str(e)}")
        
        if processed_count > 0:
            return jsonify({
                'success': True,
                'message': f'Successfully processed salary for {processed_count} employee(s)',
                'total_amount': total_amount,
                'payments': payments,
                'errors': errors if errors else None
            })
        else:
            return jsonify({
                'success': False,
                'message': 'No salaries were processed',
                'errors': errors
            }), 400
        
    except Exception as e:
        print(f"Error processing salary payment: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@payroll_bp.route('/api/print-payslip/<receipt_number>', methods=['GET'])
@login_required
def print_payslip(receipt_number):
    """Generate PDF salary slip for printing"""
    user = session.get('user')
    institute = get_institute_id(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        payment_response = supabase.table('salary_payments')\
            .select('*, employees(name, employee_id, role)')\
            .eq('receipt_number', receipt_number)\
            .eq('institute_id', institute['id'])\
            .execute()
        
        if not payment_response.data:
            return jsonify({'success': False, 'message': 'Payslip not found'}), 404
        
        payment = payment_response.data[0]
        employee = payment['employees']
        
        # Generate PDF
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
        
        bold_style = ParagraphStyle(
            'Bold',
            parent=styles['Normal'],
            fontSize=9,
            alignment=0,
            spaceAfter=3,
            fontName='Helvetica-Bold'
        )
        
        # Institute Header
        story.append(Paragraph(institute.get('institute_name', 'School Name'), title_style))
        story.append(Paragraph(institute.get('target_line', ''), center_style))
        story.append(Paragraph(institute.get('address', ''), center_style))
        story.append(Paragraph(f"Tel: {institute.get('phone_number', '')}", center_style))
        story.append(Spacer(1, 5))
        
        # Receipt Title
        story.append(Paragraph("=" * 35, normal_style))
        story.append(Paragraph("SALARY PAYMENT SLIP", title_style))
        story.append(Paragraph("=" * 35, normal_style))
        story.append(Spacer(1, 5))
        
        # Employee Details
        emp_data = [
            ['Receipt No:', payment['receipt_number']],
            ['Date:', payment['payment_date']],
            ['Month:', payment['payment_month']],
            ['', ''],
            ['Employee ID:', employee['employee_id']],
            ['Employee Name:', employee['name']],
            ['Role:', employee.get('role', 'Staff').replace('_', ' ').title()],
        ]
        
        t = Table(emp_data, colWidths=[30*mm, 40*mm])
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
        
        # Salary Details
        story.append(Paragraph("-" * 35, normal_style))
        
        salary_data = [
            ['Gross Salary:', f"UGX {float(payment.get('gross_salary', 0)):,.0f}"],
        ]
        
        if payment.get('deductions', 0) > 0:
            salary_data.append(['Deductions:', f"- UGX {float(payment.get('deductions', 0)):,.0f}"])
        
        if payment.get('bonuses', 0) > 0:
            salary_data.append(['Bonuses:', f"+ UGX {float(payment.get('bonuses', 0)):,.0f}"])
        
        salary_data.append(['', ''])
        salary_data.append(['NET PAYABLE:', f"UGX {float(payment['amount']):,.0f}"])
        
        t2 = Table(salary_data, colWidths=[30*mm, 40*mm])
        t2.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        
        # Make the last row bold
        t2.setStyle(TableStyle([
            ('FONTNAME', (0, -1), (1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, -1), (1, -1), 11),
        ]))
        
        story.append(t2)
        
        # Payment Method
        story.append(Spacer(1, 5))
        story.append(Paragraph(f"Payment Method: {payment['payment_method'].upper()}", normal_style))
        
        # Notes
        if payment.get('notes'):
            story.append(Spacer(1, 5))
            story.append(Paragraph(f"Notes: {payment['notes']}", normal_style))
        
        story.append(Paragraph("-" * 35, normal_style))
        
        # Footer
        story.append(Spacer(1, 8))
        story.append(Paragraph("Thank you for your service!", center_style))
        story.append(Paragraph("This is a computer generated payslip", center_style))
        story.append(Paragraph("No signature required", center_style))
        
        doc.build(story)
        buffer.seek(0)
        
        return send_file(
            buffer,
            as_attachment=False,
            download_name=f"payslip_{receipt_number}.pdf",
            mimetype='application/pdf'
        )
        
    except Exception as e:
        print(f"Error generating payslip: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@payroll_bp.route('/api/download-payroll-pdf', methods=['POST'])
@login_required
def download_payroll_pdf():
    """Download payroll summary as PDF"""
    user = session.get('user')
    institute = get_institute_id(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        employees = data.get('employees', [])
        month = data.get('month')
        
        if not employees:
            return jsonify({'success': False, 'message': 'No data to export'}), 400
        
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4,
                                rightMargin=20, leftMargin=20,
                                topMargin=20, bottomMargin=20)
        
        story = []
        styles = getSampleStyleSheet()
        
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=16,
            textColor=colors.HexColor('#ffa500'),
            alignment=1,
            spaceAfter=20
        )
        
        if institute.get('logo_url'):
            try:
                response = requests.get(institute['logo_url'], timeout=5)
                img_data = response.content
                img_buffer = io.BytesIO(img_data)
                pil_img = PILImage.open(img_buffer)
                
                with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
                    pil_img.save(tmp.name)
                    logo = Image(tmp.name, width=1.5*inch, height=1.5*inch)
                    logo.hAlign = 'CENTER'
                    story.append(logo)
                    os.unlink(tmp.name)
            except:
                pass
        
        story.append(Paragraph(institute.get('institute_name', 'School Name'), title_style))
        story.append(Paragraph(institute.get('address', ''), styles['Normal']))
        story.append(Paragraph(f"Tel: {institute.get('phone_number', '')}", styles['Normal']))
        story.append(Spacer(1, 10))
        
        story.append(Paragraph(f"PAYROLL SUMMARY - {month}", title_style))
        story.append(Spacer(1, 10))
        
        table_data = [
            ['S/N', 'Employee ID', 'Employee Name', 'Gross Salary', 'Deductions', 'Bonuses', 'Net Pay (UGX)']
        ]
        
        total_gross = 0
        total_deductions = 0
        total_bonuses = 0
        total_net = 0
        
        for idx, emp in enumerate(employees, 1):
            gross = float(emp.get('monthly_salary', 0))
            deductions = float(emp.get('deductions', 0))
            bonuses = float(emp.get('bonuses', 0))
            net = gross - deductions + bonuses
            
            total_gross += gross
            total_deductions += deductions
            total_bonuses += bonuses
            total_net += net
            
            role_display = emp.get('role', 'Staff').replace('_', ' ').title() if emp.get('role') else 'Staff'
            
            table_data.append([
                str(idx),
                emp.get('employee_id', 'N/A'),
                emp.get('name', 'N/A'),
                f"{gross:,.0f}",
                f"{deductions:,.0f}",
                f"{bonuses:,.0f}",
                f"{net:,.0f}"
            ])
        
        table_data.append(['', '', '', '', '', 'TOTAL:', f"{total_net:,.0f}"])
        
        table = Table(table_data, colWidths=[0.5*inch, 1.2*inch, 1.8*inch, 1*inch, 1*inch, 1*inch, 1.2*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#ffa500')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('ALIGN', (3, 1), (6, -2), 'RIGHT'),
            ('ALIGN', (6, -1), (6, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#fef3c7')),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -2), 0.5, colors.grey),
            ('BOX', (0, -1), (-1, -1), 1, colors.black),
        ]))
        
        story.append(table)
        story.append(Spacer(1, 20))
        
        story.append(Paragraph(f"Generated on: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}", styles['Normal']))
        story.append(Paragraph("This is a computer generated document", styles['Normal']))
        
        doc.build(story)
        buffer.seek(0)
        
        return send_file(
            buffer,
            as_attachment=True,
            download_name=f"payroll_{month}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
            mimetype='application/pdf'
        )
        
    except Exception as e:
        print(f"Error generating PDF: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

def generate_salary_receipt_number(institute_id):
    """Generate unique salary receipt number"""
    try:
        year = datetime.now().strftime('%Y')
        month = datetime.now().strftime('%m')
        
        random_component = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
        
        response = supabase.table('salary_payments')\
            .select('id', count='exact')\
            .eq('institute_id', institute_id)\
            .gte('created_at', f"{year}-{month}-01")\
            .execute()
        
        count = (response.count or 0) + 1
        return f"SLP-{year}{month}-{random_component}-{str(count).zfill(3)}"
    except:
        return f"SLP-{datetime.now().strftime('%Y%m%d%H%M%S')}"