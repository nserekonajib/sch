# sendMessageToParents.py - Complete rewrite with dedup, history pagination, fixed search
from flask import Blueprint, render_template, request, jsonify, session
from supabase import create_client, Client
import os
import uuid
import re
from datetime import datetime
from functools import wraps
from dotenv import load_dotenv
from routes.accounts.accounts import get_institute_id as get_institute_id_func
from routes.permissions.permissions import role_required

load_dotenv()

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

MASTER_API_USERNAME = os.getenv('COMMS_API_USERNAME', '')
MASTER_API_KEY = os.getenv('COMMS_API_KEY', '')

message_bp = Blueprint('message', __name__, url_prefix='/send-message')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Please login'}), 401
        return f(*args, **kwargs)
    return decorated_function


def get_institute_details(institute_id):
    try:
        response = supabase.table('institutes').select('*').eq('id', institute_id).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error getting institute details: {e}")
        return None


def get_sms_settings(institute_id):
    try:
        response = supabase.table('sms_settings').select('*').eq('institute_id', institute_id).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error getting SMS settings: {e}")
        return None


def calculate_sms_cost(message, cost_per_sms=35):
    has_unicode = any(ord(c) > 127 for c in message)
    segment_size = 70 if has_unicode else 160
    segments = (len(message) + segment_size - 1) // segment_size
    total_cost = segments * cost_per_sms
    return {
        'length': len(message),
        'segments': segments,
        'cost': total_cost,
        'encoding': 'Unicode' if has_unicode else 'GSM',
        'cost_per_sms': cost_per_sms
    }


def format_phone_number(phone):
    """Format phone number to international format (+256...)."""
    if not phone:
        return None
    phone = str(phone).strip().replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
    if not phone:
        return None
    if phone.startswith('+'):
        return phone
    if phone.startswith('0'):
        return '+256' + phone[1:]
    elif phone.startswith('256'):
        return '+' + phone
    elif len(phone) == 9 and phone.isdigit():
        return '+256' + phone
    elif len(phone) == 12 and phone.isdigit():
        return '+' + phone
    else:
        return '+256' + phone


def deduct_from_balance(institute_id, amount):
    try:
        response = supabase.table('institutes').select('balance, total_spent').eq('id', institute_id).execute()
        if not response.data:
            return False, "Institute not found"
        current_balance = response.data[0].get('balance', 0)
        current_total_spent = response.data[0].get('total_spent', 0)
        if current_balance < amount:
            return False, f"Insufficient balance. Available: UGX {current_balance:,.2f}, Required: UGX {amount:,.2f}"
        new_balance = current_balance - amount
        new_total_spent = current_total_spent + amount
        supabase.table('institutes').update({
            'balance': new_balance,
            'total_spent': new_total_spent,
            'last_balance_update': datetime.now().isoformat()
        }).eq('id', institute_id).execute()
        return True, new_balance
    except Exception as e:
        print(f"Error deducting from balance: {e}")
        return False, str(e)


def log_bulk_sms_sent(log_entries):
    """Log multiple SMS entries in batch."""
    try:
        if not log_entries:
            return True
        batch_data = []
        for entry in log_entries:
            batch_data.append({
                'id': str(uuid.uuid4()),
                'institute_id': entry.get('institute_id'),
                'student_id': entry.get('student_id'),
                'phone_number': entry.get('phone_number'),
                'message': entry.get('message', '')[:500],
                'message_length': entry.get('message_length', 0),
                'segments': entry.get('segments', 0),
                'cost': entry.get('cost', 0),
                'status': entry.get('status', 'sent'),
                'error_message': entry.get('error_message', '')[:500] if entry.get('error_message') else None,
                'sent_at': datetime.now().isoformat()
            })
        if batch_data:
            supabase.table('sms_log').insert(batch_data).execute()
        return True
    except Exception as e:
        print(f"Error batch logging SMS: {e}")
        return False


def dedupe_recipients(recipients):
    """
    Deduplicate recipients by phone number.
    Returns (unique_recipients, duplicate_map) where duplicate_map maps
    phone -> list of student dicts that shared that phone.
    The first occurrence is kept as the primary recipient; the rest are
    attached to it as 'also_for' (so all students get logged).
    """
    seen = {}
    unique = []
    for r in recipients:
        phone = (r.get('phone') or '').strip()
        if not phone:
            continue
        if phone in seen:
            seen[phone].setdefault('also_for', []).append({
                'id': r.get('id'),
                'name': r.get('name'),
                'student_id': r.get('student_id'),
            })
        else:
            primary = dict(r)
            primary['also_for'] = []
            seen[phone] = primary
            unique.append(primary)
    return unique, seen


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@message_bp.route('/')
@role_required(['owner', 'teacher', 'accountant'])
def index():
    user = session.get('user')
    institute_id = get_institute_id_func(user['id'])

    if not institute_id:
        return render_template('message/index.html', classes=[], students=[], institute=None, sms_settings=None, balance=0)

    try:
        institute = get_institute_details(institute_id)

        classes_response = supabase.table('classes') \
            .select('*') \
            .eq('institute_id', institute_id) \
            .order('name') \
            .execute()
        classes = classes_response.data if classes_response.data else []

        students_response = supabase.table('students') \
            .select('id, name, student_id, class_id, classes(name), contact_number, father_name, mother_name') \
            .eq('institute_id', institute_id) \
            .eq('status', 'active') \
            .order('name') \
            .limit(500) \
            .execute()
        students = students_response.data if students_response.data else []

        sms_settings = get_sms_settings(institute_id)
        current_balance = institute.get('balance', 0) if institute else 0

        return render_template(
            'message/index.html',
            classes=classes,
            students=students,
            institute=institute,
            sms_settings=sms_settings,
            balance=current_balance
        )
    except Exception as e:
        print(f"Error loading message page: {e}")
        return render_template('message/index.html', classes=[], students=[], institute=None, sms_settings=None, balance=0)


@message_bp.route('/api/get-recipients', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def get_recipients():
    """Get recipients based on selected criteria (dedup by phone)."""
    user = session.get('user')
    institute_id = get_institute_id_func(user['id'])
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400

    try:
        data = request.get_json()
        apply_to = data.get('apply_to')
        class_id = data.get('class_id')
        student_ids = data.get('student_ids', [])

        query = supabase.table('students') \
            .select('id, name, student_id, contact_number') \
            .eq('institute_id', institute_id) \
            .eq('status', 'active')

        if apply_to == 'class' and class_id:
            query = query.eq('class_id', class_id)
        elif apply_to == 'student' and student_ids:
            query = query.in_('id', student_ids)

        response = query.execute()

        raw = []
        for student in response.data if response.data else []:
            phone = format_phone_number(student.get('contact_number', ''))
            if phone:
                raw.append({
                    'id': student['id'],
                    'name': student['name'],
                    'student_id': student['student_id'],
                    'phone': phone
                })

        # Dedup by phone
        unique_recipients, seen_map = dedupe_recipients(raw)
        # Attach also_for lists
        for r in unique_recipients:
            r['also_for'] = seen_map[r['phone']].get('also_for', [])

        duplicates_removed = len(raw) - len(unique_recipients)

        return jsonify({
            'success': True,
            'recipients': unique_recipients,
            'count': len(unique_recipients),
            'total_students': len(raw),
            'duplicates_removed': duplicates_removed
        })
    except Exception as e:
        print(f"Error getting recipients: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@message_bp.route('/api/search-students', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def search_students():
    """Fast live search for students - dynamic with phone formatting."""
    user = session.get('user')
    institute_id = get_institute_id_func(user['id'])
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400

    try:
        search_term = request.args.get('q', '').strip()
        class_id = request.args.get('class_id', '').strip()

        if len(search_term) < 1:
            return jsonify({'success': True, 'students': [], 'count': 0})

        query = supabase.table('students') \
            .select('id, name, student_id, class_id, classes(name), contact_number, father_name, mother_name') \
            .eq('institute_id', institute_id) \
            .eq('status', 'active')

        if class_id:
            query = query.eq('class_id', class_id)

        # Search across name, student_id, and contact_number
        # Escape % and _ for PostgREST ilike
        safe = search_term.replace('%', '').replace('_', '').replace(',', '')
        query = query.or_(
            f"name.ilike.%{safe}%,student_id.ilike.%{safe}%,contact_number.ilike.%{safe}%"
        )

        response = query.limit(50).execute()

        students = []
        for student in response.data if response.data else []:
            raw_phone = student.get('contact_number', '') or ''
            phone = format_phone_number(raw_phone) if raw_phone else None
            students.append({
                'id': student['id'],
                'name': student['name'],
                'student_id': student['student_id'],
                'class_name': student['classes']['name'] if student.get('classes') else 'N/A',
                'phone': phone,
                'raw_phone': raw_phone,
                'father_name': student.get('father_name', '') or '',
                'mother_name': student.get('mother_name', '') or ''
            })

        return jsonify({
            'success': True,
            'students': students,
            'count': len(students)
        })
    except Exception as e:
        print(f"Error searching students: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


@message_bp.route('/api/calculate-cost', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def calculate_cost():
    user = session.get('user')
    institute_id = get_institute_id_func(user['id'])
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400

    try:
        data = request.get_json()
        message = data.get('message', '')
        recipient_count = data.get('recipient_count', 1)

        sms_settings = get_sms_settings(institute_id)
        cost_per_sms = sms_settings.get('cost_per_sms', 35) if sms_settings else 35

        cost_info = calculate_sms_cost(message, cost_per_sms)
        total_cost = cost_info['cost'] * recipient_count

        institute = get_institute_details(institute_id)
        current_balance = institute.get('balance', 0) if institute else 0

        return jsonify({
            'success': True,
            'cost_info': {
                'per_message': cost_info,
                'recipient_count': recipient_count,
                'total_cost': total_cost,
                'current_balance': current_balance,
                'has_sufficient_balance': current_balance >= total_cost,
                'balance_after': current_balance - total_cost
            }
        })
    except Exception as e:
        print(f"Error calculating cost: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@message_bp.route('/api/send', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def send_message():
    """Send SMS - dedupes by phone number, logs all students per phone."""
    user = session.get('user')
    institute_id = get_institute_id_func(user['id'])
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400

    try:
        data = request.get_json()
        recipients = data.get('recipients', [])
        message = data.get('message', '').strip()
        sender_id = data.get('sender_id', 'SCHOOL')
        personalization = data.get('personalization', True)

        if not recipients:
            return jsonify({'success': False, 'message': 'No recipients selected'}), 400
        if not message:
            return jsonify({'success': False, 'message': 'Message cannot be empty'}), 400

        institute = get_institute_details(institute_id)
        if not institute:
            return jsonify({'success': False, 'message': 'Institute not found'}), 400

        sms_settings = get_sms_settings(institute_id)
        if not sms_settings:
            return jsonify({'success': False, 'message': 'SMS settings not configured. Please configure SMS settings first.'}), 400
        if not sms_settings.get('enabled'):
            return jsonify({'success': False, 'message': 'SMS is not enabled. Please enable SMS in settings.'}), 400

        cost_per_sms = sms_settings.get('cost_per_sms', 35)
        institute_name = institute.get('institute_name', 'School')

        # Dedup by phone - preserve also_for mapping
        unique_recipients, seen_map = dedupe_recipients(recipients)
        # Re-attach also_for (dedupe_recipients already does it, but be safe)
        for r in unique_recipients:
            r['also_for'] = seen_map[r['phone']].get('also_for', [])

        total_students = len(recipients)
        unique_count = len(unique_recipients)
        duplicates_skipped = total_students - unique_count

        if unique_count == 0:
            return jsonify({'success': False, 'message': 'No valid recipients with phone numbers'}), 400

        # Cost estimate using base message (no personalization) as before
        base_message = f"{message}\n\n{institute_name}"
        base_cost_info = calculate_sms_cost(base_message, cost_per_sms)

        # Estimate total cost (upper bound using base segments; personalization may add)
        estimated_total = base_cost_info['cost'] * unique_count
        current_balance = institute.get('balance', 0)

        if current_balance < estimated_total:
            return jsonify({
                'success': False,
                'message': f'Insufficient balance. Available: UGX {current_balance:,.0f}, Required (approx): UGX {estimated_total:,.0f} for {unique_count} unique phone(s) x {base_cost_info["segments"]} segment(s) @ UGX {cost_per_sms}/segment',
                'insufficient_balance': True,
                'balance': current_balance,
                'required': estimated_total
            }), 400

        if not MASTER_API_USERNAME or not MASTER_API_KEY:
            return jsonify({'success': False, 'message': 'SMS API credentials not configured. Please contact support.'}), 500

        try:
            from comms_sdk import CommsSDK, MessagePriority
            sdk = CommsSDK.authenticate(MASTER_API_USERNAME, MASTER_API_KEY)

            log_entries = []
            success_count = 0
            failed_recipients = []
            actual_cost_total = 0

            for recipient in unique_recipients:
                phone = (recipient.get('phone') or '').strip()
                if not phone:
                    continue

                student_name = recipient.get('name', 'Student')
                personalized_msg = base_message
                if personalization and '{student_name}' in personalized_msg:
                    personalized_msg = personalized_msg.replace('{student_name}', student_name)
                elif personalization:
                    personalized_msg = f"Dear {student_name},\n\n{personalized_msg}"

                personal_cost = calculate_sms_cost(personalized_msg, cost_per_sms)

                try:
                    sdk.send_sms(
                        [phone],
                        personalized_msg,
                        sender_id=sender_id[:11],
                        priority=MessagePriority.HIGHEST
                    )
                    success_count += 1
                    actual_cost_total += personal_cost['cost']

                    # Log primary recipient
                    log_entries.append({
                        'institute_id': institute_id,
                        'student_id': recipient.get('id'),
                        'phone_number': phone,
                        'message': personalized_msg,
                        'message_length': len(personalized_msg),
                        'segments': personal_cost['segments'],
                        'cost': personal_cost['cost'],
                        'status': 'sent'
                    })

                    # Log additional students sharing the same phone (cost 0)
                    for extra in recipient.get('also_for', []):
                        log_entries.append({
                            'institute_id': institute_id,
                            'student_id': extra.get('id'),
                            'phone_number': phone,
                            'message': personalized_msg,
                            'message_length': len(personalized_msg),
                            'segments': 0,
                            'cost': 0,
                            'status': 'sent',
                            'error_message': None
                        })
                except Exception as single_error:
                    failed_recipients.append(phone)
                    err = str(single_error)
                    log_entries.append({
                        'institute_id': institute_id,
                        'student_id': recipient.get('id'),
                        'phone_number': phone,
                        'message': personalized_msg,
                        'message_length': len(personalized_msg),
                        'segments': personal_cost['segments'],
                        'cost': personal_cost['cost'],
                        'status': 'failed',
                        'error_message': err
                    })
                    for extra in recipient.get('also_for', []):
                        log_entries.append({
                            'institute_id': institute_id,
                            'student_id': extra.get('id'),
                            'phone_number': phone,
                            'message': personalized_msg,
                            'message_length': len(personalized_msg),
                            'segments': 0,
                            'cost': 0,
                            'status': 'failed',
                            'error_message': err
                        })
                    print(f"Error sending to {phone}: {single_error}")

            if log_entries:
                log_bulk_sms_sent(log_entries)

            if success_count > 0:
                deduct_success, result = deduct_from_balance(institute_id, actual_cost_total)
                if not deduct_success:
                    print(f"Warning: SMS sent but balance deduction failed: {result}")
                    return jsonify({
                        'success': True,
                        'message': f'Message sent to {success_count} unique number(s) but balance deduction failed. Please contact support.',
                        'recipient_count': success_count,
                        'balance_deduction_failed': True
                    })

                updated_institute = get_institute_details(institute_id)
                new_balance = updated_institute.get('balance', 0) if updated_institute else 0

                msg = f'Message sent successfully to {success_count} unique number(s).'
                if duplicates_skipped > 0:
                    msg += f' {duplicates_skipped} duplicate phone number(s) were skipped.'
                if failed_recipients:
                    msg += f' Failed: {len(failed_recipients)}.'

                return jsonify({
                    'success': True,
                    'message': msg,
                    'recipient_count': success_count,
                    'total_students': total_students,
                    'unique_numbers': unique_count,
                    'duplicates_skipped': duplicates_skipped,
                    'failed_count': len(failed_recipients),
                    'cost': actual_cost_total,
                    'new_balance': new_balance,
                    'segments_per_sms': base_cost_info['segments'],
                    'cost_per_sms': base_cost_info['cost']
                })
            else:
                return jsonify({
                    'success': False,
                    'message': 'Failed to send any messages. No messages were sent and no balance was deducted.',
                    'failed_count': len(failed_recipients)
                }), 500

        except ImportError:
            return jsonify({'success': False, 'message': 'CommsSDK not installed. Please install it first.'}), 500
        except Exception as e:
            error_msg = str(e)
            print(f"SMS sending error: {error_msg}")
            return jsonify({'success': False, 'message': f'SMS sending failed: {error_msg}'}), 500

    except Exception as e:
        print(f"Error sending message: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


@message_bp.route('/api/message-history', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_message_history():
    """
    Paginated SMS history. Supports:
      ?page=1&per_page=50
      ?search=<term>     (search student name / phone / message)
      ?status=sent|failed
    Returns logs plus summary stats (computed across ALL logs, not just page).
    """
    user = session.get('user')
    institute_id = get_institute_id_func(user['id'])
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400

    try:
        page = max(1, request.args.get('page', 1, type=int))
        per_page = min(200, max(5, request.args.get('per_page', 50, type=int)))
        search = (request.args.get('search') or '').strip()
        status_filter = (request.args.get('status') or '').strip().lower()

        # Base query
        query = supabase.table('sms_log') \
            .select('*, students(name, student_id)', count='exact') \
            .eq('institute_id', institute_id)

        if status_filter in ('sent', 'failed'):
            query = query.eq('status', status_filter)

        if search:
            safe = search.replace('%', '').replace('_', '').replace(',', '')
            # Search on phone or message (student name search handled client-side since it's a join)
            query = query.or_(f"phone_number.ilike.%{safe}%,message.ilike.%{safe}%")

        offset = (page - 1) * per_page
        response = query.order('sent_at', desc=True).range(offset, offset + per_page - 1).execute()

        logs = response.data if response.data else []
        total_count = getattr(response, 'count', None) or 0

        formatted_logs = []
        for log in logs:
            student_info = log.get('students') or {}
            formatted_logs.append({
                'id': log.get('id'),
                'phone_number': log.get('phone_number'),
                'student_name': student_info.get('name'),
                'student_id': student_info.get('student_id'),
                'message': log.get('message'),
                'message_length': log.get('message_length'),
                'segments': log.get('segments'),
                'cost': log.get('cost'),
                'status': log.get('status'),
                'error_message': log.get('error_message'),
                'sent_at': log.get('sent_at')
            })

        # Summary stats (all-time, not filtered by search/page)
        stats_sent_resp = supabase.table('sms_log') \
            .select('id', count='exact') \
            .eq('institute_id', institute_id) \
            .eq('status', 'sent') \
            .execute()
        stats_failed_resp = supabase.table('sms_log') \
            .select('id', count='exact') \
            .eq('institute_id', institute_id) \
            .eq('status', 'failed') \
            .execute()

        total_sent = getattr(stats_sent_resp, 'count', 0) or 0
        total_failed = getattr(stats_failed_resp, 'count', 0) or 0

        cost_resp = supabase.table('sms_log') \
            .select('cost') \
            .eq('institute_id', institute_id) \
            .eq('status', 'sent') \
            .execute()
        total_cost = sum((log.get('cost') or 0) for log in (cost_resp.data or []))

        has_more = (offset + len(formatted_logs)) < total_count

        return jsonify({
            'success': True,
            'logs': formatted_logs,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total_count,
                'total_pages': (total_count + per_page - 1) // per_page if per_page else 1,
                'has_more': has_more
            },
            'summary': {
                'total_sent': total_sent,
                'total_failed': total_failed,
                'total_cost': total_cost
            }
        })
    except Exception as e:
        print(f"Error getting message history: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': True,
            'logs': [],
            'pagination': {'page': 1, 'per_page': 50, 'total': 0, 'total_pages': 1, 'has_more': False},
            'summary': {'total_sent': 0, 'total_failed': 0, 'total_cost': 0}
        })


@message_bp.route('/api/get-balance', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_balance():
    user = session.get('user')
    institute_id = get_institute_id_func(user['id'])
    if not institute_id:
        return jsonify({'success': False, 'balance': 0}), 400
    institute = get_institute_details(institute_id)
    return jsonify({
        'success': True,
        'balance': institute.get('balance', 0) if institute else 0,
        'total_spent': institute.get('total_spent', 0) if institute else 0
    })