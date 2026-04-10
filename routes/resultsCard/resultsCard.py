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
@login_required
def r():
    return render_template('results/index2.html')
@results_bp.route('/')
@login_required
def index():
    user = session.get('user')
    institute = get_institute(user['id'])
    
    if not institute:
        return render_template('results/index.html', exams=[], classes=[], students=[], institute=None)
    
    try:
        exams_response = supabase.table('exams')\
            .select('*')\
            .eq('institute_id', institute['id'])\
            .order('created_at', desc=True)\
            .execute()
        
        exams = exams_response.data if exams_response.data else []
        
        classes_response = supabase.table('classes')\
            .select('*')\
            .eq('institute_id', institute['id'])\
            .order('name')\
            .execute()
        
        classes = classes_response.data if classes_response.data else []
        
        students_response = supabase.table('students')\
            .select('id, name, student_id, class_id, classes(name), photo_url, gender')\
            .eq('institute_id', institute['id'])\
            .eq('status', 'active')\
            .order('name')\
            .execute()
        
        students = students_response.data if students_response.data else []
        
        return render_template('results/index.html', exams=exams, classes=classes, students=students, institute=institute)
        
    except Exception as e:
        print(f"Error loading results page: {e}")
        return render_template('results/index.html', exams=[], classes=[], students=[], institute=institute)

def generate_single_student_pdf(student_id, exam_ids, term, year, institute, grading):
    """Generate PDF for a single student and return as BytesIO"""
    try:
        # Get student details
        student_response = supabase.table('students')\
            .select('*, classes(name)')\
            .eq('id', student_id)\
            .eq('institute_id', institute['id'])\
            .execute()
        
        if not student_response.data:
            return None
        
        student = student_response.data[0]
        
        # Get exam details
        exams_response = supabase.table('exams')\
            .select('*')\
            .in_('id', exam_ids)\
            .execute()
        print(exams_response)
        exams = exams_response.data if exams_response.data else []
        
        # Get subjects for student's class
        class_id = student.get('class_id')
        subjects_response = supabase.table('class_subjects')\
            .select('*, subjects(name)')\
            .eq('class_id', class_id)\
            .eq('institute_id', institute['id'])\
            .execute()
        
        subjects = subjects_response.data if subjects_response.data else []
        
        if not subjects:
            return None
        
        # Get marks for each exam
        all_marks = {}
        for exam in exams:
            marks_response = supabase.table('exam_marks')\
                .select('*')\
                .eq('exam_id', exam['id'])\
                .eq('student_id', student_id)\
                .eq('institute_id', institute['id'])\
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
        
        # Calculate position in class
        class_students_response = supabase.table('students')\
            .select('id, name')\
            .eq('class_id', class_id)\
            .eq('institute_id', institute['id'])\
            .eq('status', 'active')\
            .execute()
        
        class_students = class_students_response.data if class_students_response.data else []
        
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
                        .eq('institute_id', institute['id'])\
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
        
        result_data = {
            'institute': institute,
            'student': student,
            'class_name': student['classes']['name'] if student.get('classes') else 'N/A',
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
        return None

@results_bp.route('/generate-class', methods=['POST'])
@login_required
def generate_class_results():
    """Generate merged PDF for entire class"""
    user = session.get('user')
    institute = get_institute(user['id'])
    
    if not institute:
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
        
        # Get all students in the class
        students_response = supabase.table('students')\
            .select('id, name, student_id')\
            .eq('class_id', class_id)\
            .eq('institute_id', institute['id'])\
            .eq('status', 'active')\
            .order('name')\
            .execute()
        
        students = students_response.data if students_response.data else []
        
        if not students:
            return jsonify({'success': False, 'message': 'No students found in this class'}), 404
        
        # Get grading settings
        grading_response = supabase.table('exam_grading')\
            .select('*')\
            .eq('institute_id', institute['id'])\
            .order('min_percentage', desc=True)\
            .execute()
        
        grading = grading_response.data if grading_response.data else []
        
        # Create a list to store PDF buffers
        pdf_buffers = []
        successful_students = []
        failed_students = []
        
        # Generate PDF for each student
        for idx, student in enumerate(students):
            pdf_buffer = generate_single_student_pdf(
                student['id'], exam_ids, term, year, institute, grading
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
@login_required
def generate_results():
    """Generate single student report card"""
    user = session.get('user')
    institute = get_institute(user['id'])
    
    if not institute:
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
            .eq('institute_id', institute['id'])\
            .order('min_percentage', desc=True)\
            .execute()
        
        grading = grading_response.data if grading_response.data else []
        
        pdf_buffer = generate_single_student_pdf(student_id, exam_ids, term, year, institute, grading)
        
        if not pdf_buffer:
            return jsonify({'success': False, 'message': 'Failed to generate report card'}), 500
        
        # Get student name
        student_response = supabase.table('students')\
            .select('name')\
            .eq('id', student_id)\
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
    """Generate xhtml2pdf-compliant HTML report card"""
    
    suffix = get_ordinal_suffix(data['position'])
    
    subject_rows = ""
    for subject in data['subjects']:
        exam_cells = ""
        for exam_mark in subject['exam_marks']:
            exam_cells += f'<td class="text-center">{exam_mark["obtained"]}</td>'
        
        subject_rows += f"""
        <tr>
            <td class="text-left"><strong>{subject['name']}</strong></td>
            {exam_cells}
            <td class="text-center"><strong>{subject['average']}%</strong></td>
            <td class="text-center">{subject['grade']}</td>
            <td class="text-left">{subject['comment']}</td>
        </tr>
        """
    
    exam_headers = ""
    for exam in data['exams']:
        exam_headers += f'<th class="text-center">{exam["exam_name"]}</th>'
    
    logo_url = data["institute"].get("logo_url")
    logo_html = f'<img src="{logo_url}" width="60" height="60" style="object-fit: contain;" />' if logo_url else '<div style="width:60px;"></div>'
    
    student_photo_url = data['student'].get('photo_url')
    if student_photo_url:
        student_photo_html = f'<img src="{student_photo_url}" width="80" height="80" style="border-radius: 50%; object-fit: cover; border: 2px solid #1a237e;" />'
    else:
        student_photo_html = '<div style="width:80px; height:80px; background-color:#f0f2f5; border-radius:50%; text-align:center; line-height:80px;">📷</div>'
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            @page {{
                size: A4;
                margin: 0.8cm;
            }}
            body {{
                font-family: Helvetica, Arial, sans-serif;
                font-size: 9pt;
                color: #333;
                line-height: 1.2;
            }}
            .text-center {{ text-align: center; }}
            .text-left {{ text-align: left; }}
            .text-right {{ text-align: right; }}
            
            .header-table {{
                width: 100%;
                border-bottom: 2px solid #1a237e;
                margin-bottom: 15px;
                padding-bottom: 10px;
            }}
            .institute-name {{
                font-size: 18pt;
                font-weight: bold;
                color: #1a237e;
                text-transform: uppercase;
            }}
            .motto {{
                font-style: italic;
                color: #ffa500;
                font-size: 8pt;
            }}
            
            .info-table {{
                width: 100%;
                background-color: #f8f9fa;
                border: 1px solid #dee2e6;
                padding: 10px;
                margin-bottom: 15px;
            }}
            .info-label {{
                color: #6c757d;
                font-size: 7pt;
                font-weight: bold;
                text-transform: uppercase;
            }}
            .info-value {{
                font-size: 10pt;
                font-weight: bold;
                color: #000;
            }}
            .position-badge {{
                background-color: #1a237e;
                color: white;
                padding: 2px 8px;
                border-radius: 12px;
                display: inline-block;
                font-size: 9pt;
            }}
            
            .results-table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 10px;
            }}
            .results-table th {{
                background-color: #1a237e;
                color: white;
                padding: 8px 4px;
                border: 1px solid #1a237e;
                font-size: 8pt;
            }}
            .results-table td {{
                border: 1px solid #dee2e6;
                padding: 6px 4px;
                font-size: 8pt;
            }}
            .total-row {{
                background-color: #f8f9fa;
                font-weight: bold;
            }}
            
            .summary-box {{
                border: 1px solid #ffa500;
                background-color: #fffbf0;
                padding: 8px;
                text-align: center;
            }}
            
            .sig-table {{
                width: 100%;
                margin-top: 40px;
            }}
            .sig-line {{
                border-top: 1px solid #333;
                width: 150px;
                margin: 0 auto;
                padding-top: 3px;
            }}
            
            .footer {{
                margin-top: 30px;
                text-align: center;
                font-size: 7pt;
                color: #6c757d;
                border-top: 1px solid #dee2e6;
                padding-top: 8px;
            }}
        </style>
    </head>
    <body>
        <table class="header-table">
            <tr>
                <td width="15%" class="text-left">{logo_html}</td>
                <td width="70%" class="text-center">
                    <div class="institute-name">{data["institute"].get("institute_name", "ACADEMIC INSTITUTION")}</div>
                    <div class="motto">{data["institute"].get("target_line", "Excellence in Education")}</div>
                    <div style="font-size: 7pt; margin-top: 4px;">
                        {data["institute"].get("address", "")}<br>
                        Tel: {data["institute"].get("phone_number", "")} | Email: {data["institute"].get("email", "")}
                    </div>
                </td>
                <td width="15%" class="text-right">
                    <div style="font-size: 10pt; font-weight: bold; color: #1a237e;">ACADEMIC<br>REPORT</div>
                </td>
            </tr>
        </table>

        <table class="info-table">
            <tr>
                <td width="75%">
                    <table width="100%" cellspacing="5">
                        <tr>
                            <td width="33%">
                                <div class="info-label">Student Name</div>
                                <div class="info-value">{data['student']['name']}</div>
                            </td>
                            <td width="33%">
                                <div class="info-label">Student ID</div>
                                <div class="info-value">{data['student']['student_id']}</div>
                            </td>
                            <td width="34%">
                                <div class="info-label">Class</div>
                                <div class="info-value">{data['class_name']}</div>
                            </td>
                        </tr>
                        <tr>
                            <td>
                                <div class="info-label">Gender</div>
                                <div class="info-value">{data['student'].get('gender', 'N/A')}</div>
                            </td>
                            <td>
                                <div class="info-label">Term / Year</div>
                                <div class="info-value">{data['term']} / {data['year']}</div>
                            </td>
                            <td>
                                <div class="info-label">Class Position</div>
                                <div class="info-value"><span class="position-badge">{data['position']}{suffix} of {data['total_students']}</span></div>
                            </td>
                        </tr>
                    </table>
                </td>
                <td width="25%" class="text-center">
                    {student_photo_html}
                </td>
            </tr>
        </table>

        <table class="results-table">
            <thead>
                <tr>
                    <th width="25%" class="text-left">SUBJECT</th>
                    {exam_headers}
                    <th width="10%">AVG (%)</th>
                    <th width="10%">GRADE</th>
                    <th width="20%" class="text-left">REMARKS</th>
                </tr>
            </thead>
            <tbody>
                {subject_rows}
                <tr class="total-row">
                    <td class="text-left"><strong>OVERALL SUMMARY</strong></td>
                    <td colspan="{len(data['exams'])}" class="text-center"><strong>{data['total_obtained']} / {data['total_possible']}</strong></td>
                    <td class="text-center"><strong>{data['overall_percentage']}%</strong></td>
                    <td class="text-center"><strong>{data['grade']}</strong></td>
                    <td class="text-left">{data['comment']}</td>
                </tr>
            </tbody>
        </table>

        <table width="100%" style="margin-top: 15px;" cellspacing="8">
            <tr>
                <td width="33%">
                    <div class="summary-box">
                        <div class="info-label">Overall Percentage</div>
                        <div style="font-size: 16pt; font-weight: bold; color: #1a237e;">{data['overall_percentage']}%</div>
                    </div>
                </td>
                <td width="33%">
                    <div class="summary-box">
                        <div class="info-label">Total Marks</div>
                        <div style="font-size: 16pt; font-weight: bold; color: #1a237e;">{data['total_obtained']}</div>
                    </div>
                </td>
                <td width="34%">
                    <div class="summary-box">
                        <div class="info-label">Final Grade</div>
                        <div style="font-size: 16pt; font-weight: bold; color: #1a237e;">{data['grade']}</div>
                    </div>
                </td>
            </tr>
        </table>

        <table class="sig-table">
            <tr>
                <td class="text-center">
                    <div class="sig-line"></div>
                    <div style="font-size: 8pt; font-weight: bold;">Class Teacher</div>
                </td>
                <td class="text-center">
                    <div class="sig-line"></div>
                    <div style="font-size: 8pt; font-weight: bold;">Head Teacher</div>
                </td>
                <td class="text-center">
                    <div class="sig-line"></div>
                    <div style="font-size: 8pt; font-weight: bold;">Parent/Guardian</div>
                </td>
            </tr>
        </table>

        <div class="footer">
            Generated on: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')} | Report ID: {data['student']['student_id']}_{data['year']}_{data['term']}
        </div>
    </body>
    </html>
    """
    
    return html

def convert_html_to_pdf(html_content):
    """Convert HTML to PDF using xhtml2pdf"""
    pdf_buffer = io.BytesIO()
    pisa_status = pisa.CreatePDF(io.StringIO(html_content), dest=pdf_buffer)
    
    if pisa_status.err:
        raise Exception("PDF generation failed")
    
    pdf_buffer.seek(0)
    return pdf_buffer