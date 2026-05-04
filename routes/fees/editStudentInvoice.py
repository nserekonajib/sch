# editStudentInvoice.py - Edit Student Invoice Management
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

edit_invoice_bp = Blueprint('edit_invoice', __name__, url_prefix='/edit-invoice')

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

@edit_invoice_bp.route('/')
@login_required
def index():
    """Edit Student Invoice Page"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return render_template('edit_invoice/index.html', institute_id=None)
    
    return render_template('edit_invoice/index.html', institute_id=institute_id)

@edit_invoice_bp.route('/api/search-students', methods=['GET'])
@login_required
def search_students():
    """Search students by name or ID"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        search_term = request.args.get('q', '').strip()
        
        if len(search_term) < 2:
            return jsonify({'success': True, 'students': []})
        
        # Search students
        response = supabase.table('students')\
            .select('id, name, student_id, class_id, classes(name), category')\
            .eq('institute_id', institute_id)\
            .eq('status', 'active')\
            .ilike('name', f'%{search_term}%')\
            .limit(20)\
            .execute()
        
        students = response.data if response.data else []
        
        # Format response
        formatted_students = []
        for student in students:
            formatted_students.append({
                'id': student['id'],
                'name': student['name'],
                'student_id': student['student_id'],
                'class_name': student['classes']['name'] if student.get('classes') else 'N/A',
                'category': student.get('category', 'N/A')
            })
        
        return jsonify({'success': True, 'students': formatted_students})
        
    except Exception as e:
        print(f"Error searching students: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@edit_invoice_bp.route('/api/student-invoices/<student_id>', methods=['GET'])
@login_required
def get_student_invoices(student_id):
    """Get all invoices for a student with balance > 0"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Get student details
        student_response = supabase.table('students')\
            .select('id, name, student_id, class_id, classes(name)')\
            .eq('id', student_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if not student_response.data:
            return jsonify({'success': False, 'message': 'Student not found'}), 404
        
        student = student_response.data[0]
        
        # Get invoices with balance > 0
        invoices_response = supabase.table('invoices')\
            .select('*, fee_particulars(fee_items)')\
            .eq('student_id', student_id)\
            .eq('institute_id', institute_id)\
            .gt('balance', 0)\
            .order('created_at', desc=True)\
            .execute()
        
        invoices = invoices_response.data if invoices_response.data else []
        
        # Parse fee items
        for invoice in invoices:
            if invoice.get('fee_particulars') and invoice['fee_particulars'].get('fee_items'):
                try:
                    invoice['fee_items'] = json.loads(invoice['fee_particulars']['fee_items'])
                except:
                    invoice['fee_items'] = []
        
        return jsonify({
            'success': True,
            'student': student,
            'invoices': invoices
        })
        
    except Exception as e:
        print(f"Error getting student invoices: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@edit_invoice_bp.route('/api/invoice/<invoice_id>', methods=['GET'])
@login_required
def get_invoice(invoice_id):
    """Get single invoice details"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        response = supabase.table('invoices')\
            .select('*, fee_particulars(fee_items), students(name, student_id)')\
            .eq('id', invoice_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if not response.data:
            return jsonify({'success': False, 'message': 'Invoice not found'}), 404
        
        invoice = response.data[0]
        
        # Parse fee items
        if invoice.get('fee_particulars') and invoice['fee_particulars'].get('fee_items'):
            try:
                invoice['fee_items'] = json.loads(invoice['fee_particulars']['fee_items'])
            except:
                invoice['fee_items'] = []
        
        return jsonify({'success': True, 'invoice': invoice})
        
    except Exception as e:
        print(f"Error getting invoice: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@edit_invoice_bp.route('/api/invoice/<invoice_id>/update', methods=['PUT'])
@login_required
def update_invoice(invoice_id):
    """Update invoice details"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        
        # Get current invoice
        current_invoice = supabase.table('invoices')\
            .select('*')\
            .eq('id', invoice_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if not current_invoice.data:
            return jsonify({'success': False, 'message': 'Invoice not found'}), 404
        
        invoice = current_invoice.data[0]
        
        # Update invoice
        update_data = {
            'total_amount': float(data.get('total_amount', 0)),
            'updated_at': datetime.now().isoformat()
        }
        
        # Recalculate balance based on paid_amount
        update_data['balance'] = update_data['total_amount'] - invoice['paid_amount']
        
        # Update status based on new balance
        if update_data['balance'] <= 0:
            update_data['status'] = 'paid'
        elif invoice['paid_amount'] > 0:
            update_data['status'] = 'partial'
        else:
            update_data['status'] = 'pending'
        
        # Update invoice
        result = supabase.table('invoices')\
            .update(update_data)\
            .eq('id', invoice_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if result.data:
            # Update fee particulars if needed
            if data.get('fee_items'):
                particulars_id = invoice['particulars_id']
                if particulars_id:
                    supabase.table('fee_particulars')\
                        .update({
                            'fee_items': json.dumps(data['fee_items']),
                            'total_amount': update_data['total_amount'],
                            'updated_at': datetime.now().isoformat()
                        })\
                        .eq('id', particulars_id)\
                        .execute()
            
            return jsonify({
                'success': True,
                'message': 'Invoice updated successfully',
                'invoice': result.data[0]
            })
        else:
            return jsonify({'success': False, 'message': 'Failed to update invoice'}), 500
            
    except Exception as e:
        print(f"Error updating invoice: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@edit_invoice_bp.route('/api/invoice/<invoice_id>/delete', methods=['DELETE'])
@login_required
def delete_invoice(invoice_id):
    """Delete an invoice"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Check if invoice has any payments
        payments_response = supabase.table('payments')\
            .select('id')\
            .eq('invoice_id', invoice_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if payments_response.data and len(payments_response.data) > 0:
            return jsonify({'success': False, 'message': 'Cannot delete invoice with existing payments'}), 400
        
        # Get invoice to get particulars_id
        invoice_response = supabase.table('invoices')\
            .select('particulars_id')\
            .eq('id', invoice_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        # Delete invoice
        result = supabase.table('invoices')\
            .delete()\
            .eq('id', invoice_id)\
            .eq('institute_id', institute_id)\
            .execute()
        
        if result.data:
            # Delete associated fee particulars
            if invoice_response.data and invoice_response.data[0].get('particulars_id'):
                supabase.table('fee_particulars')\
                    .delete()\
                    .eq('id', invoice_response.data[0]['particulars_id'])\
                    .execute()
            
            return jsonify({'success': True, 'message': 'Invoice deleted successfully'})
        else:
            return jsonify({'success': False, 'message': 'Invoice not found'}), 404
            
    except Exception as e:
        print(f"Error deleting invoice: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500