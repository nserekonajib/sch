# utils/navigation.py - Role-based navigation with owner-editable overrides

from utils.permission_resolver import can_access_menu

ALL_SECTIONS = {
    'dashboard': {
        'label': 'Dashboard', 'icon': 'fa-chart-line',
        'url_endpoint': 'dashboard.index',
        'roles': ['owner', 'accountant', 'teacher', 'librarian', 'secretary', 'support_staff']
    },
    'study_resources': {
        'label': 'Study Resources', 'icon': 'fa-book-open',
        'url_endpoint': 'studyresource.index',
        'roles': ['owner', 'teacher', 'librarian']
    },
    'general_settings': {
        'label': 'General Settings', 'icon': 'fa-sliders-h',
        'roles': ['owner'],
        'submenu': [
            {'label': 'Institute Profile', 'endpoint': 'instituteProfile.profile'},
            {'label': 'Profile', 'endpoint': 'auth.profile'},
            {'label': 'SMS Settings', 'endpoint': 'sms_settings.index'},
            {'label': 'WhatsApp Settings', 'endpoint': 'whatsapp.index'},
            {'label': 'SchoolPay Settings', 'endpoint': 'schoolpay.index'},
          
            {'label': 'Role Manager', 'endpoint': 'roles.index'},   # NEW
            {'label': 'Marks Grading', 'endpoint': 'grading.index'},
            {'label': 'CB Settings', 'endpoint': 'cdc_settings.index'},
        ]
    },
    'classes': {
        'label': 'Classes', 'icon': 'fa-chalkboard',
        'roles': ['owner', 'teacher', 'secretary'],
        'submenu': [
            {'label': 'All Classes', 'endpoint': 'class.index'},
            {'label': 'New Class', 'endpoint': 'class.create'},
        ]
    },
    'subjects': {
        'label': 'Subjects', 'icon': 'fa-book',
        'roles': ['owner', 'teacher'],
        'submenu': [
            {'label': 'Classes With Subjects', 'endpoint': 'subjects.index'},
            {'label': 'Assign Subjects', 'endpoint': None, 'action': 'assign-subjects'},
        ]
    },
    'students': {
        'label': 'Students', 'icon': 'fa-user-graduate',
        'roles': ['owner', 'teacher', 'secretary', 'accountant'],
        'submenu': [
            {'label': 'Student Management', 'endpoint': 'student.index'},
            {'label': 'Student Houses', 'endpoint': 'houses.index'},
            {'label': 'Student ID Cards', 'endpoint': 'id.index'},
            {'label': 'Print Basic List', 'endpoint': 'student_list.index'},
            {'label': 'Promote Students', 'endpoint': 'promote.index'},
        ]
    },
    'employees': {
        'label': 'Employees', 'icon': 'fa-chalkboard-user',
        'roles': ['owner', 'secretary'],
        'submenu': [{'label': 'Employees Management', 'endpoint': 'employees.index'}]
    },
    'accounts': {
        'label': 'Accounts', 'icon': 'fa-wallet',
        'menu_class': 'menu-accounts',
        'roles': ['owner', 'accountant'],
        'submenu': [
            {'label': 'Accounts Management', 'endpoint': 'accounts.index'},
            {'label': 'Student Statements', 'endpoint': 'statements.index'},
            {'label': 'Expenses', 'endpoint': 'accounts.expenses'},
            {'label': 'Income', 'endpoint': 'accounts.income'},
            {'label': 'Budget', 'endpoint': 'budget.index'},
        ]
    },
    'reporting': {
        'label': 'Reporting Center', 'icon': 'fa-chart-pie',
        'menu_class': 'menu-reporting',
        'roles': ['owner', 'accountant'],
        'submenu': [
            {'label': 'Daily Collection', 'endpoint': 'center.daily_collection'},
            {'label': 'Balance Report', 'endpoint': 'center.balance_report'},
            {'label': 'Income & Expenses', 'endpoint': 'center.income_expense'},
            {'label': 'Income Statement', 'endpoint': 'center.income_statement'},
            {'label': 'Student Report', 'endpoint': 'center.student_report'},
            {'label': 'Class Report', 'endpoint': 'center.class_report'},
            {'label': 'Payment Methods', 'endpoint': 'center.payment_methods'},
            {'label': 'AI Analysis', 'endpoint': 'center.ai_analysis'},
        ]
    },
    'fees': {
        'label': 'Fees', 'icon': 'fa-money-bill-wave',
        'roles': ['owner', 'accountant', 'secretary'],
        'submenu': [
            {'label': 'Fees Management', 'endpoint': 'fees.index'},
            {'label': 'Non Invoiced Students', 'endpoint': 'fees.students_without_invoices_page'},
            {'label': 'Collect Fees', 'endpoint': 'collect.index'},
            {'label': 'Requirements', 'endpoint': 'requirements.index'},
            {'label': 'School Pay', 'endpoint': 'sync.index'},
            {'label': 'Import SchoolPay Data', 'endpoint': 'sync.import_page'},
            {'label': 'Transaction List', 'endpoint': 'payments_list.index'},
            {'label': 'Edit Invoice', 'endpoint': 'edit_invoice.index'},
            {'label': 'Discounts', 'endpoint': 'collect.discounts_page'},
        ]
    },
    'salary': {
        'label': 'Salary', 'icon': 'fa-credit-card',
        'roles': ['owner', 'accountant'],
        'submenu': [{'label': 'Pay Salary', 'endpoint': 'salary.index'}]
    },
    'attendance': {
        'label': 'Attendance', 'icon': 'fa-fingerprint',
        'menu_class': 'menu-attendance',
        'roles': ['owner', 'teacher', 'secretary'],
        'submenu': [
            {'label': 'Students Attendance', 'endpoint': 'attendance.index'},
            {'label': 'Employees Attendance', 'endpoint': 'staff_attendance.index'},
            {'label': 'Students Attendance Report', 'endpoint': 'attendance_report.index'},
            {'label': 'Employees Attendance Report', 'endpoint': 'staff_attendance_report.index'},
        ]
    },
    'exams': {
        'label': 'Exams & Report Cards', 'icon': 'fa-file-alt',
        'menu_class': 'menu-exams',
        'roles': ['owner', 'teacher'],
        'submenu': [
            {'label': 'Exams', 'endpoint': 'exams.index'},
            {'label': 'Exam Marks', 'endpoint': 'exams.marks'},
            {'label': 'Report Cards', 'endpoint': 'results.r'},
        ]
    },
    'messaging': {
        'label': 'Messaging', 'icon': 'fa-comment-dots',
        'url_endpoint': 'message.index',
        'roles': ['owner', 'secretary']
    },
    'billing': {
        'label': 'Billing', 'icon': 'fa-credit-card',
        'url_endpoint': 'billing.index',
        'roles': ['owner']
    },
    'library': {
        'label': 'International Library', 'icon': 'fa-globe-americas',
        'menu_class': 'menu-library',
        'url_endpoint': 'library.index',
        'roles': ['owner', 'librarian', 'teacher']
    },
}


def get_all_roles():
    """Roles that can be edited by the owner."""
    return ['accountant', 'teacher', 'librarian', 'secretary', 'support_staff']


def get_all_menus():
    """Flat list of menu keys + labels for the owner's UI."""
    return [
        {'key': k, 'label': v['label'], 'icon': v.get('icon')}
        for k, v in ALL_SECTIONS.items()
        if k != 'general_settings'    # owner-only, not editable
    ]


async def get_navigation_for_role_async(institute_id, role, is_employee=False):
    """
    Async version that respects owner-editable overrides.
    Use this from async Flask views / template filters.
    """
    if not is_employee:
        role = 'owner'

    navigation = []
    for section_key, section in ALL_SECTIONS.items():
        # 1. Role is explicitly allowed by defaults
        default_allowed = role in section.get('roles', [])

        # 2. Owner override (if exists)
        if role == 'owner':
            override = True  # owner sees everything
        elif institute_id:
            override = await can_access_menu(institute_id, role, section_key)
        else:
            override = None

        allowed = override if override is not None else default_allowed

        if not allowed:
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


def get_role_display_name(role):
    return {
        'owner': 'Administrator',
        'accountant': 'Accountant',
        'teacher': 'Teacher',
        'librarian': 'Librarian',
        'secretary': 'Secretary',
        'support_staff': 'Support Staff'
    }.get(role, role.replace('_', ' ').title())


def get_role_responsibilities(role):
    return {
        'owner': 'Complete system control',
        'accountant': 'Finance, fees, salaries, reports',
        'teacher': 'Classes, students, attendance, exams',
        'librarian': 'Library and study resources',
        'secretary': 'Admissions, student records, communication',
        'support_staff': 'Assigned administrative tasks'
    }.get(role, 'General access')
    
    
# utils/navigation.py

# Build a lookup: endpoint → section key
_ENDPOINT_TO_MENU = {}

def _build_endpoint_lookup():
    _ENDPOINT_TO_MENU.clear()
    for section_key, section in ALL_SECTIONS.items():
        # Direct link
        if section.get('url_endpoint'):
            _ENDPOINT_TO_MENU[section['url_endpoint']] = section_key
        # Submenu items
        for item in section.get('submenu', []):
            ep = item.get('endpoint')
            if ep:
                _ENDPOINT_TO_MENU[ep] = section_key

_build_endpoint_lookup()


def get_route_menu_key(endpoint: str):
    """
    Map a Flask endpoint (e.g. 'billing.index') to its parent menu key (e.g. 'billing').
    Returns None if not found.
    """
    if not endpoint:
        return None
    # Exact match
    if endpoint in _ENDPOINT_TO_MENU:
        return _ENDPOINT_TO_MENU[endpoint]
    # Prefix match: 'billing.xyz' → try 'billing.index' style lookups
    prefix = endpoint.split('.')[0]
    for ep, key in _ENDPOINT_TO_MENU.items():
        if ep.split('.')[0] == prefix:
            return key
    return None