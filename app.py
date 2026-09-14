# app.py - Main Application Entry Point
from flask import (
    Flask, json, render_template, redirect, url_for,
    flash, request, send_from_directory, session,
)
from flask import Blueprint
import os
import asyncio
import threading
import ssl
import certifi
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from dotenv import load_dotenv
from flask_cors import CORS

from utils.navigation import (
    get_navigation_for_role_async,
    get_role_display_name,
    get_role_responsibilities,
    get_all_roles,
    get_all_menus,
    ALL_SECTIONS,
)

# Load environment variables
load_dotenv()

# Fix SSL certificates for httpx / supabase on Windows
ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())

# Initialize Flask app
app = Flask(__name__)
CORS(app)
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')


# ═══════════════════════════════════════════════════════════════════════════════
# CONTEXT PROCESSORS
# ═══════════════════════════════════════════════════════════════════════════════
@app.context_processor
def inject_globals():
    """Inject session-derived values + datetime helpers into every template."""
    user = session.get('user', {}) or {}
    return {
        'institute_id': user.get('institute_id'),
        'datetime': datetime,
        'now': datetime.now(),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# JINJA GLOBALS & FILTERS
# ═══════════════════════════════════════════════════════════════════════════════
app.jinja_env.globals['get_role_display_name'] = get_role_display_name
app.jinja_env.globals['get_role_responsibilities'] = get_role_responsibilities
app.jinja_env.globals['get_all_roles'] = get_all_roles
app.jinja_env.globals['get_all_menus'] = get_all_menus


@app.template_filter('from_json')
def from_json_filter(value):
    """Convert JSON string to Python object."""
    if value is None:
        return []
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []


@app.template_filter('format_number')
def format_number(value):
    """Format number with commas."""
    try:
        return f"{int(value):,}"
    except (ValueError, TypeError):
        return value


# ═══════════════════════════════════════════════════════════════════════════════
# NAVIGATION RESOLVER — Option A: isolated event loop on a worker thread
# ═══════════════════════════════════════════════════════════════════════════════

# Dedicated thread pool for Jinja → async bridging.
# Reusing threads avoids spawning a fresh thread on every render.
_nav_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="nav_resolver")


def _static_nav_fallback(role, is_employee):
    """
    Pure-Python fallback that doesn't touch the DB or async.
    Mirrors the logic in get_navigation_for_role_async, but with NO overrides.
    Used when:
      - institute_id is not available yet (mid-login), OR
      - the async resolver fails for any reason.
    """
    if not is_employee:
        role = 'owner'

    navigation = []
    for section_key, section in ALL_SECTIONS.items():
        if role not in section.get('roles', []):
            continue

        nav_section = {
            'key': section_key,
            'label': section['label'],
            'icon': section.get('icon', 'fa-circle'),
            'menu_class': section.get('menu_class', ''),
            'url_endpoint': section.get('url_endpoint'),
            'submenu': [],
        }

        for item in section.get('submenu', []):
            nav_section['submenu'].append({
                'label': item['label'],
                'endpoint': item.get('endpoint'),
                'action': item.get('action'),
            })

        if nav_section['url_endpoint'] or nav_section['submenu']:
            navigation.append(nav_section)

    return navigation


def _run_async_in_isolated_loop(coro):
    """
    Runs `coro` inside a brand-new event loop on a worker thread.
    Safe to call even when the calling thread already has a running loop
    (which is the case under asgiref / async Flask views).
    """
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        try:
            loop.close()
        finally:
            asyncio.set_event_loop(None)


def nav_for_role_sync(institute_id, role, is_employee=False):
    """
    Jinja-callable wrapper around the async navigation resolver.
    Executes the coroutine on a worker thread with its own event loop,
    so it works even inside an async Flask request context
    (asgiref / async view functions).
    """
    # No institute yet (mid-login edge case) — skip DB entirely.
    if not institute_id:
        return _static_nav_fallback(role, is_employee)

    coro = None
    try:
        coro = get_navigation_for_role_async(institute_id, role, is_employee)
        # Submit to worker thread → runs in isolated event loop → returns real list.
        future = _nav_executor.submit(_run_async_in_isolated_loop, coro)
        return future.result(timeout=10)
    except Exception as e:
        # If the coroutine was never awaited (submit failed before scheduling),
        # close it explicitly to avoid the RuntimeWarning.
        try:
            if coro is not None and asyncio.iscoroutine(coro):
                coro.close()
        except Exception:
            pass
        print(f"[nav_for_role_sync] falling back to static nav: {e}")
        return _static_nav_fallback(role, is_employee)


app.jinja_env.globals['nav_for_role'] = nav_for_role_sync


# ═══════════════════════════════════════════════════════════════════════════════
# BLUEPRINTS — IMPORTS
# ═══════════════════════════════════════════════════════════════════════════════
from routes.auth.auth import auth_bp
from routes.institution.instituteProfile import instituteProfile_bp
from routes.classes.createClass import class_bp
from routes.students.student import student_bp
from routes.students.studentID import id_bp
from routes.fees.fees import fees_bp
from routes.fees.collectFees import collect_bp
from routes.sms.sms_settings import sms_settings_bp
from routes.discount.discountManagement import discount_bp
from routes.fees.feesReport import fee_reports_bp
from routes.accounts.accounts import accounts_bp
from routes.accounts.studentStatement import statement_bp
from routes.employees.employees import employees_bp
from routes.employees.employeeIdCard import employeeID_bp
from routes.students.promoteStudents import promote_bp
from routes.subjects.assignSubjectsToClass import subjects_bp
from routes.employees.employeePayroll import payroll_bp
from routes.attendance.studentAttendance import attendance_bp
from routes.attendance.studentAttendanceReport import attendance_report_bp
from routes.attendance.staffAttendance import staff_attendance_bp
from routes.attendance.staffAttendanceReport import staff_attendance_report_bp
from routes.exams.exams import exams_bp
from routes.exams.examGradingSetting import grading_bp
from routes.resultsCard.resultsCard import results_bp
from routes.students.printStudentList import student_list_bp
from routes.sms.sendMessageToParents import message_bp
from routes.requirements.schoolRequirementsManagement import requirements_bp
from routes.billing.billingModule import billing_bp
from routes.dashboard.dashboard import dashboard_bp
from routes.resultsCard.competenceReportCard import competence_bp
from routes.admin.admin import admin_bp
from routes.careers.careers import agent_bp
from routes.fees.editStudentInvoice import edit_invoice_bp
from routes.schoolpay.schoolPayIntegration import schoolpay_bp
from routes.schoolpay.syncSchoolPayToDb import sync_bp
from routes.library.library import library_bp
from routes.entertainment.entertainment import entertainment_bp
from routes.resources.studyresources import studyresource_bp as resources_bp
from routes.resultsCard.report_templates import templates_bp
from routes.fees.listEnDelete import payments_bp as list_delete_bp
from routes.employees.advance import salary_bp as advance_bp
from routes.houses.house import houses_bp
from routes.reports.reports import reports_bp
from routes.students.studentDetails import student_detail_bp
from routes.permissions.permissions_management import permissions_bp
from routes.reports.reportCentre import center_bp
from routes.fees.createFeeNames import fee_names_bp
from routes.whatsapp.whatsappIntegrationSettings import whatsapp_bp
from routes.reports.profitLossAndBalanceSheet import financial_reports_bp as profit_loss_bp
from routes.resultsCard.CDCReportSettings import settings_bp as cdc_report_settings_bp
from routes.accounts.budget import budget_bp
from routes.admin.registeredUserDetails import registered_users_bp
from routes.roles.roles import roles_bp


# ═══════════════════════════════════════════════════════════════════════════════
# BLUEPRINTS — REGISTRATION
# ═══════════════════════════════════════════════════════════════════════════════
app.register_blueprint(auth_bp, url_prefix='/auth')
app.register_blueprint(dashboard_bp, url_prefix='/dashboard')
app.register_blueprint(instituteProfile_bp)
app.register_blueprint(class_bp, url_prefix='/classes')
app.register_blueprint(student_bp, url_prefix='/students')
app.register_blueprint(id_bp, url_prefix='/student-id')
app.register_blueprint(fees_bp, url_prefix='/fees')
app.register_blueprint(collect_bp, url_prefix='/collect-fees')
app.register_blueprint(sms_settings_bp, url_prefix='/sms-settings')
app.register_blueprint(discount_bp, url_prefix='/discounts')
app.register_blueprint(fee_reports_bp, url_prefix='/fee-reports')
app.register_blueprint(accounts_bp, url_prefix='/accounts')
app.register_blueprint(statement_bp, url_prefix='/statements')
app.register_blueprint(employees_bp, url_prefix='/employees')
app.register_blueprint(employeeID_bp, url_prefix='/employee-id')
app.register_blueprint(promote_bp, url_prefix='/promote-students')
app.register_blueprint(subjects_bp, url_prefix='/subjects')
app.register_blueprint(payroll_bp, url_prefix='/payroll')
app.register_blueprint(attendance_bp, url_prefix='/attendance')
app.register_blueprint(attendance_report_bp, url_prefix='/attendance-report')
app.register_blueprint(staff_attendance_bp, url_prefix='/staff-attendance')
app.register_blueprint(staff_attendance_report_bp, url_prefix='/staff-attendance-report')
app.register_blueprint(exams_bp, url_prefix='/exams')
app.register_blueprint(grading_bp, url_prefix='/exam-grading')
app.register_blueprint(results_bp, url_prefix='/results')
app.register_blueprint(student_list_bp, url_prefix='/student-list')
app.register_blueprint(message_bp, url_prefix='/send-message')
app.register_blueprint(requirements_bp, url_prefix='/requirements')
app.register_blueprint(billing_bp, url_prefix='/billing')
app.register_blueprint(competence_bp, url_prefix='/competence-report')
app.register_blueprint(admin_bp, url_prefix='/admin')
app.register_blueprint(agent_bp, url_prefix='/agent')
app.register_blueprint(edit_invoice_bp, url_prefix='/edit-invoice')
app.register_blueprint(schoolpay_bp, url_prefix='/schoolpay')
app.register_blueprint(sync_bp, url_prefix='/sync-schoolpay')
app.register_blueprint(library_bp, url_prefix='/library')
app.register_blueprint(entertainment_bp, url_prefix='/entertainment')
app.register_blueprint(resources_bp, url_prefix='/study-resources')
app.register_blueprint(templates_bp, url_prefix='/report-templates')
app.register_blueprint(list_delete_bp)
app.register_blueprint(advance_bp)
app.register_blueprint(houses_bp)
app.register_blueprint(reports_bp)
app.register_blueprint(student_detail_bp)
app.register_blueprint(permissions_bp)
app.register_blueprint(center_bp)
app.register_blueprint(fee_names_bp)
app.register_blueprint(whatsapp_bp)
app.register_blueprint(profit_loss_bp)
app.register_blueprint(cdc_report_settings_bp)
app.register_blueprint(budget_bp)
app.register_blueprint(registered_users_bp)
app.register_blueprint(roles_bp)


# ═══════════════════════════════════════════════════════════════════════════════
# TOP-LEVEL ROUTES
# ═══════════════════════════════════════════════════════════════════════════════
@app.route('/')
def landing():
    """Landing page route."""
    return render_template('landing/index.html')


@app.route('/login')
def login_page():
    """Login page route."""
    return render_template('auth.html', mode='login')


@app.route('/register')
def register_page():
    """Register page route."""
    return render_template('auth.html', mode='register')


@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    # Production-ish server. For development you can swap in app.run().
    # app.run(host="0.0.0.0", port=40000)
    from waitress import serve
    serve(app, host='0.0.0.0', port=40000)