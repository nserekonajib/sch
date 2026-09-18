# syncSchoolPayToDb.py - Role-aware SchoolPay sync
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

from routes.permissions.permissions import role_required
from routes.accounts.accounts import get_institute_id

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

sync_bp = Blueprint('sync', __name__, url_prefix='/sync-schoolpay')


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _session_user_id():
    """Extract the session user id (works for owner + employee)."""
    return session.get('user_id') or session.get('user', {}).get('id')


def get_all_schoolpay_accounts(institute_id):
    """Get ALL SchoolPay accounts for the institute."""
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
    """Generate MD5 hash for SchoolPay API authentication."""
    hash_input = school_code + date + password
    return hashlib.md5(hash_input.encode()).hexdigest().upper()


def fetch_schoolpay_transactions(school_code, password, from_date, to_date=None):
    """Fetch transactions from SchoolPay API."""
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
    Parse payment date from various formats and return YYYY-MM-DD.
    Handles: "2023-08-22 13:36:53", "2023-08-22", "2023-08", etc.
    """
    try:
        if not date_string:
            return datetime.now().date().isoformat()

        date_string = str(date_string).strip()

        # "2023-08-22 13:36:53" → "2023-08-22"
        if ' ' in date_string:
            date_part = date_string.split(' ')[0]
            return date_part

        # Already YYYY-MM-DD
        if len(date_string) >= 10 and date_string[4] == '-' and date_string[7] == '-':
            return date_string[:10]

        # YYYY-MM → first day of month
        if len(date_string) == 7 and date_string[4] == '-':
            return f"{date_string}-01"

        for fmt in ['%Y-%m-%d', '%Y-%m-%dT%H:%M:%S', '%d/%m/%Y', '%m/%d/%Y', '%Y%m%d']:
            try:
                dt = datetime.strptime(date_string, fmt)
                return dt.date().isoformat()
            except Exception:
                continue

        return datetime.now().date().isoformat()

    except Exception as e:
        print(f"Error parsing date {date_string}: {e}")
        return datetime.now().date().isoformat()


def extract_transaction_date(transaction):
    """Extract the actual transaction date from SchoolPay response."""
    date_fields = [
        'transactionCompletionDateAndTime',
        'completionDate',
        'paymentDate',
        'transactionDate',
        'created_at',
        'createdAt',
        'date',
    ]
    for field in date_fields:
        date_value = transaction.get(field)
        if date_value:
            parsed_date = parse_payment_date(date_value)
            if parsed_date and '-' in parsed_date and len(parsed_date) == 10:
                return parsed_date
    return datetime.now().date().isoformat()


# ═══════════════════════════════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@sync_bp.route('/')
@role_required(['owner', 'accountant'])
def index():
    institute_id = get_institute_id(_session_user_id())

    if not institute_id:
        return render_template('schoolpay/sync.html', accounts_count=0, now=datetime.now())

    accounts = get_all_schoolpay_accounts(institute_id)
    return render_template('schoolpay/sync.html', accounts_count=len(accounts), now=datetime.now())


@sync_bp.route('/import', methods=['GET', 'POST'])
@role_required(['owner', 'accountant'])
def import_page():
    institute_id = get_institute_id(_session_user_id())

    if not institute_id:
        return render_template('schoolpay/import.html', accounts_count=0, now=datetime.now())

    accounts = get_all_schoolpay_accounts(institute_id)
    return render_template('schoolpay/import.html', accounts_count=len(accounts), now=datetime.now())


@sync_bp.route('/api/accounts', methods=['GET'])
@role_required(['owner', 'accountant'])
def get_accounts_list():
    """Get list of SchoolPay accounts for the institute."""
    institute_id = get_institute_id(_session_user_id())

    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400

    accounts = get_all_schoolpay_accounts(institute_id)

    return jsonify({
        'success': True,
        'accounts': [{'id': a['id'], 'account_name': a['account_name']} for a in accounts],
        'count': len(accounts),
    })


@sync_bp.route('/api/sync', methods=['POST'])
@role_required(['owner', 'accountant'])
def sync_transactions():
    """Sync transactions from ALL SchoolPay accounts for the institute."""
    institute_id = get_institute_id(_session_user_id())

    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400

    accounts = get_all_schoolpay_accounts(institute_id)

    if not accounts:
        return jsonify({
            'success': False,
            'message': 'No active SchoolPay accounts found. Please configure your API credentials first.',
        }), 400

    try:
        data = request.get_json() or {}
        sync_type = data.get('sync_type', 'date_range')
        sync_date = data.get('sync_date', datetime.now().strftime('%Y-%m-%d'))
        from_date = data.get('from_date', sync_date)
        to_date = data.get('to_date', sync_date)

        # Existing receipt numbers — avoid duplicates
        existing_receipts_response = supabase.table('payments')\
            .select('receipt_number')\
            .eq('institute_id', institute_id)\
            .execute()

        existing_receipts = set()
        if existing_receipts_response.data:
            existing_receipts = {r['receipt_number'] for r in existing_receipts_response.data}

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

            if sync_type == 'date_range':
                transactions = fetch_schoolpay_transactions(school_code, password, from_date, to_date)
            else:
                transactions = fetch_schoolpay_transactions(school_code, password, sync_date)

            if not transactions:
                all_failed_payments.append({
                    'account_name': account['account_name'],
                    'message': f'Failed to fetch transactions for account {account["account_name"]}',
                })
                continue

            transaction_list = None
            if isinstance(transactions, dict):
                transaction_list = (
                    transactions.get('transactions')
                    or transactions.get('data')
                    or transactions.get('results')
                )
                if not transaction_list and transactions.get('status') == 'success':
                    transaction_list = [transactions]
            elif isinstance(transactions, list):
                transaction_list = transactions

            if not transaction_list:
                print(f"No transactions found for account {account['account_name']}")
                continue

            print(f"Found {len(transaction_list)} transactions for account {account['account_name']}")

            student_codes = set()
            transaction_map = {}

            for transaction in transaction_list:
                student_code = (
                    transaction.get('studentPaymentCode')
                    or transaction.get('studentCode')
                    or transaction.get('student_id')
                    or transaction.get('studentId')
                    or transaction.get('studentID')
                )
                if student_code:
                    student_codes.add(str(student_code))
                    transaction_map.setdefault(str(student_code), []).append(transaction)

            # Bulk fetch students
            if student_codes:
                students_response = supabase.table('students')\
                    .select('id, name, student_id')\
                    .eq('institute_id', institute_id)\
                    .in_('student_id', list(student_codes))\
                    .execute()
            else:
                students_response = None

            student_lookup = {}
            if students_response and students_response.data:
                for student in students_response.data:
                    student_lookup[student['student_id']] = student

            payments_to_batch = []

            for student_code, transactions_list in transaction_map.items():
                student = student_lookup.get(student_code)

                if not student:
                    for transaction in transactions_list:
                        all_not_found_students.append({
                            'account_name': account['account_name'],
                            'student_payment_code': student_code,
                            'student_name': transaction.get('studentName', 'Unknown'),
                            'student_class': transaction.get('studentClass', 'N/A'),
                            'amount': float(transaction.get('amount', 0)),
                            'payment_date': extract_transaction_date(transaction),
                        })
                    continue

                for transaction in transactions_list:
                    amount = float(transaction.get('amount', 0))
                    payment_date = extract_transaction_date(transaction)

                    receipt_number = (
                        transaction.get('schoolpayReceiptNumber')
                        or transaction.get('receiptNumber')
                        or transaction.get('receipt')
                        or transaction.get('transactionId')
                        or transaction.get('id')
                        or transaction.get('TransactionID')
                    )

                    if not receipt_number:
                        receipt_number = f"SCHOOLPAY-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"
                    else:
                        receipt_number = str(receipt_number)

                    transaction_id = (
                        transaction.get('transactionId')
                        or transaction.get('id')
                        or transaction.get('reference')
                        or transaction.get('TransactionReference')
                    )

                    if receipt_number in existing_receipts:
                        all_duplicate_payments.append({
                            'account_name': account['account_name'],
                            'student_name': student['name'],
                            'receipt_number': receipt_number,
                            'amount': amount,
                            'payment_date': payment_date,
                        })
                        continue

                    existing_receipts.add(receipt_number)

                    payments_to_batch.append({
                        'student_id': student['id'],
                        'student_name': student['name'],
                        'student_code': student['student_id'],
                        'amount': amount,
                        'payment_date': payment_date,
                        'receipt_number': receipt_number,
                        'transaction_id': transaction_id,
                        'fee_month': payment_date,
                        'account_name': account['account_name'],
                    })

            # Batch insert
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
                        'created_at': datetime.now().isoformat(),
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
                                'payment_date': payment['payment_date'],
                            })
                    else:
                        for payment in payments_to_batch:
                            all_failed_payments.append({
                                'account_name': payment['account_name'],
                                'student_name': payment['student_name'],
                                'amount': payment['amount'],
                                'reason': 'Failed to insert payment',
                            })
                except Exception as e:
                    print(f"Batch insert error: {e}")
                    for payment in payments_to_batch:
                        all_failed_payments.append({
                            'account_name': payment['account_name'],
                            'student_name': payment['student_name'],
                            'amount': payment['amount'],
                            'reason': str(e),
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
            'not_found': all_not_found_students,
        }

        if all_duplicate_payments:
            response_data['warning'] = f"{len(all_duplicate_payments)} duplicate payment(s) skipped (receipt already exists)."
        if all_not_found_students:
            response_data['warning'] = (
                response_data.get('warning', '')
                + f" {len(all_not_found_students)} student(s) not found in the system. You can download the list."
            )

        return jsonify(response_data)

    except Exception as e:
        print(f"Error syncing transactions: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


@sync_bp.route('/api/download-not-found', methods=['POST'])
@role_required(['owner', 'accountant'])
def download_not_found_students():
    """Download list of not found students as Excel."""
    institute_id = get_institute_id(_session_user_id())

    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400

    try:
        data = request.get_json() or {}
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
            'payment_date': 'Payment Date',
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
                    except Exception:
                        pass
                worksheet.column_dimensions[column_letter].width = min(max_length + 2, 30)

        output.seek(0)
        filename = f"schoolpay_not_found_students_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

        return send_file(
            output,
            as_attachment=True,
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )

    except Exception as e:
        print(f"Error downloading not found students: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@sync_bp.route('/api/download-duplicates', methods=['POST'])
@role_required(['owner', 'accountant'])
def download_duplicates():
    """Download list of duplicate payments as Excel."""
    institute_id = get_institute_id(_session_user_id())

    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400

    try:
        data = request.get_json() or {}
        duplicate_payments = data.get('duplicate_payments', [])

        if not duplicate_payments:
            return jsonify({'success': False, 'message': 'No data to export'}), 400

        df = pd.DataFrame(duplicate_payments)
        df = df.rename(columns={
            'account_name': 'SchoolPay Account',
            'student_name': 'Student Name',
            'receipt_number': 'Receipt Number',
            'amount': 'Amount (UGX)',
            'payment_date': 'Payment Date',
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
                    except Exception:
                        pass
                worksheet.column_dimensions[column_letter].width = min(max_length + 2, 30)

        output.seek(0)
        filename = f"schoolpay_duplicate_payments_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

        return send_file(
            output,
            as_attachment=True,
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )

    except Exception as e:
        print(f"Error downloading duplicates: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@sync_bp.route('/api/accounts/check', methods=['GET'])
@role_required(['owner', 'accountant'])
def check_accounts():
    """Check if there are any SchoolPay accounts configured."""
    institute_id = get_institute_id(_session_user_id())

    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400

    accounts = get_all_schoolpay_accounts(institute_id)

    return jsonify({
        'success': True,
        'has_accounts': len(accounts) > 0,
        'accounts_count': len(accounts),
    })

@sync_bp.route('/api/import-excel', methods=['POST'])
@role_required(['owner', 'accountant'])
def import_excel():
    """Import payments from a SchoolPay Excel file — receipt number is required and unique."""
    institute_id = get_institute_id(_session_user_id())

    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400

    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'No file uploaded'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'message': 'No file selected'}), 400

    if not file.filename.endswith(('.xlsx', '.xls')):
        return jsonify({'success': False, 'message': 'Only Excel files (.xlsx, .xls) are allowed'}), 400

    try:
        df = pd.read_excel(file)

        if df.empty:
            return jsonify({'success': False, 'message': 'The Excel file is empty'}), 400

        columns = df.columns.tolist()

        # Normalize common typos so 'reciept' matches 'receipt', etc.
        def _normalize(s):
            return (
                str(s).lower()
                .strip()
                .replace('reciept', 'receipt')
                .replace('receit', 'receipt')
                .replace('_', ' ')
                .replace('-', ' ')
            )

        def find_column(patterns):
            for col in columns:
                col_norm = _normalize(col)
                for pattern in patterns:
                    p = _normalize(pattern)
                    if p in col_norm:
                        return col
            return None

        payment_code_col = find_column([
            'payment code', 'studentpaymentcode', 'student code',
            'student_id', 'studentid', 'paymentcode',
        ])
        student_name_col = find_column(['student name', 'name', 'full name', 'student'])
        amount_col = find_column(['amount', 'total', 'fee', 'payment amount', 'amount paid'])
        receipt_col = find_column([
            'receipt number', 'receipt', 'schoolpayreceiptnumber',
            'receiptno', 'receipt_no', 'transaction',
        ])
        date_col = find_column(['date', 'payment date', 'transaction date', 'completion date', 'payment_date'])
        class_col = find_column(['class', 'class code', 'student class', 'grade', 'level', 'form'])

        # ── Required columns: payment code, amount, AND receipt number ──
        if not payment_code_col or not amount_col or not receipt_col:
            missing = []
            if not payment_code_col: missing.append('"Payment Code"')
            if not amount_col:      missing.append('"Amount"')
            if not receipt_col:     missing.append('"Receipt Number"')
            return jsonify({
                'success': False,
                'message': f'Required column(s) not found: {", ".join(missing)}. '
                           f'The Excel file must contain a "Receipt Number" column. '
                           f'Columns found in your file: {", ".join(str(c) for c in columns)}',
            }), 400

        # Load existing receipts from DB (scoped to this institute)
        existing_receipts_response = supabase.table('payments')\
            .select('receipt_number')\
            .eq('institute_id', institute_id)\
            .execute()

        existing_receipts = set()
        if existing_receipts_response.data:
            existing_receipts = {
                str(r['receipt_number']).strip()
                for r in existing_receipts_response.data
                if r.get('receipt_number')
            }
        existing_receipts_lower = {r.lower() for r in existing_receipts}

        # Collect student codes
        student_codes = set()
        for _, row in df.iterrows():
            code = str(row[payment_code_col]).strip() if pd.notna(row[payment_code_col]) else None
            if code:
                student_codes.add(code)

        students_response = supabase.table('students')\
            .select('id, name, student_id')\
            .eq('institute_id', institute_id)\
            .in_('student_id', list(student_codes))\
            .execute()

        student_lookup = {}
        if students_response.data:
            for student in students_response.data:
                student_lookup[student['student_id']] = student

        synced_payments = []
        failed_payments = []
        not_found_students = []
        duplicate_payments = []

        # Track receipts seen within this file (case-insensitive key)
        seen_receipts_in_file = set()

        for index, row in df.iterrows():
            try:
                payment_code = str(row[payment_code_col]).strip() if pd.notna(row[payment_code_col]) else None
                if not payment_code:
                    failed_payments.append({
                        'account_name': 'Excel Import',
                        'student_name': 'Unknown',
                        'student_payment_code': '',
                        'amount': 0,
                        'reason': f'Row {index + 1}: Missing payment code',
                    })
                    continue

                # ── Receipt number is MANDATORY for every row ──
                receipt_number = None
                if pd.notna(row[receipt_col]):
                    receipt_number = str(row[receipt_col]).strip()
                    # Guard against Excel turning numbers into "12345.0"
                    if receipt_number.endswith('.0') and receipt_number[:-2].isdigit():
                        receipt_number = receipt_number[:-2]

                if not receipt_number:
                    failed_payments.append({
                        'account_name': 'Excel Import',
                        'student_name': 'Unknown',
                        'student_payment_code': payment_code,
                        'amount': 0,
                        'reason': f'Row {index + 1}: Missing receipt number',
                    })
                    continue

                receipt_key = receipt_number.lower()

                # ── Duplicate inside the same file ──
                if receipt_key in seen_receipts_in_file:
                    duplicate_payments.append({
                        'account_name': 'Excel Import',
                        'student_name': 'Unknown',
                        'receipt_number': receipt_number,
                        'amount': 0,
                        'payment_date': '',
                        'reason': f'Row {index + 1}: Duplicate receipt number within the file',
                    })
                    continue

                # ── Duplicate already in the DB ──
                if receipt_number in existing_receipts or receipt_key in existing_receipts_lower:
                    duplicate_payments.append({
                        'account_name': 'Excel Import',
                        'student_name': 'Unknown',
                        'receipt_number': receipt_number,
                        'amount': float(row[amount_col]) if pd.notna(row[amount_col]) else 0,
                        'payment_date': str(row[date_col]) if date_col and pd.notna(row[date_col]) else '',
                        'reason': f'Row {index + 1}: Receipt number already exists in the system',
                    })
                    continue

                # Lookup student
                student = student_lookup.get(payment_code)
                if not student:
                    student_name = str(row[student_name_col]) if student_name_col and pd.notna(row[student_name_col]) else 'Unknown'
                    student_class = str(row[class_col]) if class_col and pd.notna(row[class_col]) else 'N/A'
                    amount = float(row[amount_col]) if pd.notna(row[amount_col]) else 0
                    payment_date = str(row[date_col]) if date_col and pd.notna(row[date_col]) else datetime.now().date().isoformat()

                    not_found_students.append({
                        'account_name': 'Excel Import',
                        'student_payment_code': payment_code,
                        'student_name': student_name,
                        'student_class': student_class,
                        'amount': amount,
                        'payment_date': parse_payment_date(payment_date),
                        'receipt_number': receipt_number,
                    })
                    continue

                # Validate amount
                try:
                    amount = float(row[amount_col]) if pd.notna(row[amount_col]) else 0
                    if amount <= 0:
                        raise ValueError("Amount must be greater than 0")
                except Exception:
                    failed_payments.append({
                        'account_name': 'Excel Import',
                        'student_name': student['name'],
                        'student_payment_code': payment_code,
                        'amount': 0,
                        'reason': f'Row {index + 1}: Invalid amount',
                    })
                    continue

                # Resolve payment date
                payment_date = datetime.now().date().isoformat()
                if date_col and pd.notna(row[date_col]):
                    payment_date = parse_payment_date(str(row[date_col]))

                payment_data = {
                    'id': str(uuid.uuid4()),
                    'institute_id': institute_id,
                    'student_id': student['id'],
                    'invoice_id': None,
                    'amount': amount,
                    'payment_method': 'schoolpay',
                    'receipt_number': receipt_number,   # comes straight from Excel
                    'payment_date': payment_date,
                    'notes': f"Imported from Excel file: {file.filename}",
                    'fee_month': payment_date,
                    'created_at': datetime.now().isoformat(),
                }

                payment_response = supabase.table('payments').insert(payment_data).execute()

                if payment_response.data:
                    # Mark receipt as used so we don't accept it again in this run
                    seen_receipts_in_file.add(receipt_key)
                    existing_receipts.add(receipt_number)
                    existing_receipts_lower.add(receipt_key)

                    synced_payments.append({
                        'account_name': 'Excel Import',
                        'student_name': student['name'],
                        'student_id': student['student_id'],
                        'amount': amount,
                        'receipt_number': receipt_number,
                        'payment_date': payment_date,
                    })
                else:
                    failed_payments.append({
                        'account_name': 'Excel Import',
                        'student_name': student['name'],
                        'student_payment_code': payment_code,
                        'amount': amount,
                        'reason': f'Row {index + 1}: Failed to insert payment (receipt {receipt_number})',
                    })

            except Exception as row_error:
                failed_payments.append({
                    'account_name': 'Excel Import',
                    'student_name': 'Unknown',
                    'student_payment_code': '',
                    'amount': 0,
                    'reason': f'Row {index + 1}: {str(row_error)}',
                })

        response_data = {
            'success': True,
            'message': f"Successfully imported {len(synced_payments)} payments from Excel file",
            'synced_count': len(synced_payments),
            'synced': synced_payments,
            'failed_count': len(failed_payments),
            'failed': failed_payments,
            'duplicate_count': len(duplicate_payments),
            'duplicates': duplicate_payments,
            'not_found_count': len(not_found_students),
            'not_found': not_found_students,
        }

        warnings = []
        if duplicate_payments:
            warnings.append(f"{len(duplicate_payments)} duplicate receipt(s) skipped.")
        if not_found_students:
            warnings.append(f"{len(not_found_students)} student(s) not found in the system.")
        if failed_payments:
            warnings.append(f"{len(failed_payments)} row(s) failed.")
        if warnings:
            response_data['warning'] = ' '.join(warnings)

        return jsonify(response_data)

    except Exception as e:
        print(f"Error importing Excel: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500