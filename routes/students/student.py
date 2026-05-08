from routes.auth.auth import role_required
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
from routes.accounts.accounts import get_institute_id

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
@role_required(['owner', 'teacher', 'accountant'])
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
@role_required(['owner', 'teacher', 'accountant'])
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
@role_required(['owner', 'teacher', 'accountant'])
def add_student():
    """Add a single student via AJAX with enrollment confirmation"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        
        # Generate unique student ID
        class_id = data.get('class_id')
        class_name = data.get('class_name', '')
        
        if not class_id:
            return jsonify({'success': False, 'message': 'Class ID is required'}), 400
        
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
        student_uuid = str(uuid.uuid4())
        current_year = datetime.now().year
        current_time = datetime.now().isoformat()
        
        student_data = {
            'id': student_uuid,
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
            'created_at': current_time,
            'updated_at': current_time
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
        
        if not result.data:
            return jsonify({'success': False, 'message': 'Failed to add student to students table'}), 500
        
        # Auto-enroll student to class
        enrollment_uuid = str(uuid.uuid4())
        enrollment_data = {
            'id': enrollment_uuid,
            'student_id': student_uuid,
            'class_id': class_id,
            'academic_year': current_year,
            'enrolled_at': current_time,
            'updated_at': current_time
        }
        
        # Insert into class_enrollments
        enrollment_result = supabase.table('class_enrollments').insert(enrollment_data).execute()
        
        # Verify enrollment was successful
        if not enrollment_result.data:
            # Rollback: Delete the student if enrollment fails
            print(f"Warning: Failed to create enrollment for student {student_uuid}. Rolling back...")
            supabase.table('students').delete().eq('id', student_uuid).execute()
            return jsonify({'success': False, 'message': 'Failed to enroll student in class'}), 500
        
        # Double-check enrollment exists
        verify_enrollment = supabase.table('class_enrollments')\
            .select('id, student_id, class_id, academic_year')\
            .eq('student_id', student_uuid)\
            .eq('class_id', class_id)\
            .eq('academic_year', current_year)\
            .execute()
        
        enrollment_verified = len(verify_enrollment.data) > 0
        
        # Also handle future academic years (optional)
        future_years = [current_year + 1, current_year + 2]
        future_enrollments = []
        
        for year in future_years:
            future_enrollment_data = {
                'id': str(uuid.uuid4()),
                'student_id': student_uuid,
                'class_id': class_id,
                'academic_year': year,
                'enrolled_at': current_time,
                'updated_at': current_time
            }
            try:
                future_result = supabase.table('class_enrollments').insert(future_enrollment_data).execute()
                if future_result.data:
                    future_enrollments.append(year)
            except Exception as e:
                print(f"Note: Could not create future enrollment for {year}: {e}")
        
        return jsonify({
            'success': True,
            'message': 'Student added and enrolled successfully!',
            'student': result.data[0],
            'enrollment': {
                'verified': enrollment_verified,
                'enrollment_id': enrollment_result.data[0]['id'] if enrollment_result.data else None,
                'academic_year': current_year,
                'future_enrollments': future_enrollments
            }
        })
            
    except Exception as e:
        print(f"Error adding student: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500
    
@student_bp.route('/update/<student_id>', methods=['PUT'])
@role_required(['owner', 'teacher', 'accountant'])
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
@role_required(['owner', 'teacher', 'accountant'])
def import_students():
    """Import students from Excel/CSV file with enrollment confirmation"""
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
        
        # Read file
        if file.filename.endswith('.csv'):
            df = pd.read_csv(io.StringIO(file.stream.read().decode('utf-8')))
        else:
            df = pd.read_excel(file)
        
        # Find the name column
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
        enrollments_added = 0
        errors = []
        current_year = datetime.now().year
        current_time = datetime.now().isoformat()
        
        for idx, row in df.iterrows():
            try:
                student_name = str(row.get(name_column, '')).strip()
                
                # Skip empty names
                if not student_name or student_name == 'nan':
                    continue
                
                student_uuid = str(uuid.uuid4())
                student_id = generate_unique_student_id(institute_id, class_name, existing_ids)
                existing_ids.add(student_id)
                
                student_data = {
                    'id': student_uuid,
                    'institute_id': institute_id,
                    'student_id': student_id,
                    'name': student_name,
                    'class_id': class_id,
                    'status': 'active',
                    'enrollment_date': datetime.now().date().isoformat(),
                    'created_at': current_time,
                    'updated_at': current_time
                }
                
                # Insert student
                result = supabase.table('students').insert(student_data).execute()
                
                if result.data:
                    students_added += 1
                    
                    # Create enrollment record
                    enrollment_data = {
                        'id': str(uuid.uuid4()),
                        'student_id': student_uuid,
                        'class_id': class_id,
                        'academic_year': current_year,
                        'enrolled_at': current_time,
                        'updated_at': current_time
                    }
                    
                    enrollment_result = supabase.table('class_enrollments').insert(enrollment_data).execute()
                    
                    if enrollment_result.data:
                        enrollments_added += 1
                    else:
                        errors.append(f"Row {idx + 2}: Student added but enrollment failed for {student_name}")
                else:
                    errors.append(f"Row {idx + 2}: Failed to add student {student_name}")
                    
            except Exception as e:
                errors.append(f"Row {idx + 2}: {str(e)}")
        
        return jsonify({
            'success': True,
            'message': f'Successfully imported {students_added} students with {enrollments_added} enrollments',
            'students_added': students_added,
            'enrollments_added': enrollments_added,
            'errors': errors if errors else None
        })
        
    except Exception as e:
        print(f"Error importing students: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@student_bp.route('/download-template', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
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
@role_required(['owner', 'teacher', 'accountant'])
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
@role_required(['owner', 'teacher', 'accountant'])
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
@role_required(['owner', 'teacher', 'accountant'])
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
    
    
# student.py - Add this new API endpoint for paginated students

@student_bp.route('/api/students', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_students_api():
    """Get students with pagination via API"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Get pagination parameters
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 30))
        
        # Get filter parameters
        search = request.args.get('search', '').strip()
        class_name = request.args.get('class', '').strip()
        category = request.args.get('category', '').strip()
        status = request.args.get('status', '').strip()
        
        # Start building query
        query = supabase.table('students')\
            .select('*, classes(name, id)', count='exact')\
            .eq('institute_id', institute_id)
        
        # Apply filters
        if search:
            # Search in name or student_id
            query = query.or_(f"name.ilike.%{search}%,student_id.ilike.%{search}%")
        
        if class_name:
            # Filter by class name (needs a more complex approach since classes is a relation)
            # First get class IDs for the given class name
            classes_response = supabase.table('classes')\
                .select('id')\
                .eq('name', class_name)\
                .eq('institute_id', institute_id)\
                .execute()
            
            if classes_response.data:
                class_ids = [c['id'] for c in classes_response.data]
                query = query.in_('class_id', class_ids)
        
        if category:
            query = query.eq('category', category)
        
        if status:
            query = query.eq('status', status)
        
        # Get total count
        count_response = query.execute()
        total = len(count_response.data) if count_response.data else 0
        
        # Calculate range
        start = (page - 1) * per_page
        end = start + per_page - 1
        
        # Get paginated data
        response = query.range(start, end).order('created_at', desc=True).execute()
        
        students = response.data if response.data else []
        
        # Check if there are more records
        has_more = (page * per_page) < total
        
        return jsonify({
            'success': True,
            'data': students,
            'total': total,
            'page': page,
            'per_page': per_page,
            'has_more': has_more
        })
        
    except Exception as e:
        print(f"Error fetching students via API: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    
    
@student_bp.route('/import-from-school-pay', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def import_from_school_pay():
    """Import students from School Pay file format - only uses Payment Code, First Name, Last Name, Student Phone"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        class_id = request.form.get('class_id')
        file = request.files.get('file')
        
        print(f"Debug - class_id: {class_id}")
        print(f"Debug - file present: {file is not None}")
        if file:
            print(f"Debug - filename: {file.filename}")
        
        if not class_id:
            return jsonify({'success': False, 'message': 'Please select a class'}), 400
        
        if not file:
            return jsonify({'success': False, 'message': 'Please select a file'}), 400
        
        # Get class name and verify class exists
        class_response = supabase.table('classes')\
            .select('name')\
            .eq('id', class_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        print(f"Debug - class_response: {class_response.data}")
        
        if not class_response.data:
            return jsonify({'success': False, 'message': 'Selected class not found'}), 400
        
        class_name = class_response.data[0]['name']
        
        # Read file with proper .xls support
        filename = file.filename.lower()
        print(f"Debug - processing file type: {filename}")
        
        try:
            if filename.endswith('.csv'):
                # Handle CSV files
                content = file.stream.read()
                print(f"Debug - CSV content length: {len(content)}")
                try:
                    # Try UTF-8 first
                    df = pd.read_csv(io.StringIO(content.decode('utf-8')))
                except UnicodeDecodeError:
                    # Try other encodings
                    try:
                        df = pd.read_csv(io.StringIO(content.decode('latin1')))
                    except:
                        df = pd.read_csv(io.BytesIO(content), encoding='utf-8', engine='python')
            
            elif filename.endswith('.xls'):
                # Handle old Excel .xls files
                import tempfile
                
                # Save uploaded file temporarily
                with tempfile.NamedTemporaryFile(suffix='.xls', delete=False) as tmp_file:
                    file.save(tmp_file.name)
                    tmp_path = tmp_file.name
                    print(f"Debug - saved .xls to temp file: {tmp_path}")
                
                try:
                    # Try reading with xlrd engine for .xls files
                    df = pd.read_excel(tmp_path, engine='xlrd')
                    print(f"Debug - successfully read .xls with xlrd, rows: {len(df)}")
                except Exception as e:
                    print(f"Debug - xlrd failed: {e}")
                    # If xlrd fails, try using openpyxl
                    try:
                        df = pd.read_excel(tmp_path, engine='openpyxl')
                        print(f"Debug - successfully read .xls with openpyxl, rows: {len(df)}")
                    except Exception as e2:
                        print(f"Debug - openpyxl also failed: {e2}")
                        raise Exception(f"Could not read .xls file. Please save as .xlsx format. Error: {str(e)}")
                finally:
                    # Clean up temp file
                    if os.path.exists(tmp_path):
                        os.unlink(tmp_path)
            
            elif filename.endswith('.xlsx'):
                # Handle modern Excel .xlsx files
                df = pd.read_excel(file, engine='openpyxl')
                print(f"Debug - successfully read .xlsx, rows: {len(df)}")
            
            else:
                return jsonify({'success': False, 'message': 'Unsupported file format. Please upload .csv, .xls, or .xlsx files'}), 400
        
        except Exception as e:
            print(f"Debug - file reading error: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({'success': False, 'message': f'Error reading file: {str(e)}'}), 400
        
        # Print column names for debugging
        print(f"Debug - columns found: {list(df.columns)}")
        
        # Required columns
        required_columns = ['Payment Code', 'First Name', 'Last Name', 'Student Phone']
        
        # Normalize column names (remove extra spaces)
        df.columns = df.columns.str.strip()
        
        # Check if all required columns exist
        missing_columns = [col for col in required_columns if col not in df.columns]
        
        if missing_columns:
            # Try case-insensitive matching
            df_columns_lower = {col.lower(): col for col in df.columns}
            found_columns = {}
            
            for req_col in required_columns:
                if req_col.lower() in df_columns_lower:
                    found_columns[req_col] = df_columns_lower[req_col.lower()]
            
            if len(found_columns) == len(required_columns):
                # Rename columns to match expected names
                for std_col, actual_col in found_columns.items():
                    df.rename(columns={actual_col: std_col}, inplace=True)
                print(f"Debug - renamed columns: {list(df.columns)}")
            else:
                return jsonify({
                    'success': False, 
                    'message': f'Missing required columns. Found columns: {list(df.columns)}. Required: {required_columns}'
                }), 400
        
        # Clean data - remove any completely empty rows
        df = df.dropna(how='all')
        
        if df.empty:
            return jsonify({'success': False, 'message': 'The uploaded file is empty'}), 400
        
        print(f"Debug - processing {len(df)} rows")
        
        # Get existing student IDs and phone numbers for this institute
        existing_response = supabase.table('students')\
            .select('student_id, contact_number')\
            .eq('institute_id', institute_id)\
            .execute()
        
        existing_ids = set()
        existing_phones = set()
        
        if existing_response.data:
            for student in existing_response.data:
                if student.get('student_id'):
                    existing_ids.add(str(student.get('student_id')))
                if student.get('contact_number'):
                    existing_phones.add(str(student.get('contact_number')))
        
        print(f"Debug - existing students: {len(existing_ids)}")
        
        # Prepare batch data
        students_batch = []
        enrollments_batch = []
        current_year = datetime.now().year
        current_time = datetime.now().isoformat()
        
        # Statistics
        students_added = 0
        students_skipped = 0
        enrollments_added = 0
        errors = []
        warnings = []
        
        # Batch size for efficient processing
        BATCH_SIZE = 100
        
        # Process each row
        for idx, row in df.iterrows():
            try:
                # Extract and clean data with proper NaN handling
                payment_code_raw = row.get('Payment Code')
                if pd.isna(payment_code_raw) or str(payment_code_raw).strip() == '':
                    payment_code = None
                else:
                    payment_code = str(payment_code_raw).strip()
                
                first_name_raw = row.get('First Name')
                if pd.isna(first_name_raw):
                    errors.append(f"Row {idx + 2}: Skipped - Missing first name")
                    students_skipped += 1
                    continue
                first_name = str(first_name_raw).strip()
                
                last_name_raw = row.get('Last Name')
                if pd.isna(last_name_raw):
                    last_name = ''
                else:
                    last_name = str(last_name_raw).strip()
                
                student_phone_raw = row.get('Student Phone')
                if pd.isna(student_phone_raw):
                    student_phone = ''
                else:
                    student_phone = str(student_phone_raw).strip()
                
                # Skip if no first name
                if not first_name or first_name == 'nan':
                    errors.append(f"Row {idx + 2}: Skipped - Missing first name")
                    students_skipped += 1
                    continue
                
                # Create full name
                full_name = f"{first_name} {last_name}".strip() if last_name else first_name
                
                # Format phone number to 256 format
                formatted_phone = None
                if student_phone and student_phone not in ['nan', 'None', '']:
                    # Remove any non-digit characters
                    digits_only = ''.join(filter(str.isdigit, student_phone))
                    
                    if digits_only:
                        # Handle different phone formats
                        if digits_only.startswith('0') and len(digits_only) == 10:
                            formatted_phone = '256' + digits_only[1:]
                        elif digits_only.startswith('256') and len(digits_only) == 12:
                            formatted_phone = digits_only
                        elif len(digits_only) == 9:
                            formatted_phone = '256' + digits_only
                        elif len(digits_only) == 12:
                            formatted_phone = digits_only
                        elif len(digits_only) > 12:
                            formatted_phone = digits_only[:12]
                        else:
                            formatted_phone = digits_only
                        
                        if formatted_phone and len(formatted_phone) == 12 and formatted_phone.startswith('256'):
                            pass
                        else:
                            warnings.append(f"Row {idx + 2}: Phone {student_phone} formatted to {formatted_phone}")
                
                # Check for duplicates
                exists = False
                check_criteria = []
                
                if payment_code and payment_code in existing_ids:
                    exists = True
                    check_criteria.append(f"Payment Code {payment_code}")
                
                if formatted_phone and formatted_phone in existing_phones:
                    exists = True
                    check_criteria.append(f"Phone {formatted_phone}")
                
                if exists:
                    students_skipped += 1
                    errors.append(f"Row {idx + 2}: {full_name} skipped - exists ({', '.join(check_criteria)})")
                    continue
                
                # Generate student ID
                if payment_code and payment_code not in existing_ids:
                    student_id = payment_code
                else:
                    student_id = generate_unique_student_id(institute_id, class_name, existing_ids)
                
                existing_ids.add(student_id)
                if formatted_phone:
                    existing_phones.add(formatted_phone)
                
                student_uuid = str(uuid.uuid4())
                
                # Prepare student data
                student_data = {
                    'id': student_uuid,
                    'institute_id': institute_id,
                    'student_id': student_id,
                    'name': full_name,
                    'contact_number': formatted_phone,
                    'class_id': class_id,
                    'status': 'active',
                    'enrollment_date': datetime.now().date().isoformat(),
                    'created_at': current_time,
                    'updated_at': current_time
                }
                
                students_batch.append(student_data)
                
                # Prepare enrollment record
                enrollment_data = {
                    'id': str(uuid.uuid4()),
                    'student_id': student_uuid,
                    'class_id': class_id,
                    'academic_year': current_year,
                    'enrolled_at': current_time,
                    'updated_at': current_time
                }
                
                enrollments_batch.append(enrollment_data)
                
                # Process in batches
                if len(students_batch) >= BATCH_SIZE:
                    # Insert batch of students
                    result = supabase.table('students').insert(students_batch).execute()
                    if result.data:
                        students_added += len(students_batch)
                        
                        # Insert batch of enrollments
                        enroll_result = supabase.table('class_enrollments').insert(enrollments_batch).execute()
                        if enroll_result.data:
                            enrollments_added += len(enrollments_batch)
                    
                    # Clear batches
                    students_batch = []
                    enrollments_batch = []
                
            except Exception as e:
                error_msg = f"Row {idx + 2}: {str(e)}"
                print(f"Debug - {error_msg}")
                errors.append(error_msg)
                students_skipped += 1
        
        # Insert remaining records
        if students_batch:
            try:
                result = supabase.table('students').insert(students_batch).execute()
                if result.data:
                    students_added += len(students_batch)
                    
                    enroll_result = supabase.table('class_enrollments').insert(enrollments_batch).execute()
                    if enroll_result.data:
                        enrollments_added += len(enrollments_batch)
            except Exception as e:
                errors.append(f"Final batch error: {str(e)}")
        
        # Prepare response
        message = f'Successfully imported {students_added} students with {enrollments_added} enrollments'
        if students_skipped > 0:
            message += f'. Skipped {students_skipped} students.'
        
        response_data = {
            'success': True,
            'message': message,
            'students_added': students_added,
            'students_skipped': students_skipped,
            'enrollments_added': enrollments_added
        }
        
        if errors:
            response_data['errors'] = errors[:20]
        
        if warnings:
            response_data['warnings'] = warnings[:10]
        
        print(f"Debug - import completed: {students_added} added, {students_skipped} skipped")
        return jsonify(response_data)
        
    except Exception as e:
        print(f"Error importing from school pay: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Import failed: {str(e)}'}), 500