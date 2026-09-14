# routes/roles/roles.py
"""
Owner-only Role Manager.
Allows the owner to toggle menus and endpoints per role.
"""

from flask import (
    Blueprint, render_template, request, jsonify,
    session, flash, redirect, url_for
)
import asyncio
from datetime import datetime

from routes.accounts.accounts import get_institute_id
from utils.navigation import (
    ALL_SECTIONS, get_all_roles, get_all_menus,
    get_role_display_name, get_role_responsibilities,
)
from utils.permission_resolver import (
    get_role_overrides, save_role_permissions,
    reset_role_permissions, invalidate_role_cache,
)

roles_bp = Blueprint('roles', __name__, url_prefix='/roles')


# ── Auth guard: owner only ───────────────────────────────────────────────────────
def owner_only(f):
    from functools import wraps
    @wraps(f)
    async def wrapper(*args, **kwargs):
        user = session.get('user', {}) or {}
        if not user:
            flash('Please login', 'warning')
            return redirect(url_for('auth.login'))
        if user.get('is_employee'):
            flash('Access denied. Owner only.', 'error')
            return redirect(url_for('dashboard.index'))
        result = f(*args, **kwargs)
        if asyncio.iscoroutine(result):
            return await result
        return result
    return wrapper


async def _run(fn, *args, **kwargs):
    return await asyncio.to_thread(fn, *args, **kwargs)


async def _institute_id():
    user_id = session.get('user_id') or session.get('user', {}).get('id')
    return await _run(get_institute_id, user_id)


# ── Page: Role Manager ───────────────────────────────────────────────────────────
@roles_bp.route('/')
@owner_only
async def index():
    """Show the role manager page."""
    institute_id = await _institute_id()
    if not institute_id:
        flash('Institute not found', 'error')
        return redirect(url_for('dashboard.index'))

    editable_roles = get_all_roles()
    editable_menus = get_all_menus()

    roles_data = []
    for role in editable_roles:
        overrides = await get_role_overrides(institute_id, role)
        roles_data.append({
            'role': role,
            'display_name': overrides.get('display_name') or get_role_display_name(role),
            'description': overrides.get('description') or get_role_responsibilities(role),
            'menu_overrides': overrides.get('menu', {}),
            'route_overrides': overrides.get('route', {}),
        })

    return render_template(
        'roles/index.html',
        editable_roles=roles_data,
        editable_menus=editable_menus,
    )


# ── API: Get current config for one role ─────────────────────────────────────────
@roles_bp.route('/api/<role>', methods=['GET'])
@owner_only
async def api_get_role(role):
    if role not in get_all_roles():
        return jsonify({'success': False, 'message': 'Invalid role'}), 400

    institute_id = await _institute_id()
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400

    overrides = await get_role_overrides(institute_id, role)
    return jsonify({
        'success': True,
        'role': role,
        'display_name': overrides.get('display_name') or get_role_display_name(role),
        'description': overrides.get('description') or get_role_responsibilities(role),
        'menu_overrides': overrides.get('menu', {}),
        'route_overrides': overrides.get('route', {}),
    })


# ── API: Save config for one role ────────────────────────────────────────────────
@roles_bp.route('/api/<role>', methods=['POST'])
@owner_only
async def api_save_role(role):
    if role not in get_all_roles():
        return jsonify({'success': False, 'message': 'Invalid role'}), 400

    institute_id = await _institute_id()
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400

    data = request.get_json(silent=True) or {}
    menu_overrides = data.get('menu_overrides') or {}
    route_overrides = data.get('route_overrides') or {}
    display_name = (data.get('display_name') or '').strip() or None
    description = (data.get('description') or '').strip() or None

    # Validate: only allow keys we know about
    valid_menus = set(ALL_SECTIONS.keys())
    menu_overrides = {k: bool(v) for k, v in menu_overrides.items() if k in valid_menus}

    ok = await save_role_permissions(
        institute_id=institute_id,
        role=role,
        menu_overrides=menu_overrides,
        route_overrides=route_overrides,
        display_name=display_name,
        description=description,
    )

    if ok:
        return jsonify({'success': True, 'message': 'Permissions saved'})
    return jsonify({'success': False, 'message': 'Failed to save'}), 500


# ── API: Reset one role ──────────────────────────────────────────────────────────
@roles_bp.route('/api/<role>/reset', methods=['POST'])
@owner_only
async def api_reset_role(role):
    if role not in get_all_roles():
        return jsonify({'success': False, 'message': 'Invalid role'}), 400

    institute_id = await _institute_id()
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400

    ok = await reset_role_permissions(institute_id, role)
    if ok:
        return jsonify({'success': True, 'message': f'{role} reset to defaults'})
    return jsonify({'success': False, 'message': 'Failed to reset'}), 500


# ── API: Get summary of all roles ────────────────────────────────────────────────
@roles_bp.route('/api/summary', methods=['GET'])
@owner_only
async def api_summary():
    institute_id = await _institute_id()
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400

    summary = []
    for role in get_all_roles():
        overrides = await get_role_overrides(institute_id, role)
        summary.append({
            'role': role,
            'display_name': overrides.get('display_name') or get_role_display_name(role),
            'menu_count': len(overrides.get('menu', {})),
            'route_count': len(overrides.get('route', {})),
        })
    return jsonify({'success': True, 'roles': summary})