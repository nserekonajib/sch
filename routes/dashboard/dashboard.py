

from flask import *
from supabase import create_client, Client
import httpx
import os
import asyncio
from datetime import datetime, timedelta
from functools import wraps
from dotenv import load_dotenv
from collections import defaultdict

from routes.auth.auth import (
    accountant_required, secretary_required, support_staff_required,
    librarian_required, teacher_required
)
from routes.accounts.accounts import get_institute_id

load_dotenv()

# ─── Supabase (sync client, wrapped via asyncio.to_thread for true non-blocking) ──
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ─── httpx client as requested (sync — used for any direct HTTP calls) ────────────
http_client = httpx.Client(
    http2=False,
    timeout=30,
)

# ─── Blueprint ────────────────────────────────────────────────────────────────────
dashboard_bp = Blueprint('dashboard', __name__, url_prefix='/dashboard')

# ─── Async-safe in-memory cache ───────────────────────────────────────────────────
_cache: dict = {}
_cache_lock = asyncio.Lock()


async def cache_get(key: str, ttl: int):
    """Return cached value if still fresh, else None."""
    async with _cache_lock:
        entry = _cache.get(key)
        if entry:
            data, timestamp = entry
            if (datetime.now() - timestamp).total_seconds() < ttl:
                return data
    return None


async def cache_set(key: str, value):
    """Store value in cache with current timestamp."""
    async with _cache_lock:
        _cache[key] = (value, datetime.now())


def async_cached(ttl: int = 300):
    """
    Async cache decorator. Cache key = function name + args + kwargs.
    Works correctly even on minimal resources — no threads, pure asyncio.
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            key = f"{func.__name__}:{args}:{kwargs}"
            cached = await cache_get(key, ttl)
            if cached is not None:
                return cached
            result = await func(*args, **kwargs)
            await cache_set(key, result)
            return result
        return wrapper
    return decorator


# ─── Helper: run any sync supabase call without blocking the event loop ───────────
async def run(fn, *args, **kwargs):
    """
    Wraps a synchronous supabase call in asyncio.to_thread so it runs in the
    default thread-pool executor — the event loop stays free the whole time.
    Works well on minimal resources: threads are released as soon as the query
    finishes, nothing is held open.
    """
    return await asyncio.to_thread(fn, *args, **kwargs)


# ─── Auth helper ──────────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    async def decorated(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Please login'}), 401
        return await f(*args, **kwargs)
    return decorated

def role_required(allowed_roles):
    """Generic role-based decorator - works with both sync and async view functions."""
    def decorator(f):
        @wraps(f)
        async def decorated_function(*args, **kwargs):
            if 'user' not in session:
                flash('Please login to access this page', 'warning')
                return redirect(url_for('auth.login'))  # noqa: F405

            user = session.get('user', {})
            is_employee = user.get('is_employee', False)
            user_role = user.get('role')

            # Institute owners (not employees)
            if not is_employee and 'owner' in allowed_roles:
                result = f(*args, **kwargs)
                # await if the view is async, return directly if sync
                if asyncio.iscoroutine(result):
                    return await result
                return result

            # Employees with a matching role
            if is_employee and user_role in allowed_roles:
                result = f(*args, **kwargs)
                if asyncio.iscoroutine(result):
                    return await result
                return result

            flash('Access denied. Insufficient privileges.', 'error')
            return redirect(url_for('dashboard.index'))

        return decorated_function
    return decorator
# ═════════════════════════════════════════════════════════════════════════════════
# ROUTES
# ═════════════════════════════════════════════════════════════════════════════════

@dashboard_bp.route('/')
@role_required(['owner', 'teacher', 'accountant'])
async def index():
    """Main Dashboard Page"""
    user_id = session.get('user_id') or session.get('user', {}).get('id')

    # Run both queries in parallel — no waiting on each other
    institute_id, institute_response = await asyncio.gather(
        run(get_institute_id, user_id),
        run(
            lambda: supabase.table('institutes')
            .select('institute_name')
            .execute()
        )
    )

    if not institute_id:
        return render_template('dashboard/index.html',
                               institute_id=None, institute_name=None)

    # Filter institute name from response
    institute_name = None
    for inst in (institute_response.data or []):
        institute_name = inst.get('institute_name')
        break

    return render_template('dashboard/index.html',
                           institute_id=institute_id,
                           institute_name=institute_name)


# ─────────────────────────────────────────────────────────────────────────────────
@dashboard_bp.route('/api/stats', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
async def get_dashboard_stats():
    """Dashboard statistics — all queries run in parallel. Includes SchoolPay payments."""
    user_id = session.get('user_id') or session.get('user', {}).get('id')
    institute_id = await run(get_institute_id, user_id)

    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400

    try:
        start_date = request.args.get('start_date') or \
            datetime.now().replace(day=1).date().isoformat()
        end_date = request.args.get('end_date') or \
            datetime.now().date().isoformat()

        cache_key = f"stats:{institute_id}:{start_date}:{end_date}"
        cached = await cache_get(cache_key, ttl=60)
        if cached is not None:
            return cached

        # Run all queries in parallel
        (students_res, employees_res, payments_res, invoices_res, 
         income_res, expense_res, discounts_res) = await asyncio.gather(
            run(lambda: supabase.table('students')
                .select('id', count='exact')
                .eq('institute_id', institute_id)
                .eq('status', 'active')
                .execute()),

            run(lambda: supabase.table('employees')
                .select('id', count='exact')
                .eq('institute_id', institute_id)
                .eq('status', 'active')
                .execute()),

            run(lambda: supabase.table('payments')
                .select('amount')
                .eq('institute_id', institute_id)
                .gte('payment_date', start_date)
                .lte('payment_date', end_date)
                .execute()),

            run(lambda: supabase.table('invoices')
                .select('total_amount')
                .eq('institute_id', institute_id)
                .execute()),

            run(lambda: supabase.table('income_transactions')
                .select('amount')
                .eq('institute_id', institute_id)
                .gte('transaction_date', start_date)
                .lte('transaction_date', end_date)
                .execute()),

            run(lambda: supabase.table('expense_transactions')
                .select('amount')
                .eq('institute_id', institute_id)
                .gte('transaction_date', start_date)
                .lte('transaction_date', end_date)
                .execute()),

            run(lambda: supabase.table('discounts')
                .select('discount_amount')
                .eq('institute_id', institute_id)
                .eq('is_active', True)
                .execute())
        )

        total_students = students_res.count or 0
        total_employees = employees_res.count or 0

        # Calculate totals
        revenue_collected = sum(float(p['amount']) for p in (payments_res.data or []))
        other_income = sum(float(i['amount']) for i in (income_res.data or []))
        total_expenses = sum(float(e['amount']) for e in (expense_res.data or []))

        # Total invoiced (only positive amounts)
        total_invoiced = 0.0
        for inv in (invoices_res.data or []):
            try:
                amount = float(inv.get('total_amount', 0))
                if amount > 0:
                    total_invoiced += amount
            except (ValueError, TypeError):
                continue

        # Total discounts
        total_discounts = sum(
            float(d.get('discount_amount', 0)) for d in (discounts_res.data or [])
            if d.get('discount_amount')
        )

        total_payable = total_invoiced - total_discounts
        
        # Collection rate (using all payments, not just invoice-linked)
        if total_payable > 0:
            collection_rate = (revenue_collected / total_payable) * 100
        else:
            collection_rate = 100.0 if revenue_collected > 0 else 0.0
        
        if collection_rate > 100:
            collection_rate = 100.0

        total_income = revenue_collected + other_income
        total_profit = total_income - total_expenses

        response = jsonify({
            'success': True,
            'stats': {
                'total_students': total_students,
                'total_employees': total_employees,
                'revenue_collected': revenue_collected,
                'other_income': other_income,
                'total_collected': total_income,
                'total_expenses': total_expenses,
                'total_profit': total_profit,
                'total_invoiced': total_invoiced,
                'total_discounts': total_discounts,
                'total_payable': total_payable,
                'collection_rate': round(collection_rate, 2),
                'start_date': start_date,
                'end_date': end_date,
            }
        })
        await cache_set(cache_key, response)
        return response

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

# ─────────────────────────────────────────────────────────────────────────────────
@dashboard_bp.route('/api/income-expense-graph', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
async def get_income_expense_graph():
    """12-month income vs expense graph — each month queried in parallel."""
    user_id = session.get('user_id') or session.get('user', {}).get('id')
    institute_id = await run(get_institute_id, user_id)

    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400

    cache_key = f"graph:{institute_id}"
    cached = await cache_get(cache_key, ttl=300)
    if cached is not None:
        return cached

    try:
        now = datetime.now()
        # Build list of (month_start, month_end) for last 12 months
        months = []
        current = (now - timedelta(days=365)).replace(day=1)
        while current <= now:
            month_start = current.date().isoformat()
            if current.month == 12:
                next_m = current.replace(year=current.year + 1, month=1)
            else:
                next_m = current.replace(month=current.month + 1)
            month_end = (next_m - timedelta(days=1)).date().isoformat()
            months.append((current.strftime('%b %Y'), month_start, month_end))
            current = next_m

        # Build one coroutine per month (3 queries each, gathered inside)
        async def fetch_month(label, ms, me):
            pays, incs, exps = await asyncio.gather(
                run(lambda: supabase.table('payments')
                    .select('amount')
                    .eq('institute_id', institute_id)
                    .gte('payment_date', ms)
                    .lte('payment_date', me)
                    .execute()),
                run(lambda: supabase.table('income_transactions')
                    .select('amount')
                    .eq('institute_id', institute_id)
                    .gte('transaction_date', ms)
                    .lte('transaction_date', me)
                    .execute()),
                run(lambda: supabase.table('expense_transactions')
                    .select('amount')
                    .eq('institute_id', institute_id)
                    .gte('transaction_date', ms)
                    .lte('transaction_date', me)
                    .execute()),
            )
            income  = sum(float(r['amount']) for r in (pays.data or []))
            income += sum(float(r['amount']) for r in (incs.data or []))
            expense = sum(float(r['amount']) for r in (exps.data or []))
            return {'month': label, 'income': income,
                    'expense': expense, 'profit': income - expense}

        # All 12 months fire at once
        monthly_data = await asyncio.gather(
            *[fetch_month(label, ms, me) for label, ms, me in months]
        )

        response = jsonify({'success': True, 'data': list(monthly_data)})
        await cache_set(cache_key, response)
        return response

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────────
@dashboard_bp.route('/api/class-attendance', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
async def get_class_attendance():
    """Today's attendance per class — 3 queries in parallel."""
    user_id = session.get('user_id') or session.get('user', {}).get('id')
    institute_id = await run(get_institute_id, user_id)

    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400

    today = datetime.now().date().isoformat()
    cache_key = f"class_att:{institute_id}:{today}"
    cached = await cache_get(cache_key, ttl=120)
    if cached is not None:
        return cached

    try:
        classes_res, students_res, attendance_res = await asyncio.gather(
            run(lambda: supabase.table('classes')
                .select('id, name')
                .eq('institute_id', institute_id)
                .order('name')
                .execute()),

            run(lambda: supabase.table('students')
                .select('id, class_id')
                .eq('institute_id', institute_id)
                .eq('status', 'active')
                .execute()),

            run(lambda: supabase.table('attendance')
                .select('student_id')
                .eq('institute_id', institute_id)
                .eq('scan_date', today)
                .execute()),
        )

        students_by_class: dict = defaultdict(list)
        for s in (students_res.data or []):
            if s.get('class_id'):
                students_by_class[s['class_id']].append(s['id'])

        present = {a['student_id'] for a in (attendance_res.data or [])}

        class_data = []
        for cls in (classes_res.data or []):
            cls_students = students_by_class.get(cls['id'], [])
            total = len(cls_students)
            if total > 0:
                present_count = sum(1 for sid in cls_students if sid in present)
                class_data.append({
                    'class_name': cls['name'],
                    'total':      total,
                    'present':    present_count,
                    'absent':     total - present_count,
                    'percentage': round(present_count / total * 100, 1),
                })

        response = jsonify({'success': True, 'data': class_data})
        await cache_set(cache_key, response)
        return response

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────────
@dashboard_bp.route('/api/staff-attendance', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
async def get_staff_attendance():
    """Today's staff attendance by role."""
    user_id = session.get('user_id') or session.get('user', {}).get('id')
    institute_id = await run(get_institute_id, user_id)

    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400

    today = datetime.now().date().isoformat()
    cache_key = f"staff_att:{institute_id}:{today}"
    cached = await cache_get(cache_key, ttl=120)
    if cached is not None:
        return cached

    try:
        employees_res, attendance_res = await asyncio.gather(
            run(lambda: supabase.table('employees')
                .select('id, role')
                .eq('institute_id', institute_id)
                .eq('status', 'active')
                .execute()),

            run(lambda: supabase.table('staff_attendance')
                .select('employee_id')
                .eq('institute_id', institute_id)
                .eq('attendance_date', today)
                .execute()),
        )

        present_ids = {p['employee_id'] for p in (attendance_res.data or [])}
        role_stats: dict = defaultdict(lambda: {'total': 0, 'present': 0})

        for emp in (employees_res.data or []):
            role = emp.get('role') or 'other'
            role_stats[role]['total'] += 1
            if emp['id'] in present_ids:
                role_stats[role]['present'] += 1

        role_data = [
            {
                'role':       role.replace('_', ' ').title(),
                'total':      s['total'],
                'present':    s['present'],
                'absent':     s['total'] - s['present'],
                'percentage': round(s['present'] / s['total'] * 100, 1)
                              if s['total'] else 0,
            }
            for role, s in role_stats.items()
        ]

        response = jsonify({'success': True, 'data': role_data})
        await cache_set(cache_key, response)
        return response

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────────
@dashboard_bp.route('/api/recent-activities', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
async def get_recent_activities():
    """Recent activities — 5 queries in parallel."""
    user_id = session.get('user_id') or session.get('user', {}).get('id')
    institute_id = await run(get_institute_id, user_id)

    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400

    cache_key = f"activities:{institute_id}"
    cached = await cache_get(cache_key, ttl=60)
    if cached is not None:
        return cached

    try:
        students_res, payments_res, employees_res, income_res, expense_res = \
            await asyncio.gather(
                run(lambda: supabase.table('students')
                    .select('name, created_at')
                    .eq('institute_id', institute_id)
                    .order('created_at', desc=True).limit(5).execute()),

                run(lambda: supabase.table('payments')
                    .select('amount, receipt_number, created_at, student:students(name)')
                    .eq('institute_id', institute_id)
                    .order('created_at', desc=True).limit(5).execute()),

                run(lambda: supabase.table('employees')
                    .select('name, created_at')
                    .eq('institute_id', institute_id)
                    .order('created_at', desc=True).limit(5).execute()),

                run(lambda: supabase.table('income_transactions')
                    .select('amount, description, created_at')
                    .eq('institute_id', institute_id)
                    .order('created_at', desc=True).limit(5).execute()),

                run(lambda: supabase.table('expense_transactions')
                    .select('amount, description, created_at')
                    .eq('institute_id', institute_id)
                    .order('created_at', desc=True).limit(5).execute()),
            )

        def trunc(s, n=50):
            return s[:47] + '...' if len(s) > n else s

        activities = []

        for s in (students_res.data or []):
            activities.append({'type': 'student', 'title': 'New Student Added',
                'description': f'{s["name"]} was enrolled',
                'time': s['created_at'], 'icon': 'user-graduate', 'color': 'green'})

        for p in (payments_res.data or []):
            name = (p.get('student') or {}).get('name', 'Student')
            activities.append({'type': 'payment', 'title': 'Fee Payment Received',
                'description': f'UGX {float(p["amount"]):,.0f} from {name}',
                'time': p['created_at'], 'icon': 'money-bill-wave', 'color': 'blue'})

        for e in (employees_res.data or []):
            activities.append({'type': 'employee', 'title': 'New Employee Added',
                'description': f'{e["name"]} joined the staff',
                'time': e['created_at'], 'icon': 'user-tie', 'color': 'purple'})

        for i in (income_res.data or []):
            desc = trunc(i.get('description') or 'No description')
            activities.append({'type': 'income', 'title': 'Other Income Recorded',
                'description': f'UGX {float(i["amount"]):,.0f} - {desc}',
                'time': i['created_at'], 'icon': 'chart-line', 'color': 'orange'})

        for ex in (expense_res.data or []):
            desc = trunc(ex.get('description') or 'No description')
            activities.append({'type': 'expense', 'title': 'Expense Recorded',
                'description': f'UGX {float(ex["amount"]):,.0f} - {desc}',
                'time': ex['created_at'], 'icon': 'receipt', 'color': 'red'})

        activities.sort(key=lambda x: x['time'], reverse=True)

        response = jsonify({'success': True, 'activities': activities[:10]})
        await cache_set(cache_key, response)
        return response

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────────
@dashboard_bp.route('/api/class-distribution', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
async def get_class_distribution():
    """Student count per class."""
    user_id = session.get('user_id') or session.get('user', {}).get('id')
    institute_id = await run(get_institute_id, user_id)

    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400

    cache_key = f"class_dist:{institute_id}"
    cached = await cache_get(cache_key, ttl=300)
    if cached is not None:
        return cached

    try:
        classes_res, students_res = await asyncio.gather(
            run(lambda: supabase.table('classes')
                .select('id, name')
                .eq('institute_id', institute_id)
                .order('name')
                .execute()),

            run(lambda: supabase.table('students')
                .select('class_id')
                .eq('institute_id', institute_id)
                .eq('status', 'active')
                .execute()),
        )

        class_counts: dict = defaultdict(int)
        for s in (students_res.data or []):
            if s.get('class_id'):
                class_counts[s['class_id']] += 1

        class_data = [
            {'name': cls['name'], 'count': class_counts[cls['id']]}
            for cls in (classes_res.data or [])
            if class_counts.get(cls['id'], 0) > 0
        ]

        response = jsonify({'success': True, 'data': class_data})
        await cache_set(cache_key, response)
        return response

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────────
@dashboard_bp.route('/api/overall-profit', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
async def get_overall_profit():
    """
    Overall profit — includes ALL payments (SchoolPay + regular)
    """
    user_id = session.get('user_id') or session.get('user', {}).get('id')
    institute_id = await run(get_institute_id, user_id)

    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400

    cache_key = f"overall_profit:{institute_id}"
    cached = await cache_get(cache_key, ttl=300)
    if cached is not None:
        return cached

    try:
        today = datetime.now()
        month_start = today.replace(day=1).date().isoformat()
        month_end = today.date().isoformat()
        year_start = today.replace(month=1, day=1).date().isoformat()
        year_end = today.date().isoformat()
        current_year = today.year

        # FIX: Get ALL payments (including SchoolPay) for current month
        payments_res = await run(
            lambda: supabase.table('payments')
            .select('amount')
            .eq('institute_id', institute_id)
            .gte('payment_date', month_start)
            .lte('payment_date', month_end)
            .execute()
        )

        # Other income — current year only
        income_res = await run(
            lambda: supabase.table('income_transactions')
            .select('amount')
            .eq('institute_id', institute_id)
            .gte('transaction_date', year_start)
            .lte('transaction_date', year_end)
            .execute()
        )

        # Expenses — current year only
        expense_res = await run(
            lambda: supabase.table('expense_transactions')
            .select('amount')
            .eq('institute_id', institute_id)
            .gte('transaction_date', year_start)
            .lte('transaction_date', year_end)
            .execute()
        )

        total_school_fees = sum(float(p['amount']) for p in (payments_res.data or []))
        total_other_income = sum(float(i['amount']) for i in (income_res.data or []))
        total_expenses = sum(float(e['amount']) for e in (expense_res.data or []))

        total_income = total_school_fees + total_other_income
        overall_profit = total_income - total_expenses

        response = jsonify({
            'success': True,
            'overall_profit': overall_profit,
            'total_school_fees': total_school_fees,
            'total_other_income': total_other_income,
            'total_expenses': total_expenses,
            'period': {
                'school_fees_period': f"{month_start} to {month_end}",
                'other_period': f"Year {current_year}",
            }
        })
        await cache_set(cache_key, response)
        return response

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500
    
    
@dashboard_bp.route('/api/fee-collection-summary', methods=['GET'])
@login_required
@role_required(['owner', 'teacher', 'accountant'])
def get_fee_collection_summary():
    """Get fee collection summary for dashboard cards - includes SchoolPay payments"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Get all invoices for the institute
        invoices_response = supabase.table('invoices')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .execute()
        
        invoices = invoices_response.data if invoices_response.data else []
        
        # Get ALL payments (including SchoolPay payments not linked to invoices)
        payments_response = supabase.table('payments')\
            .select('amount')\
            .eq('institute_id', institute_id)\
            .execute()
        
        payments = payments_response.data if payments_response.data else []
        
        # Get all discounts
        discounts_response = supabase.table('discounts')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .eq('is_active', True)\
            .execute()
        
        discounts = discounts_response.data if discounts_response.data else []
        
        # Calculate totals safely
        total_invoiced = 0.0
        
        # Calculate from invoices - only positive amounts (negative are credit notes)
        for inv in invoices:
            try:
                total_amount = inv.get('total_amount')
                if total_amount is not None and total_amount != '':
                    amount = float(total_amount)
                    # Only count positive invoices (debits), skip credit notes
                    if amount > 0:
                        total_invoiced += amount
            except (ValueError, TypeError):
                continue
        
        # Calculate total paid from ALL payments (including SchoolPay)
        total_paid = 0.0
        for p in payments:
            try:
                amount = p.get('amount')
                if amount is not None and amount != '':
                    total_paid += float(amount)
            except (ValueError, TypeError):
                continue
        
        # Calculate total discount
        total_discount = 0.0
        for d in discounts:
            try:
                discount_amount = d.get('discount_amount')
                if discount_amount is not None and discount_amount != '':
                    total_discount += float(discount_amount)
            except (ValueError, TypeError):
                continue
        
        # Total payable = total invoiced - total discounts
        total_payable = total_invoiced - total_discount
        
        # Collection percentage based on total payable
        if total_payable > 0:
            collection_percentage = (total_paid / total_payable) * 100
        else:
            collection_percentage = 100.0 if total_paid > 0 else 0.0
        
        # Ensure percentage doesn't exceed 100%
        if collection_percentage > 100:
            collection_percentage = 100.0
        
        return jsonify({
            'success': True,
            'summary': {
                'total_invoiced': round(total_invoiced, 2),
                'total_discount_applied': round(total_discount, 2),
                'total_payable': round(total_payable, 2),
                'total_collected': round(total_paid, 2),
                'overall_collection_percentage': round(collection_percentage, 2),
                'total_invoices': len(invoices),
                'total_discount_records': len(discounts),
                'total_payments': len(payments)
            }
        })
        
    except Exception as e:
        print(f"Error getting fee collection summary: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500
    
# Add this to your routes/fees/fees.py or wherever your fee endpoints are

@fees_bp.route('/overall-payable-summary', methods=['GET'])
@login_required
@role_required(['owner', 'teacher', 'accountant'])
def get_overall_payable_summary():
    """Get overall payable summary with SchoolPay payments included"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Get ALL invoices for the institute
        invoices_response = supabase.table('invoices')\
            .select('total_amount, paid_amount, balance, status')\
            .eq('institute_id', institute_id)\
            .execute()
        
        invoices = invoices_response.data if invoices_response.data else []
        
        # Get ALL payments (including SchoolPay payments)
        payments_response = supabase.table('payments')\
            .select('amount')\
            .eq('institute_id', institute_id)\
            .execute()
        
        payments = payments_response.data if payments_response.data else []
        
        # Get all discounts
        discounts_response = supabase.table('discounts')\
            .select('discount_amount, is_active')\
            .eq('institute_id', institute_id)\
            .execute()
        
        discounts = discounts_response.data if discounts_response.data else []
        
        # Calculate totals
        total_invoiced = 0.0
        total_invoice_paid = 0.0
        
        for inv in invoices:
            try:
                total_amount = inv.get('total_amount')
                if total_amount is not None and total_amount != '':
                    amount = float(total_amount)
                    if amount > 0:  # Only positive invoices
                        total_invoiced += amount
                
                # Get paid amount from invoices (for reference)
                paid_amount = inv.get('paid_amount')
                if paid_amount is not None and paid_amount != '':
                    total_invoice_paid += float(paid_amount)
            except (ValueError, TypeError):
                continue
        
        # Calculate total paid from ALL payments (including SchoolPay)
        total_paid_from_payments = 0.0
        for p in payments:
            try:
                amount = p.get('amount')
                if amount is not None and amount != '':
                    total_paid_from_payments += float(amount)
            except (ValueError, TypeError):
                continue
        
        # Calculate total discounts (only active ones)
        total_discount = 0.0
        for d in discounts:
            try:
                if d.get('is_active', True):  # Only active discounts
                    discount_amount = d.get('discount_amount')
                    if discount_amount is not None and discount_amount != '':
                        total_discount += float(discount_amount)
            except (ValueError, TypeError):
                continue
        
        # Total payable = total invoiced - total discounts
        total_payable = total_invoiced - total_discount
        
        # Use the higher of invoice-paid or payment-collected for total collected
        # This ensures SchoolPay payments are counted
        total_collected = max(total_paid_from_payments, total_invoice_paid)
        
        # If total_collected is 0 but we have payments, use payments total
        if total_collected == 0 and total_paid_from_payments > 0:
            total_collected = total_paid_from_payments
        
        # Collection percentage based on total payable
        if total_payable > 0:
            collection_percentage = (total_collected / total_payable) * 100
        else:
            collection_percentage = 100.0 if total_collected > 0 else 0.0
        
        # Ensure percentage doesn't exceed 100%
        if collection_percentage > 100:
            collection_percentage = 100.0
        
        # Get category breakdown (optional)
        category_breakdown = []
        try:
            # Get invoices by category if you have category field
            category_response = supabase.table('invoices')\
                .select('category, total_amount')\
                .eq('institute_id', institute_id)\
                .execute()
            
            category_data = {}
            for inv in (category_response.data or []):
                cat = inv.get('category', 'Uncategorized')
                amount = float(inv.get('total_amount', 0))
                if amount > 0:
                    category_data[cat] = category_data.get(cat, 0) + amount
            
            category_breakdown = [
                {'category': cat, 'amount': amount}
                for cat, amount in category_data.items()
            ]
        except Exception as e:
            print(f"Error getting category breakdown: {e}")
        
        return jsonify({
            'success': True,
            'summary': {
                'total_invoiced': round(total_invoiced, 2),
                'total_discount_applied': round(total_discount, 2),
                'total_payable': round(total_payable, 2),
                'total_collected': round(total_collected, 2),
                'overall_collection_percentage': round(collection_percentage, 2),
                'total_invoices': len(invoices),
                'total_discount_records': len(discounts),
                'total_payments': len(payments),
                'total_paid_from_payments': round(total_paid_from_payments, 2),
                'total_paid_from_invoices': round(total_invoice_paid, 2)
            },
            'category_breakdown': category_breakdown
        })
        
    except Exception as e:
        print(f"Error getting overall payable summary: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500