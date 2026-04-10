# student.py - Updated with unique student ID generation across institutes
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, send_file
from supabase import create_client, Client
import os
import cloudinary
import cloudinary.uploader
from functools import wraps
from datetime import datetime
import uuid
import random
import string
import pandas as pd
import io
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

student_bp = Blueprint('student', __name__, url_prefix='/students')

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
            .select('id')\
            .eq('user_id', user_id)\
            .execute()
        
        if response.data and len(response.data) > 0:
            return response.data[0]['id']
        return None
    except Exception as e:
        print(f"Error getting institute ID: {e}")
        return None

def generate_unique_student_id(institute_id, class_name, existing_ids=None):
    """Generate unique student ID with retry logic and random component"""
    max_attempts = 10
    attempts = 0
    
    if existing_ids is None:
        existing_ids = set()
    
    # Get all existing student IDs for this institute
    if not existing_ids:
        try:
            response = supabase.table('students')\
                .select('student_id')\
                .eq('institute_id', institute_id)\
                .execute()
            
            if response.data:
                for student in response.data:
                    existing_ids.add(student['student_id'])
        except Exception as e:
            print(f"Error fetching existing student IDs: {e}")
    
    while attempts < max_attempts:
        try:
            year = datetime.now().strftime('%Y')
            month = datetime.now().strftime('%m')
            
            # Get prefix from class name
            if class_name:
                prefix = class_name[:3].upper()
            else:
                prefix = 'STD'
            
            # Random component: 4 random letters/digits
            random_component = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
            
            # Get count of students this month for this institute
            response = supabase.table('students')\
                .select('id', count='exact')\
                .eq('institute_id', institute_id)\
                .gte('created_at', f"{year}-{month}-01")\
                .execute()
            
            count = (response.count or 0) + 1
            
            # Create student ID with random component
            student_id = f"{prefix}{year}{month}-{random_component}-{str(count).zfill(3)}"
            
            # Check if this ID already exists
            if student_id not in existing_ids:
                return student_id
                
        except Exception as e:
            print(f"Error generating student ID (attempt {attempts + 1}): {e}")
        
        attempts += 1
        # Add a small delay before retry
        import time
        time.sleep(0.05)
    
    # If all attempts fail, use timestamp-based number
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S%f')
    fallback_id = f"STD-{timestamp}"
    
    # Check if fallback exists
    if fallback_id in existing_ids:
        fallback_id = f"STD-{timestamp}-{random.randint(1000, 9999)}"
    
    return fallback_id

@student_bp.route('/')
@login_required
def index():
    """List all students"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return render_template('students/index.html', students=[], classes=[])
    
    try:
        # Get students with their class info
        response = supabase.table('students')\
            .select('*, classes(name)')\
            .eq('institute_id', institute_id)\
            .order('created_at', desc=True)\
            .execute()
        
        students = response.data if response.data else []
        
        # Get classes for filter
        classes_response = supabase.table('classes')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('name')\
            .execute()
        
        classes = classes_response.data if classes_response.data else []
        
        return render_template('students/index.html', students=students, classes=classes)
        
    except Exception as e:
        print(f"Error fetching students: {e}")
        return render_template('students/index.html', students=[], classes=[])

@student_bp.route('/stats', methods=['GET'])
@login_required
def get_stats():
    """Get student statistics via API"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Get all students
        response = supabase.table('students')\
            .select('status, category')\
            .eq('institute_id', institute_id)\
            .execute()
        
        students = response.data if response.data else []
        
        # Calculate stats
        total = len(students)
        active = sum(1 for s in students if s.get('status') == 'active')
        inactive = total - active
        boarding = sum(1 for s in students if s.get('category') == 'Boarding')
        day = sum(1 for s in students if s.get('category') == 'Day')
        
        # Get total classes count
        classes_response = supabase.table('classes')\
            .select('id', count='exact')\
            .eq('institute_id', institute_id)\
            .execute()
        
        total_classes = classes_response.count or 0
        
        return jsonify({
            'success': True,
            'stats': {
                'total': total,
                'active': active,
                'inactive': inactive,
                'boarding': boarding,
                'day': day,
                'total_classes': total_classes
            }
        })
        
    except Exception as e:
        print(f"Error getting stats: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@student_bp.route('/add', methods=['POST'])
@login_required
def add_student():
    """Add a single student via AJAX"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        
        # Generate unique student ID
        class_id = data.get('class_id')
        class_name = data.get('class_name', '')
        
        # Get existing student IDs for this institute
        existing_ids_response = supabase.table('students')\
            .select('student_id')\
            .eq('institute_id', institute_id)\
            .execute()
        
        existing_ids = set()
        if existing_ids_response.data:
            for student in existing_ids_response.data:
                existing_ids.add(student['student_id'])
        
        student_id = generate_unique_student_id(institute_id, class_name, existing_ids)
        
        # Prepare student data
        student_data = {
            'id': str(uuid.uuid4()),
            'institute_id': institute_id,
            'student_id': student_id,
            'name': data.get('name', '').strip(),
            'gender': data.get('gender'),
            'date_of_birth': data.get('date_of_birth'),
            'nationality': data.get('nationality'),
            'address': data.get('address', '').strip(),
            'contact_number': data.get('contact_number', '').strip(),
            'email': data.get('email', '').strip(),
            'father_name': data.get('father_name', '').strip(),
            'mother_name': data.get('mother_name', '').strip(),
            'religion': data.get('religion'),
            'occupation': data.get('occupation'),
            'reason_for_admission': data.get('reason_for_admission', '').strip(),
            'all_parents': data.get('all_parents'),
            'category': data.get('category'),
            'class_id': class_id,
            'status': 'active',
            'enrollment_date': datetime.now().date().isoformat(),
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        # Handle photo upload
        if data.get('photo_data'):
            try:
                import base64
                import tempfile
                
                photo_data = data['photo_data'].split(',')[1] if ',' in data['photo_data'] else data['photo_data']
                image_bytes = base64.b64decode(photo_data)
                
                with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp_file:
                    tmp_file.write(image_bytes)
                    tmp_path = tmp_file.name
                
                upload_result = cloudinary.uploader.upload(
                    tmp_path,
                    folder=f"student_photos/{institute_id}",
                    public_id=f"{student_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                    overwrite=True
                )
                
                student_data['photo_url'] = upload_result['secure_url']
                student_data['photo_public_id'] = upload_result['public_id']
                
                os.unlink(tmp_path)
                
            except Exception as e:
                print(f"Photo upload error: {e}")
        
        # Insert student
        result = supabase.table('students').insert(student_data).execute()
        
        if result.data:
            # Auto-enroll student to class
            enrollment_data = {
                'student_id': result.data[0]['id'],
                'class_id': class_id,
                'enrolled_at': datetime.now().isoformat(),
                'academic_year': datetime.now().year
            }
            supabase.table('class_enrollments').insert(enrollment_data).execute()
            
            return jsonify({
                'success': True,
                'message': 'Student added successfully!',
                'student': result.data[0]
            })
        else:
            return jsonify({'success': False, 'message': 'Failed to add student'}), 500
            
    except Exception as e:
        print(f"Error adding student: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@student_bp.route('/update/<student_id>', methods=['PUT'])
@login_required
def update_student(student_id):
    """Update student details via AJAX"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        
        # Prepare update data
        update_data = {
            'name': data.get('name', '').strip(),
            'gender': data.get('gender'),
            'date_of_birth': data.get('date_of_birth'),
            'nationality': data.get('nationality'),
            'address': data.get('address', '').strip(),
            'contact_number': data.get('contact_number', '').strip(),
            'email': data.get('email', '').strip(),
            'father_name': data.get('father_name', '').strip(),
            'mother_name': data.get('mother_name', '').strip(),
            'religion': data.get('religion'),
            'occupation': data.get('occupation'),
            'reason_for_admission': data.get('reason_for_admission', '').strip(),
            'all_parents': data.get('all_parents'),
            'category': data.get('category'),
            'updated_at': datetime.now().isoformat()
        }
        
        # Handle class change
        if data.get('class_id'):
            update_data['class_id'] = data.get('class_id')
            
            # Update enrollment
            supabase.table('class_enrollments')\
                .update({'class_id': data.get('class_id'), 'updated_at': datetime.now().isoformat()})\
                .eq('student_id', student_id)\
                .eq('academic_year', datetime.now().year)\
                .execute()
        
        # Handle photo upload
        if data.get('photo_data') and not data.get('photo_data').startswith('http'):
            try:
                import base64
                import tempfile
                
                photo_data = data['photo_data'].split(',')[1] if ',' in data['photo_data'] else data['photo_data']
                image_bytes = base64.b64decode(photo_data)
                
                with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp_file:
                    tmp_file.write(image_bytes)
                    tmp_path = tmp_file.name
                
                # Delete old photo if exists
                old_student = supabase.table('students').select('photo_public_id').eq('id', student_id).execute()
                if old_student.data and old_student.data[0].get('photo_public_id'):
                    try:
                        cloudinary.uploader.destroy(old_student.data[0]['photo_public_id'])
                    except:
                        pass
                
                upload_result = cloudinary.uploader.upload(
                    tmp_path,
                    folder=f"student_photos/{institute_id}",
                    public_id=f"{student_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                    overwrite=True
                )
                
                update_data['photo_url'] = upload_result['secure_url']
                update_data['photo_public_id'] = upload_result['public_id']
                
                os.unlink(tmp_path)
                
            except Exception as e:
                print(f"Photo upload error: {e}")
        
        # Update student
        result = supabase.table('students')\
            .update(update_data)\
            .eq('id', student_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if result.data:
            return jsonify({
                'success': True,
                'message': 'Student updated successfully!',
                'student': result.data[0]
            })
        else:
            return jsonify({'success': False, 'message': 'Student not found'}), 404
            
    except Exception as e:
        print(f"Error updating student: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@student_bp.route('/import', methods=['POST'])
@login_required
def import_students():
    """Import students from Excel/CSV file - simplified to only require names"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        class_id = request.form.get('class_id')
        file = request.files.get('file')
        
        if not class_id:
            return jsonify({'success': False, 'message': 'Please select a class'}), 400
        
        if not file:
            return jsonify({'success': False, 'message': 'Please select a file'}), 400
        
        # Get class name
        class_response = supabase.table('classes')\
            .select('name')\
            .eq('id', class_id)\
            .execute()
        
        class_name = class_response.data[0]['name'] if class_response.data else ''
        
        # Read file - only expecting Name column
        if file.filename.endswith('.csv'):
            df = pd.read_csv(io.StringIO(file.stream.read().decode('utf-8')))
        else:
            df = pd.read_excel(file)
        
        # Find the name column (case insensitive)
        name_column = None
        for col in df.columns:
            if col.lower() in ['name', 'student name', 'full name', 'student_name']:
                name_column = col
                break
        
        if not name_column:
            return jsonify({'success': False, 'message': 'File must contain a "Name" column'}), 400
        
        # Get existing student IDs for this institute
        existing_ids_response = supabase.table('students')\
            .select('student_id')\
            .eq('institute_id', institute_id)\
            .execute()
        
        existing_ids = set()
        if existing_ids_response.data:
            for student in existing_ids_response.data:
                existing_ids.add(student['student_id'])
        
        students_added = 0
        errors = []
        
        for idx, row in df.iterrows():
            try:
                student_name = str(row.get(name_column, '')).strip()
                
                # Skip empty names
                if not student_name or student_name == 'nan':
                    continue
                
                student_id = generate_unique_student_id(institute_id, class_name, existing_ids)
                existing_ids.add(student_id)  # Add to set to avoid duplicates in same batch
                
                student_data = {
                    'id': str(uuid.uuid4()),
                    'institute_id': institute_id,
                    'student_id': student_id,
                    'name': student_name,
                    'class_id': class_id,
                    'status': 'active',
                    'enrollment_date': datetime.now().date().isoformat(),
                    'created_at': datetime.now().isoformat(),
                    'updated_at': datetime.now().isoformat()
                }
                
                # Insert student
                result = supabase.table('students').insert(student_data).execute()
                
                if result.data:
                    # Auto-enroll
                    enrollment_data = {
                        'student_id': result.data[0]['id'],
                        'class_id': class_id,
                        'enrolled_at': datetime.now().isoformat(),
                        'academic_year': datetime.now().year
                    }
                    supabase.table('class_enrollments').insert(enrollment_data).execute()
                    students_added += 1
                else:
                    errors.append(f"Row {idx + 2}: Failed to add student")
                    
            except Exception as e:
                errors.append(f"Row {idx + 2}: {str(e)}")
        
        return jsonify({
            'success': True,
            'message': f'Successfully imported {students_added} students',
            'errors': errors if errors else None
        })
        
    except Exception as e:
        print(f"Error importing students: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@student_bp.route('/download-template', methods=['GET'])
@login_required
def download_template():
    """Download sample Excel template for student import"""
    # Create sample data with just names
    df = pd.DataFrame({
        'Name': ['John Doe', 'Jane Smith', 'Michael Brown', 'Sarah Wilson', 'David Lee']
    })
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Students', index=False)
    
    output.seek(0)
    
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='student_import_template.xlsx'
    )

@student_bp.route('/<student_id>', methods=['GET'])
@login_required
def get_student(student_id):
    """Get student details"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    try:
        response = supabase.table('students')\
            .select('*, classes(name, id)')\
            .eq('id', student_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if response.data:
            return jsonify({'success': True, 'student': response.data[0]})
        else:
            return jsonify({'success': False, 'message': 'Student not found'}), 404
            
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@student_bp.route('/<student_id>/status', methods=['PUT'])
@login_required
def update_status(student_id):
    """Update student status (active/inactive)"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    try:
        data = request.get_json()
        status = data.get('status')
        
        result = supabase.table('students')\
            .update({'status': status, 'updated_at': datetime.now().isoformat()})\
            .eq('id', student_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if result.data:
            return jsonify({'success': True, 'message': f'Student marked as {status}'})
        else:
            return jsonify({'success': False, 'message': 'Student not found'}), 404
            
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@student_bp.route('/get-classes', methods=['GET'])
@login_required
def get_classes():
    """Get all classes for dropdown"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    try:
        response = supabase.table('classes')\
            .select('id, name')\
            .eq('institute_id', institute_id)\
            .order('name')\
            .execute()
        
        return jsonify({'success': True, 'classes': response.data or []})
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500