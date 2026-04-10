# employeeIdCard.py - Fixed PDF generation with proper None handling
from flask import Blueprint, render_template, request, jsonify, session, send_file
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
from reportlab.graphics.shapes import Drawing, Rect, String
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

employeeID_bp = Blueprint('employee_id', __name__, url_prefix='/employee-id')

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

@employeeID_bp.route('/')
@login_required
def index():
    """Employee ID Card Generation Page"""
    user = session.get('user')
    institute = get_institute_id(user['id'])
    
    if not institute:
        return render_template('employee_id/index.html', employees=[], institute=None)
    
    try:
        # Get all active employees
        employees_response = supabase.table('employees')\
            .select('*')\
            .eq('institute_id', institute['id'])\
            .eq('status', 'active')\
            .order('name')\
            .execute()
        
        employees = employees_response.data if employees_response.data else []
        
        return render_template('employee_id/index.html', employees=employees, institute=institute)
        
    except Exception as e:
        print(f"Error loading ID page: {e}")
        return render_template('employee_id/index.html', employees=[], institute=institute)

@employeeID_bp.route('/generate', methods=['POST'])
@login_required
def generate_ids():
    """Generate ID cards for selected employees"""
    user = session.get('user')
    institute = get_institute_id(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        employee_ids = data.get('employee_ids', [])
        
        if not employee_ids:
            return jsonify({'success': False, 'message': 'Please select at least one employee'}), 400
        
        # Get selected employees
        employees_response = supabase.table('employees')\
            .select('*')\
            .eq('institute_id', institute['id'])\
            .in_('id', employee_ids)\
            .order('name')\
            .execute()
        
        employees = employees_response.data if employees_response.data else []
        
        if not employees:
            return jsonify({'success': False, 'message': 'No employees found'}), 404
        
        # Generate ID cards for each employee
        id_cards = []
        for employee in employees:
            # Generate QR code
            qr_data = f"{institute['institute_code']}|{employee['employee_id']}|{employee['name']}"
            qr_code = generate_qr_code(qr_data)
            
            # Format dates with proper None handling
            joining_date = employee.get('date_of_joining')
            if joining_date:
                if isinstance(joining_date, str):
                    try:
                        joining_date = datetime.strptime(joining_date, '%Y-%m-%d').date()
                        joining_date_str = joining_date.strftime('%d %b %Y')
                    except:
                        joining_date_str = joining_date
                else:
                    joining_date_str = joining_date.strftime('%d %b %Y') if hasattr(joining_date, 'strftime') else str(joining_date)
            else:
                joining_date_str = 'N/A'
            
            dob = employee.get('date_of_birth')
            if dob:
                if isinstance(dob, str):
                    try:
                        dob_date = datetime.strptime(dob, '%Y-%m-%d').date()
                        dob_formatted = dob_date.strftime('%d %b %Y')
                    except:
                        dob_formatted = dob
                else:
                    dob_formatted = dob.strftime('%d %b %Y') if hasattr(dob, 'strftime') else str(dob)
            else:
                dob_formatted = 'N/A'
            
            # Format role for display
            role_display = employee.get('role', 'Staff')
            if role_display:
                role_display = role_display.replace('_', ' ').title()
            else:
                role_display = 'Staff'
            
            # Format other fields with None handling
            gender = employee.get('gender') or 'N/A'
            phone = employee.get('phone') or 'N/A'
            email = employee.get('email') or 'N/A'
            
            id_card = {
                'employee_id': employee['employee_id'],
                'name': employee['name'],
                'role': role_display,
                'gender': gender,
                'date_of_joining': joining_date_str,
                'date_of_birth': dob_formatted,
                'phone': phone,
                'email': email,
                'photo_url': employee.get('photo_url'),
                'qr_code': qr_code,
                'institute': institute
            }
            id_cards.append(id_card)
        
        return jsonify({
            'success': True,
            'employees': id_cards,
            'count': len(id_cards)
        })
        
    except Exception as e:
        print(f"Error generating IDs: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@employeeID_bp.route('/print-all', methods=['POST'])
@login_required
def print_all():
    """Generate HTML for printing all ID cards"""
    user = session.get('user')
    institute = get_institute_id(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        employees = data.get('employees', [])
        
        if not employees:
            return jsonify({'success': False, 'message': 'No employees to print'}), 400
        
        # Generate HTML for all cards
        html_content = generate_print_html(employees, institute)
        
        return jsonify({
            'success': True,
            'html': html_content
        })
        
    except Exception as e:
        print(f"Error generating print HTML: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@employeeID_bp.route('/preview/<employee_id>', methods=['GET'])
@login_required
def preview_card(employee_id):
    """Preview single ID card"""
    user = session.get('user')
    institute = get_institute_id(user['id'])
    
    if not institute:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Get employee details
        employee_response = supabase.table('employees')\
            .select('*')\
            .eq('id', employee_id)\
            .eq('institute_id', institute['id'])\
            .execute()
        
        if not employee_response.data:
            return jsonify({'success': False, 'message': 'Employee not found'}), 404
        
        employee = employee_response.data[0]
        
        # Generate QR code
        qr_data = f"{institute['institute_code']}|{employee['employee_id']}|{employee['name']}"
        qr_code = generate_qr_code(qr_data)
        
        # Format dates
        joining_date = employee.get('date_of_joining')
        if joining_date:
            if isinstance(joining_date, str):
                try:
                    joining_date = datetime.strptime(joining_date, '%Y-%m-%d').date()
                    joining_date_str = joining_date.strftime('%d %b %Y')
                except:
                    joining_date_str = joining_date
            else:
                joining_date_str = joining_date.strftime('%d %b %Y') if hasattr(joining_date, 'strftime') else str(joining_date)
        else:
            joining_date_str = 'N/A'
        
        dob = employee.get('date_of_birth')
        if dob:
            if isinstance(dob, str):
                try:
                    dob_date = datetime.strptime(dob, '%Y-%m-%d').date()
                    dob_formatted = dob_date.strftime('%d %b %Y')
                except:
                    dob_formatted = dob
            else:
                dob_formatted = dob.strftime('%d %b %Y') if hasattr(dob, 'strftime') else str(dob)
        else:
            dob_formatted = 'N/A'
        
        role_display = employee.get('role', 'Staff')
        if role_display:
            role_display = role_display.replace('_', ' ').title()
        else:
            role_display = 'Staff'
        
        card_data = {
            'employee_id': employee['employee_id'],
            'name': employee['name'],
            'role': role_display,
            'gender': employee.get('gender') or 'N/A',
            'date_of_joining': joining_date_str,
            'date_of_birth': dob_formatted,
            'phone': employee.get('phone') or 'N/A',
            'email': employee.get('email') or 'N/A',
            'photo_url': employee.get('photo_url'),
            'qr_code': qr_code,
            'institute': institute
        }
        
        return jsonify({'success': True, 'card': card_data})
        
    except Exception as e:
        print(f"Error previewing card: {e}")
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

def generate_print_html(employees, institute):
    """Generate HTML for printing all ID cards"""
    
    cards_html = ""
    for emp in employees:
        photo_html = f'<img src="{emp["photo_url"]}" class="photo" alt="{emp["name"]}">' if emp.get("photo_url") else '<div class="photo-placeholder"><i class="fas fa-user-tie"></i></div>'
        
        cards_html += f'''
        <div class="id-card">
            <div class="card-header">
                <div class="header-content">
                    {f'<img src="{institute.get("logo_url")}" class="logo" alt="Logo">' if institute.get("logo_url") else '<i class="fas fa-school"></i>'}
                    <div>
                        <h3>{institute.get("institute_name", "School")}</h3>
                        <p>{institute.get("target_line", "")}</p>
                    </div>
                </div>
            </div>
            <div class="card-body">
                <div class="photo-section">
                    {photo_html}
                    <div class="info">
                        <h2>{emp["name"]}</h2>
                        <p class="id">ID: {emp["employee_id"]}</p>
                        <p><strong>Role:</strong> {emp["role"]}</p>
                        <p><strong>Gender:</strong> {emp["gender"]}</p>
                        <p><strong>DOB:</strong> {emp["date_of_birth"]}</p>
                        <p><strong>DOJ:</strong> {emp["date_of_joining"]}</p>
                        <p><strong>Phone:</strong> {emp["phone"]}</p>
                    </div>
                </div>
                <div class="footer-section">
                    <div class="qr-code">
                        <img src="{emp["qr_code"]}" alt="QR Code">
                    </div>
                    <div class="contact">
                        <p>{institute.get("address", "")}</p>
                        <p>{institute.get("phone_number", "")}</p>
                    </div>
                </div>
            </div>
            <div class="card-footer">
                <p>Authorized Signature</p>
            </div>
        </div>
        '''
    
    return f'''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Employee ID Cards - {institute.get("institute_name", "School")}</title>
        <meta charset="UTF-8">
        <style>
            * {{
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }}
            body {{
                font-family: Arial, sans-serif;
                background: #f3f4f6;
                padding: 20px;
            }}
            .print-container {{
                display: flex;
                flex-wrap: wrap;
                gap: 20px;
                justify-content: center;
            }}
            .id-card {{
                width: 350px;
                background: white;
                border-radius: 16px;
                overflow: hidden;
                box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.1);
                border: 2px solid #ffa500;
                page-break-inside: avoid;
                break-inside: avoid;
            }}
            .card-header {{
                background: linear-gradient(135deg, #ffa500, #ff8c00);
                padding: 12px 16px;
                color: white;
            }}
            .header-content {{
                display: flex;
                align-items: center;
                gap: 10px;
            }}
            .header-content i, .header-content .logo {{
                font-size: 32px;
                width: 40px;
                height: 40px;
                object-fit: cover;
                border-radius: 50%;
            }}
            .header-content h3 {{
                font-size: 14px;
                margin: 0;
            }}
            .header-content p {{
                font-size: 9px;
                margin: 2px 0 0;
                opacity: 0.9;
            }}
            .card-body {{
                padding: 16px;
            }}
            .photo-section {{
                display: flex;
                gap: 15px;
                margin-bottom: 15px;
            }}
            .photo {{
                width: 80px;
                height: 80px;
                border-radius: 50%;
                object-fit: cover;
                border: 3px solid #ffa500;
            }}
            .photo-placeholder {{
                width: 80px;
                height: 80px;
                border-radius: 50%;
                background: linear-gradient(135deg, #fed7aa, #fed7aa);
                display: flex;
                align-items: center;
                justify-content: center;
                border: 3px solid #ffa500;
            }}
            .photo-placeholder i {{
                font-size: 35px;
                color: #ffa500;
            }}
            .info {{
                flex: 1;
            }}
            .info h2 {{
                font-size: 16px;
                margin: 0 0 5px;
                color: #1f2937;
            }}
            .info .id {{
                font-size: 11px;
                color: #ffa500;
                margin-bottom: 8px;
            }}
            .info p {{
                font-size: 11px;
                margin: 3px 0;
                color: #4b5563;
            }}
            .footer-section {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding-top: 12px;
                border-top: 1px solid #e5e7eb;
            }}
            .qr-code img {{
                width: 70px;
                height: 70px;
            }}
            .contact {{
                text-align: right;
            }}
            .contact p {{
                font-size: 9px;
                margin: 2px 0;
                color: #6b7280;
            }}
            .card-footer {{
                background: #fff7ed;
                padding: 6px;
                text-align: center;
            }}
            .card-footer p {{
                font-size: 9px;
                color: #ffa500;
                margin: 0;
            }}
            @media print {{
                body {{
                    background: white;
                    padding: 0;
                }}
                .id-card {{
                    box-shadow: none;
                    break-inside: avoid;
                    page-break-inside: avoid;
                }}
                .no-print {{
                    display: none;
                }}
            }}
        </style>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    </head>
    <body>
        <div class="no-print" style="text-align: center; margin-bottom: 20px;">
            <button onclick="window.print()" style="padding: 10px 24px; background: #ffa500; color: white; border: none; border-radius: 8px; cursor: pointer; font-size: 14px;">
                <i class="fas fa-print"></i> Print All ID Cards
            </button>
            <button onclick="window.close()" style="padding: 10px 24px; background: #6b7280; color: white; border: none; border-radius: 8px; cursor: pointer; font-size: 14px; margin-left: 10px;">
                <i class="fas fa-times"></i> Close
            </button>
        </div>
        <div class="print-container">
            {cards_html}
        </div>
        <script>
            // Auto-print when loaded (optional - uncomment if needed)
            // setTimeout(() => window.print(), 1000);
        </script>
    </body>
    </html>
    '''