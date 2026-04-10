# promoteStudents.py - Student Promotion Blueprint (Fixed with proper promotion logic)
from flask import Blueprint, render_template, request, jsonify, session
from supabase import create_client, Client
import os
from datetime import datetime
import uuid
from functools import wraps
from dotenv import load_dotenv

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

promote_bp = Blueprint('promote', __name__, url_prefix='/promote-students')

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

@promote_bp.route('/')
@login_required
def index():
    """Student Promotion Page"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return render_template('promotion/index.html', classes=[], institute_id=None, current_year=datetime.now().year)
    
    try:
        # Get all classes for dropdowns
        classes_response = supabase.table('classes')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('name')\
            .execute()
        
        classes = classes_response.data if classes_response.data else []
        
        return render_template('promotion/index.html', classes=classes, institute_id=institute_id, current_year=datetime.now().year)
        
    except Exception as e:
        print(f"Error loading promotion page: {e}")
        return render_template('promotion/index.html', classes=[], institute_id=institute_id, current_year=datetime.now().year)

@promote_bp.route('/api/students', methods=['GET'])
@login_required
def get_students():
    """Get students by class for promotion"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        class_id = request.args.get('class_id')
        search_term = request.args.get('search', '').strip()
        academic_year = request.args.get('academic_year', str(datetime.now().year))
        
        if not class_id:
            return jsonify({'success': False, 'message': 'Please select a class'}), 400
        
        # Build query - get students currently enrolled in this class for the selected academic year
        query = supabase.table('students')\
            .select('*, classes(name), class_enrollments!inner(academic_year)')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')\
            .eq('class_enrollments.academic_year', int(academic_year))\
            .eq('class_enrollments.class_id', class_id)
        
        # Apply search filter if provided
        if search_term:
            query = query.or_(f"name.ilike.%{search_term}%,student_id.ilike.%{search_term}%")
        
        response = query.order('name').execute()
        
        students = response.data if response.data else []
        
        # Format student data
        formatted_students = []
        for student in students:
            formatted_students.append({
                'id': student['id'],
                'student_id': student['student_id'],
                'name': student['name'],
                'current_class': student['classes']['name'] if student.get('classes') else 'N/A',
                'current_class_id': student['class_id'],
                'gender': student.get('gender', 'N/A'),
                'photo_url': student.get('photo_url')
            })
        
        return jsonify({
            'success': True,
            'students': formatted_students,
            'count': len(formatted_students)
        })
        
    except Exception as e:
        print(f"Error getting students: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@promote_bp.route('/api/classes', methods=['GET'])
@login_required
def get_classes():
    """Get all classes for dropdown"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        response = supabase.table('classes')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('name')\
            .execute()
        
        classes = response.data if response.data else []
        
        return jsonify({'success': True, 'classes': classes})
        
    except Exception as e:
        print(f"Error getting classes: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@promote_bp.route('/api/promote', methods=['POST'])
@login_required
def promote_students():
    """Promote selected students to new class - CORRECT LOGIC"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        student_ids = data.get('student_ids', [])
        new_class_id = data.get('new_class_id')
        academic_year = data.get('academic_year', datetime.now().year)
        
        if not student_ids:
            return jsonify({'success': False, 'message': 'No students selected'}), 400
        
        if not new_class_id:
            return jsonify({'success': False, 'message': 'Please select a target class'}), 400
        
        # Get new class name
        class_response = supabase.table('classes')\
            .select('name')\
            .eq('id', new_class_id)\
            .execute()
        
        new_class_name = class_response.data[0]['name'] if class_response.data else 'N/A'
        print(f"Promoting to class: {new_class_name} (ID: {new_class_id}) for academic year: {academic_year}")
        
        promoted_count = 0
        promotion_records = []
        errors = []
        
        for student_id in student_ids:
            try:
                # Get current student data
                student_response = supabase.table('students')\
                    .select('*, classes(name)')\
                    .eq('id', student_id)\
                    .execute()
                
                if not student_response.data:
                    errors.append(f"Student {student_id} not found")
                    continue
                
                student = student_response.data[0]
                old_class_id = student['class_id']
                old_class_name = student['classes']['name'] if student.get('classes') else 'Old Class'
                
                # STEP 1: Create promotion record
                promotion_id = str(uuid.uuid4())
                promotion_data = {
                    'id': promotion_id,
                    'institute_id': institute_id,
                    'student_id': student_id,
                    'from_class_id': old_class_id,
                    'to_class_id': new_class_id,
                    'promotion_date': datetime.now().date().isoformat(),
                    'academic_year': academic_year,
                    'created_at': datetime.now().isoformat()
                }
                
                supabase.table('student_promotions').insert(promotion_data).execute()
                
                # STEP 2: UPDATE existing enrollment for this academic year (don't insert new)
                # Check if enrollment exists for this academic year
                existing_enrollment = supabase.table('class_enrollments')\
                    .select('id')\
                    .eq('student_id', student_id)\
                    .eq('academic_year', academic_year)\
                    .execute()
                
                if existing_enrollment.data:
                    # UPDATE existing enrollment
                    supabase.table('class_enrollments')\
                        .update({
                            'class_id': new_class_id,
                            'enrolled_at': datetime.now().isoformat(),
                            'updated_at': datetime.now().isoformat()
                        })\
                        .eq('student_id', student_id)\
                        .eq('academic_year', academic_year)\
                        .execute()
                    print(f"Updated enrollment for {student['name']} to {new_class_name}")
                else:
                    # INSERT new enrollment (should not happen if data is clean)
                    enrollment_data = {
                        'id': str(uuid.uuid4()),
                        'student_id': student_id,
                        'class_id': new_class_id,
                        'enrolled_at': datetime.now().isoformat(),
                        'academic_year': academic_year,
                        'created_at': datetime.now().isoformat(),
                        'updated_at': datetime.now().isoformat()
                    }
                    supabase.table('class_enrollments').insert(enrollment_data).execute()
                    print(f"Created new enrollment for {student['name']} to {new_class_name}")
                
                # STEP 3: Update student's current class in students table
                supabase.table('students')\
                    .update({
                        'class_id': new_class_id,
                        'updated_at': datetime.now().isoformat()
                    })\
                    .eq('id', student_id)\
                    .execute()
                
                promoted_count += 1
                promotion_records.append({
                    'student_id': student['student_id'],
                    'student_name': student['name'],
                    'from_class': old_class_name,
                    'to_class': new_class_name,
                    'academic_year': academic_year
                })
                
            except Exception as e:
                print(f"Error promoting student {student_id}: {e}")
                errors.append(f"Error promoting student {student.get('name', student_id)}: {str(e)}")
        
        if promoted_count > 0:
            return jsonify({
                'success': True,
                'message': f'Successfully promoted {promoted_count} student(s) to {new_class_name} for academic year {academic_year}',
                'promoted': promotion_records,
                'errors': errors if errors else None
            })
        else:
            return jsonify({
                'success': False,
                'message': 'No students were promoted',
                'errors': errors
            }), 500
        
    except Exception as e:
        print(f"Error promoting students: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@promote_bp.route('/api/student-year-check', methods=['GET'])
@login_required
def check_student_year():
    """Check if student already has enrollment for a year"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        student_id = request.args.get('student_id')
        academic_year = request.args.get('academic_year')
        
        if not student_id or not academic_year:
            return jsonify({'success': False, 'message': 'Student ID and academic year required'}), 400
        
        response = supabase.table('class_enrollments')\
            .select('id, class_id, classes(name)')\
            .eq('student_id', student_id)\
            .eq('academic_year', int(academic_year))\
            .execute()
        
        if response.data:
            return jsonify({
                'success': True,
                'has_enrollment': True,
                'current_class': response.data[0]['classes']['name'] if response.data[0].get('classes') else 'N/A',
                'class_id': response.data[0]['class_id']
            })
        else:
            return jsonify({
                'success': True,
                'has_enrollment': False
            })
        
    except Exception as e:
        print(f"Error checking student year: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500