# app.py - Main Application Entry Point
from flask import Flask, json, render_template, redirect, url_for, flash, request
from flask import Blueprint
import os
from dotenv import load_dotenv
from flask import send_from_directory

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
import ssl
import certifi

ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())

@app.template_filter('from_json')
def from_json_filter(value):
    """Convert JSON string to Python object"""
    if value is None:
        return []
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []
    
@app.context_processor
def utility_processor():
    from datetime import datetime
    return {'now': datetime.now()}


# Import and register auth blueprint
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



@app.route('/')
def landing():
    """Landing page route"""
    return render_template('landing/index.html')

@app.route('/login')
def login_page():
    """Login page route"""
    return render_template('auth.html', mode='login')

@app.route('/register')
def register_page():
    """Register page route"""
    return render_template('auth.html', mode='register')


# Add to app.py



@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

if __name__ == '__main__':
     app.run(host="0.0.0.0", port=40000)
    # from waitress import serve
    # serve(app, host='0.0.0.0', port=40000)