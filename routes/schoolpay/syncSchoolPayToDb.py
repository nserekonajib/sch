# syncSchoolPayToDb.py - Fixed to sync through all accounts per institution
from flask import Blueprint, render_template, request, jsonify, session, send_file
from supabase import create_client, Client
import os
import uuid
import hashlib
import requests
from datetime import datetime, timedelta
import json
import pandas as pd
import io
from functools import wraps
from dotenv import load_dotenv

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

sync_bp = Blueprint('sync', __name__, url_prefix='/sync-schoolpay')

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
        print(f"Error getting institute ID: {e}")
        return None

def get_all_schoolpay_accounts(institute_id):
    """Get ALL SchoolPay accounts for the institute"""
    try:
        response = supabase.table('schoolpay_accounts')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .eq('is_active', True)\
            .execute()
        
        return response.data if response.data else []
    except Exception as e:
        print(f"Error getting SchoolPay accounts: {e}")
        return []

def generate_md5_hash(school_code, date, password):
    """Generate MD5 hash for SchoolPay API authentication"""
    hash_input = school_code + date + password
    return hashlib.md5(hash_input.encode()).hexdigest().upper()

def fetch_schoolpay_transactions(school_code, password, from_date, to_date=None):
    """Fetch transactions from SchoolPay API"""
    if to_date:
        request_hash = generate_md5_hash(school_code, from_date, password)
        url = f"https://schoolpay.co.ug/paymentapi/AndroidRS/SchoolRangeTransactions/{school_code}/{from_date}/{to_date}/{request_hash}"
    else:
        request_hash = generate_md5_hash(school_code, from_date, password)
        url = f"https://schoolpay.co.ug/paymentapi/AndroidRS/SyncSchoolTransactions/{school_code}/{from_date}/{request_hash}"
    
    print(f"Fetching from URL: {url}")
    
    try:
        response = requests.get(url, timeout=60)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"API returned status code: {response.status_code}")
            return None
    except Exception as e:
        print(f"Error fetching transactions: {e}")
        return None

def parse_payment_date(date_string):
    """
    Parse payment date from various formats and return YYYY-MM-DD
    Handles: "2023-08-22 13:36:53", "2023-08-22", "2023-08", etc.
    """
    try:
        if not date_string:
            return datetime.now().date().isoformat()
        
        date_string = str(date_string).strip()
        
        # Handle "2023-08-22 13:36:53" format
        if ' ' in date_string:
            date_part = date_string.split(' ')[0]
            return date_part
        
        # Already in YYYY-MM-DD format
        if len(date_string) >= 10 and date_string[4] == '-' and date_string[7] == '-':
            return date_string[:10]
        
        # YYYY-MM format - convert to first day of month
        if len(date_string) == 7 and date_string[4] == '-':
            return f"{date_string}-01"
        
        # Try other formats
        for fmt in ['%Y-%m-%d', '%Y-%m-%dT%H:%M:%S', '%d/%m/%Y', '%m/%d/%Y', '%Y%m%d']:
            try:
                dt = datetime.strptime(date_string, fmt)
                return dt.date().isoformat()
            except:
                continue
        
        return datetime.now().date().isoformat()
        
    except Exception as e:
        print(f"Error parsing date {date_string}: {e}")
        return datetime.now().date().isoformat()

def extract_transaction_date(transaction):
    """Extract the actual transaction date from SchoolPay response"""
    date_fields = [
        'transactionCompletionDateAndTime',
        'completionDate',
        'paymentDate',
        'transactionDate',
        'created_at',
        'createdAt',
        'date'
    ]
    
    for field in date_fields:
        date_value = transaction.get(field)
        if date_value:
            parsed_date = parse_payment_date(date_value)
            if parsed_date and '-' in parsed_date and len(parsed_date) == 10:
                return parsed_date
    
    return datetime.now().date().isoformat()

@sync_bp.route('/')
@login_required
def index():
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return render_template('schoolpay/sync.html', accounts_count=0, now=datetime.now())
    
    accounts = get_all_schoolpay_accounts(institute_id)
    
    return render_template('schoolpay/sync.html', accounts_count=len(accounts), now=datetime.now())

@sync_bp.route('/api/accounts', methods=['GET'])
@login_required
def get_accounts_list():
    """Get list of SchoolPay accounts for the institute"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    accounts = get_all_schoolpay_accounts(institute_id)
    
    return jsonify({
        'success': True,
        'accounts': [{'id': a['id'], 'account_name': a['account_name']} for a in accounts],
        'count': len(accounts)
    })

@sync_bp.route('/api/sync', methods=['POST'])
@login_required
def sync_transactions():
    """Sync transactions from ALL SchoolPay accounts for the institute"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    accounts = get_all_schoolpay_accounts(institute_id)
    
    if not accounts:
        return jsonify({'success': False, 'message': 'No active SchoolPay accounts found. Please configure your API credentials first.'}), 400
    
    try:
        data = request.get_json()
        sync_type = data.get('sync_type', 'date_range')
        sync_date = data.get('sync_date', datetime.now().strftime('%Y-%m-%d'))
        from_date = data.get('from_date', sync_date)
        to_date = data.get('to_date', sync_date)
        
        # Get ALL existing receipt numbers to avoid duplicates
        existing_receipts_response = supabase.table('payments')\
            .select('receipt_number')\
            .eq('institute_id', institute_id)\
            .execute()
        
        existing_receipts = set()
        if existing_receipts_response.data:
            existing_receipts = {r['receipt_number'] for r in existing_receipts_response.data}
        
        # Process each account
        all_synced_payments = []
        all_failed_payments = []
        all_not_found_students = []
        all_duplicate_payments = []
        
        for account in accounts:
            print(f"\n{'='*50}")
            print(f"Processing account: {account['account_name']} (School Code: {account['school_code']})")
            print(f"{'='*50}")
            
            school_code = account['school_code']
            password = account['api_password']
            
            # Fetch transactions for this account
            if sync_type == 'date_range':
                transactions = fetch_schoolpay_transactions(school_code, password, from_date, to_date)
            else:
                transactions = fetch_schoolpay_transactions(school_code, password, sync_date)
            
            if not transactions:
                all_failed_payments.append({
                    'account_name': account['account_name'],
                    'message': f'Failed to fetch transactions for account {account["account_name"]}'
                })
                continue
            
            # Extract transaction list
            transaction_list = None
            if isinstance(transactions, dict):
                transaction_list = transactions.get('transactions') or transactions.get('data') or transactions.get('results')
                if not transaction_list and 'status' in transactions and transactions.get('status') == 'success':
                    transaction_list = [transactions]
            elif isinstance(transactions, list):
                transaction_list = transactions
            
            if not transaction_list:
                print(f"No transactions found for account {account['account_name']}")
                continue
            
            print(f"Found {len(transaction_list)} transactions for account {account['account_name']}")
            
            # Get all student payment codes from this account's transactions
            student_codes = set()
            transaction_map = {}
            
            for transaction in transaction_list:
                student_code = (
                    transaction.get('studentPaymentCode') or 
                    transaction.get('studentCode') or 
                    transaction.get('student_id') or
                    transaction.get('studentId') or
                    transaction.get('studentID')
                )
                if student_code:
                    student_codes.add(str(student_code))
                    if str(student_code) not in transaction_map:
                        transaction_map[str(student_code)] = []
                    transaction_map[str(student_code)].append(transaction)
            
            # BULK FETCH all students at once
            if student_codes:
                students_response = supabase.table('students')\
                    .select('id, name, student_id')\
                    .eq('institute_id', institute_id)\
                    .in_('student_id', list(student_codes))\
                    .execute()
            else:
                students_response = None
            
            # Create lookup dictionary for students
            student_lookup = {}
            if students_response and students_response.data:
                for student in students_response.data:
                    student_lookup[student['student_id']] = student
            
            # Process transactions for this account
            payments_to_batch = []
            
            for student_code, transactions_list in transaction_map.items():
                student = student_lookup.get(student_code)
                
                if not student:
                    for transaction in transactions_list:
                        amount = float(transaction.get('amount', 0))
                        transaction_date = extract_transaction_date(transaction)
                        
                        all_not_found_students.append({
                            'account_name': account['account_name'],
                            'student_payment_code': student_code,
                            'student_name': transaction.get('studentName', 'Unknown'),
                            'student_class': transaction.get('studentClass', 'N/A'),
                            'amount': amount,
                            'payment_date': transaction_date
                        })
                    continue
                
                # Process payments for found student
                for transaction in transactions_list:
                    amount = float(transaction.get('amount', 0))
                    payment_date = extract_transaction_date(transaction)
                    
                    # Get receipt number
                    receipt_number = (
                        transaction.get('schoolpayReceiptNumber') or
                        transaction.get('receiptNumber') or 
                        transaction.get('receipt') or 
                        transaction.get('transactionId') or
                        transaction.get('id') or
                        transaction.get('TransactionID')
                    )
                    
                    if not receipt_number or receipt_number == '':
                        receipt_number = f"SCHOOLPAY-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"
                    else:
                        receipt_number = str(receipt_number)
                    
                    transaction_id = (
                        transaction.get('transactionId') or 
                        transaction.get('id') or 
                        transaction.get('reference') or
                        transaction.get('TransactionReference')
                    )
                    
                    # Check for duplicate
                    if receipt_number in existing_receipts:
                        all_duplicate_payments.append({
                            'account_name': account['account_name'],
                            'student_name': student['name'],
                            'receipt_number': receipt_number,
                            'amount': amount,
                            'payment_date': payment_date
                        })
                        continue
                    
                    existing_receipts.add(receipt_number)
                    
                    # Calculate fee_month from payment_date (YYYY-MM-DD)
                    fee_month = payment_date
                    
                    payments_to_batch.append({
                        'student_id': student['id'],
                        'student_name': student['name'],
                        'student_code': student['student_id'],
                        'amount': amount,
                        'payment_date': payment_date,
                        'receipt_number': receipt_number,
                        'transaction_id': transaction_id,
                        'fee_month': fee_month,
                        'account_name': account['account_name']
                    })
            
            # BATCH INSERT all payments for this account
            if payments_to_batch:
                batch_data = []
                for payment in payments_to_batch:
                    batch_data.append({
                        'id': str(uuid.uuid4()),
                        'institute_id': institute_id,
                        'student_id': payment['student_id'],
                        'invoice_id': None,
                        'amount': payment['amount'],
                        'payment_method': 'schoolpay',
                        'receipt_number': payment['receipt_number'],
                        'payment_date': payment['payment_date'],
                        'notes': f"Synced from SchoolPay ({payment['account_name']}). Transaction ID: {payment.get('transaction_id', 'N/A')}",
                        'fee_month': payment['fee_month'],
                        'created_at': datetime.now().isoformat()
                    })
                
                try:
                    result = supabase.table('payments').insert(batch_data).execute()
                    if result.data:
                        for payment in payments_to_batch:
                            all_synced_payments.append({
                                'account_name': payment['account_name'],
                                'student_name': payment['student_name'],
                                'student_id': payment['student_code'],
                                'amount': payment['amount'],
                                'receipt_number': payment['receipt_number'],
                                'payment_date': payment['payment_date']
                            })
                    else:
                        for payment in payments_to_batch:
                            all_failed_payments.append({
                                'account_name': payment['account_name'],
                                'student_name': payment['student_name'],
                                'amount': payment['amount'],
                                'reason': 'Failed to insert payment'
                            })
                except Exception as e:
                    print(f"Batch insert error: {e}")
                    for payment in payments_to_batch:
                        all_failed_payments.append({
                            'account_name': payment['account_name'],
                            'student_name': payment['student_name'],
                            'amount': payment['amount'],
                            'reason': str(e)
                        })
        
        response_data = {
            'success': True,
            'message': f"Synced {len(all_synced_payments)} payments from {len(accounts)} account(s)",
            'accounts_processed': len(accounts),
            'synced_count': len(all_synced_payments),
            'synced': all_synced_payments,
            'failed_count': len(all_failed_payments),
            'failed': all_failed_payments,
            'duplicate_count': len(all_duplicate_payments),
            'duplicates': all_duplicate_payments,
            'not_found_count': len(all_not_found_students),
            'not_found': all_not_found_students
        }
        
        if all_duplicate_payments:
            response_data['warning'] = f"{len(all_duplicate_payments)} duplicate payment(s) skipped (receipt already exists)."
        
        if all_not_found_students:
            response_data['warning'] = (response_data.get('warning', '') + f" {len(all_not_found_students)} student(s) not found in the system. You can download the list.")
        
        return jsonify(response_data)
        
    except Exception as e:
        print(f"Error syncing transactions: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@sync_bp.route('/api/download-not-found', methods=['POST'])
@login_required
def download_not_found_students():
    """Download list of not found students as Excel"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        not_found_students = data.get('not_found_students', [])
        
        if not not_found_students:
            return jsonify({'success': False, 'message': 'No data to export'}), 400
        
        df = pd.DataFrame(not_found_students)
        df = df.rename(columns={
            'account_name': 'SchoolPay Account',
            'student_payment_code': 'Payment Code',
            'student_name': 'Student Name',
            'student_class': 'Class',
            'amount': 'Amount (UGX)',
            'payment_date': 'Payment Date'
        })
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Not Found Students', index=False)
            
            worksheet = writer.sheets['Not Found Students']
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
        
        filename = f"schoolpay_not_found_students_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        
        return send_file(
            output,
            as_attachment=True,
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        
    except Exception as e:
        print(f"Error downloading not found students: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@sync_bp.route('/api/download-duplicates', methods=['POST'])
@login_required
def download_duplicates():
    """Download list of duplicate payments as Excel"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        data = request.get_json()
        duplicate_payments = data.get('duplicate_payments', [])
        
        if not duplicate_payments:
            return jsonify({'success': False, 'message': 'No data to export'}), 400
        
        df = pd.DataFrame(duplicate_payments)
        df = df.rename(columns={
            'account_name': 'SchoolPay Account',
            'student_name': 'Student Name',
            'receipt_number': 'Receipt Number',
            'amount': 'Amount (UGX)',
            'payment_date': 'Payment Date'
        })
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Duplicate Payments', index=False)
            
            worksheet = writer.sheets['Duplicate Payments']
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
        
        filename = f"schoolpay_duplicate_payments_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        
        return send_file(
            output,
            as_attachment=True,
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        
    except Exception as e:
        print(f"Error downloading duplicates: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@sync_bp.route('/api/accounts/check', methods=['GET'])
@login_required
def check_accounts():
    """Check if there are any SchoolPay accounts configured"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    accounts = get_all_schoolpay_accounts(institute_id)
    
    return jsonify({
        'success': True,
        'has_accounts': len(accounts) > 0,
        'accounts_count': len(accounts)
    })