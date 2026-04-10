# competenceReportCard.py - Complete Competence-Based Report Card System
from flask import Blueprint, render_template, request, jsonify, session, send_file
from supabase import create_client, Client
import os
import uuid
from datetime import datetime
import json
import re
from functools import wraps
from dotenv import load_dotenv
import io
from xhtml2pdf import pisa
import requests
from PyPDF2 import PdfMerger

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

competence_bp = Blueprint('competence', __name__, url_prefix='/competence-report')

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

def parse_exam_name(exam_name):
    patterns = {
        'A': re.compile(r'^A\d+$', re.IGNORECASE),
        'BOT': re.compile(r'^BOT$', re.IGNORECASE),
        'EOT': re.compile(r'^EOT$', re.IGNORECASE),
        'MT': re.compile(r'^MT$', re.IGNORECASE),
    }
    for pattern_type, pattern in patterns.items():
        if pattern.match(exam_name.strip().upper()):
            return pattern_type
    return 'OTHER'

@competence_bp.route('/')
@login_required
def index():
    user = session.get('user')
    institute = get_institute(user['id'])
    
    if not institute:
        return render_template('competence/index.html', exams=[], classes=[], students=[], institute=None)
    
    try:
        exams_response = supabase.table('exams')\
            .select('*')\
            .eq('institute_id', institute['id'])\
            .order('exam_date', desc=True)\
            .execute()
        
        exams = exams_response.data if exams_response.data else []
        
        classes_response = supabase.table('classes')\
            .select('*')\
            .eq('institute_id', institute['id'])\
            .order('name')\
            .execute()
        
        classes = classes_response.data if classes_response.data else []
        
        students_response = supabase.table('students')\
            .select('id, name, student_id, class_id, classes(name), photo_url, gender, category')\
            .eq('institute_id', institute['id'])\
            .eq('status', 'active')\
            .order('name')\
            .execute()
        
        students = students_response.data if students_response.data else []
        
        return render_template('competence/index.html', exams=exams, classes=classes, students=students, institute=institute)
        
    except Exception as e:
        print(f"Error loading competence page: {e}")
        return render_template('competence/index.html', exams=[], classes=[], students=[], institute=institute)

@competence_bp.route('/api/exams/classify', methods=['POST'])
@login_required
def classify_exams():
    user = session.get('user')
    institute = get_institute(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        exam_ids = data.get('exam_ids', [])
        
        if not exam_ids:
            return jsonify({'success': False, 'message': 'No exams selected'}), 400
        
        exams_response = supabase.table('exams')\
            .select('*')\
            .in_('id', exam_ids)\
            .execute()
        
        exams = exams_response.data if exams_response.data else []
        
        classified = {'a_series': [], 'bot': None, 'eot': None, 'mt': None, 'other': []}
        
        for exam in exams:
            exam_type = parse_exam_name(exam['exam_name'])
            if exam_type == 'A':
                match = re.search(r'(\d+)', exam['exam_name'])
                number = int(match.group(1)) if match else 0
                classified['a_series'].append({
                    'id': exam['id'], 'name': exam['exam_name'], 
                    'total_marks': exam['total_marks'], 'number': number
                })
            elif exam_type == 'BOT':
                classified['bot'] = {'id': exam['id'], 'name': exam['exam_name'], 'total_marks': exam['total_marks']}
            elif exam_type == 'EOT':
                classified['eot'] = {'id': exam['id'], 'name': exam['exam_name'], 'total_marks': exam['total_marks']}
            elif exam_type == 'MT':
                classified['mt'] = {'id': exam['id'], 'name': exam['exam_name'], 'total_marks': exam['total_marks']}
            else:
                classified['other'].append({'id': exam['id'], 'name': exam['exam_name'], 'total_marks': exam['total_marks']})
        
        classified['a_series'].sort(key=lambda x: x['number'])
        
        return jsonify({'success': True, 'classified': classified})
        
    except Exception as e:
        print(f"Error classifying exams: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@competence_bp.route('/generate', methods=['POST'])
@login_required
def generate_report():
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
        
        if not student_id or not exam_ids or not term:
            return jsonify({'success': False, 'message': 'Missing required fields'}), 400
        
        # Get student details
        student_response = supabase.table('students')\
            .select('*, classes(name)')\
            .eq('id', student_id)\
            .eq('institute_id', institute['id'])\
            .execute()
        
        if not student_response.data:
            return jsonify({'success': False, 'message': 'Student not found'}), 404
        
        student = student_response.data[0]
        
        # Get exams
        exams_response = supabase.table('exams')\
            .select('*')\
            .in_('id', exam_ids)\
            .execute()
        
        exams = exams_response.data if exams_response.data else []
        
        # Classify exams
        a_series = []
        eot_exam = None
        for exam in exams:
            exam_type = parse_exam_name(exam['exam_name'])
            if exam_type == 'A':
                match = re.search(r'(\d+)', exam['exam_name'])
                number = int(match.group(1)) if match else 0
                a_series.append({'id': exam['id'], 'name': exam['exam_name'], 'total_marks': exam['total_marks'], 'number': number})
            elif exam_type == 'EOT':
                eot_exam = exam
        
        a_series.sort(key=lambda x: x['number'])
        
        # Get subjects
        class_id = student.get('class_id')
        subjects_response = supabase.table('class_subjects')\
            .select('*, subjects(name)')\
            .eq('class_id', class_id)\
            .eq('institute_id', institute['id'])\
            .execute()
        
        subjects = subjects_response.data if subjects_response.data else []
        
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
        for subject in subjects:
            subject_name = subject['subjects']['name'] if subject.get('subjects') else 'N/A'
            
            a_series_marks = []
            for a_exam in a_series:
                obtained = all_marks.get(a_exam['id'], {}).get(subject['subject_id'])
                a_series_marks.append(obtained if obtained is not None else 0)
            
            a_series_avg = sum(a_series_marks) / len(a_series_marks) if a_series_marks else 0
            twenty_percent = (a_series_avg / 3) * 20 if a_series_marks else 0
            
            eot_mark = all_marks.get(eot_exam['id'], {}).get(subject['subject_id'], 0) if eot_exam else 0
            eighty_percent = (eot_mark / eot_exam['total_marks']) * 80 if eot_exam and eot_exam['total_marks'] > 0 else 0
            
            total_percentage = twenty_percent + eighty_percent
            
            # Determine grade (A: 80-100, B: 70-79, C: 60-69, D: 40-59, E: 0-39)
            if total_percentage >= 80:
                grade = 'A'
                remark = 'Exceptional'
            elif total_percentage >= 70:
                grade = 'B'
                remark = 'Outstanding'
            elif total_percentage >= 60:
                grade = 'C'
                remark = 'Satisfactory'
            elif total_percentage >= 40:
                grade = 'D'
                remark = 'Basic'
            else:
                grade = 'E'
                remark = 'Insufficient'
            
            subject_results.append({
                'name': subject_name,
                'code': str(100 + subject_results.__len__() + 1),
                'a_series_marks': a_series_marks,
                'a_series_avg': round(a_series_avg, 1),
                'twenty_percent': round(twenty_percent, 1),
                'eot_mark': eot_mark,
                'eighty_percent': round(eighty_percent, 1),
                'total_percentage': round(total_percentage, 1),
                'grade': grade,
                'remark': remark
            })
        
        # Calculate overall average
        overall_percentage = sum([s['total_percentage'] for s in subject_results]) / len(subject_results) if subject_results else 0
        
        if overall_percentage >= 80:
            overall_grade = 'A'
        elif overall_percentage >= 70:
            overall_grade = 'B'
        elif overall_percentage >= 60:
            overall_grade = 'C'
        elif overall_percentage >= 40:
            overall_grade = 'D'
        else:
            overall_grade = 'E'
        
        result_data = {
            'institute': institute,
            'student': student,
            'class_name': student['classes']['name'] if student.get('classes') else 'N/A',
            'section': student.get('category', 'Day'),
            'gender': student.get('gender', 'N/A'),
            'term': term,
            'year': year,
            'printed_date': datetime.now().strftime('%d/%m/%Y'),
            'a_series': a_series,
            'has_eot': eot_exam is not None,
            'subjects': subject_results,
            'overall_percentage': round(overall_percentage, 1),
            'overall_grade': overall_grade,
            'teacher_comment': f"{student['name']}, You're on the right track. Focus on building on your strengths and addressing areas for improvement."
        }
        
        html_content = generate_competence_report_html(result_data)
        pdf_buffer = convert_html_to_pdf(html_content)
        
        return send_file(
            pdf_buffer,
            as_attachment=True,
            download_name=f"competence_report_{student['name']}_{term}_{year}.pdf",
            mimetype='application/pdf'
        )
        
    except Exception as e:
        print(f"Error generating competence report: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500
    
    
def generate_competence_report_html(data):
    """
    Fixed layout: Photo at top right, logo at top left.
    Strict A4 formatting to prevent text overlap.
    """
    
    subject_rows = ""
    for subject in data['subjects']:
        a_marks = subject.get('a_series_marks', [])
        a_vals = [f"{a_marks[i]:.1f}" if i < len(a_marks) else "-" for i in range(3)]
        
        avg = subject['a_series_avg']
        identifier = "1" if avg < 1.5 else ("2" if avg < 2.5 else "3")

        subject_rows += f"""
        <tr>
            <td style="text-align:left; font-weight:bold; padding-left:5px;">{subject['name']}</td>
            <td>{a_vals[0]}</td><td>{a_vals[1]}</td><td>{a_vals[2]}</td>
            <td class="bg-grey">{subject['a_series_avg']:.1f}</td>
            <td>{subject['twenty_percent']:.1f}</td>
            <td>{subject['eighty_percent']:.1f}</td>
            <td class="font-bold">{subject['total_percentage']:.1f}</td>
            <td>{identifier}</td>
            <td class="font-bold">{subject['grade']}</td>
            <td style="text-align:left; font-size: 8pt; line-height:1.1;">{subject['remark']}</td>
        </tr>
        """

    school_name = data['institute'].get('institute_name', 'ST CHARLES LWANGA SS-AKASHANDA').upper()
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            @page {{ size: A4; margin: 0.4cm; }}
            body {{ font-family: Arial, sans-serif; color: #1a365d; margin: 0; padding: 0; line-height: 1.1; }}
            
            .container {{ width: 100%; }}
            table {{ width: 100%; border-collapse: collapse; table-layout: fixed; margin-bottom: 4px; }}
            td, th {{ border: 1px solid #1a365d; padding: 2px; text-align: center; overflow: hidden; text-overflow: ellipsis; word-wrap: break-word; }}
            
            /* Header specifically for Logo-Info-Photo layout */
            .header-table {{ border: none; }}
            .header-table td {{ border: none; vertical-align: middle; }}
            .school-name {{ font-size: 16pt; font-weight: bold; margin-bottom: 2px; }}
            
            .report-banner {{ background-color: #1a365d; color: white; text-align: center; font-weight: bold; padding: 5px; font-size: 13pt; margin: 4px 0; }}
            
            /* Subject Table */
            .perf-table th {{ background-color: #f0f4f8; font-size: 8pt; height: 24px; }}
            .perf-table td {{ font-size: 9pt; height: 20px; }}
            .label {{ font-weight: bold; background-color: #f7fafc; text-align: left; padding-left: 5px; width: 15%; }}
            
            .font-bold {{ font-weight: bold; }}
            .bg-grey {{ background-color: #f1f5f9; }}
            .comment-box {{ border: 1px solid #1a365d; padding: 5px; font-size: 9pt; min-height: 28px; margin-top: 2px; }}
            
            .legend-table td {{ font-size: 8pt; padding: 2px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <table class="header-table">
                <tr>
                    <td width="15%" style="text-align:left;">
                        <img src="{data['institute'].get('logo_url', '')}" width="75">
                    </td>
                    <td width="70%" style="text-align:center;">
                        <div class="school-name">{school_name}</div>
                        <div style="font-size:10pt;">{data['institute'].get('address', 'Kampala')}</div>
                        <div style="font-size:9pt;">TEL: {data['institute'].get('phone_number', '+256757632756')}</div>
                        <div style="font-size:9pt; color: #2563eb;">{data['institute'].get('email', 'nserekonajib3@gmail.com')}</div>
                    </td>
                    <td width="15%" style="text-align:right;">
                        <img src="{data['student'].get('photo_url', '')}" width="80" style="border: 1px solid #1a365d; border-radius: 2px;">
                    </td>
                </tr>
            </table>

            <div class="report-banner">TERM {data['term']} REPORT CARD {data['year']}</div>

            <table>
                <tr>
                    <td class="label">NAME:</td>
                    <td colspan="3" style="text-align:left; padding-left:5px; font-weight:bold;">{data['student']['name'].upper()}</td>
                    <td class="label">GENDER:</td>
                    <td style="text-align:left; padding-left:5px;">{data['gender'].upper()}</td>
                </tr>
                <tr>
                    <td class="label">CLASS:</td>
                    <td style="text-align:left; padding-left:5px;">{data['class_name']}</td>
                    <td class="label">SECTION:</td>
                    <td style="text-align:left; padding-left:5px;">{data['section']}</td>
                    <td class="label">TERM:</td>
                    <td style="text-align:left; padding-left:5px;">{data['term']}</td>
                </tr>
            </table>

            <table class="perf-table">
                <thead>
                    <tr>
                        <th width="22%" style="text-align:left; padding-left:5px;">Subject</th>
                        <th width="5%">A1</th><th width="5%">A2</th><th width="5%">A3</th>
                        <th width="7%">AVG</th><th width="7%">20%</th><th width="7%">80%</th>
                        <th width="8%">100%</th><th width="6%">Ident</th><th width="7%">GRADE</th>
                        <th width="21%">Remarks/Descriptors</th>
                    </tr>
                </thead>
                <tbody>
                    {subject_rows}
                    <tr class="font-bold bg-grey">
                        <td style="text-align:left; padding-left:5px;">AVERAGE:</td>
                        <td colspan="3"></td>
                        <td>{data.get('avg_score', '2.0')}</td>
                        <td>13.5</td><td>63.9</td><td>77.4</td>
                        <td colspan="3"></td>
                    </tr>
                </tbody>
            </table>

            <table>
                <tr>
                    <td class="font-bold">Overall Identifier</td><td width="10%">{data.get('overall_ident', '2')}</td>
                    <td class="font-bold">Overall Achievement</td><td width="20%">MODERATE</td>
                    <td class="font-bold">Overall Grade</td><td width="10%">{data['overall_grade']}</td>
                </tr>
            </table>
            
            <table>
                <tr class="bg-grey font-bold">
                    <td>GRADE</td><td>A</td><td>B</td><td>C</td><td>D</td><td>E</td>
                </tr>
                <tr>
                    <td>SCORES</td><td>100 - 80</td><td>80 - 70</td><td>69 - 60</td><td>60 - 40</td><td>40 - 0</td>
                </tr>
            </table>

            <div class="comment-box"><strong>Class teacher's Comment:</strong> <i>{data['teacher_comment']}</i></div>
            <div class="comment-box"><strong>Headteacher's Comment:</strong> __________________________________________</div>

            <table class="legend-table" style="margin-top:5px;">
                <tr>
                    <td rowspan="4" width="15%" class="font-bold">Key to Terms:</td>
                    <td class="font-bold" width="10%">A1-A3</td><td style="text-align:left;">Chapter Assessments</td>
                    <td class="font-bold" width="10%">80%</td><td style="text-align:left;">End of term assessment</td>
                </tr>
                <tr>
                    <td class="font-bold">1 - Basic</td><td colspan="3" style="text-align:left;">0.9-1.49: Few Learning Outcomes (LOs) achieved</td>
                </tr>
                <tr>
                    <td class="font-bold">2 - Moderate</td><td colspan="3" style="text-align:left;">1.5-2.49: Many LOs achieved, sufficient for achievement</td>
                </tr>
                <tr>
                    <td class="font-bold">3 - Outstanding</td><td colspan="3" style="text-align:left;">2.5-3.0: Most or all LOs achieved excellently</td>
                </tr>
            </table>

            <div style="border-top: 1px solid #1a365d; margin-top:5px; padding-top:2px; font-size:8pt; display:flex; justify-content:space-between; font-weight:bold;">
                <span>NEXT TERM BEGINS: 05/23/2026</span>
                <span>FEES BALANCE: ___________</span>
                <span>PRINTED ON: {data['printed_date']}</span>
            </div>
        </div>
    </body>
    </html>
    """
    return html


def convert_html_to_pdf(html_content):
    pdf_buffer = io.BytesIO()
    pisa_status = pisa.CreatePDF(io.StringIO(html_content), dest=pdf_buffer)
    
    if pisa_status.err:
        raise Exception(f"PDF generation failed: {pisa_status.err}")
    
    pdf_buffer.seek(0)
    return pdf_buffer