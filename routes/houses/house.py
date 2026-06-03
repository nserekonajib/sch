# studentHouses.py - Student Houses/Groups Management Blueprint
from flask import Blueprint, render_template, request, jsonify, session, send_file
from supabase import create_client, Client
import os
import uuid
from datetime import datetime
import json
import io
import pandas as pd
from functools import wraps
from dotenv import load_dotenv
from routes.permissions.permissions import role_required
from routes.accounts.accounts import get_institute_id

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

houses_bp = Blueprint('houses', __name__, url_prefix='/student-houses')

def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Please login'}), 401
        return f(*args, **kwargs)
    return decorated_function


@houses_bp.route('/')
@role_required(['admin', 'teacher', 'owner'])
def index():
    """Houses Management Page"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return render_template('houses/index.html', houses=[], students=[], classes=[], institute_id=None)
    
    try:
        # Get all houses
        houses_response = supabase.table('student_houses')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('name')\
            .execute()
        
        houses = houses_response.data if houses_response.data else []
        
        # Get all students with their house assignments
        students_response = supabase.table('students')\
            .select('id, name, student_id, class_id, classes(name), gender, student_house_id, student_houses(name, color)')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')\
            .order('name')\
            .execute()
        
        students = students_response.data if students_response.data else []
        
        # Get all classes for filter
        classes_response = supabase.table('classes')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('name')\
            .execute()
        
        classes = classes_response.data if classes_response.data else []
        
        return render_template('houses/index.html', houses=houses, students=students, classes=classes, institute_id=institute_id)
        
    except Exception as e:
        print(f"Error loading houses page: {e}")
        return render_template('houses/index.html', houses=[], students=[], classes=[], institute_id=institute_id)


@houses_bp.route('/api/houses', methods=['GET'])
@role_required(['admin', 'teacher', 'owner'])
def get_houses():
    """Get all houses"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        response = supabase.table('student_houses')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('name')\
            .execute()
        
        houses = response.data if response.data else []
        
        return jsonify({'success': True, 'houses': houses})
        
    except Exception as e:
        print(f"Error getting houses: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@houses_bp.route('/api/houses', methods=['POST'])
@role_required(['admin', 'teacher', 'owner'])
def create_house():
    """Create a new house/group"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        
        house_name = data.get('name', '').strip()
        color = data.get('color', '#ffa500')
        motto = data.get('motto', '')
        description = data.get('description', '')
        
        if not house_name:
            return jsonify({'success': False, 'message': 'House name is required'}), 400
        
        # Check if house already exists
        existing = supabase.table('student_houses')\
            .select('id')\
            .eq('institute_id', institute_id)\
            .eq('name', house_name)\
            .execute()
        
        if existing.data:
            return jsonify({'success': False, 'message': 'House with this name already exists'}), 400
        
        house_id = str(uuid.uuid4())
        house_data = {
            'id': house_id,
            'institute_id': institute_id,
            'name': house_name,
            'color': color,
            'motto': motto,
            'description': description,
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        result = supabase.table('student_houses').insert(house_data).execute()
        
        if result.data:
            return jsonify({'success': True, 'message': 'House created successfully', 'house': result.data[0]})
        else:
            return jsonify({'success': False, 'message': 'Failed to create house'}), 500
            
    except Exception as e:
        print(f"Error creating house: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@houses_bp.route('/api/houses/<house_id>', methods=['PUT'])
@role_required(['admin', 'teacher', 'owner'])
def update_house(house_id):
    """Update a house/group"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        
        update_data = {
            'name': data.get('name', '').strip(),
            'color': data.get('color', '#ffa500'),
            'motto': data.get('motto', ''),
            'description': data.get('description', ''),
            'updated_at': datetime.now().isoformat()
        }
        
        if not update_data['name']:
            return jsonify({'success': False, 'message': 'House name is required'}), 400
        
        result = supabase.table('student_houses')\
            .update(update_data)\
            .eq('id', house_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if result.data:
            return jsonify({'success': True, 'message': 'House updated successfully', 'house': result.data[0]})
        else:
            return jsonify({'success': False, 'message': 'House not found'}), 404
            
    except Exception as e:
        print(f"Error updating house: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@houses_bp.route('/api/houses/<house_id>', methods=['DELETE'])
@role_required(['admin', 'teacher', 'owner'])
def delete_house(house_id):
    """Delete a house/group"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Check if any students are assigned to this house
        students_response = supabase.table('students')\
            .select('id', count='exact')\
            .eq('student_house_id', house_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if students_response.count and students_response.count > 0:
            return jsonify({'success': False, 'message': f'Cannot delete house. {students_response.count} student(s) are still assigned to this house.'}), 400
        
        result = supabase.table('student_houses')\
            .delete()\
            .eq('id', house_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if result.data:
            return jsonify({'success': True, 'message': 'House deleted successfully'})
        else:
            return jsonify({'success': False, 'message': 'House not found'}), 404
            
    except Exception as e:
        print(f"Error deleting house: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@houses_bp.route('/api/students', methods=['GET'])
@role_required(['admin', 'teacher', 'owner'])
def get_students():
    """Get students with optional filtering"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        class_id = request.args.get('class_id')
        house_id = request.args.get('house_id')
        
        query = supabase.table('students')\
            .select('id, name, student_id, class_id, classes(name), gender, student_house_id')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')
        
        if class_id:
            query = query.eq('class_id', class_id)
        
        if house_id:
            query = query.eq('student_house_id', house_id)
        
        response = query.order('name').execute()
        
        students = response.data if response.data else []
        
        return jsonify({'success': True, 'students': students})
        
    except Exception as e:
        print(f"Error getting students: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@houses_bp.route('/api/students/assign', methods=['POST'])
@role_required(['admin', 'teacher', 'owner'])
def assign_students():
    """Assign students to a house"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        student_ids = data.get('student_ids', [])
        house_id = data.get('house_id')
        
        if not student_ids:
            return jsonify({'success': False, 'message': 'No students selected'}), 400
        
        if not house_id:
            return jsonify({'success': False, 'message': 'Please select a house'}), 400
        
        assigned_count = 0
        
        for student_id in student_ids:
            result = supabase.table('students')\
                .update({
                    'student_house_id': house_id,
                    'updated_at': datetime.now().isoformat()
                })\
                .eq('id', student_id)\
                .eq('institute_id', institute_id)\
                .execute()
            
            if result.data:
                assigned_count += 1
        
        return jsonify({
            'success': True,
            'message': f'Successfully assigned {assigned_count} student(s) to house'
        })
        
    except Exception as e:
        print(f"Error assigning students: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@houses_bp.route('/api/students/bulk-assign', methods=['POST'])
@role_required(['admin', 'teacher', 'owner'])
def bulk_assign_students():
    """Bulk assign students to houses based on class or all students"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        class_id = data.get('class_id')
        house_id = data.get('house_id')
        
        if not house_id:
            return jsonify({'success': False, 'message': 'Please select a house'}), 400
        
        query = supabase.table('students')\
            .select('id')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')
        
        if class_id:
            query = query.eq('class_id', class_id)
        
        response = query.execute()
        students = response.data if response.data else []
        
        if not students:
            return jsonify({'success': False, 'message': 'No students found'}), 404
        
        assigned_count = 0
        
        for student in students:
            result = supabase.table('students')\
                .update({
                    'student_house_id': house_id,
                    'updated_at': datetime.now().isoformat()
                })\
                .eq('id', student['id'])\
                .eq('institute_id', institute_id)\
                .execute()
            
            if result.data:
                assigned_count += 1
        
        return jsonify({
            'success': True,
            'message': f'Successfully assigned {assigned_count} student(s) to house'
        })
        
    except Exception as e:
        print(f"Error bulk assigning students: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@houses_bp.route('/api/students/unassign', methods=['POST'])
@role_required(['admin', 'teacher', 'owner'])
def unassign_students():
    """Remove students from their house assignment"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        student_ids = data.get('student_ids', [])
        
        if not student_ids:
            return jsonify({'success': False, 'message': 'No students selected'}), 400
        
        unassigned_count = 0
        
        for student_id in student_ids:
            result = supabase.table('students')\
                .update({
                    'student_house_id': None,
                    'updated_at': datetime.now().isoformat()
                })\
                .eq('id', student_id)\
                .eq('institute_id', institute_id)\
                .execute()
            
            if result.data:
                unassigned_count += 1
        
        return jsonify({
            'success': True,
            'message': f'Successfully unassigned {unassigned_count} student(s)'
        })
        
    except Exception as e:
        print(f"Error unassigning students: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@houses_bp.route('/api/stats', methods=['GET'])
@role_required(['admin', 'teacher', 'owner'])
def get_stats():
    """Get house statistics"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Get all houses
        houses_response = supabase.table('student_houses')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .execute()
        
        houses = houses_response.data if houses_response.data else []
        
        # Get student count per house
        for house in houses:
            count_response = supabase.table('students')\
                .select('id', count='exact')\
                .eq('student_house_id', house['id'])\
                .eq('institute_id', institute_id)\
                .eq('status', 'active')\
                .execute()
            
            house['student_count'] = count_response.count or 0
        
        # Get total students
        total_students_response = supabase.table('students')\
            .select('id', count='exact')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')\
            .execute()
        
        total_students = total_students_response.count or 0
        
        # Get assigned students
        assigned_response = supabase.table('students')\
            .select('id', count='exact')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')\
            .not_.is_('student_house_id', 'null')\
            .execute()
        
        assigned_count = assigned_response.count or 0
        
        return jsonify({
            'success': True,
            'stats': {
                'total_houses': len(houses),
                'total_students': total_students,
                'assigned_students': assigned_count,
                'unassigned_students': total_students - assigned_count,
                'houses': houses
            }
        })
        
    except Exception as e:
        print(f"Error getting stats: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@houses_bp.route('/api/export/<house_id>', methods=['GET'])
@role_required(['admin', 'teacher', 'owner'])
def export_house_students(house_id):
    """Export students in a house to Excel"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Get house details
        house_response = supabase.table('student_houses')\
            .select('*')\
            .eq('id', house_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if not house_response.data:
            return jsonify({'success': False, 'message': 'House not found'}), 404
        
        house = house_response.data[0]
        
        # Get students in this house
        students_response = supabase.table('students')\
            .select('*, classes(name)')\
            .eq('student_house_id', house_id)\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')\
            .order('name')\
            .execute()
        
        students = students_response.data if students_response.data else []
        
        # Create DataFrame
        data_rows = []
        for idx, student in enumerate(students, 1):
            data_rows.append({
                'S/N': idx,
                'Student Name': student['name'],
                'Student ID': student['student_id'],
                'Class': student['classes']['name'] if student.get('classes') else 'N/A',
                'Gender': student.get('gender', 'N/A'),
                'Contact': student.get('contact_number', 'N/A'),
                'Email': student.get('email', 'N/A')
            })
        
        df = pd.DataFrame(data_rows)
        
        # Create Excel file
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name=f'{house["name"]} Students', index=False)
            
            # Add summary sheet
            summary_data = {
                'House Name': [house['name']],
                'Motto': [house.get('motto', 'N/A')],
                'Total Students': [len(students)],
                'Report Date': [datetime.now().strftime('%Y-%m-%d')]
            }
            summary_df = pd.DataFrame(summary_data)
            summary_df.to_excel(writer, sheet_name='Summary', index=False)
            
            # Style the worksheet
            workbook = writer.book
            worksheet = writer.sheets[f'{house["name"]} Students']
            
            # Adjust column widths
            for column in worksheet.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = min(max_length + 2, 30)
                worksheet.column_dimensions[column_letter].width = adjusted_width
        
        output.seek(0)
        
        filename = f"{house['name']}_students_{datetime.now().strftime('%Y%m%d')}.xlsx"
        
        return send_file(
            output,
            as_attachment=True,
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        
    except Exception as e:
        print(f"Error exporting students: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@houses_bp.route('/api/export-all', methods=['GET'])
@role_required(['admin', 'teacher', 'owner'])
def export_all_houses():
    """Export all houses and their students to Excel"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Get all houses
        houses_response = supabase.table('student_houses')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('name')\
            .execute()
        
        houses = houses_response.data if houses_response.data else []
        
        # Create Excel file with multiple sheets
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            # Create a master sheet with house summaries
            master_data = []
            for house in houses:
                # Get student count
                count_response = supabase.table('students')\
                    .select('id', count='exact')\
                    .eq('student_house_id', house['id'])\
                    .eq('institute_id', institute_id)\
                    .eq('status', 'active')\
                    .execute()
                
                master_data.append({
                    'House Name': house['name'],
                    'Color': house['color'],
                    'Motto': house.get('motto', 'N/A'),
                    'Student Count': count_response.count or 0,
                    'Created': house['created_at'][:10] if house.get('created_at') else 'N/A'
                })
            
            master_df = pd.DataFrame(master_data)
            master_df.to_excel(writer, sheet_name='All Houses', index=False)
            
            # Create a sheet for each house with students
            for house in houses:
                students_response = supabase.table('students')\
                    .select('*, classes(name)')\
                    .eq('student_house_id', house['id'])\
                    .eq('institute_id', institute_id)\
                    .eq('status', 'active')\
                    .order('name')\
                    .execute()
                
                students = students_response.data if students_response.data else []
                
                if students:
                    student_data = []
                    for idx, student in enumerate(students, 1):
                        student_data.append({
                            'S/N': idx,
                            'Student Name': student['name'],
                            'Student ID': student['student_id'],
                            'Class': student['classes']['name'] if student.get('classes') else 'N/A',
                            'Gender': student.get('gender', 'N/A'),
                            'Contact': student.get('contact_number', 'N/A'),
                            'Email': student.get('email', 'N/A')
                        })
                    
                    student_df = pd.DataFrame(student_data)
                    # Clean sheet name (max 31 chars, no special chars)
                    sheet_name = house['name'][:31].replace('/', '-').replace('\\', '-')
                    student_df.to_excel(writer, sheet_name=sheet_name, index=False)
            
            # Add unassigned students sheet
            unassigned_response = supabase.table('students')\
                .select('*, classes(name)')\
                .is_('student_house_id', 'null')\
                .eq('institute_id', institute_id)\
                .eq('status', 'active')\
                .order('name')\
                .execute()
            
            unassigned = unassigned_response.data if unassigned_response.data else []
            
            if unassigned:
                unassigned_data = []
                for idx, student in enumerate(unassigned, 1):
                    unassigned_data.append({
                        'S/N': idx,
                        'Student Name': student['name'],
                        'Student ID': student['student_id'],
                        'Class': student['classes']['name'] if student.get('classes') else 'N/A',
                        'Gender': student.get('gender', 'N/A'),
                        'Contact': student.get('contact_number', 'N/A'),
                        'Email': student.get('email', 'N/A')
                    })
                
                unassigned_df = pd.DataFrame(unassigned_data)
                unassigned_df.to_excel(writer, sheet_name='Unassigned Students', index=False)
        
        output.seek(0)
        
        filename = f"all_houses_report_{datetime.now().strftime('%Y%m%d')}.xlsx"
        
        return send_file(
            output,
            as_attachment=True,
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        
    except Exception as e:
        print(f"Error exporting all houses: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500