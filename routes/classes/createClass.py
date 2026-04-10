# createClass.py - Updated with modal-based edit functionality
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from supabase import create_client, Client
import os
from functools import wraps
from datetime import datetime
import uuid
from dotenv import load_dotenv

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

class_bp = Blueprint('class', __name__, url_prefix='/classes')

def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            flash('Please login to access this page', 'error')
            return redirect(url_for('auth.login'))
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

@class_bp.route('/')
@login_required
def index():
    """List all classes"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        flash('Please complete your institute profile first', 'warning')
        return redirect(url_for('instituteProfile.profile'))
    
    try:
        # Get all classes with their sections
        response = supabase.table('classes')\
            .select('*, class_sections(section_id), sections(name, id)')\
            .eq('institute_id', institute_id)\
            .order('created_at', desc=True)\
            .execute()
        
        classes = response.data if response.data else []
        
        # Process classes to include sections properly
        for class_item in classes:
            # Get sections for this class
            sections_response = supabase.table('class_sections')\
                .select('sections(id, name)')\
                .eq('class_id', class_item['id'])\
                .execute()
            
            class_item['sections'] = []
            if sections_response.data:
                for cs in sections_response.data:
                    if cs.get('sections'):
                        class_item['sections'].append(cs['sections'])
        
        # Get all sections for dropdown
        sections_response = supabase.table('sections')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('name')\
            .execute()
        
        sections = sections_response.data if sections_response.data else []
        
        return render_template('classes/index.html', classes=classes, sections=sections)
        
    except Exception as e:
        print(f"Error fetching classes: {e}")
        flash('Error loading classes', 'error')
        return render_template('classes/index.html', classes=[], sections=[])

@class_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    """Create a new class"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        flash('Please complete your institute profile first', 'warning')
        return redirect(url_for('instituteProfile.profile'))
    
    if request.method == 'POST':
        try:
            class_name = request.form.get('class_name', '').strip()
            section_ids = request.form.getlist('sections[]')
            
            if not class_name:
                flash('Class name is required', 'error')
                return redirect(url_for('class.create'))
            
            # Check if class already exists
            existing = supabase.table('classes')\
                .select('id')\
                .eq('institute_id', institute_id)\
                .eq('name', class_name)\
                .execute()
            
            if existing.data and len(existing.data) > 0:
                flash('A class with this name already exists', 'error')
                return redirect(url_for('class.create'))
            
            # Create the class
            class_id = str(uuid.uuid4())
            class_data = {
                'id': class_id,
                'institute_id': institute_id,
                'name': class_name,
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }
            
            class_result = supabase.table('classes').insert(class_data).execute()
            
            if class_result.data:
                # Link sections to class if any selected
                if section_ids:
                    class_sections = []
                    for section_id in section_ids:
                        class_sections.append({
                            'class_id': class_id,
                            'section_id': section_id,
                            'created_at': datetime.now().isoformat()
                        })
                    
                    supabase.table('class_sections').insert(class_sections).execute()
                
                flash('Class created successfully!', 'success')
                return redirect(url_for('class.index'))
            else:
                flash('Failed to create class', 'error')
                
        except Exception as e:
            print(f"Error creating class: {e}")
            flash(f'Error: {str(e)}', 'error')
    
    # Get all sections for dropdown
    sections_response = supabase.table('sections')\
        .select('*')\
        .eq('institute_id', institute_id)\
        .order('name')\
        .execute()
    
    sections = sections_response.data if sections_response.data else []
    
    return render_template('classes/create.html', sections=sections)

@class_bp.route('/api/class/<class_id>', methods=['GET'])
@login_required
def get_class(class_id):
    """Get class data for editing via API"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Get class data
        class_response = supabase.table('classes')\
            .select('*')\
            .eq('id', class_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if not class_response.data:
            return jsonify({'success': False, 'message': 'Class not found'}), 404
        
        class_data = class_response.data[0]
        
        # Get linked sections for this class
        linked_response = supabase.table('class_sections')\
            .select('section_id')\
            .eq('class_id', class_id)\
            .execute()
        
        linked_section_ids = [item['section_id'] for item in (linked_response.data or [])]
        
        # Get all sections
        sections_response = supabase.table('sections')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('name')\
            .execute()
        
        sections = sections_response.data if sections_response.data else []
        
        return jsonify({
            'success': True,
            'class': class_data,
            'linked_sections': linked_section_ids,
            'sections': sections
        })
        
    except Exception as e:
        print(f"Error fetching class: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@class_bp.route('/api/class/<class_id>/update', methods=['POST'])
@login_required
def update_class(class_id):
    """Update class via API"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        class_name = data.get('class_name', '').strip()
        section_ids = data.get('sections', [])
        
        if not class_name:
            return jsonify({'success': False, 'message': 'Class name is required'}), 400
        
        # Check if class exists and belongs to institute
        class_check = supabase.table('classes')\
            .select('id')\
            .eq('id', class_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if not class_check.data:
            return jsonify({'success': False, 'message': 'Class not found'}), 404
        
        # Update class
        update_data = {
            'name': class_name,
            'updated_at': datetime.now().isoformat()
        }
        
        result = supabase.table('classes')\
            .update(update_data)\
            .eq('id', class_id)\
            .execute()
        
        if result.data:
            # Update class sections
            # Remove existing links
            supabase.table('class_sections')\
                .delete()\
                .eq('class_id', class_id)\
                .execute()
            
            # Add new links
            if section_ids:
                class_sections = []
                for section_id in section_ids:
                    class_sections.append({
                        'class_id': class_id,
                        'section_id': section_id,
                        'created_at': datetime.now().isoformat()
                    })
                
                supabase.table('class_sections').insert(class_sections).execute()
            
            return jsonify({'success': True, 'message': 'Class updated successfully'})
        else:
            return jsonify({'success': False, 'message': 'Failed to update class'}), 500
            
    except Exception as e:
        print(f"Error updating class: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@class_bp.route('/<class_id>/delete', methods=['POST'])
@login_required
def delete(class_id):
    """Delete a class"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    try:
        # Check if class exists
        class_check = supabase.table('classes')\
            .select('id')\
            .eq('id', class_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if not class_check.data:
            return jsonify({'success': False, 'message': 'Class not found'}), 404
        
        # Delete class sections first
        supabase.table('class_sections')\
            .delete()\
            .eq('class_id', class_id)\
            .execute()
        
        # Delete class
        result = supabase.table('classes')\
            .delete()\
            .eq('id', class_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if result.data:
            return jsonify({'success': True, 'message': 'Class deleted successfully'})
        else:
            return jsonify({'success': False, 'message': 'Failed to delete class'}), 500
            
    except Exception as e:
        print(f"Error deleting class: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

# Section Management APIs
@class_bp.route('/api/sections', methods=['GET'])
@login_required
def get_sections():
    """Get all sections for dropdown"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        response = supabase.table('sections')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('name')\
            .execute()
        
        sections = response.data if response.data else []
        return jsonify({'success': True, 'sections': sections})
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@class_bp.route('/api/sections/create', methods=['POST'])
@login_required
def create_section():
    """Create a new section via API"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        section_name = data.get('name', '').strip().upper()
        
        if not section_name:
            return jsonify({'success': False, 'message': 'Section name is required'}), 400
        
        # Check if section already exists
        existing = supabase.table('sections')\
            .select('id')\
            .eq('institute_id', institute_id)\
            .eq('name', section_name)\
            .execute()
        
        if existing.data and len(existing.data) > 0:
            return jsonify({'success': False, 'message': 'Section already exists'}), 400
        
        # Create new section
        section_id = str(uuid.uuid4())
        section_data = {
            'id': section_id,
            'institute_id': institute_id,
            'name': section_name,
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        result = supabase.table('sections').insert(section_data).execute()
        
        if result.data:
            new_section = result.data[0]
            return jsonify({
                'success': True,
                'section': new_section,
                'message': 'Section created successfully'
            })
        else:
            return jsonify({'success': False, 'message': 'Failed to create section'}), 500
            
    except Exception as e:
        print(f"Error creating section: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500