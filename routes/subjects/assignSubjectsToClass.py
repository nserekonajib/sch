# assignSubjectsToClass.py - Fixed with correct table relationship
from flask import Blueprint, render_template, request, jsonify, session
from supabase import create_client, Client
import os
import uuid
from datetime import datetime
import json
from functools import wraps
from dotenv import load_dotenv

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

subjects_bp = Blueprint('subjects', __name__, url_prefix='/subjects')

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

@subjects_bp.route('/')
@login_required
def index():
    """Classes With Subjects Page"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return render_template('subjects/index.html', classes_data=[], teachers=[], institute_id=None)
    
    try:
        # Get all classes with their subjects
        classes_response = supabase.table('classes')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('name')\
            .execute()
        
        classes = classes_response.data if classes_response.data else []
        
        print(f"Classes found: {len(classes)}")
        
        if not classes:
            return render_template('subjects/index.html', classes_data=[], teachers=[], institute_id=institute_id)
        
        # Get all subjects with their class associations - Fix: Don't join with teachers, fetch separately
        subjects_response = supabase.table('class_subjects')\
            .select('*, subjects(*)')\
            .eq('institute_id', institute_id)\
            .execute()
        
        subjects_data = subjects_response.data if subjects_response.data else []
        
        print(f"Subjects found: {len(subjects_data)}")
        
        # Manually fetch teacher info for each subject
        for subject in subjects_data:
            if subject.get('teacher_id'):
                teacher_response = supabase.table('employees')\
                    .select('id, name, employee_id, photo_url')\
                    .eq('id', subject['teacher_id'])\
                    .execute()
                if teacher_response.data:
                    subject['teachers'] = teacher_response.data[0]
        
        # Organize subjects by class
        classes_data = []
        for class_item in classes:
            class_subjects = [s for s in subjects_data if s.get('class_id') == class_item['id']]
            classes_data.append({
                'class': class_item,
                'subjects': class_subjects
            })
        
        # Get teachers for the modal (only those with role = 'teacher')
        teachers_response = supabase.table('employees')\
            .select('id, name, employee_id, photo_url')\
            .eq('institute_id', institute_id)\
            .eq('role', 'teacher')\
            .eq('status', 'active')\
            .order('name')\
            .execute()
        
        teachers = teachers_response.data if teachers_response.data else []
        
        print(f"Teachers found: {len(teachers)}")
        
        return render_template('subjects/index.html', classes_data=classes_data, teachers=teachers, institute_id=institute_id)
        
    except Exception as e:
        print(f"Error loading subjects page: {e}")
        import traceback
        traceback.print_exc()
        return render_template('subjects/index.html', classes_data=[], teachers=[], institute_id=institute_id)

@subjects_bp.route('/api/teachers/search', methods=['GET'])
@login_required
def search_teachers():
    """Search teachers for assignment"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        search_term = request.args.get('q', '').strip()
        
        query = supabase.table('employees')\
            .select('id, name, employee_id, photo_url')\
            .eq('institute_id', institute_id)\
            .eq('role', 'teacher')\
            .eq('status', 'active')
        
        if search_term and len(search_term) >= 2:
            query = query.or_(f"name.ilike.%{search_term}%,employee_id.ilike.%{search_term}%")
        
        response = query.limit(20).execute()
        teachers = response.data if response.data else []
        
        return jsonify({'success': True, 'teachers': teachers})
        
    except Exception as e:
        print(f"Error searching teachers: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@subjects_bp.route('/api/classes', methods=['GET'])
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

@subjects_bp.route('/api/class-subjects', methods=['GET'])
@login_required
def get_class_subjects():
    """Get subjects for a specific class"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        class_id = request.args.get('class_id')
        
        if not class_id:
            return jsonify({'success': False, 'message': 'Class ID required'}), 400
        
        response = supabase.table('class_subjects')\
            .select('*, subjects(*)')\
            .eq('class_id', class_id)\
            .eq('institute_id', institute_id)\
            .order('created_at')\
            .execute()
        
        subjects = response.data if response.data else []
        
        # Manually fetch teacher info
        for subject in subjects:
            if subject.get('teacher_id'):
                teacher_response = supabase.table('employees')\
                    .select('id, name, employee_id')\
                    .eq('id', subject['teacher_id'])\
                    .execute()
                if teacher_response.data:
                    subject['teachers'] = teacher_response.data[0]
        
        return jsonify({'success': True, 'subjects': subjects})
        
    except Exception as e:
        print(f"Error getting class subjects: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@subjects_bp.route('/api/assign', methods=['POST'])
@login_required
def assign_subjects():
    """Assign subjects to a class with teacher"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        class_id = data.get('class_id')
        subjects = data.get('subjects', [])
        
        if not class_id:
            return jsonify({'success': False, 'message': 'Please select a class'}), 400
        
        if not subjects:
            return jsonify({'success': False, 'message': 'Please add at least one subject'}), 400
        
        # Get existing subjects for this class
        existing_response = supabase.table('class_subjects')\
            .select('id, subject_id')\
            .eq('class_id', class_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        existing_subjects = {s['subject_id']: s['id'] for s in existing_response.data} if existing_response.data else {}
        
        assigned_count = 0
        updated_count = 0
        errors = []
        
        for subject_data in subjects:
            try:
                subject_name = subject_data.get('name', '').strip()
                marks = float(subject_data.get('marks', 0))
                teacher_id = subject_data.get('teacher_id')
                
                if not subject_name:
                    errors.append(f"Subject name is required")
                    continue
                
                if marks <= 0:
                    errors.append(f"Invalid marks for subject: {subject_name}")
                    continue
                
                if not teacher_id:
                    errors.append(f"Please select a teacher for subject: {subject_name}")
                    continue
                
                # Check if subject already exists in the subjects table
                subject_response = supabase.table('subjects')\
                    .select('*')\
                    .eq('name', subject_name)\
                    .eq('institute_id', institute_id)\
                    .execute()
                
                if subject_response.data:
                    subject_id = subject_response.data[0]['id']
                else:
                    # Create new subject
                    subject_id = str(uuid.uuid4())
                    subject_data_db = {
                        'id': subject_id,
                        'institute_id': institute_id,
                        'name': subject_name,
                        'created_at': datetime.now().isoformat(),
                        'updated_at': datetime.now().isoformat()
                    }
                    supabase.table('subjects').insert(subject_data_db).execute()
                
                # Check if subject is already assigned to this class
                if subject_id in existing_subjects:
                    # Update existing assignment
                    supabase.table('class_subjects')\
                        .update({
                            'marks': marks,
                            'teacher_id': teacher_id,
                            'updated_at': datetime.now().isoformat()
                        })\
                        .eq('id', existing_subjects[subject_id])\
                        .execute()
                    updated_count += 1
                    del existing_subjects[subject_id]
                else:
                    # Create new assignment
                    class_subject_id = str(uuid.uuid4())
                    class_subject_data = {
                        'id': class_subject_id,
                        'institute_id': institute_id,
                        'class_id': class_id,
                        'subject_id': subject_id,
                        'marks': marks,
                        'teacher_id': teacher_id,
                        'created_at': datetime.now().isoformat(),
                        'updated_at': datetime.now().isoformat()
                    }
                    supabase.table('class_subjects').insert(class_subject_data).execute()
                    assigned_count += 1
                    
            except Exception as e:
                errors.append(f"Error with subject {subject_name}: {str(e)}")
        
        # Remove subjects that were not in the new list
        for old_subject_id in existing_subjects.values():
            supabase.table('class_subjects')\
                .delete()\
                .eq('id', old_subject_id)\
                .execute()
        
        return jsonify({
            'success': True,
            'message': f'Successfully assigned {assigned_count} new subject(s) and updated {updated_count} subject(s)',
            'assigned': assigned_count,
            'updated': updated_count,
            'errors': errors if errors else None
        })
        
    except Exception as e:
        print(f"Error assigning subjects: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@subjects_bp.route('/api/subject/delete/<class_subject_id>', methods=['DELETE'])
@login_required
def delete_subject(class_subject_id):
    """Remove a subject from a class"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        result = supabase.table('class_subjects')\
            .delete()\
            .eq('id', class_subject_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if result.data:
            return jsonify({'success': True, 'message': 'Subject removed successfully'})
        else:
            return jsonify({'success': False, 'message': 'Subject not found'}), 404
            
    except Exception as e:
        print(f"Error deleting subject: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500