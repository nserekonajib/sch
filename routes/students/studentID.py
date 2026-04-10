# studentID.py - Updated with Class Name Fix and Print All
from flask import Blueprint, render_template, request, jsonify, send_file, session
from supabase import create_client, Client
import os
import qrcode
from io import BytesIO
import base64
from datetime import datetime
import uuid
import json
import tempfile
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, portrait
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, mm
from reportlab.pdfgen import canvas
from reportlab.graphics.shapes import Drawing, Rect
from reportlab.graphics import renderPDF
from PIL import Image as PILImage
import cloudinary
import cloudinary.uploader
import requests
from functools import wraps
from dotenv import load_dotenv

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Configure Cloudinary
cloudinary.config(
    cloud_name=os.getenv('CLOUDINARY_CLOUD_NAME'),
    api_key=os.getenv('CLOUDINARY_API_KEY'),
    api_secret=os.getenv('CLOUDINARY_API_SECRET'),
    secure=True
)

id_bp = Blueprint('id', __name__, url_prefix='/student-id')

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

@id_bp.route('/')
@login_required
def index():
    """Student ID Card Generation Page"""
    user = session.get('user')
    institute = get_institute_id(user['id'])
    
    if not institute:
        return render_template('student_id/index.html', classes=[], institute=None)
    
    try:
        # Get classes for dropdown
        classes_response = supabase.table('classes')\
            .select('*')\
            .eq('institute_id', institute['id'])\
            .order('name')\
            .execute()
        
        classes = classes_response.data if classes_response.data else []
        
        return render_template('student_id/index.html', classes=classes, institute=institute)
        
    except Exception as e:
        print(f"Error loading ID page: {e}")
        return render_template('student_id/index.html', classes=[], institute=institute)

@id_bp.route('/generate', methods=['POST'])
@login_required
def generate_ids():
    """Generate ID cards for selected class"""
    user = session.get('user')
    institute = get_institute_id(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        class_id = data.get('class_id')
        theme_color = data.get('theme_color', '#ffa500')
        
        if not class_id:
            return jsonify({'success': False, 'message': 'Please select a class'}), 400
        
        # Get class name
        class_response = supabase.table('classes')\
            .select('name')\
            .eq('id', class_id)\
            .execute()
        
        class_name = class_response.data[0]['name'] if class_response.data else 'N/A'
        
        # Get students in the class with class info
        students_response = supabase.table('students')\
            .select('*, classes(name)')\
            .eq('class_id', class_id)\
            .eq('institute_id', institute['id'])\
            .eq('status', 'active')\
            .order('name')\
            .execute()
        
        students = students_response.data if students_response.data else []
        
        if not students:
            return jsonify({'success': False, 'message': 'No students found in this class'}), 404
        
        # Generate ID cards for each student
        id_cards = []
        for student in students:
            # Generate QR code
            qr_data = f"{institute['institute_code']}|{student['student_id']}|{student['name']}"
            qr_code = generate_qr_code(qr_data)
            
            # Format dates
            doa = student.get('enrollment_date', datetime.now().date())
            if isinstance(doa, str):
                try:
                    doa = datetime.strptime(doa, '%Y-%m-%d').date()
                except:
                    doa = datetime.now().date()
            
            dob = student.get('date_of_birth', '')
            if isinstance(dob, str) and dob:
                try:
                    dob_date = datetime.strptime(dob, '%Y-%m-%d').date()
                    dob_formatted = dob_date.strftime('%d %b %Y')
                except:
                    dob_formatted = dob
            else:
                dob_formatted = 'N/A'
            
            id_card = {
                'student_id': student['student_id'],
                'name': student['name'],
                'class': student.get('classes', {}).get('name', class_name),
                'gender': student.get('gender', 'N/A'),
                'nationality': student.get('nationality', 'N/A'),
                'date_of_birth': dob_formatted,
                'date_of_admission': doa.strftime('%d %b %Y'),
                'photo_url': student.get('photo_url'),
                'qr_code': qr_code,
                'institute': institute,
                'theme_color': theme_color
            }
            id_cards.append(id_card)
        
        return jsonify({
            'success': True,
            'students': id_cards,
            'count': len(id_cards)
        })
        
    except Exception as e:
        print(f"Error generating IDs: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@id_bp.route('/download-pdf', methods=['POST'])
@login_required
def download_pdf():
    """Download ID cards as PDF"""
    user = session.get('user')
    institute = get_institute_id(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        students = data.get('students', [])
        
        if not students:
            return jsonify({'success': False, 'message': 'No students to export'}), 400
        
        # Create PDF in memory
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=portrait(letter),
                                rightMargin=20, leftMargin=20,
                                topMargin=20, bottomMargin=20)
        
        story = []
        
        # Add title
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=16,
            textColor=colors.HexColor('#ffa500'),
            alignment=1,
            spaceAfter=20
        )
        
        institute_name = institute.get('institute_name', 'School')
        story.append(Paragraph(f"{institute_name} - Student ID Cards", title_style))
        story.append(Spacer(1, 10))
        
        # Create ID cards (4 per page in grid)
        cards_per_row = 2
        rows = []
        current_row = []
        
        for idx, student in enumerate(students):
            card = create_id_card_pdf(student, institute)
            current_row.append(card)
            
            if len(current_row) == cards_per_row:
                # Create table for the row
                t = Table([current_row], colWidths=[3.2*inch, 3.2*inch])
                t.setStyle(TableStyle([
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 10),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 10),
                    ('TOPPADDING', (0, 0), (-1, -1), 10),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
                ]))
                story.append(t)
                story.append(Spacer(1, 20))
                current_row = []
        
        # Handle remaining cards
        if current_row:
            while len(current_row) < cards_per_row:
                current_row.append("")
            t = Table([current_row], colWidths=[3.2*inch, 3.2*inch])
            t.setStyle(TableStyle([
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ]))
            story.append(t)
        
        doc.build(story)
        buffer.seek(0)
        
        return send_file(
            buffer,
            as_attachment=True,
            download_name=f"student_id_cards_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
            mimetype='application/pdf'
        )
        
    except Exception as e:
        print(f"Error generating PDF: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

def generate_qr_code(data):
    """Generate QR code as base64 string"""
    try:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=4,
            border=2,
        )
        qr.add_data(data)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Convert to base64
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode()
        
        return f"data:image/png;base64,{img_str}"
    except Exception as e:
        print(f"QR generation error: {e}")
        return None

def create_id_card_pdf(student, institute):
    """Create a single ID card for PDF - Vertical Layout"""
    from reportlab.lib.colors import HexColor
    from reportlab.graphics.shapes import String
    
    # Parse theme color
    theme_color = student.get('theme_color', '#ffa500')
    try:
        theme_hex = HexColor(theme_color)
    except:
        theme_hex = HexColor('#ffa500')
    
    # Create a drawing for the card
    card_width = 3.2 * inch
    card_height = 4.8 * inch
    
    d = Drawing(card_width, card_height)
    
    # Background with rounded corners effect
    d.add(Rect(0, 0, card_width, card_height, fillColor=colors.white, strokeColor=theme_hex, strokeWidth=2))
    
    # Header
    d.add(Rect(0, card_height - 0.7*inch, card_width, 0.7*inch, fillColor=theme_hex, strokeColor=theme_hex))
    
    # Institute Name
    institute_name = institute.get('institute_name', 'School')[:25]
    d.add(String(card_width/2, card_height - 0.35*inch, institute_name,
                 fontSize=10, fillColor=colors.white, textAnchor='middle'))
    
    # Student Photo
    photo_y = card_height - 1.4*inch
    photo_size = 1.1*inch
    photo_x = card_width/2 - photo_size/2
    
    if student.get('photo_url'):
        try:
            response = requests.get(student['photo_url'], timeout=5)
            img_data = response.content
            img_buffer = BytesIO(img_data)
            pil_img = PILImage.open(img_buffer)
            
            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
                pil_img.save(tmp.name)
                photo = Image(tmp.name, width=photo_size, height=photo_size)
                photo.x = photo_x
                photo.y = photo_y - photo_size
                d.add(photo)
                os.unlink(tmp.name)
        except Exception as e:
            print(f"Photo error: {e}")
            d.add(Rect(photo_x, photo_y - photo_size, photo_size, photo_size,
                      fillColor=colors.lightgrey, strokeColor=theme_hex))
    else:
        d.add(Rect(photo_x, photo_y - photo_size, photo_size, photo_size,
                  fillColor=colors.lightgrey, strokeColor=theme_hex))
    
    # Student Info - Vertical Layout
    info_y = photo_y - photo_size - 0.15*inch
    line_height = 0.22*inch
    
    # Name
    d.add(String(card_width/2, info_y, student['name'][:25],
                 fontSize=11, fillColor=colors.black, textAnchor='middle', fontWeight='bold'))
    
    # Student ID
    info_y -= line_height
    d.add(String(card_width/2, info_y, f"ID: {student['student_id']}",
                 fontSize=8, fillColor=colors.grey, textAnchor='middle'))
    
    # Gender
    info_y -= line_height
    d.add(String(0.2*inch, info_y, "Gender:",
                 fontSize=8, fillColor=colors.grey))
    d.add(String(card_width - 0.2*inch, info_y, student.get('gender', 'N/A'),
                 fontSize=8, fillColor=colors.black, textAnchor='end'))
    
    # Nationality
    info_y -= line_height
    d.add(String(0.2*inch, info_y, "Nationality:",
                 fontSize=8, fillColor=colors.grey))
    d.add(String(card_width - 0.2*inch, info_y, student.get('nationality', 'N/A'),
                 fontSize=8, fillColor=colors.black, textAnchor='end'))
    
    # Date of Birth
    info_y -= line_height
    d.add(String(0.2*inch, info_y, "DOB:",
                 fontSize=8, fillColor=colors.grey))
    d.add(String(card_width - 0.2*inch, info_y, student.get('date_of_birth', 'N/A'),
                 fontSize=8, fillColor=colors.black, textAnchor='end'))
    
    # Class
    info_y -= line_height
    d.add(String(0.2*inch, info_y, "Class:",
                 fontSize=8, fillColor=colors.grey))
    d.add(String(card_width - 0.2*inch, info_y, student.get('class', 'N/A'),
                 fontSize=8, fillColor=colors.black, textAnchor='end'))
    
    # Date of Admission
    info_y -= line_height
    d.add(String(0.2*inch, info_y, "DOA:",
                 fontSize=8, fillColor=colors.grey))
    d.add(String(card_width - 0.2*inch, info_y, student.get('date_of_admission', 'N/A'),
                 fontSize=8, fillColor=colors.black, textAnchor='end'))
    
    # QR Code at bottom
    qr_y = 0.2*inch
    qr_size = 0.7*inch
    
    if student.get('qr_code'):
        try:
            qr_data = student['qr_code'].split(',')[1] if ',' in student['qr_code'] else student['qr_code']
            qr_bytes = base64.b64decode(qr_data)
            qr_buffer = BytesIO(qr_bytes)
            qr_img = PILImage.open(qr_buffer)
            
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                qr_img.save(tmp.name)
                qr = Image(tmp.name, width=qr_size, height=qr_size)
                qr.x = 0.2*inch
                qr.y = qr_y
                d.add(qr)
                os.unlink(tmp.name)
        except:
            pass
    
    # Phone number
    d.add(String(card_width - 0.2*inch, qr_y + qr_size/2, institute.get('phone_number', ''),
                 fontSize=7, fillColor=colors.grey, textAnchor='end'))
    
    return d

@id_bp.route('/preview/<student_id>', methods=['GET'])
@login_required
def preview_card(student_id):
    """Preview single ID card"""
    user = session.get('user')
    institute = get_institute_id(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Get student details with class info
        student_response = supabase.table('students')\
            .select('*, classes(name)')\
            .eq('id', student_id)\
            .eq('institute_id', institute['id'])\
            .execute()
        
        if not student_response.data:
            return jsonify({'success': False, 'message': 'Student not found'}), 404
        
        student = student_response.data[0]
        
        # Generate QR code
        qr_data = f"{institute['institute_code']}|{student['student_id']}|{student['name']}"
        qr_code = generate_qr_code(qr_data)
        
        # Format dates
        doa = student.get('enrollment_date', datetime.now().date())
        if isinstance(doa, str):
            try:
                doa = datetime.strptime(doa, '%Y-%m-%d').date()
            except:
                doa = datetime.now().date()
        
        dob = student.get('date_of_birth', '')
        if isinstance(dob, str) and dob:
            try:
                dob_date = datetime.strptime(dob, '%Y-%m-%d').date()
                dob_formatted = dob_date.strftime('%d %b %Y')
            except:
                dob_formatted = dob
        else:
            dob_formatted = 'N/A'
        
        card_data = {
            'student_id': student['student_id'],
            'name': student['name'],
            'class': student.get('classes', {}).get('name', 'N/A'),
            'gender': student.get('gender', 'N/A'),
            'nationality': student.get('nationality', 'N/A'),
            'date_of_birth': dob_formatted,
            'date_of_admission': doa.strftime('%d %b %Y'),
            'photo_url': student.get('photo_url'),
            'qr_code': qr_code,
            'institute': institute
        }
        
        return jsonify({'success': True, 'card': card_data})
        
    except Exception as e:
        print(f"Error previewing card: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500