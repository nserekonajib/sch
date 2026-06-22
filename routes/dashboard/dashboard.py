from flask import *
from flask import session
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
    """Dashboard statistics — properly includes SchoolPay payments."""
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
        
        # 🔥 FIX: Clear cache to get fresh data
        async with _cache_lock:
            if cache_key in _cache:
                del _cache[cache_key]
        
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

            # 🔥 FIX: Get ALL payments (including SchoolPay) for the period
            run(lambda: supabase.table('payments')
                .select('amount, student_id, payment_method')
                .eq('institute_id', institute_id)
                .gte('payment_date', start_date)
                .lte('payment_date', end_date)
                .execute()),

            # 🔥 FIX: Get invoices created within the date range
            run(lambda: supabase.table('invoices')
                .select('total_amount, student_id, status, created_at')
                .eq('institute_id', institute_id)
                .gte('created_at', f"{start_date}T00:00:00")
                .lte('created_at', f"{end_date}T23:59:59")
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
                .select('discount_amount, student_id, created_at')
                .eq('institute_id', institute_id)
                .eq('is_active', True)
                .gte('created_at', f"{start_date}T00:00:00")
                .lte('created_at', f"{end_date}T23:59:59")
                .execute())
        )

        total_students = students_res.count or 0
        total_employees = employees_res.count or 0

        # 🔥 FIX: Calculate revenue from ALL payments (including SchoolPay)
        payments_data = payments_res.data or []
        revenue_collected = sum(float(p['amount']) for p in payments_data)
        
        # 🔥 FIX: Calculate other income
        income_data = income_res.data or []
        other_income = sum(float(i['amount']) for i in income_data)

        # 🔥 FIX: Calculate total invoiced (positive amounts only)
        invoices_data = invoices_res.data or []
        total_invoiced = 0.0
        for inv in invoices_data:
            try:
                amount = float(inv.get('total_amount', 0))
                if amount > 0:
                    total_invoiced += amount
            except (ValueError, TypeError):
                continue

        # 🔥 FIX: Calculate total discounts
        discounts_data = discounts_res.data or []
        total_discounts = 0.0
        for d in discounts_data:
            try:
                discount_amount = float(d.get('discount_amount', 0))
                if discount_amount > 0:
                    total_discounts += discount_amount
            except (ValueError, TypeError):
                continue

        # 🔥 FIX: Calculate total payable
        total_payable = total_invoiced - total_discounts
        
        # 🔥 FIX: Collection rate using ALL payments
        if total_payable > 0:
            collection_rate = (revenue_collected / total_payable) * 100
        else:
            collection_rate = 100.0 if revenue_collected > 0 else 0.0

        total_income = revenue_collected + other_income
        total_expenses = sum(float(e['amount']) for e in (expense_res.data or []))
        total_profit = total_income - total_expenses

        # 🔥 FIX: Breakdown of payments by method
        payment_method_breakdown = {}
        schoolpay_total = 0
        manual_total = 0
        for p in payments_data:
            method = p.get('payment_method', 'unknown')
            amount = float(p['amount'])
            payment_method_breakdown[method] = payment_method_breakdown.get(method, 0) + amount
            if method == 'schoolpay':
                schoolpay_total += amount
            else:
                manual_total += amount

        # 🔥 DEBUG: Log the values
        print(f"=== DASHBOARD STATS ===")
        print(f"Payments count: {len(payments_data)}")
        print(f"Revenue collected: {revenue_collected}")
        print(f"Invoices count: {len(invoices_data)}")
        print(f"Total invoiced: {total_invoiced}")
        print(f"Total discounts: {total_discounts}")
        print(f"Total payable: {total_payable}")
        print(f"Collection rate: {collection_rate}%")
        print(f"SchoolPay total: {schoolpay_total}")
        print(f"Manual total: {manual_total}")
        print(f"======================")

        response_data = {
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
                'payment_method_breakdown': payment_method_breakdown,
                'schoolpay_total': schoolpay_total,
                'manual_total': manual_total,
                'payment_count': len(payments_data),
                'invoice_count': len(invoices_data)
            }
        }
        
        response = jsonify(response_data)
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
    """12-month income vs expense graph — includes SchoolPay payments."""
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

        # Build one coroutine per month
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
            income = sum(float(r['amount']) for r in (pays.data or []))
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
        import traceback
        traceback.print_exc()
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
                    'total': total,
                    'present': present_count,
                    'absent': total - present_count,
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
                'role': role.replace('_', ' ').title(),
                'total': s['total'],
                'present': s['present'],
                'absent': s['total'] - s['present'],
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
    """Recent activities — includes SchoolPay payment indicators."""
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
                    .select('amount, receipt_number, created_at, payment_method, student:students(name)')
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
            method = p.get('payment_method', 'unknown')
            method_icon = '📱' if method == 'schoolpay' else '💳'
            method_label = 'SchoolPay' if method == 'schoolpay' else 'Manual'
            activities.append({'type': 'payment', 'title': f'Fee Payment Received {method_icon}',
                'description': f'UGX {float(p["amount"]):,.0f} from {name} ({method_label})',
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
        import traceback
        traceback.print_exc()
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

        # Get ALL payments (including SchoolPay) for current month
        payments_res = await run(
            lambda: supabase.table('payments')
            .select('amount, payment_date, payment_method')
            .eq('institute_id', institute_id)
            .gte('payment_date', month_start)
            .lte('payment_date', month_end)
            .execute()
        )

        # Get ALL payments for current year
        payments_year_res = await run(
            lambda: supabase.table('payments')
            .select('amount, payment_method')
            .eq('institute_id', institute_id)
            .gte('payment_date', year_start)
            .lte('payment_date', year_end)
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

        # Calculate totals from ALL payments
        total_school_fees_month = sum(float(p['amount']) for p in (payments_res.data or []))
        total_school_fees_year = sum(float(p['amount']) for p in (payments_year_res.data or []))
        total_other_income = sum(float(i['amount']) for i in (income_res.data or []))
        total_expenses = sum(float(e['amount']) for e in (expense_res.data or []))

        # Breakdown of payments by method for the month
        payment_method_breakdown = {}
        for p in (payments_res.data or []):
            method = p.get('payment_method', 'unknown')
            amount = float(p['amount'])
            payment_method_breakdown[method] = payment_method_breakdown.get(method, 0) + amount

        total_income = total_school_fees_year + total_other_income
        overall_profit = total_income - total_expenses

        response = jsonify({
            'success': True,
            'overall_profit': overall_profit,
            'total_school_fees': total_school_fees_year,
            'total_school_fees_month': total_school_fees_month,
            'total_other_income': total_other_income,
            'total_expenses': total_expenses,
            'total_income': total_income,
            'payment_method_breakdown': payment_method_breakdown,
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


# ─────────────────────────────────────────────────────────────────────────────────
@dashboard_bp.route('/api/fee-collection-summary', methods=['GET'])
@login_required
@role_required(['owner', 'teacher', 'accountant'])
def get_fee_collection_summary():
    """Get fee collection summary for dashboard cards - includes ALL payments including SchoolPay"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    
    try:
        # Get ALL invoices for the institute
        invoices_response = supabase.table('invoices')\
            .select('total_amount, student_id, status')\
            .eq('institute_id', institute_id)\
            .execute()
        
        invoices = invoices_response.data if invoices_response.data else []
        
        # Get ALL payments (including SchoolPay payments)
        payments_response = supabase.table('payments')\
            .select('amount, student_id, payment_date, payment_method')\
            .eq('institute_id', institute_id)\
            .execute()
        
        payments = payments_response.data if payments_response.data else []
        
        # Get ALL discounts
        discounts_response = supabase.table('discounts')\
            .select('discount_amount, student_id, is_active')\
            .eq('institute_id', institute_id)\
            .execute()
        
        discounts = discounts_response.data if discounts_response.data else []
        
        # Calculate totals safely
        total_invoiced = 0.0
        
        # Calculate from invoices - only positive amounts
        for inv in invoices:
            try:
                total_amount = inv.get('total_amount')
                if total_amount is not None and total_amount != '':
                    amount = float(total_amount)
                    if amount > 0:
                        total_invoiced += amount
            except (ValueError, TypeError):
                continue
        
        # Calculate total paid from ALL payments (including SchoolPay)
        total_paid = 0.0
        schoolpay_paid = 0.0
        manual_paid = 0.0
        
        for p in payments:
            try:
                amount = p.get('amount')
                if amount is not None and amount != '':
                    amt = float(amount)
                    total_paid += amt
                    if p.get('payment_method') == 'schoolpay':
                        schoolpay_paid += amt
                    else:
                        manual_paid += amt
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
        
        # Don't cap - allow showing >100% for overpayments
        # if collection_percentage > 100:
        #     collection_percentage = 100.0
        
        # Get breakdown by student
        student_payments = {}
        for p in payments:
            student_id = p.get('student_id')
            if student_id:
                student_payments[student_id] = student_payments.get(student_id, 0) + float(p['amount'])
        
        student_invoices = {}
        for inv in invoices:
            student_id = inv.get('student_id')
            if student_id:
                amount = float(inv.get('total_amount', 0))
                if amount > 0:
                    student_invoices[student_id] = student_invoices.get(student_id, 0) + amount
        
        # Find students with payments but no invoices (SchoolPay only)
        students_with_payments_only = []
        for sid in student_payments:
            if sid not in student_invoices:
                # Get student name
                try:
                    student_res = supabase.table('students')\
                        .select('name, student_id')\
                        .eq('id', sid)\
                        .execute()
                    if student_res.data:
                        students_with_payments_only.append({
                            'student_id': student_res.data[0].get('student_id'),
                            'name': student_res.data[0].get('name'),
                            'amount': student_payments[sid]
                        })
                except:
                    students_with_payments_only.append({
                        'student_id': sid,
                        'name': 'Unknown',
                        'amount': student_payments[sid]
                    })
        
        # Find students with invoices but no payments
        students_with_invoices_only = [
            sid for sid in student_invoices.keys() 
            if sid not in student_payments
        ]
        
        return jsonify({
            'success': True,
            'summary': {
                'total_invoiced': round(total_invoiced, 2),
                'total_discount_applied': round(total_discount, 2),
                'total_payable': round(total_payable, 2),
                'total_collected': round(total_paid, 2),
                'schoolpay_collected': round(schoolpay_paid, 2),
                'manual_collected': round(manual_paid, 2),
                'overall_collection_percentage': round(collection_percentage, 2),
                'total_invoices': len(invoices),
                'total_discount_records': len(discounts),
                'total_payments': len(payments),
                'students_with_payments_only': len(students_with_payments_only),
                'students_with_invoices_only': len(students_with_invoices_only)
            },
            'students_with_payments_only': students_with_payments_only[:10]
        })
        
    except Exception as e:
        print(f"Error getting fee collection summary: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500