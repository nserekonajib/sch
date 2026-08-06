# studentID.py - Fixed firstName handling for single-name students
from flask import Blueprint, render_template, request, jsonify, send_file, session
from supabase import create_client, Client
import os
import qrcode
from io import BytesIO
import base64
from datetime import datetime
import json
import requests
from functools import wraps
from dotenv import load_dotenv
from routes.accounts.accounts import get_institute_id
from routes.permissions.permissions import role_required

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ID Card API Configuration
ID_CARD_API_BATCH_URL = os.getenv('ID_CARD_API_BATCH_URL', ' http://d44cgg048cgckw4kwo4osw4k.195.200.15.127.sslip.io/api/id-cards/batch')
id_bp = Blueprint('id', __name__, url_prefix='/student-id')

def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Please login'}), 401
        return f(*args, **kwargs)
    return decorated_function


@id_bp.route('/')
@role_required(['owner', 'teacher', 'accountant'])
def index():
    """Student ID Card Generation Page"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return render_template('student_id/index.html', classes=[], institute=None)
    
    try:
        # Get institute details
        institute_response = supabase.table('institutes')\
            .select('*')\
            .eq('id', institute_id)\
            .execute()
        
        institute = institute_response.data[0] if institute_response.data else None
        
        # Get classes for dropdown
        classes_response = supabase.table('classes')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('name')\
            .execute()
        
        classes = classes_response.data if classes_response.data else []
        
        return render_template('student_id/index.html', classes=classes, institute=institute)
        
    except Exception as e:
        print(f"Error loading ID page: {e}")
        return render_template('student_id/index.html', classes=[], institute=None)


@id_bp.route('/generate', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def generate_ids():
    """Generate ID cards for selected class - returns data for display"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        class_id = data.get('class_id')
        
        if not class_id:
            return jsonify({'success': False, 'message': 'Please select a class'}), 400
        
        # Get institute details
        institute_response = supabase.table('institutes')\
            .select('*')\
            .eq('id', institute_id)\
            .execute()
        
        institute = institute_response.data[0] if institute_response.data else None
        
        if not institute:
            return jsonify({'success': False, 'message': 'Institute not found'}), 404
        
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
            .eq('institute_id', institute_id)\
            .eq('status', 'active')\
            .order('name')\
            .execute()
        
        students = students_response.data if students_response.data else []
        
        if not students:
            return jsonify({'success': False, 'message': 'No students found in this class'}), 404
        
        # Generate preview data for each student (for frontend display)
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
            
            # Get photo as base64 data URL for API
            photo_base64 = None
            if student.get('photo_url'):
                try:
                    photo_response = requests.get(student['photo_url'], timeout=10)
                    if photo_response.status_code == 200:
                        content_type = photo_response.headers.get('content-type', 'image/jpeg')
                        if 'png' in content_type:
                            mime_type = 'image/png'
                        elif 'gif' in content_type:
                            mime_type = 'image/gif'
                        else:
                            mime_type = 'image/jpeg'
                        photo_base64 = f"data:{mime_type};base64,{base64.b64encode(photo_response.content).decode()}"
                except Exception as e:
                    print(f"Error loading photo for {student['name']}: {e}")
            
            id_card = {
                'student_id': student['student_id'],
                'name': student['name'],
                'class': student.get('classes', {}).get('name', class_name),
                'gender': student.get('gender', 'N/A'),
                'nationality': student.get('nationality', 'N/A'),
                'date_of_birth': dob_formatted,
                'date_of_admission': doa.strftime('%d %b %Y'),
                'photo_url': student.get('photo_url'),
                'photo_base64': photo_base64,
                'qr_code': qr_code,
                'institute': {
                    'institute_name': institute.get('institute_name', 'School'),
                    'logo_url': institute.get('logo_url'),
                    'address': institute.get('address', ''),
                    'phone_number': institute.get('phone_number', ''),
                    'institute_code': institute.get('institute_code', '')
                }
            }
            id_cards.append(id_card)
        
        return jsonify({
            'success': True,
            'students': id_cards,
            'count': len(id_cards)
        })
        
    except Exception as e:
        print(f"Error generating IDs: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


@id_bp.route('/download-pdf', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def download_pdf():
    """Download ID cards as PDF using the ID Card API service"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        students = data.get('students', [])
        theme_color = data.get('theme_color', '#ffa500')
        
        if not students:
            return jsonify({'success': False, 'message': 'No students to export'}), 400
        
        # Get institute details
        institute_response = supabase.table('institutes')\
            .select('*')\
            .eq('id', institute_id)\
            .execute()
        
        institute = institute_response.data[0] if institute_response.data else {}
        
        # Build batch request for the ID Card API
        batch_payload = build_batch_payload(students, institute, theme_color)
        
        # Log the request for debugging
        print(f"Sending batch request with {len(batch_payload['cards'])} cards")
        
        # Call the ID Card API batch endpoint
        response = requests.post(
            ID_CARD_API_BATCH_URL,
            json=batch_payload,
            headers={'Content-Type': 'application/json'},
            timeout=120
        )
        
        if response.status_code != 200:
            error_msg = 'Failed to generate PDF'
            try:
                error_data = response.json()
                error_msg = error_data.get('error', 'Unknown error')
                print(f"API Error: {error_msg}")
            except Exception as e:
                print(f"Error parsing API response: {e}")
                print(f"Response status: {response.status_code}")
                print(f"Response content: {response.text[:500]}")
            return jsonify({'success': False, 'message': f'ID Card API error: {error_msg}'}), 500
        
        # Return the PDF directly
        pdf_data = response.content
        
        return send_file(
            BytesIO(pdf_data),
            as_attachment=True,
            download_name=f"student_id_cards_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
            mimetype='application/pdf'
        )
        
    except requests.exceptions.Timeout:
        return jsonify({'success': False, 'message': 'ID Card API timeout - please try again'}), 500
    except requests.exceptions.ConnectionError:
        return jsonify({'success': False, 'message': 'ID Card API is not available. Please check if the service is running.'}), 500
    except Exception as e:
        print(f"Error generating PDF: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


def split_name(full_name):
    """Split a full name into surname and first name.
    Handles various name formats:
    - "John Doe" -> surname: "Doe", firstName: "John"
    - "John" -> surname: "John", firstName: "John"
    - "John Michael Doe" -> surname: "Doe", firstName: "John Michael"
    - "Doe, John" -> surname: "Doe", firstName: "John"
    """
    if not full_name or not full_name.strip():
        return "Unknown", "Student"
    
    full_name = full_name.strip()
    
    # Check if name is in "Last, First" format
    if ',' in full_name:
        parts = full_name.split(',', 1)
        surname = parts[0].strip()
        first_name = parts[1].strip() if len(parts) > 1 else surname
        return surname, first_name
    
    # Split by spaces
    name_parts = full_name.split()
    
    if len(name_parts) == 0:
        return "Unknown", "Student"
    elif len(name_parts) == 1:
        # Single name - use it as both surname and first name
        return name_parts[0], name_parts[0]
    elif len(name_parts) == 2:
        # Two names - first and last
        return name_parts[1], name_parts[0]
    else:
        # More than 2 names - last word is surname, rest is first name
        surname = name_parts[-1]
        first_name = ' '.join(name_parts[:-1])
        return surname, first_name


def build_batch_payload(students, institute, theme_color):
    """Build the request payload for the ID Card API batch endpoint"""
    
    primary_color = theme_color or '#ffa500'
    
    # Build the base branding
    branding = {
        "organizationName": institute.get('institute_name', 'Greenfield International School'),
        "organizationSubtitle": "Student ID Card",
        "primaryColor": primary_color,
        "secondaryColor": adjust_color_brightness(primary_color, 1.3),
        "legalFooter": f"{institute.get('institute_name', 'School')} • {institute.get('address', '')} • {institute.get('phone_number', '')}"
    }
    
    # Add logo if available
    if institute.get('logo_url'):
        try:
            logo_response = requests.get(institute['logo_url'], timeout=10)
            if logo_response.status_code == 200:
                content_type = logo_response.headers.get('content-type', 'image/png')
                if 'png' in content_type:
                    mime_type = 'image/png'
                elif 'jpeg' in content_type or 'jpg' in content_type:
                    mime_type = 'image/jpeg'
                else:
                    mime_type = 'image/png'
                branding["logoBase64"] = f"data:{mime_type};base64,{base64.b64encode(logo_response.content).decode()}"
        except Exception as e:
            print(f"Error loading logo: {e}")
    
    # Build cards array
    cards = []
    for idx, student in enumerate(students):
        # Get photo from the student data (already fetched during generation)
        photo_base64 = student.get('photo_base64')
        
        # If photo_base64 is not available, try to fetch it now
        if not photo_base64 and student.get('photo_url'):
            try:
                photo_response = requests.get(student['photo_url'], timeout=10)
                if photo_response.status_code == 200:
                    content_type = photo_response.headers.get('content-type', 'image/jpeg')
                    if 'png' in content_type:
                        mime_type = 'image/png'
                    elif 'gif' in content_type:
                        mime_type = 'image/gif'
                    else:
                        mime_type = 'image/jpeg'
                    photo_base64 = f"data:{mime_type};base64,{base64.b64encode(photo_response.content).decode()}"
            except Exception as e:
                print(f"Error loading photo for {student['name']}: {e}")
        
        # Split name into surname and first name
        surname, first_name = split_name(student['name'])
        
        # Prepare student data for the API
        student_data = {
            "surname": surname,
            "firstName": first_name,
            "studentId": student['student_id'],
            "program": student.get('class', 'N/A'),
            "nationality": student.get('nationality', ''),
            "sex": student.get('gender', '').upper()[0] if student.get('gender') else '',
            "dateOfBirth": format_date_for_api(student.get('date_of_birth', '')),
            "issueDate": datetime.now().strftime('%Y-%m-%d'),
            "expiryDate": (datetime.now().replace(year=datetime.now().year + 2)).strftime('%Y-%m-%d'),
            "address": institute.get('address', ''),
            "status": "Active"
        }
        
        # Add photo if available (API requires this)
        if photo_base64:
            student_data["photoBase64"] = photo_base64
        else:
            # If no photo is available, create a placeholder
            print(f"Warning: No photo available for student {student['name']} (ID: {student['student_id']})")
            placeholder = create_placeholder_photo(student['name'])
            if placeholder:
                student_data["photoBase64"] = placeholder
        
        # Create card entry
        card = {
            "student": student_data,
            "qrData": f"{institute.get('institute_code', '')}|{student['student_id']}|{student['name']}"
        }
        
        cards.append(card)
    
    # Return the complete batch payload
    return {
        "branding": branding,
        "options": {
            "bleedMm": 3,
            "includeMrz": True
        },
        "cards": cards
    }


def create_placeholder_photo(name):
    """Create a placeholder photo with initials for students without photos"""
    try:
        from PIL import Image, ImageDraw, ImageFont
        import io
        
        # Create a 200x200 placeholder image
        size = 200
        img = Image.new('RGB', (size, size), color='#e5e7eb')
        draw = ImageDraw.Draw(img)
        
        # Get initials
        initials = ''.join([part[0].upper() for part in name.split()[:2]])
        if not initials:
            initials = '?'
        
        # Try to use a default font
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 60)
        except:
            try:
                font = ImageFont.truetype("arial.ttf", 60)
            except:
                font = ImageFont.load_default()
        
        # Draw initials
        bbox = draw.textbbox((0, 0), initials, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        x = (size - text_width) // 2
        y = (size - text_height) // 2
        
        draw.text((x, y), initials, fill='#6b7280', font=font)
        
        # Convert to base64
        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        return f"data:image/png;base64,{base64.b64encode(buffered.getvalue()).decode()}"
    except Exception as e:
        print(f"Error creating placeholder photo: {e}")
        return None


def adjust_color_brightness(hex_color, factor):
    """Adjust brightness of a hex color"""
    try:
        hex_color = hex_color.lstrip('#')
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        
        r = min(255, int(r * factor))
        g = min(255, int(g * factor))
        b = min(255, int(b * factor))
        
        return f"#{r:02x}{g:02x}{b:02x}"
    except:
        return '#e8b400'


def format_date_for_api(date_str):
    """Format date for the API (YYYY-MM-DD)"""
    if not date_str:
        return None
    try:
        for fmt in ['%d %b %Y', '%d-%m-%Y', '%d/%m/%Y']:
            try:
                dt = datetime.strptime(date_str, fmt)
                return dt.strftime('%Y-%m-%d')
            except:
                continue
        return date_str
    except:
        return None


def generate_qr_code(data):
    """Generate QR code as base64 string for preview display"""
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
        
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode()
        
        return f"data:image/png;base64,{img_str}"
    except Exception as e:
        print(f"QR generation error: {e}")
        return None


@id_bp.route('/preview/<student_id>', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def preview_card(student_id):
    """Preview single ID card - returns data for frontend display"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        institute_response = supabase.table('institutes')\
            .select('*')\
            .eq('id', institute_id)\
            .execute()
        
        institute = institute_response.data[0] if institute_response.data else None
        
        if not institute:
            return jsonify({'success': False, 'message': 'Institute not found'}), 404
        
        student_response = supabase.table('students')\
            .select('*, classes(name)')\
            .eq('id', student_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if not student_response.data:
            return jsonify({'success': False, 'message': 'Student not found'}), 404
        
        student = student_response.data[0]
        
        qr_data = f"{institute['institute_code']}|{student['student_id']}|{student['name']}"
        qr_code = generate_qr_code(qr_data)
        
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
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500
