# printStudentList.py - Fixed Student List Printing Blueprint
from flask import Blueprint, render_template, request, jsonify, session, send_file
from supabase import create_client, Client
import os
from datetime import datetime
from functools import wraps
from dotenv import load_dotenv
import io
from xhtml2pdf import pisa
import requests

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

def get_institute(user_id):
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

@student_list_bp.route('/')
@login_required
def index():
    """Student List Page"""
    user = session.get('user')
    institute = get_institute(user['id'])
    
    if not institute:
        return render_template('student_list/index.html', classes=[], institute=None)
    
    try:
        # Get all classes for dropdown
        classes_response = supabase.table('classes')\
            .select('*')\
            .eq('institute_id', institute['id'])\
            .order('name')\
            .execute()
        
        classes = classes_response.data if classes_response.data else []
        
        return render_template('student_list/index.html', classes=classes, institute=institute)
        
    except Exception as e:
        print(f"Error loading student list page: {e}")
        return render_template('student_list/index.html', classes=[], institute=institute)

@student_list_bp.route('/api/students', methods=['GET'])
@login_required
def get_students():
    """Get students by class with fees balance"""
    user = session.get('user')
    institute = get_institute(user['id'])
    
    if not institute:
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
        
        # Then get student details from students table (which has institute_id)
        students_response = supabase.table('students')\
            .select('id, name, student_id, gender, photo_url, contact_number, email, status')\
            .eq('institute_id', institute['id'])\
            .in_('id', student_ids)\
            .execute()
        
        students = students_response.data if students_response.data else []
        
        # Get fees balance for each student
        students_with_balance = []
        total_fees_balance = 0
        male_count = 0
        female_count = 0
        
        for student in students:
            # Get fees balance from invoices
            invoices_response = supabase.table('invoices')\
                .select('balance')\
                .eq('student_id', student['id'])\
                .eq('institute_id', institute['id'])\
                .neq('status', 'paid')\
                .execute()
            
            balance = sum(float(inv['balance']) for inv in invoices_response.data) if invoices_response.data else 0
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
                'fees_balance': balance
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
@login_required
def export_pdf():
    """Export student list to PDF"""
    user = session.get('user')
    institute = get_institute(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        students = data.get('students', [])
        class_name = data.get('class_name', 'Students')
        academic_year = data.get('academic_year', datetime.now().year)
        summary = data.get('summary', {})
        
        if not students:
            return jsonify({'success': False, 'message': 'No students to export'}), 400
        
        html_content = generate_student_list_html(institute, students, class_name, academic_year, summary)
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
from datetime import datetime
from jinja2 import Template

def generate_student_list_html(institute, students, class_name, academic_year, summary):
    """
    Fixed version to prevent Student ID overflow.
    Uses 'table-layout: fixed' and 'word-wrap' to force text containment.
    """
    
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
        </style>
    </head>
    <body>
        <div class="header-container">
            <table>
                <tr>
                    <td style="width: 60px; border:none;">
                        {% if institute.logo_url %}<img src="{{ institute.logo_url }}" width="50" height="50">{% endif %}
                    </td>
                    <td class="text-center" style="border:none;">
                        <div class="institute-name">{{ institute.institute_name | upper }}</div>
                        <div style="font-style: italic; font-size: 8pt;">{{ institute.target_line }}</div>
                        <div style="font-size: 8pt;">{{ institute.address }} | {{ institute.phone_number }}</div>
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
                <td class="text-center">Total Students<br><strong>{{ summary.total_students }}</strong></td>
                <td class="text-center">M / F<br><strong>{{ summary.male_count }} / {{ summary.female_count }}</strong></td>
                <td class="text-center">Total Balance<br><strong>UGX {{ "{:,.0f}".format(summary.total_fees_balance) }}</strong></td>
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
                    <td class="bold">{{ student.student_id }}</td>
                    <td>{{ student.name | upper }}</td>
                    <td class="text-center">{{ student.gender[:1] | upper }}</td>
                    <td class="text-center">{{ student.contact_number }}</td>
                    <td class="text-right {{ 'text-danger' if student.fees_balance > 0 else 'text-success' }}">
                        {{ "{:,.0f}".format(student.fees_balance) }}
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

    return Template(html_template).render(
        institute=institute, students=students, 
        class_name=class_name, academic_year=academic_year, 
        summary=summary, generated_at=datetime.now().strftime('%d/%m/%Y')
    )
    
    
def convert_html_to_pdf(html_content):
    """Convert HTML to PDF using xhtml2pdf"""
    pdf_buffer = io.BytesIO()
    pisa_status = pisa.CreatePDF(io.StringIO(html_content), dest=pdf_buffer)
    
    if pisa_status.err:
        raise Exception("PDF generation failed")
    
    pdf_buffer.seek(0)
    return pdf_buffer