# createFeeNames.py - Fee Names Management Blueprint
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

fee_names_bp = Blueprint('fee_names', __name__, url_prefix='/fee-names')

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

@fee_names_bp.route('/')
@login_required
def index():
    """Fee Names Management Page"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return render_template('fee_names/index.html', fee_names=[], institute_id=None)
    
    try:
        # Get all fee names
        response = supabase.table('fee_names')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('created_at', desc=True)\
            .execute()
        
        fee_names = response.data if response.data else []
        
        return render_template('fee_names/index.html', fee_names=fee_names, institute_id=institute_id)
        
    except Exception as e:
        print(f"Error loading fee names: {e}")
        return render_template('fee_names/index.html', fee_names=[], institute_id=institute_id)

@fee_names_bp.route('/api/fee-names', methods=['GET'])
@login_required
def get_fee_names():
    """Get all fee names"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        response = supabase.table('fee_names')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('created_at', desc=True)\
            .execute()
        
        fee_names = response.data if response.data else []
        
        return jsonify({'success': True, 'fee_names': fee_names})
        
    except Exception as e:
        print(f"Error getting fee names: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@fee_names_bp.route('/api/fee-names', methods=['POST'])
@login_required
def create_fee_name():
    """Create a new fee name preset"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        
        fee_name = data.get('fee_name', '').strip()
        standard_amount = float(data.get('standard_amount', 0))
        is_optional = data.get('is_optional', False)
        description = data.get('description', '')
        
        if not fee_name:
            return jsonify({'success': False, 'message': 'Fee name is required'}), 400
        
        if standard_amount <= 0:
            return jsonify({'success': False, 'message': 'Standard amount must be greater than 0'}), 400
        
        # Check if fee name already exists for this institute
        existing = supabase.table('fee_names')\
            .select('id')\
            .eq('institute_id', institute_id)\
            .eq('fee_name', fee_name)\
            .execute()
        
        if existing.data:
            return jsonify({'success': False, 'message': 'Fee name already exists'}), 400
        
        fee_name_id = str(uuid.uuid4())
        fee_name_data = {
            'id': fee_name_id,
            'institute_id': institute_id,
            'fee_name': fee_name,
            'standard_amount': standard_amount,
            'is_optional': is_optional,
            'description': description,
            'is_active': True,
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        result = supabase.table('fee_names').insert(fee_name_data).execute()
        
        if result.data:
            return jsonify({
                'success': True,
                'message': 'Fee name created successfully',
                'fee_name': result.data[0]
            })
        else:
            return jsonify({'success': False, 'message': 'Failed to create fee name'}), 500
            
    except Exception as e:
        print(f"Error creating fee name: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@fee_names_bp.route('/api/fee-names/<fee_name_id>', methods=['PUT'])
@login_required
def update_fee_name(fee_name_id):
    """Update a fee name preset"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        
        update_data = {
            'fee_name': data.get('fee_name', '').strip(),
            'standard_amount': float(data.get('standard_amount', 0)),
            'is_optional': data.get('is_optional', False),
            'description': data.get('description', ''),
            'updated_at': datetime.now().isoformat()
        }
        
        if not update_data['fee_name']:
            return jsonify({'success': False, 'message': 'Fee name is required'}), 400
        
        if update_data['standard_amount'] <= 0:
            return jsonify({'success': False, 'message': 'Standard amount must be greater than 0'}), 400
        
        result = supabase.table('fee_names')\
            .update(update_data)\
            .eq('id', fee_name_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if result.data:
            return jsonify({
                'success': True,
                'message': 'Fee name updated successfully',
                'fee_name': result.data[0]
            })
        else:
            return jsonify({'success': False, 'message': 'Fee name not found'}), 404
            
    except Exception as e:
        print(f"Error updating fee name: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@fee_names_bp.route('/api/fee-names/<fee_name_id>', methods=['DELETE'])
@login_required
def delete_fee_name(fee_name_id):
    """Delete a fee name preset"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Check if this fee name is being used in any fee particulars
        used_response = supabase.table('fee_particulars')\
            .select('id', count='exact')\
            .eq('institute_id', institute_id)\
            .contains('fee_items', [{'fee_name_id': fee_name_id}])\
            .execute()
        
        if used_response.count > 0:
            return jsonify({'success': False, 'message': f'Cannot delete. This fee name is used in {used_response.count} fee structure(s).'}), 400
        
        result = supabase.table('fee_names')\
            .delete()\
            .eq('id', fee_name_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if result.data:
            return jsonify({'success': True, 'message': 'Fee name deleted successfully'})
        else:
            return jsonify({'success': False, 'message': 'Fee name not found'}), 404
            
    except Exception as e:
        print(f"Error deleting fee name: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@fee_names_bp.route('/api/fee-names/toggle-status/<fee_name_id>', methods=['PUT'])
@login_required
def toggle_status(fee_name_id):
    """Toggle fee name active/inactive status"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        is_active = data.get('is_active', False)
        
        result = supabase.table('fee_names')\
            .update({
                'is_active': is_active,
                'updated_at': datetime.now().isoformat()
            })\
            .eq('id', fee_name_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if result.data:
            status = 'activated' if is_active else 'deactivated'
            return jsonify({'success': True, 'message': f'Fee name {status} successfully'})
        else:
            return jsonify({'success': False, 'message': 'Fee name not found'}), 404
            
    except Exception as e:
        print(f"Error toggling status: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@fee_names_bp.route('/api/bulk-create', methods=['POST'])
@login_required
def bulk_create_fee_names():
    """Create multiple fee names at once"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        fee_items = data.get('fee_items', [])
        
        if not fee_items:
            return jsonify({'success': False, 'message': 'No fee items provided'}), 400
        
        created_count = 0
        errors = []
        
        for item in fee_items:
            fee_name = item.get('fee_name', '').strip()
            standard_amount = float(item.get('standard_amount', 0))
            is_optional = item.get('is_optional', False)
            description = item.get('description', '')
            
            if not fee_name or standard_amount <= 0:
                errors.append(f"Skipped invalid item: {fee_name or 'Unknown'}")
                continue
            
            # Check if fee name already exists
            existing = supabase.table('fee_names')\
                .select('id')\
                .eq('institute_id', institute_id)\
                .eq('fee_name', fee_name)\
                .execute()
            
            if existing.data:
                errors.append(f"Fee name '{fee_name}' already exists")
                continue
            
            fee_name_id = str(uuid.uuid4())
            fee_name_data = {
                'id': fee_name_id,
                'institute_id': institute_id,
                'fee_name': fee_name,
                'standard_amount': standard_amount,
                'is_optional': is_optional,
                'description': description,
                'is_active': True,
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }
            
            result = supabase.table('fee_names').insert(fee_name_data).execute()
            
            if result.data:
                created_count += 1
            else:
                errors.append(f"Failed to create '{fee_name}'")
        
        return jsonify({
            'success': True,
            'message': f'Successfully created {created_count} fee name(s)',
            'created_count': created_count,
            'errors': errors if errors else None
        })
        
    except Exception as e:
        print(f"Error bulk creating fee names: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500