# printStudentList.py - Fixed Student List Printing Blueprint
# FIXED: Properly calculates balances including SchoolPay payments
from routes.permissions.permissions import role_required
from flask import Blueprint, render_template, request, jsonify, session, send_file
from supabase import create_client, Client
import os
from datetime import datetime
from functools import wraps
from dotenv import load_dotenv
import io
from xhtml2pdf import pisa
import requests
from routes.accounts.accounts import get_institute_id

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

student_list_bp = Blueprint('student_list', __name__, url_prefix='/student-list')

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Please login'}), 401
        return f(*args, **kwargs)
    return decorated_function


@student_list_bp.route('/')
@role_required(['owner', 'teacher', 'accountant'])
def index():
    """Student List Page"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return render_template('student_list/index.html', classes=[], institute=None)
    
    try:
        # Get institute details for display
        institute_response = supabase.table('institutes')\
            .select('*')\
            .eq('id', institute_id)\
            .execute()
        
        institute = institute_response.data[0] if institute_response.data else None
        
        # Get all classes for dropdown
        classes_response = supabase.table('classes')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('name')\
            .execute()
        
        classes = classes_response.data if classes_response.data else []
        
        return render_template('student_list/index.html', classes=classes, institute=institute)
        
    except Exception as e:
        print(f"Error loading student list page: {e}")
        return render_template('student_list/index.html', classes=[], institute=None)


@student_list_bp.route('/api/students', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_students():
    """
    Get students by class with fees balance.
    FIXED: Properly calculates balance including SchoolPay payments.
    Balance = Total Invoiced - Total Paid (including SchoolPay) - Total Discounts
    """
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        class_id = request.args.get('class_id')
        academic_year = request.args.get('academic_year', str(datetime.now().year))
        
        if not class_id:
            return jsonify({'success': False, 'message': 'Please select a class'}), 400
        
        # First get student IDs from class_enrollments for this class and academic year
        enrollments_response = supabase.table('class_enrollments')\
            .select('student_id')\
            .eq('class_id', class_id)\
            .eq('academic_year', int(academic_year))\
            .execute()
        
        student_ids = [e['student_id'] for e in enrollments_response.data] if enrollments_response.data else []
        
        if not student_ids:
            return jsonify({
                'success': True,
                'students': [],
                'summary': {
                    'total_students': 0,
                    'male_count': 0,
                    'female_count': 0,
                    'total_fees_balance': 0
                }
            })
        
        # Then get student details from students table
        students_response = supabase.table('students')\
            .select('id, name, student_id, gender, photo_url, contact_number, email, status')\
            .eq('institute_id', institute_id)\
            .in_('id', student_ids)\
            .execute()
        
        students = students_response.data if students_response.data else []
        
        # 🔥 FIX: Get fees balance for each student using ALL transactions
        students_with_balance = []
        total_fees_balance = 0
        male_count = 0
        female_count = 0
        
        for student in students:
            # 🔥 FIX: Get ALL invoices (both paid and unpaid) for this student
            invoices_response = supabase.table('invoices')\
                .select('total_amount')\
                .eq('student_id', student['id'])\
                .eq('institute_id', institute_id)\
                .execute()
            
            # Calculate total invoiced (positive amounts only)
            total_invoiced = 0.0
            for inv in (invoices_response.data or []):
                try:
                    amount = float(inv.get('total_amount', 0))
                    if amount > 0:
                        total_invoiced += amount
                except (ValueError, TypeError):
                    continue
            
            # 🔥 FIX: Get ALL payments (including SchoolPay) for this student
            payments_response = supabase.table('payments')\
                .select('amount')\
                .eq('student_id', student['id'])\
                .eq('institute_id', institute_id)\
                .execute()
            
            total_paid = 0.0
            for p in (payments_response.data or []):
                try:
                    amount = float(p.get('amount', 0))
                    if amount > 0:
                        total_paid += amount
                except (ValueError, TypeError):
                    continue
            
            # 🔥 FIX: Get ALL discounts for this student
            discounts_response = supabase.table('discounts')\
                .select('discount_amount')\
                .eq('student_id', student['id'])\
                .eq('institute_id', institute_id)\
                .execute()
            
            total_discount = 0.0
            for d in (discounts_response.data or []):
                try:
                    amount = float(d.get('discount_amount', 0))
                    if amount > 0:
                        total_discount += amount
                except (ValueError, TypeError):
                    continue
            
            # 🔥 FIX: Calculate actual balance = invoiced - paid - discount
            balance = total_invoiced - total_paid - total_discount
            
            # Don't show negative balance (overpayment)
            if balance < 0:
                balance = 0
            
            total_fees_balance += balance
            
            if student.get('gender') == 'Male':
                male_count += 1
            elif student.get('gender') == 'Female':
                female_count += 1
            
            students_with_balance.append({
                'id': student['id'],
                'student_id': student['student_id'],
                'name': student['name'],
                'gender': student.get('gender', 'N/A'),
                'contact_number': student.get('contact_number', 'N/A'),
                'email': student.get('email', 'N/A'),
                'photo_url': student.get('photo_url'),
                'status': student.get('status', 'active'),
                'fees_balance': balance,
                # 🔥 Optional debug info - remove for production
                '_debug_total_invoiced': total_invoiced,
                '_debug_total_paid': total_paid,
                '_debug_total_discount': total_discount
            })
        
        # Sort by name
        students_with_balance.sort(key=lambda x: x['name'])
        
        return jsonify({
            'success': True,
            'students': students_with_balance,
            'summary': {
                'total_students': len(students_with_balance),
                'male_count': male_count,
                'female_count': female_count,
                'total_fees_balance': total_fees_balance
            }
        })
        
    except Exception as e:
        print(f"Error getting students: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


@student_list_bp.route('/api/export-pdf', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def export_pdf():
    """Export student list to PDF"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        students = data.get('students', [])
        class_name = data.get('class_name', 'Students')
        academic_year = data.get('academic_year', datetime.now().year)
        summary = data.get('summary', {})
        
        if not students:
            return jsonify({'success': False, 'message': 'No students to export'}), 400
        
        # Sanitize students data - ensure each student is a dictionary
        sanitized_students = []
        for student in students:
            if student is None:
                student = {}
            if not isinstance(student, dict):
                student = {}
            # Ensure all expected fields exist with defaults
            sanitized_students.append({
                'student_id': student.get('student_id', 'N/A') or 'N/A',
                'name': student.get('name', 'N/A') or 'N/A',
                'gender': student.get('gender', 'N/A') or 'N/A',
                'contact_number': student.get('contact_number', 'N/A') or 'N/A',
                'fees_balance': student.get('fees_balance', 0) or 0,
                'class_name': student.get('class_name', '') or '',
                'academic_year': student.get('academic_year', '') or '',
            })
        
        # Get institute details for PDF header
        institute_response = supabase.table('institutes')\
            .select('*')\
            .eq('id', institute_id)\
            .execute()
        
        # FIX: Check if data exists and is not None
        institute = {}
        if institute_response.data and len(institute_response.data) > 0:
            institute = institute_response.data[0] or {}
        
        # Pass None if institute is empty, the generate function will handle it
        html_content = generate_student_list_html(institute, sanitized_students, class_name, academic_year, summary)
        pdf_buffer = convert_html_to_pdf(html_content)
        
        return send_file(
            pdf_buffer,
            as_attachment=True,
            download_name=f"student_list_{class_name}_{academic_year}_{datetime.now().strftime('%Y%m%d')}.pdf",
            mimetype='application/pdf'
        )
        
    except Exception as e:
        print(f"Error exporting PDF: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


def generate_student_list_html(institute, students, class_name, academic_year, summary):
    """
    Fixed version to handle None, null, and empty values properly.
    All dictionary access uses .get() with safe defaults.
    """
    
    # Ensure institute is a dictionary, even if None
    if institute is None:
        institute = {}
    
    # Ensure summary is a dictionary, even if None
    if summary is None:
        summary = {}
    
    # Safely get values with defaults
    institute_name = institute.get('institute_name', 'School Name') or 'School Name'
    institute_logo = institute.get('logo_url', '') or ''
    institute_target = institute.get('target_line', '') or ''
    institute_address = institute.get('address', '') or ''
    institute_phone = institute.get('phone_number', '') or ''
    
    # Ensure students is a list and each student is a dict with safe defaults
    if students is None:
        students = []
    
    # Safely get summary values
    total_students = summary.get('total_students', 0) or 0
    male_count = summary.get('male_count', 0) or 0
    female_count = summary.get('female_count', 0) or 0
    total_fees_balance = summary.get('total_fees_balance', 0) or 0
    
    html_template = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <style>
            @page { size: A4; margin: 1cm 1.2cm; }
            body {
                font-family: 'Helvetica', 'Arial', sans-serif;
                font-size: 8.5pt;
                color: #2d3436;
                line-height: 1.2;
                margin: 0;
            }

            /* THE FIX: Table layout fixed ensures columns respect the % width */
            table { 
                width: 100%; 
                border-collapse: collapse; 
                table-layout: fixed; 
            }

            /* THE FIX: Ensure every cell wraps long IDs or Names */
            td, th { 
                padding: 6px 4px; 
                border: 1px solid #e0e0e0;
                vertical-align: middle;
                word-wrap: break-word;      /* Legacy support */
                overflow-wrap: break-word;  /* Modern support */
                word-break: break-all;      /* Forces wrap even if no spaces exist */
            }

            th {
                background-color: #0d47a1;
                color: white;
                font-weight: bold;
                text-transform: uppercase;
                font-size: 7.5pt;
            }

            /* Specific column widths to balance the space */
            .col-index { width: 5%; }
            .col-id { width: 18%; }
            .col-name { width: 37%; }
            .col-sex { width: 8%; }
            .col-contact { width: 15%; }
            .col-balance { width: 17%; }

            .text-center { text-align: center; }
            .text-right { text-align: right; }
            .bold { font-weight: bold; }
            .text-danger { color: #b71c1c; font-weight: bold; }
            .text-success { color: #1b5e20; }

            /* Header and Branding */
            .header-container { border-bottom: 2px solid #0d47a1; margin-bottom: 15px; padding-bottom: 8px; }
            .institute-name { font-size: 15pt; font-weight: bold; color: #0d47a1; margin: 0; }
            
            .summary-table { background-color: #f8f9fa; margin-bottom: 15px; border: 1px solid #dee2e6; }
            .summary-table td { border: none; padding: 10px; border-right: 1px solid #dee2e6; }
            .summary-table td:last-child { border-right: none; }
            
            .sig-section { margin-top: 40px; }
            .sig-box { border: none; padding-top: 30px; }
            .sig-line { border-top: 1px solid #2d3436; width: 80%; margin: 0 auto; padding-top: 4px; font-size: 8pt; }
            
            .logo-container {
                width: 50px;
                height: 50px;
                display: flex;
                align-items: center;
                justify-content: center;
            }
            .logo-container img {
                max-width: 50px;
                max-height: 50px;
                object-fit: contain;
            }
        </style>
    </head>
    <body>
        <div class="header-container">
            <table>
                <tr>
                    <td style="width: 60px; border:none; vertical-align: middle;">
                        {% if logo_url and logo_url|string|trim %}
                        <div class="logo-container">
                            <img src="{{ logo_url }}" alt="Logo" width="50" height="50">
                        </div>
                        {% endif %}
                    </td>
                    <td class="text-center" style="border:none; vertical-align: middle;">
                        <div class="institute-name">{{ institute_name | upper }}</div>
                        {% if target_line and target_line|string|trim %}
                        <div style="font-style: italic; font-size: 8pt;">{{ target_line }}</div>
                        {% endif %}
                        <div style="font-size: 8pt;">
                            {% if address and address|string|trim %}{{ address }}{% endif %}
                            {% if address and address|string|trim and phone and phone|string|trim %} | {% endif %}
                            {% if phone and phone|string|trim %}{{ phone }}{% endif %}
                        </div>
                    </td>
                    <td style="width: 60px; border:none;"></td>
                </tr>
            </table>
        </div>

        <div class="text-center" style="margin-bottom: 15px;">
            <div style="font-size: 12pt; font-weight: bold; color: #0d47a1;">STUDENT ENROLLMENT LIST</div>
            <div>Class: <strong>{{ class_name }}</strong> | Academic Year: <strong>{{ academic_year }}</strong></div>
        </div>

        <table class="summary-table">
            <tr>
                <td class="text-center">Total Students<br><strong>{{ total_students }}</strong></td>
                <td class="text-center">M / F<br><strong>{{ male_count }} / {{ female_count }}</strong></td>
                <td class="text-center">Total Balance<br><strong>UGX {{ total_fees_balance_formatted }}</strong></td>
            </tr>
        </table>

        <table>
            <thead>
                <tr>
                    <th class="col-index">#</th>
                    <th class="col-id">Student ID</th>
                    <th class="col-name">Full Name</th>
                    <th class="col-sex text-center">Sex</th>
                    <th class="col-contact text-center">Contact</th>
                    <th class="col-balance text-right">Balance</th>
                </tr>
            </thead>
            <tbody>
                {% for student in students %}
                <tr>
                    <td class="text-center">{{ loop.index }}</td>
                    <td class="bold">{{ student.get('student_id', 'N/A') }}</td>
                    <td>{{ student.get('name', 'N/A') | upper }}</td>
                    <td class="text-center">{{ (student.get('gender', 'N/A')[:1]) | upper }}</td>
                    <td class="text-center">{{ student.get('contact_number', 'N/A') }}</td>
                    <td class="text-right {{ 'text-danger' if student.get('fees_balance', 0)|float > 0 else 'text-success' }}">
                        {{ "{:,.0f}".format(student.get('fees_balance', 0)|float) }}
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>

        <div class="sig-section">
            <table>
                <tr>
                    <td class="sig-box text-center" style="border:none;">
                        <div class="sig-line">Class Teacher</div>
                    </td>
                    <td class="sig-box text-center" style="border:none;">
                        <div class="sig-line">Accounts Office</div>
                    </td>
                    <td class="sig-box text-center" style="border:none;">
                        <div class="sig-line">Head Teacher / Stamp</div>
                    </td>
                </tr>
            </table>
        </div>
    </body>
    </html>
    """

    from jinja2 import Template
    
    # Format the total fees balance with commas
    total_fees_balance_formatted = "{:,.0f}".format(total_fees_balance or 0)
    
    return Template(html_template).render(
        institute_name=institute_name,
        logo_url=institute_logo,
        target_line=institute_target,
        address=institute_address,
        phone=institute_phone,
        students=students,
        class_name=class_name or 'Class',
        academic_year=academic_year or '2026',
        total_students=total_students,
        male_count=male_count,
        female_count=female_count,
        total_fees_balance_formatted=total_fees_balance_formatted,
        generated_at=datetime.now().strftime('%d/%m/%Y')
    )


def convert_html_to_pdf(html_content):
    """Convert HTML to PDF using xhtml2pdf"""
    pdf_buffer = io.BytesIO()
    pisa_status = pisa.CreatePDF(io.StringIO(html_content), dest=pdf_buffer)
    
    if pisa_status.err:
        raise Exception("PDF generation failed")
    
    pdf_buffer.seek(0)
    return pdf_buffer


@student_list_bp.route('/api/student/<student_id>', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_student(student_id):
    """Get a single student's details for editing"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        response = supabase.table('students')\
            .select('id, name, student_id, gender, contact_number, email, photo_url, status')\
            .eq('id', student_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if not response.data:
            return jsonify({'success': False, 'message': 'Student not found'}), 404
        
        return jsonify({
            'success': True,
            'student': response.data[0]
        })
        
    except Exception as e:
        print(f"Error getting student: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@student_list_bp.route('/api/student/<student_id>', methods=['PUT'])
@role_required(['owner', 'teacher', 'accountant'])
def update_student(student_id):
    """Update student details (name and contact_number)"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        name = data.get('name', '').strip()
        contact_number = data.get('contact_number', '').strip()
        
        if not name:
            return jsonify({'success': False, 'message': 'Student name is required'}), 400
        
        # Check if student exists and belongs to this institute
        check_response = supabase.table('students')\
            .select('id')\
            .eq('id', student_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if not check_response.data:
            return jsonify({'success': False, 'message': 'Student not found'}), 404
        
        # Update student
        update_data = {
            'name': name,
            'contact_number': contact_number,
            'updated_at': datetime.now().isoformat()
        }
        
        response = supabase.table('students')\
            .update(update_data)\
            .eq('id', student_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        # Get updated student data
        updated_response = supabase.table('students')\
            .select('id, name, student_id, gender, contact_number, email, photo_url, status')\
            .eq('id', student_id)\
            .execute()
        
        return jsonify({
            'success': True,
            'message': 'Student updated successfully',
            'student': updated_response.data[0] if updated_response.data else None
        })
        
    except Exception as e:
        print(f"Error updating student: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


# ============================================================================
# 🔥 NEW: API endpoint to get student balance (for Payment Management page)
# ============================================================================
@student_list_bp.route('/api/student-balance/<student_id>', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_student_balance(student_id):
    """
    Get a student's current balance including SchoolPay payments.
    Used by Payment Management page to show accurate balance.
    """
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Get ALL invoices for this student
        invoices_response = supabase.table('invoices')\
            .select('total_amount')\
            .eq('student_id', student_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        total_invoiced = 0.0
        for inv in (invoices_response.data or []):
            try:
                amount = float(inv.get('total_amount', 0))
                if amount > 0:
                    total_invoiced += amount
            except (ValueError, TypeError):
                continue
        
        # Get ALL payments (including SchoolPay) for this student
        payments_response = supabase.table('payments')\
            .select('amount')\
            .eq('student_id', student_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        total_paid = 0.0
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
        
        total_discount = 0.0
        for d in (discounts_response.data or []):
            try:
                amount = float(d.get('discount_amount', 0))
                if amount > 0:
                    total_discount += amount
            except (ValueError, TypeError):
                continue
        
        # Calculate balance
        balance = total_invoiced - total_paid - total_discount
        if balance < 0:
            balance = 0
        
        return jsonify({
            'success': True,
            'student_id': student_id,
            'balance': balance,
            'total_invoiced': total_invoiced,
            'total_paid': total_paid,
            'total_discount': total_discount
        })
        
    except Exception as e:
        print(f"Error getting student balance: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500