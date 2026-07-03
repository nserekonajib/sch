# CDCReportSettings.py - Competency-Based Report Card Settings Management
from flask import Blueprint, render_template, request, jsonify, session
from supabase import create_client, Client
import os
import json
from datetime import datetime
from functools import wraps
from dotenv import load_dotenv
from routes.permissions.permissions import role_required
from routes.accounts.accounts import get_institute_id as get_institute_id_func

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

settings_bp = Blueprint('cdc_settings', __name__, url_prefix='/cdc-settings')

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Please login'}), 401
        return f(*args, **kwargs)
    return decorated_function

# ============================================================================
# DEFAULT SETTINGS (used when no custom settings exist)
# ============================================================================

DEFAULT_GRADING_SCALE = [
    {'grade': 'A', 'range': '100 - 75', 'min': 75, 'max': 100, 'label': 'Exceptional'},
    {'grade': 'B', 'range': '75 - 60', 'min': 60, 'max': 74, 'label': 'Outstanding'},
    {'grade': 'C', 'range': '60 - 50', 'min': 50, 'max': 59, 'label': 'Satisfactory'},
    {'grade': 'D', 'range': '50 - 35', 'min': 35, 'max': 49, 'label': 'Basic'},
    {'grade': 'E', 'range': '35 - 0', 'min': 0, 'max': 34, 'label': 'Insufficient'}
]

DEFAULT_RESULT_DEFINITIONS = [
    {'id': 'result_1', 'label': 'Result 1', 'text': 'The learner sits for minimum 8 subjects with grade D and above in all subjects'},
    {'id': 'result_2', 'label': 'Result 2', 'text': 'The learner sits for minimum 8 subjects but with grade E in not more than 2 subjects'},
    {'id': 'result_3', 'label': 'Result 3', 'text': 'The learner scores only grade E in the subjects taken'}
]

DEFAULT_KEY_TERMS = [
    {'code': 'A1', 'label': 'Average Chapter Assessment (20% weight)'},
    {'code': '80%', 'label': 'End of Term Assessment (80% weight)'},
    {'code': 'TR', 'label': "Teacher's Initials"}
]

DEFAULT_WEIGHTED_COLUMNS = [
    {'key': '20%', 'label': '20%'},
    {'key': '80%', 'label': '80%'},
    {'key': '100%', 'label': '100%'}
]

DEFAULT_IDENTIFIER_RULES = [
    {'id': 'ident_1', 'label': 'Identifier 1', 'min': 0, 'max': 39, 'description': 'Below Average'},
    {'id': 'ident_2', 'label': 'Identifier 2', 'min': 40, 'max': 69, 'description': 'Average'},
    {'id': 'ident_3', 'label': 'Identifier 3', 'min': 70, 'max': 100, 'description': 'Above Average'}
]

DEFAULT_ACHIEVEMENT_LEVELS = [
    {'min': 80, 'max': 100, 'level': 'Excellent', 'color': '#10b981'},
    {'min': 70, 'max': 79, 'level': 'Very Good', 'color': '#3b82f6'},
    {'min': 60, 'max': 69, 'level': 'Good', 'color': '#f59e0b'},
    {'min': 40, 'max': 59, 'level': 'Average', 'color': '#f97316'},
    {'min': 0, 'max': 39, 'level': 'Needs Improvement', 'color': '#ef4444'}
]

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_default_settings(institute_id):
    """Return default settings structure for an institute"""
    return {
        'institute_id': institute_id,
        'grading_scale': DEFAULT_GRADING_SCALE,
        'result_definitions': DEFAULT_RESULT_DEFINITIONS,
        'key_terms': DEFAULT_KEY_TERMS,
        'weighted_columns': DEFAULT_WEIGHTED_COLUMNS,
        'identifier_rules': DEFAULT_IDENTIFIER_RULES,
        'achievement_levels': DEFAULT_ACHIEVEMENT_LEVELS,
        'report_title': 'COMPETENCY BASED ASSESSMENT REPORT',
        'show_photo': True,
        'show_logo': True,
        'show_aggregates': True,
        'footer_fields': [
            {'label': 'Term Ended On', 'key': 'term_ended_on'},
            {'label': 'Next Term Begins', 'key': 'next_term_begins'},
            {'label': 'Fees Balance', 'key': 'fees_balance'},
            {'label': 'Fees Next Term', 'key': 'fees_next_term'},
            {'label': 'Other Requirement', 'key': 'other_requirement'}
        ],
        'updated_at': datetime.now().isoformat(),
        'updated_by': None
    }

def get_cdc_settings(institute_id):
    """Get CDC settings for an institute, or create default if none exist"""
    try:
        response = supabase.table('cdc_report_settings')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .execute()
        
        if response.data and len(response.data) > 0:
            return response.data[0]
        else:
            # Create default settings
            default_settings = get_default_settings(institute_id)
            insert_response = supabase.table('cdc_report_settings')\
                .insert(default_settings)\
                .execute()
            return insert_response.data[0] if insert_response.data else default_settings
    except Exception as e:
        print(f"Error getting CDC settings: {e}")
        return get_default_settings(institute_id)

def update_cdc_settings(institute_id, settings_data):
    """Update CDC settings for an institute"""
    try:
        # Remove any fields that shouldn't be updated
        if 'id' in settings_data:
            del settings_data['id']
        if 'institute_id' in settings_data:
            del settings_data['institute_id']
        if 'created_at' in settings_data:
            del settings_data['created_at']
        
        settings_data['updated_at'] = datetime.now().isoformat()
        
        # Check if settings exist
        response = supabase.table('cdc_report_settings')\
            .select('id')\
            .eq('institute_id', institute_id)\
            .execute()
        
        if response.data and len(response.data) > 0:
            # Update existing
            update_response = supabase.table('cdc_report_settings')\
                .update(settings_data)\
                .eq('institute_id', institute_id)\
                .execute()
            return update_response.data[0] if update_response.data else None
        else:
            # Insert new
            settings_data['institute_id'] = institute_id
            insert_response = supabase.table('cdc_report_settings')\
                .insert(settings_data)\
                .execute()
            return insert_response.data[0] if insert_response.data else None
    except Exception as e:
        print(f"Error updating CDC settings: {e}")
        return None

# ============================================================================
# ROUTES
# ============================================================================

@settings_bp.route('/')
@role_required(['owner', 'admin'])
def index():
    """Main settings page"""
    user = session.get('user')
    institute_id = get_institute_id_func(user['id'])
    
    if not institute_id:
        return render_template('cdc_settings/index.html', settings=None, institute=None)
    
    try:
        # Get institute details
        institute_response = supabase.table('institutes')\
            .select('*')\
            .eq('id', institute_id)\
            .execute()
        
        institute = institute_response.data[0] if institute_response.data else {}
        
        # Get CDC settings
        settings = get_cdc_settings(institute_id)
        
        return render_template('cdc_settings/index.html', 
                             settings=settings, 
                             institute=institute)
    except Exception as e:
        print(f"Error loading CDC settings: {e}")
        return render_template('cdc_settings/index.html', settings=None, institute=None)

@settings_bp.route('/api/settings', methods=['GET'])
@role_required(['owner', 'admin'])
def api_get_settings():
    """API endpoint to get CDC settings"""
    user = session.get('user')
    institute_id = get_institute_id_func(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    settings = get_cdc_settings(institute_id)
    return jsonify({'success': True, 'settings': settings})

@settings_bp.route('/api/settings', methods=['POST'])
@role_required(['owner', 'admin'])
def api_update_settings():
    """API endpoint to update CDC settings"""
    user = session.get('user')
    institute_id = get_institute_id_func(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        
        # Validate required fields
        if not data:
            return jsonify({'success': False, 'message': 'No data provided'}), 400
        
        # Add updated_by if user is available
        if user and user.get('id'):
            data['updated_by'] = user['id']
        
        # Update settings
        updated_settings = update_cdc_settings(institute_id, data)
        
        if updated_settings:
            return jsonify({
                'success': True, 
                'message': 'Settings updated successfully',
                'settings': updated_settings
            })
        else:
            return jsonify({'success': False, 'message': 'Failed to update settings'}), 500
            
    except Exception as e:
        print(f"Error updating CDC settings: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@settings_bp.route('/api/settings/reset', methods=['POST'])
@role_required(['owner', 'admin'])
def api_reset_settings():
    """Reset CDC settings to defaults"""
    user = session.get('user')
    institute_id = get_institute_id_func(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        default_settings = get_default_settings(institute_id)
        # Remove institute_id from update data
        if 'institute_id' in default_settings:
            del default_settings['institute_id']
        
        # Add updated_by if user is available
        if user and user.get('id'):
            default_settings['updated_by'] = user['id']
        
        updated_settings = update_cdc_settings(institute_id, default_settings)
        
        if updated_settings:
            return jsonify({
                'success': True, 
                'message': 'Settings reset to defaults',
                'settings': updated_settings
            })
        else:
            return jsonify({'success': False, 'message': 'Failed to reset settings'}), 500
            
    except Exception as e:
        print(f"Error resetting CDC settings: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@settings_bp.route('/api/grading-scale', methods=['POST'])
@role_required(['owner', 'admin'])
def api_update_grading_scale():
    """Update only the grading scale"""
    user = session.get('user')
    institute_id = get_institute_id_func(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        grading_scale = data.get('grading_scale', [])
        
        if not grading_scale:
            return jsonify({'success': False, 'message': 'Grading scale cannot be empty'}), 400
        
        # Validate grading scale
        for grade in grading_scale:
            if not all(k in grade for k in ['grade', 'min', 'max']):
                return jsonify({'success': False, 'message': 'Invalid grading scale format'}), 400
        
        # Update only the grading scale
        update_data = {
            'grading_scale': grading_scale,
            'updated_at': datetime.now().isoformat()
        }
        if user and user.get('id'):
            update_data['updated_by'] = user['id']
        
        updated_settings = update_cdc_settings(institute_id, update_data)
        
        if updated_settings:
            return jsonify({
                'success': True, 
                'message': 'Grading scale updated successfully',
                'grading_scale': grading_scale
            })
        else:
            return jsonify({'success': False, 'message': 'Failed to update grading scale'}), 500
            
    except Exception as e:
        print(f"Error updating grading scale: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@settings_bp.route('/api/result-definitions', methods=['POST'])
@role_required(['owner', 'admin'])
def api_update_result_definitions():
    """Update only the result definitions"""
    user = session.get('user')
    institute_id = get_institute_id_func(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        result_definitions = data.get('result_definitions', [])
        
        if not result_definitions:
            return jsonify({'success': False, 'message': 'Result definitions cannot be empty'}), 400
        
        # Validate result definitions
        for rd in result_definitions:
            if not all(k in rd for k in ['id', 'label', 'text']):
                return jsonify({'success': False, 'message': 'Invalid result definition format'}), 400
        
        update_data = {
            'result_definitions': result_definitions,
            'updated_at': datetime.now().isoformat()
        }
        if user and user.get('id'):
            update_data['updated_by'] = user['id']
        
        updated_settings = update_cdc_settings(institute_id, update_data)
        
        if updated_settings:
            return jsonify({
                'success': True, 
                'message': 'Result definitions updated successfully',
                'result_definitions': result_definitions
            })
        else:
            return jsonify({'success': False, 'message': 'Failed to update result definitions'}), 500
            
    except Exception as e:
        print(f"Error updating result definitions: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@settings_bp.route('/api/key-terms', methods=['POST'])
@role_required(['owner', 'admin'])
def api_update_key_terms():
    """Update only the key terms"""
    user = session.get('user')
    institute_id = get_institute_id_func(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        key_terms = data.get('key_terms', [])
        
        if not key_terms:
            return jsonify({'success': False, 'message': 'Key terms cannot be empty'}), 400
        
        # Validate key terms
        for kt in key_terms:
            if not all(k in kt for k in ['code', 'label']):
                return jsonify({'success': False, 'message': 'Invalid key term format'}), 400
        
        update_data = {
            'key_terms': key_terms,
            'updated_at': datetime.now().isoformat()
        }
        if user and user.get('id'):
            update_data['updated_by'] = user['id']
        
        updated_settings = update_cdc_settings(institute_id, update_data)
        
        if updated_settings:
            return jsonify({
                'success': True, 
                'message': 'Key terms updated successfully',
                'key_terms': key_terms
            })
        else:
            return jsonify({'success': False, 'message': 'Failed to update key terms'}), 500
            
    except Exception as e:
        print(f"Error updating key terms: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@settings_bp.route('/api/achievement-levels', methods=['POST'])
@role_required(['owner', 'admin'])
def api_update_achievement_levels():
    """Update only the achievement levels"""
    user = session.get('user')
    institute_id = get_institute_id_func(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        achievement_levels = data.get('achievement_levels', [])
        
        if not achievement_levels:
            return jsonify({'success': False, 'message': 'Achievement levels cannot be empty'}), 400
        
        # Validate achievement levels
        for al in achievement_levels:
            if not all(k in al for k in ['min', 'max', 'level']):
                return jsonify({'success': False, 'message': 'Invalid achievement level format'}), 400
        
        update_data = {
            'achievement_levels': achievement_levels,
            'updated_at': datetime.now().isoformat()
        }
        if user and user.get('id'):
            update_data['updated_by'] = user['id']
        
        updated_settings = update_cdc_settings(institute_id, update_data)
        
        if updated_settings:
            return jsonify({
                'success': True, 
                'message': 'Achievement levels updated successfully',
                'achievement_levels': achievement_levels
            })
        else:
            return jsonify({'success': False, 'message': 'Failed to update achievement levels'}), 500
            
    except Exception as e:
        print(f"Error updating achievement levels: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@settings_bp.route('/api/display-options', methods=['POST'])
@role_required(['owner', 'admin'])
def api_update_display_options():
    """Update display options"""
    user = session.get('user')
    institute_id = get_institute_id_func(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        
        update_data = {
            'show_photo': data.get('show_photo', True),
            'show_logo': data.get('show_logo', True),
            'show_aggregates': data.get('show_aggregates', True),
            'report_title': data.get('report_title', 'COMPETENCY BASED ASSESSMENT REPORT'),
            'footer_fields': data.get('footer_fields', [
                {'label': 'Term Ended On', 'key': 'term_ended_on'},
                {'label': 'Next Term Begins', 'key': 'next_term_begins'},
                {'label': 'Fees Balance', 'key': 'fees_balance'},
                {'label': 'Fees Next Term', 'key': 'fees_next_term'},
                {'label': 'Other Requirement', 'key': 'other_requirement'}
            ]),
            'updated_at': datetime.now().isoformat()
        }
        if user and user.get('id'):
            update_data['updated_by'] = user['id']
        
        updated_settings = update_cdc_settings(institute_id, update_data)
        
        if updated_settings:
            return jsonify({
                'success': True, 
                'message': 'Display options updated successfully',
                'settings': updated_settings
            })
        else:
            return jsonify({'success': False, 'message': 'Failed to update display options'}), 500
            
    except Exception as e:
        print(f"Error updating display options: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

# ============================================================================
# INITIALIZATION FUNCTION (call this once to create the table)
# ============================================================================
