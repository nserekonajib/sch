# routes/report_templates.py
from flask import Blueprint, flash, render_template, request, jsonify, session
from supabase import create_client, Client
import json
from datetime import datetime
from functools import wraps
from routes.auth.auth import role_required
from routes.accounts.accounts import get_institute_id
import os
from dotenv import load_dotenv

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

templates_bp = Blueprint('templates', __name__, url_prefix='/report-templates')

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Please login'}), 401
        return f(*args, **kwargs)
    return decorated_function
@templates_bp.route('/designer')
@role_required(['owner', 'teacher'])
def designer():
    """Report card template designer interface"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    context = {
        'templates': [],
        'institute': None
    }
    
    if not institute_id:
        return render_template('results/template_designer.html', **context)
    
    try:
        # Get existing templates for this institute
        templates_response = supabase.table('report_templates')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('created_at', desc=True)\
            .execute()
        
        context['templates'] = templates_response.data if templates_response.data else []
        
        # Get institute details
        institute_response = supabase.table('institutes')\
            .select('*')\
            .eq('id', institute_id)\
            .execute()
        
        context['institute'] = institute_response.data[0] if institute_response.data else {}
        
        return render_template('results/template_designer.html', **context)
    
    except Exception as e:
        print(f"Error loading template designer: {e}")
        import traceback
        traceback.print_exc()
        flash('An error occurred while loading the template designer. Please try again later.', 'error')
        return render_template('dashboard/index.html')
    

@templates_bp.route('/save', methods=['POST'])
@role_required(['owner', 'teacher'])
def save_template():
    """Save report card template"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        template_id = data.get('template_id')
        template_name = data.get('name')
        template_data = data.get('template_data')
        html_template = data.get('html_template')
        css_style = data.get('css_style', '')
        is_default = data.get('is_default', False)
        
        if not template_name:
            return jsonify({'success': False, 'message': 'Template name is required'}), 400
        
        if not template_data:
            return jsonify({'success': False, 'message': 'Template data is required'}), 400
        
        # If setting as default, remove default flag from other templates
        if is_default:
            supabase.table('report_templates')\
                .update({'is_default': False})\
                .eq('institute_id', institute_id)\
                .execute()
        
        if template_id:
            # Update existing template
            result = supabase.table('report_templates')\
                .update({
                    'name': template_name,
                    'template_data': template_data,
                    'html_template': html_template,
                    'css_style': css_style,
                    'is_default': is_default,
                    'updated_at': datetime.now().isoformat()
                })\
                .eq('id', template_id)\
                .eq('institute_id', institute_id)\
                .execute()
            
            return jsonify({
                'success': True, 
                'message': 'Template updated successfully',
                'template_id': template_id
            })
        else:
            # Create new template
            result = supabase.table('report_templates')\
                .insert({
                    'institute_id': institute_id,
                    'name': template_name,
                    'template_data': template_data,
                    'html_template': html_template,
                    'css_style': css_style,
                    'is_default': is_default,
                    'created_at': datetime.now().isoformat(),
                    'updated_at': datetime.now().isoformat()
                })\
                .execute()
            
            new_template_id = result.data[0]['id'] if result.data else None
            
            return jsonify({
                'success': True, 
                'message': 'Template saved successfully',
                'template_id': new_template_id
            })
        
    except Exception as e:
        print(f"Error saving template: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@templates_bp.route('/list', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def list_templates():
    """Get all templates for institute"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify([]), 200
    
    try:
        templates = supabase.table('report_templates')\
            .select('id, name, is_default, created_at, updated_at')\
            .eq('institute_id', institute_id)\
            .order('is_default', desc=True)\
            .order('created_at', desc=True)\
            .execute()
        
        return jsonify(templates.data if templates.data else [])
        
    except Exception as e:
        print(f"Error listing templates: {e}")
        return jsonify([]), 200

@templates_bp.route('/get/<template_id>', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_template(template_id):
    """Get a specific template by ID"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        template = supabase.table('report_templates')\
            .select('*')\
            .eq('id', template_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if not template.data:
            return jsonify({'success': False, 'message': 'Template not found'}), 404
        
        return jsonify({
            'success': True,
            'template': template.data[0]
        })
        
    except Exception as e:
        print(f"Error loading template: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@templates_bp.route('/delete/<template_id>', methods=['DELETE'])
@role_required(['owner', 'teacher'])
def delete_template(template_id):
    """Delete a template"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Check if template exists
        template = supabase.table('report_templates')\
            .select('id, is_default')\
            .eq('id', template_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if not template.data:
            return jsonify({'success': False, 'message': 'Template not found'}), 404
        
        # Don't allow deleting default template if it's the only one
        if template.data[0]['is_default']:
            other_templates = supabase.table('report_templates')\
                .select('id')\
                .eq('institute_id', institute_id)\
                .neq('id', template_id)\
                .execute()
            
            if not other_templates.data:
                return jsonify({'success': False, 'message': 'Cannot delete the only template. Create another template first.'}), 400
        
        # Delete the template
        supabase.table('report_templates')\
            .delete()\
            .eq('id', template_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        # If deleted template was default, set another as default
        if template.data[0]['is_default']:
            next_template = supabase.table('report_templates')\
                .select('id')\
                .eq('institute_id', institute_id)\
                .limit(1)\
                .execute()
            
            if next_template.data:
                supabase.table('report_templates')\
                    .update({'is_default': True})\
                    .eq('id', next_template.data[0]['id'])\
                    .execute()
        
        return jsonify({'success': True, 'message': 'Template deleted successfully'})
        
    except Exception as e:
        print(f"Error deleting template: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@templates_bp.route('/duplicate/<template_id>', methods=['POST'])
@role_required(['owner', 'teacher'])
def duplicate_template(template_id):
    """Duplicate an existing template"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Get original template
        original = supabase.table('report_templates')\
            .select('*')\
            .eq('id', template_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if not original.data:
            return jsonify({'success': False, 'message': 'Template not found'}), 404
        
        original_template = original.data[0]
        
        # Create duplicate with new name
        new_name = f"{original_template['name']} (Copy)"
        
        # Check if name already exists
        existing = supabase.table('report_templates')\
            .select('id')\
            .eq('institute_id', institute_id)\
            .eq('name', new_name)\
            .execute()
        
        if existing.data:
            new_name = f"{original_template['name']} (Copy {datetime.now().strftime('%Y%m%d_%H%M%S')})"
        
        # Insert duplicate
        result = supabase.table('report_templates')\
            .insert({
                'institute_id': institute_id,
                'name': new_name,
                'template_data': original_template['template_data'],
                'html_template': original_template['html_template'],
                'css_style': original_template.get('css_style', ''),
                'is_default': False,
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            })\
            .execute()
        
        return jsonify({
            'success': True, 
            'message': 'Template duplicated successfully',
            'template_id': result.data[0]['id'] if result.data else None
        })
        
    except Exception as e:
        print(f"Error duplicating template: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@templates_bp.route('/set-default/<template_id>', methods=['POST'])
@role_required(['owner', 'teacher'])
def set_default_template(template_id):
    """Set a template as default"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Remove default flag from all templates
        supabase.table('report_templates')\
            .update({'is_default': False})\
            .eq('institute_id', institute_id)\
            .execute()
        
        # Set selected template as default
        result = supabase.table('report_templates')\
            .update({'is_default': True})\
            .eq('id', template_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if not result.data:
            return jsonify({'success': False, 'message': 'Template not found'}), 404
        
        return jsonify({'success': True, 'message': 'Default template updated successfully'})
        
    except Exception as e:
        print(f"Error setting default template: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@templates_bp.route('/export/<template_id>', methods=['GET'])
@role_required(['owner', 'teacher'])
def export_template(template_id):
    """Export template as JSON file"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        template = supabase.table('report_templates')\
            .select('*')\
            .eq('id', template_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if not template.data:
            return jsonify({'success': False, 'message': 'Template not found'}), 404
        
        # Prepare export data
        export_data = {
            'name': template.data[0]['name'],
            'template_data': template.data[0]['template_data'],
            'html_template': template.data[0]['html_template'],
            'css_style': template.data[0].get('css_style', ''),
            'version': '1.0',
            'exported_at': datetime.now().isoformat()
        }
        
        # Return as JSON file
        from flask import make_response
        response = make_response(json.dumps(export_data, indent=2))
        response.headers['Content-Type'] = 'application/json'
        response.headers['Content-Disposition'] = f'attachment; filename=template_{template.data[0]["name"]}.json'
        return response
        
    except Exception as e:
        print(f"Error exporting template: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@templates_bp.route('/import', methods=['POST'])
@role_required(['owner', 'teacher'])
def import_template():
    """Import template from JSON file"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'message': 'No file provided'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'message': 'No file selected'}), 400
        
        if not file.filename.endswith('.json'):
            return jsonify({'success': False, 'message': 'Only JSON files are allowed'}), 400
        
        # Parse JSON file
        file_content = file.read().decode('utf-8')
        import_data = json.loads(file_content)
        
        # Validate required fields
        required_fields = ['name', 'template_data']
        for field in required_fields:
            if field not in import_data:
                return jsonify({'success': False, 'message': f'Missing required field: {field}'}), 400
        
        # Check if template with same name exists
        existing = supabase.table('report_templates')\
            .select('id')\
            .eq('institute_id', institute_id)\
            .eq('name', import_data['name'])\
            .execute()
        
        template_name = import_data['name']
        if existing.data:
            template_name = f"{import_data['name']} (Imported {datetime.now().strftime('%Y%m%d')})"
        
        # Insert imported template
        result = supabase.table('report_templates')\
            .insert({
                'institute_id': institute_id,
                'name': template_name,
                'template_data': import_data['template_data'],
                'html_template': import_data.get('html_template', ''),
                'css_style': import_data.get('css_style', ''),
                'is_default': False,
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            })\
            .execute()
        
        return jsonify({
            'success': True, 
            'message': 'Template imported successfully',
            'template_id': result.data[0]['id'] if result.data else None
        })
        
    except json.JSONDecodeError:
        return jsonify({'success': False, 'message': 'Invalid JSON file'}), 400
    except Exception as e:
        print(f"Error importing template: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@templates_bp.route('/render/<template_id>', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def render_template_to_pdf(template_id):
    """Render a template with data and return PDF"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        student_data = data.get('student_data', {})
        
        # Get template
        template = supabase.table('report_templates')\
            .select('*')\
            .eq('id', template_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if not template.data:
            return jsonify({'success': False, 'message': 'Template not found'}), 404
        
        template_data = template.data[0]
        
        # Render HTML template with data
        from jinja2 import Template
        html_template = Template(template_data['html_template'])
        rendered_html = html_template.render(**student_data)
        
        # Add custom CSS
        if template_data.get('css_style'):
            rendered_html = rendered_html.replace('</head>', f'<style>{template_data["css_style"]}</style></head>')
        
        # Convert to PDF
        from xhtml2pdf import pisa
        import io
        
        pdf_buffer = io.BytesIO()
        pisa_status = pisa.CreatePDF(io.StringIO(rendered_html), dest=pdf_buffer)
        
        if pisa_status.err:
            return jsonify({'success': False, 'message': 'PDF generation failed'}), 500
        
        pdf_buffer.seek(0)
        
        # Return PDF
        from flask import send_file
        return send_file(
            pdf_buffer,
            as_attachment=True,
            download_name=f"report_card_{template_data['name']}.pdf",
            mimetype='application/pdf'
        )
        
    except Exception as e:
        print(f"Error rendering template: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500