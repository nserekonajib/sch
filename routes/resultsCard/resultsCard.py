from routes.permissions.permissions import role_required
# resultsCard.py - Student Results Card Generation with Class-wise PDF Merge
from flask import Blueprint, render_template, request, jsonify, session, send_file
from supabase import create_client, Client
import os
import uuid
from datetime import datetime
import json
from functools import wraps
from dotenv import load_dotenv
import io
from xhtml2pdf import pisa
import requests
from PyPDF2 import PdfMerger
import tempfile
from routes.accounts.accounts import get_institute_id as get_institute_id_func

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

results_bp = Blueprint('results', __name__, url_prefix='/results')

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Please login'}), 401
        return f(*args, **kwargs)
    return decorated_function

def get_ordinal_suffix(n):
    if 11 <= n % 100 <= 13:
        return 'th'
    return {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')

def get_grade_comment(percentage, grading_settings):
    for grade in grading_settings:
        if grade['min_percentage'] <= percentage <= grade['max_percentage']:
            return grade['grade_name'], grade['status']
    return 'N/A', 'No Grade Assigned'

@results_bp.route('/r')
@role_required(['owner', 'teacher', 'accountant'])
def r():
    return render_template('results/index2.html')

@results_bp.route('/')
@role_required(['owner', 'teacher', 'accountant'])
def index():
    user = session.get('user')
    institute_id = get_institute_id_func(user['id'])
    
    if not institute_id:
        return render_template('results/index.html', exams=[], classes=[], students=[], institute=None)
    
    try:
        # Get institute details
        institute_response = supabase.table('institutes')\
            .select('*')\
            .eq('id', institute_id)\
            .execute()
        
        institute = institute_response.data[0] if institute_response.data else {}
        
        exams_response = supabase.table('exams')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('created_at', desc=True)\
            .execute()
        
        exams = exams_response.data if exams_response.data else []
        
        classes_response = supabase.table('classes')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('name')\
            .execute()
        
        classes = classes_response.data if classes_response.data else []
        
        # Direct query to students table - no class_enrollments
        students_response = supabase.table('students')\
            .select('id, name, student_id, class_id, classes(name), photo_url, gender, status')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')\
            .order('name')\
            .execute()
        
        students = students_response.data if students_response.data else []
        
        # Process students to ensure class name is accessible
        for student in students:
            if student.get('classes') and isinstance(student['classes'], dict):
                student['class_name'] = student['classes'].get('name', 'N/A')
            else:
                student['class_name'] = 'N/A'
        
        return render_template('results/index.html', exams=exams, classes=classes, students=students, institute=institute)
        
    except Exception as e:
        print(f"Error loading results page: {e}")
        import traceback
        traceback.print_exc()
        return render_template('results/index.html', exams=[], classes=[], students=[], institute=None)

def generate_single_student_pdf(student_id, exam_ids, term, year, institute_id, grading):
    """Generate PDF for a single student and return as BytesIO"""
    try:
        # Get institute details
        institute_response = supabase.table('institutes')\
            .select('*')\
            .eq('id', institute_id)\
            .execute()
        
        institute = institute_response.data[0] if institute_response.data else {}
        
        # Get student details with class info - direct query
        student_response = supabase.table('students')\
            .select('*, classes(id, name)')\
            .eq('id', student_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if not student_response.data:
            print(f"Student not found: {student_id}")
            return None
        
        student = student_response.data[0]
        
        # Get exam details
        exams_response = supabase.table('exams')\
            .select('*')\
            .in_('id', exam_ids)\
            .eq('institute_id', institute_id)\
            .execute()
        
        exams = exams_response.data if exams_response.data else []
        
        # Get class_id from student record
        class_id = student.get('class_id')
        if not class_id:
            print(f"No class_id for student: {student_id}")
            return None
        
        # Get subjects for student's class
        subjects_response = supabase.table('class_subjects')\
            .select('*, subjects(id, name)')\
            .eq('class_id', class_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        subjects = subjects_response.data if subjects_response.data else []
        
        if not subjects:
            print(f"No subjects found for class: {class_id}")
            # Return a simple PDF with message instead of None
            return generate_empty_results_pdf(student, institute, term, year, "No subjects configured for this class")
        
        # Get marks for each exam
        all_marks = {}
        for exam in exams:
            marks_response = supabase.table('exam_marks')\
                .select('*')\
                .eq('exam_id', exam['id'])\
                .eq('student_id', student_id)\
                .eq('institute_id', institute_id)\
                .execute()
            
            marks_dict = {}
            for mark in marks_response.data if marks_response.data else []:
                marks_dict[mark['subject_id']] = float(mark['obtained_marks'])
            all_marks[exam['id']] = marks_dict
        
        # Prepare subject data
        subject_results = []
        subject_totals = {}
        
        for subject in subjects:
            subject_name = subject['subjects']['name'] if subject.get('subjects') else 'N/A'
            max_marks = float(subject['marks'])
            
            subject_data = {
                'name': subject_name,
                'max_marks': max_marks,
                'exam_marks': []
            }
            
            total_obtained = 0
            total_possible = 0
            
            for exam in exams:
                exam_id = exam['id']
                obtained = all_marks.get(exam_id, {}).get(subject['subject_id'])
                subject_data['exam_marks'].append({
                    'exam_name': exam['exam_name'],
                    'obtained': obtained if obtained is not None else '-',
                    'max': max_marks
                })
                
                if obtained is not None:
                    total_obtained += obtained
                    total_possible += max_marks
            
            if total_possible > 0:
                subject_average = (total_obtained / total_possible) * 100
                subject_data['average'] = round(subject_average, 1)
                subject_grade, subject_comment = get_grade_comment(subject_average, grading)
                subject_data['grade'] = subject_grade
                subject_data['comment'] = subject_comment
                subject_totals[subject_name] = {
                    'obtained': total_obtained,
                    'possible': total_possible,
                    'average': subject_average
                }
            else:
                subject_data['average'] = 0
                subject_data['grade'] = 'N/A'
                subject_data['comment'] = 'No Data'
            
            subject_results.append(subject_data)
        
        # Calculate overall totals
        total_obtained_all = sum([s['obtained'] for s in subject_totals.values()])
        total_possible_all = sum([s['possible'] for s in subject_totals.values()])
        overall_percentage = (total_obtained_all / total_possible_all * 100) if total_possible_all > 0 else 0
        
        overall_grade, overall_comment = get_grade_comment(overall_percentage, grading)
        
        # Get class students directly from students table by class_id
        class_students_response = supabase.table('students')\
            .select('id, name')\
            .eq('class_id', class_id)\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')\
            .execute()
        
        class_students = class_students_response.data if class_students_response.data else []
        
        # Calculate percentages for all students in class
        class_percentages = []
        for class_student in class_students:
            student_total = 0
            student_possible = 0
            
            for subject in subjects:
                subject_id = subject['subject_id']
                max_marks = float(subject['marks'])
                
                for exam in exams:
                    exam_id = exam['id']
                    marks_resp = supabase.table('exam_marks')\
                        .select('obtained_marks')\
                        .eq('exam_id', exam_id)\
                        .eq('student_id', class_student['id'])\
                        .eq('subject_id', subject_id)\
                        .eq('institute_id', institute_id)\
                        .execute()
                    
                    if marks_resp.data:
                        student_total += float(marks_resp.data[0]['obtained_marks'])
                        student_possible += max_marks
            
            percentage = (student_total / student_possible * 100) if student_possible > 0 else 0
            class_percentages.append({
                'student_id': class_student['id'],
                'name': class_student['name'],
                'percentage': percentage
            })
        
        class_percentages.sort(key=lambda x: x['percentage'], reverse=True)
        
        position = 1
        for idx, cp in enumerate(class_percentages, 1):
            if cp['student_id'] == student_id:
                position = idx
                break
        
        total_students = len(class_percentages)
        
        # Get class name from student's classes relation
        class_name = student.get('classes', {}).get('name') if student.get('classes') else 'N/A'
        
        result_data = {
            'institute': institute,
            'student': student,
            'class_name': class_name,
            'exams': exams,
            'subjects': subject_results,
            'overall_percentage': round(overall_percentage, 1),
            'total_obtained': int(total_obtained_all),
            'total_possible': int(total_possible_all),
            'grade': overall_grade,
            'comment': overall_comment,
            'position': position,
            'total_students': total_students,
            'term': term,
            'year': year
        }
        
        html_content = generate_report_card_html(result_data)
        pdf_buffer = convert_html_to_pdf(html_content)
        
        return pdf_buffer
        
    except Exception as e:
        print(f"Error generating PDF for student {student_id}: {e}")
        import traceback
        traceback.print_exc()
        return None

def generate_empty_results_pdf(student, institute, term, year, message):
    """Generate a PDF for a student with no results"""
    try:
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                @page {{ size: A4; margin: 1cm; }}
                body {{ font-family: Arial, sans-serif; text-align: center; padding: 50px; }}
                .message {{ color: #ffa500; font-size: 14pt; margin-top: 50px; }}
                .info {{ margin-top: 30px; font-size: 10pt; }}
            </style>
        </head>
        <body>
            <h2>{institute.get('institute_name', 'Academic Institute')}</h2>
            <h3>Student Report Card</h3>
            <div class="info">
                <p><strong>Student Name:</strong> {student.get('name', 'N/A')}</p>
                <p><strong>Student ID:</strong> {student.get('student_id', 'N/A')}</p>
                <p><strong>Term/Year:</strong> {term} / {year}</p>
            </div>
            <div class="message">
                <p>{message}</p>
                <p>Please contact the administrator to configure subjects and marks.</p>
            </div>
        </body>
        </html>
        """
        return convert_html_to_pdf(html)
    except Exception as e:
        print(f"Error generating empty results PDF: {e}")
        return None

@results_bp.route('/generate-class', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def generate_class_results():
    """Generate merged PDF for entire class"""
    user = session.get('user')
    institute_id = get_institute_id_func(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        class_id = data.get('class_id')
        exam_ids = data.get('exam_ids', [])
        term = data.get('term', '')
        year = data.get('year', datetime.now().year)
        
        if not class_id:
            return jsonify({'success': False, 'message': 'Please select a class'}), 400
        
        if not exam_ids:
            return jsonify({'success': False, 'message': 'Please select at least one exam'}), 400
        
        if not term:
            return jsonify({'success': False, 'message': 'Please enter the term'}), 400
        
        # Get all students in the class directly from students table
        students_response = supabase.table('students')\
            .select('id, name, student_id')\
            .eq('class_id', class_id)\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')\
            .order('name')\
            .execute()
        
        students = students_response.data if students_response.data else []
        
        if not students:
            return jsonify({'success': False, 'message': 'No active students found in this class'}), 404
        
        # Get grading settings
        grading_response = supabase.table('exam_grading')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('min_percentage', desc=True)\
            .execute()
        
        grading = grading_response.data if grading_response.data else []
        
        # Create a list to store PDF buffers
        pdf_buffers = []
        successful_students = []
        failed_students = []
        
        # Generate PDF for each student
        for student in students:
            print(f"Generating PDF for student: {student['name']}")
            pdf_buffer = generate_single_student_pdf(
                student['id'], exam_ids, term, year, institute_id, grading
            )
            
            if pdf_buffer:
                pdf_buffers.append(pdf_buffer)
                successful_students.append(student['name'])
            else:
                failed_students.append(student['name'])
        
        if not pdf_buffers:
            return jsonify({'success': False, 'message': 'Failed to generate any report cards'}), 500
        
        # Merge PDFs
        merger = PdfMerger()
        for pdf_buffer in pdf_buffers:
            pdf_buffer.seek(0)
            merger.append(pdf_buffer)
        
        # Create merged PDF buffer
        merged_buffer = io.BytesIO()
        merger.write(merged_buffer)
        merger.close()
        merged_buffer.seek(0)
        
        # Get class name
        class_response = supabase.table('classes')\
            .select('name')\
            .eq('id', class_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        class_name = class_response.data[0]['name'] if class_response.data else 'Class'
        
        return send_file(
            merged_buffer,
            as_attachment=True,
            download_name=f"report_cards_{class_name}_{term}_{year}.pdf",
            mimetype='application/pdf'
        )
        
    except Exception as e:
        print(f"Error generating class results: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@results_bp.route('/generate', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def generate_results():
    """Generate single student report card"""
    user = session.get('user')
    institute_id = get_institute_id_func(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        student_id = data.get('student_id')
        exam_ids = data.get('exam_ids', [])
        term = data.get('term', '')
        year = data.get('year', datetime.now().year)
        
        if not student_id:
            return jsonify({'success': False, 'message': 'Please select a student'}), 400
        
        if not exam_ids:
            return jsonify({'success': False, 'message': 'Please select at least one exam'}), 400
        
        # Get grading settings
        grading_response = supabase.table('exam_grading')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('min_percentage', desc=True)\
            .execute()
        
        grading = grading_response.data if grading_response.data else []
        
        pdf_buffer = generate_single_student_pdf(student_id, exam_ids, term, year, institute_id, grading)
        
        if not pdf_buffer:
            return jsonify({'success': False, 'message': 'Failed to generate report card'}), 500
        
        # Get student name
        student_response = supabase.table('students')\
            .select('name')\
            .eq('id', student_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        student_name = student_response.data[0]['name'] if student_response.data else 'Student'
        
        return send_file(
            pdf_buffer,
            as_attachment=True,
            download_name=f"report_card_{student_name}_{term}_{year}.pdf",
            mimetype='application/pdf'
        )
        
    except Exception as e:
        print(f"Error generating results: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500
    
def generate_report_card_html(data):
    """Generate xhtml2pdf-compliant HTML report card - Single Page, Horizontal Summary, Clean B&W"""
    
    suffix = get_ordinal_suffix(data['position'])
    
    # Build subject rows with exam marks
    subject_rows = ""
    for subject in data['subjects']:
        exam_cells = ""
        for exam_mark in subject['exam_marks']:
            exam_cells += f'<td class="text-center">{exam_mark["obtained"]}</td>'
        
        subject_rows += f"""
        <tr>
            <td class="text-left subject-cell"><strong>{subject['name']}</strong></td>
            {exam_cells}
            <td class="text-center"><strong>{subject['average']}</strong></td>
            <td class="text-center grade-cell">{subject['grade']}</td>
            <td class="text-left remarks-cell">{subject['comment']}</td>
            <td class="text-center initials-cell">{subject.get('initials', '')}</td>
        </tr>
        """
    
    # Build exam headers dynamically
    exam_headers = ""
    for exam in data['exams']:
        exam_headers += f'<th class="text-center exam-header">{exam["exam_name"]}</th>'
    
    exams_count = len(data['exams'])
    
    # Logo handling - larger and more visible
    logo_url = data["institute"].get("logo_url")
    if logo_url:
        logo_html = f'<img src="{logo_url}" width="80" height="80" style="object-fit: contain; display: block;" />'
    else:
        logo_html = '<div style="width:80px; height:80px; border:1px solid #000; background:#f9f9f9; text-align:center; line-height:80px; font-size:10px;">LOGO</div>'
    
    # Student photo - NO visible border, transparent frame
    student_photo_url = data['student'].get('photo_url')
    if student_photo_url:
        student_photo_html = f'<img src="{student_photo_url}" width="100" height="100" style="object-fit: cover; border: none; display: block;" />'
    else:
        student_photo_html = '<div style="width:100px; height:100px; background:#f0f0f0; text-align:center; line-height:100px; font-size:40px; color:#aaa; border: none;">📷</div>'
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Academic Report Card</title>
        <style>
            @page {{
                size: A4;
                margin: 0.8cm 0.8cm;
            }}
            body {{
                font-family: 'Times New Roman', 'Georgia', 'Helvetica', Arial, sans-serif;
                font-size: 9.5pt;
                color: #000000;
                line-height: 1.2;
                background: white;
                margin: 0;
                padding: 0;
            }}
            .text-center {{ text-align: center; }}
            .text-left {{ text-align: left; }}
            .text-right {{ text-align: right; }}
            .bold {{ font-weight: 700; }}
            
            /* MAIN CONTAINER - TIGHT BUT READABLE */
            .report-container {{
                width: 100%;
                border: 1px solid #000000;
                padding: 15px 18px;
                background: #ffffff;
            }}
            
            /* HEADER SECTION */
            .header-section {{
                border-bottom: 2px solid #000000;
                margin-bottom: 14px;
                padding-bottom: 10px;
            }}
            .institute-name {{
                font-size: 18pt;
                font-weight: 800;
                letter-spacing: 0.5px;
                text-transform: uppercase;
                color: #000000;
            }}
            .motto-text {{
                font-style: italic;
                font-size: 8pt;
                color: #333;
                margin-top: 2px;
            }}
            .address-text {{
                font-size: 6.5pt;
                color: #444;
                margin-top: 3px;
            }}
            .report-badge {{
                font-size: 10pt;
                font-weight: 800;
                text-transform: uppercase;
                border: 1px solid #000;
                padding: 4px 10px;
                display: inline-block;
                letter-spacing: 1px;
            }}
            
            /* STUDENT INFO - MINIMAL BORDERS */
            .info-section {{
                margin-bottom: 14px;
            }}
            .info-grid {{
                width: 100%;
                border-collapse: collapse;
                border: 1px solid #000;
            }}
            .info-grid td {{
                border: 1px solid #aaa;
                padding: 6px 8px;
                vertical-align: middle;
            }}
            .info-label {{
                font-size: 7.5pt;
                font-weight: 700;
                text-transform: uppercase;
                background-color: #f0f0f0;
                width: 100px;
            }}
            .info-value {{
                font-size: 10pt;
                font-weight: 600;
                color: #000;
            }}
            .position-badge {{
                background-color: #000000;
                color: white;
                padding: 2px 10px;
                display: inline-block;
                font-weight: 700;
                font-size: 9pt;
            }}
            .photo-cell {{
                text-align: center;
                vertical-align: middle;
                width: 120px;
            }}
            
            /* RESULTS TABLE - COMPACT */
            .results-table {{
                width: 100%;
                border-collapse: collapse;
                margin: 12px 0;
                font-size: 8pt;
            }}
            .results-table th {{
                border: 1px solid #000000;
                background-color: #e8e8e8;
                padding: 6px 4px;
                font-weight: 800;
                text-transform: uppercase;
                font-size: 7.5pt;
            }}
            .results-table td {{
                border: 1px solid #aaa;
                padding: 5px 4px;
                vertical-align: middle;
            }}
            .subject-cell {{
                background-color: #fafaf5;
                font-weight: 700;
            }}
            .grade-cell {{
                font-weight: 700;
            }}
            .remarks-cell {{
                font-size: 7.5pt;
            }}
            .initials-cell {{
                font-family: monospace;
                font-weight: 600;
            }}
            .total-row {{
                background-color: #ecece5;
                font-weight: 800;
                border-top: 2px solid #000;
            }}
            .total-row td {{
                font-weight: 800;
            }}
            
            /* HORIZONTAL SUMMARY TABLE - KEY CHANGE */
            .summary-horizontal {{
                width: 100%;
                border-collapse: collapse;
                margin: 12px 0;
                border: 1px solid #000;
            }}
            .summary-horizontal th {{
                background-color: #e0e0e0;
                border: 1px solid #000;
                padding: 8px 5px;
                font-size: 8pt;
                font-weight: 800;
                text-transform: uppercase;
            }}
            .summary-horizontal td {{
                border: 1px solid #aaa;
                padding: 8px 5px;
                text-align: center;
                font-size: 11pt;
                font-weight: 800;
            }}
            .summary-label {{
                background-color: #f0f0f0;
                font-weight: 700;
                font-size: 8pt;
                text-transform: uppercase;
            }}
            
            /* GRADING SCALE - COMPACT */
            .grading-reference {{
                margin: 10px 0 8px 0;
                border-top: 1px solid #ccc;
                border-bottom: 1px solid #ccc;
                padding: 5px 0;
                background: #fefcf8;
            }}
            .grading-grid {{
                display: flex;
                flex-wrap: wrap;
                justify-content: space-between;
                gap: 3px;
                font-size: 6pt;
                font-family: monospace;
            }}
            .grade-item {{
                padding: 1px 6px;
                border-right: 1px solid #ddd;
            }}
            
            /* COMMENTS SECTION - SIMPLE LINES */
            .comments-section {{
                margin: 12px 0 10px 0;
            }}
            .comment-line {{
                width: 100%;
                border-collapse: collapse;
                margin-bottom: 5px;
            }}
            .comment-line td {{
                border-bottom: 1px solid #000;
                padding: 5px 2px;
            }}
            .comment-label {{
                font-weight: 800;
                font-size: 8pt;
                text-transform: uppercase;
                width: 140px;
            }}
            
            /* SIGNATURES - 3 COLUMN */
            .signature-area {{
                margin-top: 18px;
                margin-bottom: 8px;
            }}
            .signature-flex {{
                width: 100%;
                display: table;
                border-collapse: collapse;
            }}
            .signature-col {{
                display: table-cell;
                text-align: center;
                width: 33%;
                padding-top: 18px;
            }}
            .sig-line {{
                border-top: 1px solid #000;
                width: 85%;
                margin: 0 auto 4px auto;
            }}
            .sig-label {{
                font-size: 8pt;
                font-weight: 700;
                text-transform: uppercase;
            }}
            
            /* NEXT TERM - RIGHT ALIGNED */
            .next-term-row {{
                margin: 8px 0;
                text-align: right;
                font-size: 8pt;
                font-weight: 600;
                border-top: 1px dashed #aaa;
                padding-top: 6px;
            }}
            
            /* FOOTER */
            .footer-note {{
                margin-top: 12px;
                text-align: center;
                font-size: 6pt;
                border-top: 1px solid #ccc;
                padding-top: 6px;
                color: #444;
                font-family: monospace;
            }}
            
            /* FORCE PAGE BREAK CONTROL */
            .keep-together {{
                page-break-inside: avoid;
            }}
        </style>
    </head>
    <body>
        <div class="report-container keep-together">
            <!-- HEADER: Institute + Logo -->
            <div class="header-section">
                <table width="100%" style="border-collapse: collapse;">
                    <tr>
                        <td width="15%" class="text-left">{logo_html}</td>
                        <td width="70%" class="text-center">
                            <div class="institute-name">{data["institute"].get("institute_name", "ACADEMIC INSTITUTION")}</div>
                            <div class="motto-text">{data["institute"].get("target_line", "Excellence in Education")}</div>
                            <div class="address-text">
                                {data["institute"].get("address", "")}<br>
                                Tel: {data["institute"].get("phone_number", "")} | Email: {data["institute"].get("email", "")}
                            </div>
                        </td>
                        <td width="15%" class="text-right">
                            <div class="report-badge">ACADEMIC<br>REPORT</div>
                        </td>
                    </tr>
                </table>
            </div>
            
            <!-- STUDENT INFORMATION + PHOTO (transparent border for photo) -->
            <div class="info-section">
                <table class="info-grid">
                    <tr>
                        <td width="75%">
                            <table width="100%" cellspacing="3">
                                <tr>
                                    <td class="info-label">STUDENT NAME</td>
                                    <td class="info-value">{data['student']['name']}</td>
                                    <td class="info-label">STUDENT ID</td>
                                    <td class="info-value">{data['student']['student_id']}</td>
                                </tr>
                                <tr>
                                    <td class="info-label">CLASS</td>
                                    <td class="info-value">{data['class_name']}</td>
                                    <td class="info-label">GENDER</td>
                                    <td class="info-value">{data['student'].get('gender', 'N/A')}</td>
                                </tr>
                                <tr>
                                    <td class="info-label">TERM / YEAR</td>
                                    <td class="info-value">{data['term']} / {data['year']}</td>
                                    <td class="info-label">POSITION</td>
                                    <td class="info-value"><span class="position-badge">{data['position']}{suffix} OUT OF {data['total_students']}</span></td>
                                </tr>
                            </table>
                        </td>
                        <td class="photo-cell" width="25%">
                            {student_photo_html}
                        </td>
                    </tr>
                </table>
            </div>
            
            <!-- MARKS TABLE -->
            <table class="results-table">
                <thead>
                    <tr>
                        <th width="18%" class="text-left">SUBJECT</th>
                        {exam_headers}
                        <th width="9%">AVG(%)</th>
                        <th width="8%">GRADE</th>
                        <th width="17%" class="text-left">REMARKS</th>
                        
                    </tr>
                </thead>
                <tbody>
                    {subject_rows}
                    <tr class="total-row" >
                        <td class="text-left"><strong>OVERALL SUMMARY</strong></td>
                        <td colspan="{exams_count}" class="text-center"><strong>{data['total_obtained']} / {data['total_possible']}</strong></td>
                        <td class="text-center"><strong>{data['overall_percentage']}</strong></td>
                        <td class="text-center"><strong>{data['grade']}</strong></td>
                        <td class="text-left"><strong>{data['comment']}</strong></td>
                        <td class="text-center">—</td>
                    </tr>
                </tbody>
            </table>
            
            <!-- HORIZONTAL SUMMARY TABLE (replaces 3 separate boxes) -->
            <table class="summary-horizontal">
                <tr>
                    <th width="33%">OVERALL PERCENTAGE</th>
                    <th width="33%">TOTAL MARKS</th>
                    <th width="34%">FINAL GRADE</th>
                </tr>
                <tr>
                    <td><strong>{data['overall_percentage']}%</strong></td>
                    <td><strong>{data['total_obtained']}</strong></td>
                    <td><strong>{data['grade']}</strong></td>
                </tr>
            </table>
            
            <!-- GRADING SYSTEM REFERENCE -->
            <div class="grading-reference">
                <div class="grading-grid">
                    <span class="grade-item"><strong>GRADING SCALE:</strong></span>
                    <span class="grade-item">80+ → D1</span>
                    <span class="grade-item">75-79 → D2</span>
                    <span class="grade-item">65-73 → C3</span>
                    <span class="grade-item">60-64 → C4</span>
                    <span class="grade-item">55-59 → C5</span>
                    <span class="grade-item">50-54 → C6</span>
                    <span class="grade-item">40-49 → P7</span>
                    <span class="grade-item">30-39 → P8</span>
                    <span class="grade-item">0-29 → F9</span>
                </div>
            </div>
            
            <!-- TEACHER & HEAD TEACHER COMMENTS (minimal) -->
            <div class="comments-section">
                <table class="comment-line">
                    <tr>
                        <td class="comment-label">CLASS TEACHER'S COMMENT:</td>
                        <td>_________________________________________</td>
                    </tr>
                </table>
                <table class="comment-line">
                    <tr>
                        <td class="comment-label">HEAD TEACHER'S COMMENT:</td>
                        <td>_________________________________________</td>
                    </tr>
                </table>
            </div>
            
            <!-- NEXT TERM BEGINS -->
            <div class="next-term-row">
                NEXT TERM BEGINS: _________________________________
            </div>
            
            <!-- FOOTER WITH MOTTO -->
            <div class="footer-note">
                {data["institute"].get("footer_motto", "Foundation for your digital ambitions")}<br>
                Generated: {datetime.now().strftime('%d/%m/%Y %H:%M')} | Report ID: {data['student']['student_id']}_{data['year']}_{data['term']}
            </div>
        </div>
    </body>
    </html>
    """
    
    return html


def convert_html_to_pdf(html_content):
    """Convert HTML to PDF using xhtml2pdf with professional settings"""
    import io
    from xhtml2pdf import pisa
    
    pdf_buffer = io.BytesIO()
    
    pisa_status = pisa.CreatePDF(
        io.StringIO(html_content), 
        dest=pdf_buffer,
        encoding='UTF-8',
        link_callback=None
    )
    
    if pisa_status.err:
        raise Exception(f"PDF generation failed: {pisa_status.err}")
    
    pdf_buffer.seek(0)
    return pdf_buffer