# requirements.py - Non-Cash Requirements Management Blueprint
from flask import Blueprint, render_template, request, jsonify, session
from supabase import create_client, Client
import os
import uuid
from datetime import datetime
from functools import wraps
from dotenv import load_dotenv

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

requirements_bp = Blueprint('requirements', __name__, url_prefix='/requirements')

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Please login'}), 401
        return f(*args, **kwargs)
    return decorated_function

def get_institute_id(user_id):
    try:
        response = supabase.table('institutes')\
            .select('id')\
            .eq('user_id', user_id)\
            .execute()
        
        if response.data and len(response.data) > 0:
            return response.data[0]['id']
        return None
    except Exception as e:
        print(f"Error getting institute: {e}")
        return None

# ==================== ITEM MANAGEMENT ====================

@requirements_bp.route('/items')
@login_required
def items_page():
    """Items management page"""
    return render_template('requirements/items.html')

@requirements_bp.route('/index')
@login_required
def index():
    """Items management page"""
    return render_template('requirements/index.html')

@requirements_bp.route('/api/items', methods=['GET'])
@login_required
def get_items():
    institute_id = get_institute_id(session['user']['id'])
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        response = supabase.table('requirement_items')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('name')\
            .execute()
        
        return jsonify({'success': True, 'items': response.data})
    except Exception as e:
        print(e)
        return jsonify({'success': False, 'message': str(e)}), 500

@requirements_bp.route('/api/items', methods=['POST'])
@login_required
def create_item():
    institute_id = get_institute_id(session['user']['id'])
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        item_id = str(uuid.uuid4())
        item_data = {
            'id': item_id,
            'institute_id': institute_id,
            'name': data['name'].strip(),
            'unit': data['unit'].strip(),
            'is_active': data.get('is_active', True),
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        result = supabase.table('requirement_items').insert(item_data).execute()
        return jsonify({'success': True, 'item': result.data[0]})
    except Exception as e:
        print(e)
        return jsonify({'success': False, 'message': str(e)}), 500

@requirements_bp.route('/api/items/<item_id>', methods=['PUT'])
@login_required
def update_item(item_id):
    institute_id = get_institute_id(session['user']['id'])
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        update_data = {
            'name': data['name'].strip(),
            'unit': data['unit'].strip(),
            'is_active': data.get('is_active', True),
            'updated_at': datetime.now().isoformat()
        }
        
        result = supabase.table('requirement_items')\
            .update(update_data)\
            .eq('id', item_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        return jsonify({'success': True, 'item': result.data[0]})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# ==================== CLASS ASSIGNMENT ====================

@requirements_bp.route('/assignments')
@login_required
def assignments_page():
    return render_template('requirements/assignments.html')

@requirements_bp.route('/api/classes', methods=['GET'])
@login_required
def get_classes():
    institute_id = get_institute_id(session['user']['id'])
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        response = supabase.table('classes')\
            .select('id, name')\
            .eq('institute_id', institute_id)\
            .order('name')\
            .execute()
        
        return jsonify({'success': True, 'classes': response.data})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@requirements_bp.route('/api/terms', methods=['GET'])
@login_required
def get_terms():
    institute_id = get_institute_id(session['user']['id'])
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        response = supabase.table('academic_terms')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('start_date', desc=True)\
            .execute()
        
        return jsonify({'success': True, 'terms': response.data})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@requirements_bp.route('/api/assignments', methods=['GET'])
@login_required
def get_assignments():
    institute_id = get_institute_id(session['user']['id'])
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        response = supabase.table('class_requirements')\
            .select('*, requirement_items(name, unit)')\
            .eq('institute_id', institute_id)\
            .execute()
        
        return jsonify({'success': True, 'assignments': response.data})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@requirements_bp.route('/api/assignments', methods=['POST'])
@login_required
def create_assignment():
    institute_id = get_institute_id(session['user']['id'])
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        assignment_id = str(uuid.uuid4())
        assignment_data = {
            'id': assignment_id,
            'institute_id': institute_id,
            'item_id': data['item_id'],
            'class_id': data.get('class_id'),
            'apply_to_all': data.get('apply_to_all', False),
            'quantity_required': float(data['quantity_required']),
            'term_id': data.get('term_id'),
            'academic_year': data.get('academic_year'),
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        result = supabase.table('class_requirements').insert(assignment_data).execute()
        return jsonify({'success': True, 'assignment': result.data[0]})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@requirements_bp.route('/api/assignments/<assignment_id>', methods=['DELETE'])
@login_required
def delete_assignment(assignment_id):
    institute_id = get_institute_id(session['user']['id'])
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        supabase.table('class_requirements')\
            .delete()\
            .eq('id', assignment_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        return jsonify({'success': True, 'message': 'Assignment deleted'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# ==================== STUDENT SUBMISSION ====================

@requirements_bp.route('/submissions')
@login_required
def submissions_page():
    return render_template('requirements/submissions.html')

@requirements_bp.route('/api/students/search', methods=['GET'])
@login_required
def search_students():
    institute_id = get_institute_id(session['user']['id'])
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        search = request.args.get('q', '')
        query = supabase.table('students')\
            .select('id, name, student_id, class_id, classes(name)')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')
        
        if search:
            query = query.or_(f"name.ilike.%{search}%,student_id.ilike.%{search}%")
        
        response = query.limit(50).execute()
        return jsonify({'success': True, 'students': response.data})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@requirements_bp.route('/api/student-requirements/<student_id>', methods=['GET'])
@login_required
def get_student_requirements(student_id):
    institute_id = get_institute_id(session['user']['id'])
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        term_id = request.args.get('term_id')
        
        # Get class requirements for the student
        requirements_query = """
            SELECT 
                ri.id as item_id,
                ri.name as item_name,
                ri.unit,
                cr.quantity_required,
                cr.apply_to_all,
                COALESCE(SUM(sr.quantity_brought), 0) as total_brought
            FROM requirement_items ri
            LEFT JOIN class_requirements cr ON cr.item_id = ri.id 
                AND cr.institute_id = ri.institute_id
                AND (cr.class_id = (SELECT class_id FROM students WHERE id = '{student_id}') OR cr.apply_to_all = true)
                AND (cr.term_id = '{term_id}' OR cr.term_id IS NULL)
            LEFT JOIN student_requirements sr ON sr.item_id = ri.id 
                AND sr.student_id = '{student_id}'
                AND sr.institute_id = ri.institute_id
            WHERE ri.institute_id = '{institute_id}'
                AND ri.is_active = true
                AND cr.id IS NOT NULL
            GROUP BY ri.id, ri.name, ri.unit, cr.quantity_required, cr.apply_to_all
        """.format(student_id=student_id, term_id=term_id, institute_id=institute_id)
        
        # Execute raw query for complex calculation
        # For simplicity, we'll do it in Python
        items_response = supabase.table('requirement_items')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .eq('is_active', True)\
            .execute()
        
        # Get student's class
        student_response = supabase.table('students')\
            .select('class_id')\
            .eq('id', student_id)\
            .execute()
        
        student_class_id = student_response.data[0]['class_id'] if student_response.data else None
        
        # Get assignments
        assignments_response = supabase.table('class_requirements')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .execute()
        
        # Get submissions
        submissions_response = supabase.table('student_requirements')\
            .select('item_id, quantity_brought')\
            .eq('student_id', student_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        # Calculate totals
        submission_totals = {}
        for sub in submissions_response.data if submissions_response.data else []:
            submission_totals[sub['item_id']] = submission_totals.get(sub['item_id'], 0) + sub['quantity_brought']
        
        requirements = []
        for item in items_response.data:
            # Find assignment for this item
            required_qty = 0
            for assignment in assignments_response.data or []:
                if assignment['item_id'] == item['id']:
                    if assignment.get('apply_to_all') or assignment.get('class_id') == student_class_id:
                        required_qty = assignment['quantity_required']
                        break
            
            if required_qty > 0:
                total_brought = submission_totals.get(item['id'], 0)
                status = 'pending' if total_brought == 0 else ('completed' if total_brought >= required_qty else 'partial')
                
                requirements.append({
                    'item_id': item['id'],
                    'item_name': item['name'],
                    'unit': item['unit'],
                    'required_quantity': required_qty,
                    'total_brought': total_brought,
                    'status': status,
                    'remaining': max(0, required_qty - total_brought)
                })
        
        return jsonify({'success': True, 'requirements': requirements})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@requirements_bp.route('/api/submissions', methods=['POST'])
@login_required
def create_submission():
    institute_id = get_institute_id(session['user']['id'])
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        submission_id = str(uuid.uuid4())
        submission_data = {
            'id': submission_id,
            'institute_id': institute_id,
            'student_id': data['student_id'],
            'item_id': data['item_id'],
            'quantity_brought': float(data['quantity_brought']),
            'date_submitted': data.get('date_submitted', datetime.now().date().isoformat()),
            'received_by': session['user']['id'],
            'notes': data.get('notes', ''),
            'created_at': datetime.now().isoformat()
        }
        
        result = supabase.table('student_requirements').insert(submission_data).execute()
        
        # Also add to inventory
        inventory_id = str(uuid.uuid4())
        inventory_data = {
            'id': inventory_id,
            'institute_id': institute_id,
            'item_id': data['item_id'],
            'quantity': float(data['quantity_brought']),
            'transaction_type': 'in',
            'source': 'student_submission',
            'reference_id': submission_id,
            'created_at': datetime.now().isoformat()
        }
        supabase.table('inventory_transactions').insert(inventory_data).execute()
        
        return jsonify({'success': True, 'submission': result.data[0]})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# ==================== INVENTORY MANAGEMENT ====================

@requirements_bp.route('/inventory')
@login_required
def inventory_page():
    return render_template('requirements/inventory.html')

@requirements_bp.route('/api/inventory', methods=['GET'])
@login_required
def get_inventory():
    institute_id = get_institute_id(session['user']['id'])
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Calculate current inventory balance
        query = """
            SELECT 
                ri.id,
                ri.name,
                ri.unit,
                COALESCE(SUM(CASE WHEN it.transaction_type = 'in' THEN it.quantity ELSE 0 END), 0) as total_received,
                COALESCE(SUM(CASE WHEN it.transaction_type = 'out' THEN it.quantity ELSE 0 END), 0) as total_used,
                COALESCE(SUM(CASE WHEN it.transaction_type = 'in' THEN it.quantity ELSE -it.quantity END), 0) as current_balance
            FROM requirement_items ri
            LEFT JOIN inventory_transactions it ON it.item_id = ri.id AND it.institute_id = ri.institute_id
            WHERE ri.institute_id = '{institute_id}'
            GROUP BY ri.id, ri.name, ri.unit
            HAVING COALESCE(SUM(CASE WHEN it.transaction_type = 'in' THEN it.quantity ELSE 0 END), 0) > 0
            ORDER BY ri.name
        """.format(institute_id=institute_id)
        
        # For simplicity, we'll calculate in Python
        items_response = supabase.table('requirement_items')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .execute()
        
        transactions_response = supabase.table('inventory_transactions')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .execute()
        
        inventory = []
        for item in items_response.data:
            total_in = sum(t['quantity'] for t in transactions_response.data if t['item_id'] == item['id'] and t['transaction_type'] == 'in')
            total_out = sum(t['quantity'] for t in transactions_response.data if t['item_id'] == item['id'] and t['transaction_type'] == 'out')
            balance = total_in - total_out
            
            if total_in > 0:
                inventory.append({
                    'id': item['id'],
                    'name': item['name'],
                    'unit': item['unit'],
                    'total_received': total_in,
                    'total_used': total_out,
                    'current_balance': balance
                })
        
        return jsonify({'success': True, 'inventory': inventory})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@requirements_bp.route('/api/inventory/use', methods=['POST'])
@login_required
def use_inventory():
    institute_id = get_institute_id(session['user']['id'])
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        item_id = data['item_id']
        quantity = float(data['quantity'])
        
        # Check current balance
        transactions_response = supabase.table('inventory_transactions')\
            .select('*')\
            .eq('item_id', item_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        total_in = sum(t['quantity'] for t in transactions_response.data if t['transaction_type'] == 'in')
        total_out = sum(t['quantity'] for t in transactions_response.data if t['transaction_type'] == 'out')
        current_balance = total_in - total_out
        
        if quantity > current_balance:
            return jsonify({'success': False, 'message': f'Insufficient stock. Available: {current_balance}'}), 400
        
        transaction_id = str(uuid.uuid4())
        transaction_data = {
            'id': transaction_id,
            'institute_id': institute_id,
            'item_id': item_id,
            'quantity': quantity,
            'transaction_type': 'out',
            'source': 'inventory_use',
            'reference_id': data.get('reference_id'),
            'notes': data.get('purpose', ''),
            'used_by': session['user']['id'],
            'created_at': datetime.now().isoformat()
        }
        
        result = supabase.table('inventory_transactions').insert(transaction_data).execute()
        return jsonify({'success': True, 'transaction': result.data[0]})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# ==================== REPORTS ====================

@requirements_bp.route('/reports')
@login_required
def reports_page():
    return render_template('requirements/reports.html')



# Update student compliance report to use date range
@requirements_bp.route('/api/reports/student-compliance', methods=['GET'])
@login_required
def student_compliance_report():
    institute_id = get_institute_id(session['user']['id'])
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        class_id = request.args.get('class_id')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        # Get students
        students_query = supabase.table('students')\
            .select('id, name, student_id, class_id')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')
        
        if class_id:
            students_query = students_query.eq('class_id', class_id)
        
        students = students_query.execute().data or []
        
        # Get items and assignments
        items = supabase.table('requirement_items')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .eq('is_active', True)\
            .execute().data or []
        
        assignments = supabase.table('class_requirements')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .execute().data or []
        
        # Get submissions within date range
        submissions_query = supabase.table('student_requirements')\
            .select('*')\
            .eq('institute_id', institute_id)
        
        if start_date:
            submissions_query = submissions_query.gte('date_submitted', start_date)
        if end_date:
            submissions_query = submissions_query.lte('date_submitted', end_date)
        
        submissions = submissions_query.execute().data or []
        
        # Build submission map
        submission_map = {}
        for sub in submissions:
            key = f"{sub['student_id']}_{sub['item_id']}"
            submission_map[key] = submission_map.get(key, 0) + sub['quantity_brought']
        
        report_data = []
        for student in students:
            student_data = {
                'student_id': student['student_id'],
                'name': student['name'],
                'items': []
            }
            
            for item in items:
                required_qty = 0
                for assignment in assignments:
                    if assignment['item_id'] == item['id']:
                        if assignment.get('apply_to_all') or assignment.get('class_id') == student['class_id']:
                            required_qty = assignment['quantity_required']
                            break
                
                if required_qty > 0:
                    total_brought = submission_map.get(f"{student['id']}_{item['id']}", 0)
                    status = 'pending' if total_brought == 0 else ('completed' if total_brought >= required_qty else 'partial')
                    
                    student_data['items'].append({
                        'item_name': item['name'],
                        'required': required_qty,
                        'brought': total_brought,
                        'status': status,
                        'unit': item['unit']
                    })
            
            if student_data['items']:
                report_data.append(student_data)
        
        return jsonify({'success': True, 'report': report_data})
    except Exception as e:
        print(f"Error generating student compliance report: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@requirements_bp.route('/api/reports/missing-requirements', methods=['GET'])
@login_required
def missing_requirements_report():
    institute_id = get_institute_id(session['user']['id'])
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        item_id = request.args.get('item_id')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        # Get all students
        students = supabase.table('students')\
            .select('id, name, student_id, class_id, classes(name)')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')\
            .execute().data or []
        
        # Get required quantities
        assignments = supabase.table('class_requirements')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .execute().data or []
        
        if item_id:
            assignments = [a for a in assignments if a['item_id'] == item_id]
        
        # Get submissions within date range
        submissions_query = supabase.table('student_requirements')\
            .select('*')\
            .eq('institute_id', institute_id)
        
        if start_date:
            submissions_query = submissions_query.gte('date_submitted', start_date)
        if end_date:
            submissions_query = submissions_query.lte('date_submitted', end_date)
        
        submissions = submissions_query.execute().data or []
        
        submission_map = {}
        for sub in submissions:
            key = f"{sub['student_id']}_{sub['item_id']}"
            submission_map[key] = submission_map.get(key, 0) + sub['quantity_brought']
        
        missing_students = []
        for student in students:
            for assignment in assignments:
                if assignment.get('apply_to_all') or assignment.get('class_id') == student['class_id']:
                    total_brought = submission_map.get(f"{student['id']}_{assignment['item_id']}", 0)
                    if total_brought < assignment['quantity_required']:
                        missing_students.append({
                            'student_name': student['name'],
                            'student_id': student['student_id'],
                            'class': student['classes']['name'] if student.get('classes') else 'N/A',
                            'item_id': assignment['item_id'],
                            'required': assignment['quantity_required'],
                            'brought': total_brought,
                            'shortage': assignment['quantity_required'] - total_brought
                        })
        
        return jsonify({'success': True, 'missing': missing_students})
    except Exception as e:
        print(f"Error generating missing requirements report: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@requirements_bp.route('/api/submissions/count', methods=['GET'])
@login_required
def get_submissions_count():
    institute_id = get_institute_id(session['user']['id'])
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        response = supabase.table('student_requirements')\
            .select('id', count='exact')\
            .eq('institute_id', institute_id)\
            .execute()
        
        return jsonify({'success': True, 'count': response.count or 0})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@requirements_bp.route('/api/submissions/recent', methods=['GET'])
@login_required
def get_recent_submissions():
    institute_id = get_institute_id(session['user']['id'])
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        response = supabase.table('student_requirements')\
            .select('*, students(name), requirement_items(name, unit)')\
            .eq('institute_id', institute_id)\
            .order('created_at', desc=True)\
            .limit(10)\
            .execute()
        
        submissions = []
        for sub in response.data if response.data else []:
            submissions.append({
                'student_name': sub.get('students', {}).get('name', 'N/A'),
                'item_name': sub.get('requirement_items', {}).get('name', 'N/A'),
                'quantity_brought': sub['quantity_brought'],
                'unit': sub.get('requirement_items', {}).get('unit', ''),
                'date_submitted': sub['date_submitted']
            })
        
        return jsonify({'success': True, 'submissions': submissions})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@requirements_bp.route('/api/reports/pending-count', methods=['GET'])
@login_required
def get_pending_compliance_count():
    institute_id = get_institute_id(session['user']['id'])
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Get all active students
        students = supabase.table('students')\
            .select('id')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')\
            .execute()
        
        # Get all assignments
        assignments = supabase.table('class_requirements')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .execute()
        
        # Get all submissions
        submissions = supabase.table('student_requirements')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .execute()
        
        # Build submission totals
        sub_totals = {}
        for sub in submissions.data or []:
            key = f"{sub['student_id']}_{sub['item_id']}"
            sub_totals[key] = sub_totals.get(key, 0) + sub['quantity_brought']
        
        # Calculate pending count
        pending_count = 0
        for student in students.data or []:
            for assignment in assignments.data or []:
                if assignment.get('apply_to_all') or assignment.get('class_id') == student.get('class_id'):
                    key = f"{student['id']}_{assignment['item_id']}"
                    total_brought = sub_totals.get(key, 0)
                    if total_brought < assignment['quantity_required']:
                        pending_count += 1
        
        return jsonify({'success': True, 'count': pending_count})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    
    

# Make sure your DELETE endpoint in requirements.py looks like this:

@requirements_bp.route('/api/items/<item_id>', methods=['DELETE'])
@login_required
def delete_item(item_id):
    """Delete a requirement item"""
    institute_id = get_institute_id(session['user']['id'])
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    # Validate UUID format
    try:
        uuid.UUID(item_id)
    except ValueError:
        return jsonify({'success': False, 'message': 'Invalid item ID format'}), 400
    
    try:
        # Check if item is used in any assignments
        assignments = supabase.table('class_requirements')\
            .select('id')\
            .eq('item_id', item_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if assignments.data and len(assignments.data) > 0:
            return jsonify({'success': False, 'message': f'Cannot delete item that is assigned to {len(assignments.data)} class(es). Please remove all assignments first.'}), 400
        
        # Check if item has any submissions
        submissions = supabase.table('student_requirements')\
            .select('id')\
            .eq('item_id', item_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if submissions.data and len(submissions.data) > 0:
            return jsonify({'success': False, 'message': f'Cannot delete item that has {len(submissions.data)} student submission(s).'}), 400
        
        # Delete the item
        result = supabase.table('requirement_items')\
            .delete()\
            .eq('id', item_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if result.data:
            return jsonify({'success': True, 'message': 'Item deleted successfully'})
        else:
            return jsonify({'success': False, 'message': 'Item not found'}), 404
            
    except Exception as e:
        print(f"Error deleting item: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
    
    
# Add to requirements.py

@requirements_bp.route('/api/items/<item_id>/dependencies', methods=['GET'])
@login_required
def check_item_dependencies(item_id):
    """Check if item has any dependencies"""
    institute_id = get_institute_id(session['user']['id'])
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Check assignments
        assignments = supabase.table('class_requirements')\
            .select('id', count='exact')\
            .eq('item_id', item_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        # Check submissions
        submissions = supabase.table('student_requirements')\
            .select('id', count='exact')\
            .eq('item_id', item_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        return jsonify({
            'success': True,
            'has_assignments': (assignments.count or 0) > 0,
            'has_submissions': (submissions.count or 0) > 0,
            'assignment_count': assignments.count or 0,
            'submission_count': submissions.count or 0
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
    
    
# Add to requirements.py - Class Compliance Report API

@requirements_bp.route('/api/reports/class-compliance', methods=['GET'])
@login_required
def class_compliance_report():
    """Get class compliance report with date range"""
    institute_id = get_institute_id(session['user']['id'])
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        class_id = request.args.get('class_id')
        
        # Get classes
        classes_query = supabase.table('classes')\
            .select('id, name')\
            .eq('institute_id', institute_id)
        
        if class_id:
            classes_query = classes_query.eq('id', class_id)
        
        classes = classes_query.execute().data or []
        
        # Get all assignments
        assignments = supabase.table('class_requirements')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .execute().data or []
        
        # Get all students
        students_query = supabase.table('students')\
            .select('id, class_id')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')
        
        students = students_query.execute().data or []
        
        # Build student count by class
        student_count = {}
        for student in students:
            student_count[student['class_id']] = student_count.get(student['class_id'], 0) + 1
        
        # Get submissions within date range
        submissions_query = supabase.table('student_requirements')\
            .select('*')\
            .eq('institute_id', institute_id)
        
        if start_date:
            submissions_query = submissions_query.gte('date_submitted', start_date)
        if end_date:
            submissions_query = submissions_query.lte('date_submitted', end_date)
        
        submissions = submissions_query.execute().data or []
        
        # Build submission totals by student
        sub_totals = {}
        for sub in submissions:
            key = f"{sub['student_id']}_{sub['item_id']}"
            sub_totals[key] = sub_totals.get(key, 0) + sub['quantity_brought']
        
        class_data = []
        for cls in classes:
            # Get students in this class
            class_students = [s for s in students if s['class_id'] == cls['id']]
            total_students = len(class_students)
            
            if total_students == 0:
                continue
            
            # Calculate total required and submitted for this class
            total_required = 0
            total_submitted = 0
            
            for student in class_students:
                for assignment in assignments:
                    if assignment.get('apply_to_all') or assignment.get('class_id') == cls['id']:
                        required = assignment['quantity_required']
                        total_required += required
                        
                        key = f"{student['id']}_{assignment['item_id']}"
                        submitted = sub_totals.get(key, 0)
                        total_submitted += min(submitted, required)
            
            compliance_rate = round((total_submitted / total_required * 100), 1) if total_required > 0 else 0
            
            if compliance_rate >= 80:
                status = 'Excellent'
                status_class = 'status-completed'
            elif compliance_rate >= 50:
                status = 'Partial'
                status_class = 'status-partial'
            else:
                status = 'Needs Improvement'
                status_class = 'status-pending'
            
            class_data.append({
                'class_id': cls['id'],
                'class_name': cls['name'],
                'total_students': total_students,
                'total_required': total_required,
                'total_submitted': total_submitted,
                'compliance_rate': compliance_rate,
                'status': status,
                'status_class': status_class
            })
        
        # Sort by compliance rate descending
        class_data.sort(key=lambda x: x['compliance_rate'], reverse=True)
        
        return jsonify({'success': True, 'classes': class_data})
        
    except Exception as e:
        print(f"Error generating class compliance report: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

