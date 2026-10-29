from routes.permissions.permissions import role_required
# assignSubjectsToClass.py - auto-merge duplicate names, no forced recreate
from flask import Blueprint, render_template, request, jsonify, session
from supabase import create_client, Client
import os
import uuid
from datetime import datetime
from functools import wraps
from dotenv import load_dotenv
from routes.accounts.accounts import get_institute_id

load_dotenv()

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

subjects_bp = Blueprint('subjects', __name__, url_prefix='/subjects')


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Please login'}), 401
        return f(*args, **kwargs)
    return decorated_function


# ------------------------------------------------------------------
#  Helpers
# ------------------------------------------------------------------
def _fmt_marks(value):
    """Return int when whole (500.0 → 500), else float (100.5 → 100.5)."""
    try:
        f = float(value)
        return int(f) if f == int(f) else f
    except (TypeError, ValueError):
        return value


def _find_collision_subjects(institute_id, current_subject_id, new_name):
    """
    Return IDs of OTHER subjects in the same institute whose name matches
    `new_name` (case-insensitive). Falls back to exact match if ilike fails.
    """
    try:
        resp = supabase.table('subjects')\
            .select('id')\
            .eq('institute_id', institute_id)\
            .ilike('name', new_name)\
            .neq('id', current_subject_id)\
            .execute()
        return [r['id'] for r in (resp.data or [])]
    except Exception as e:
        print(f"ilike collision lookup failed, using eq: {e}")
        try:
            resp = supabase.table('subjects')\
                .select('id')\
                .eq('institute_id', institute_id)\
                .eq('name', new_name)\
                .neq('id', current_subject_id)\
                .execute()
            return [r['id'] for r in (resp.data or [])]
        except Exception as e2:
            print(f"eq collision lookup failed too: {e2}")
            return []


def _merge_collision_subject(institute_id, current_subject_id, collision_subject_id):
    """
    Merge a colliding subject into the current one:
      - Transfer class_subjects from collision → current
      - If both exist in same class, keep current, delete collision's row
      - Delete the collision subject record
    Returns the number of class assignments merged (int).
    """
    merged = 0
    try:
        usage = supabase.table('class_subjects')\
            .select('id, class_id')\
            .eq('subject_id', collision_subject_id)\
            .execute()

        current_usage = supabase.table('class_subjects')\
            .select('id, class_id')\
            .eq('subject_id', current_subject_id)\
            .execute()
        current_class_ids = {r['class_id'] for r in (current_usage.data or [])}

        for row in (usage.data or []):
            if row['class_id'] in current_class_ids:
                # Duplicate in same class → drop the collision copy
                supabase.table('class_subjects')\
                    .delete()\
                    .eq('id', row['id'])\
                    .execute()
            else:
                # Move the class assignment to the current subject
                supabase.table('class_subjects')\
                    .update({
                        'subject_id': current_subject_id,
                        'updated_at': datetime.now().isoformat()
                    })\
                    .eq('id', row['id'])\
                    .execute()
                merged += 1

        # Remove the now-redundant subject record
        supabase.table('subjects')\
            .delete()\
            .eq('id', collision_subject_id)\
            .eq('institute_id', institute_id)\
            .execute()

        return merged
    except Exception as e:
        print(f"Error merging collision subject {collision_subject_id}: {e}")
        return merged


# ------------------------------------------------------------------
#  Page
# ------------------------------------------------------------------
@subjects_bp.route('/')
@role_required(['owner', 'teacher', 'accountant'])
def index():
    user = session.get('user')
    institute_id = get_institute_id(user['id'])

    if not institute_id:
        return render_template('subjects/index.html', classes_data=[], teachers=[], institute_id=None)

    try:
        classes_response = supabase.table('classes')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('name')\
            .execute()
        classes = classes_response.data if classes_response.data else []

        if not classes:
            return render_template('subjects/index.html', classes_data=[], teachers=[], institute_id=institute_id)

        subjects_response = supabase.table('class_subjects')\
            .select('*, subjects(*)')\
            .eq('institute_id', institute_id)\
            .execute()
        subjects_data = subjects_response.data if subjects_response.data else []

        for subject in subjects_data:
            # Clean marks for display
            if subject.get('marks') is not None:
                subject['marks'] = _fmt_marks(subject['marks'])
            if subject.get('teacher_id'):
                teacher_response = supabase.table('employees')\
                    .select('id, name, employee_id, photo_url')\
                    .eq('id', subject['teacher_id'])\
                    .execute()
                if teacher_response.data:
                    subject['teachers'] = teacher_response.data[0]

        classes_data = []
        for class_item in classes:
            class_subjects = [s for s in subjects_data if s.get('class_id') == class_item['id']]
            classes_data.append({'class': class_item, 'subjects': class_subjects})

        teachers_response = supabase.table('employees')\
            .select('id, name, employee_id, photo_url')\
            .eq('institute_id', institute_id)\
            .eq('role', 'teacher')\
            .eq('status', 'active')\
            .order('name')\
            .execute()
        teachers = teachers_response.data if teachers_response.data else []

        return render_template('subjects/index.html',
                               classes_data=classes_data,
                               teachers=teachers,
                               institute_id=institute_id)

    except Exception as e:
        print(f"Error loading subjects page: {e}")
        import traceback
        traceback.print_exc()
        return render_template('subjects/index.html', classes_data=[], teachers=[], institute_id=institute_id)


# ------------------------------------------------------------------
#  APIs
# ------------------------------------------------------------------
@subjects_bp.route('/api/teachers/search', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def search_teachers():
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    try:
        search_term = request.args.get('q', '').strip()
        query = supabase.table('employees')\
            .select('id, name, employee_id, photo_url')\
            .eq('institute_id', institute_id)\
            .eq('role', 'teacher')\
            .eq('status', 'active')
        if search_term and len(search_term) >= 2:
            query = query.or_(f"name.ilike.%{search_term}%,employee_id.ilike.%{search_term}%")
        response = query.limit(20).execute()
        teachers = response.data if response.data else []
        return jsonify({'success': True, 'teachers': teachers})
    except Exception as e:
        print(f"Error searching teachers: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@subjects_bp.route('/api/classes', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_classes():
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    try:
        response = supabase.table('classes')\
            .select('*')\
            .eq('institute_id', institute_id)\
            .order('name')\
            .execute()
        return jsonify({'success': True, 'classes': response.data if response.data else []})
    except Exception as e:
        print(f"Error getting classes: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@subjects_bp.route('/api/class-subjects', methods=['GET'])
@role_required(['owner', 'teacher', 'accountant'])
def get_class_subjects():
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    try:
        class_id = request.args.get('class_id')
        if not class_id:
            return jsonify({'success': False, 'message': 'Class ID required'}), 400

        response = supabase.table('class_subjects')\
            .select('*, subjects(*)')\
            .eq('class_id', class_id)\
            .eq('institute_id', institute_id)\
            .order('created_at')\
            .execute()
        subjects = response.data if response.data else []

        for subject in subjects:
            if subject.get('marks') is not None:
                subject['marks'] = _fmt_marks(subject['marks'])
            if subject.get('teacher_id'):
                teacher_response = supabase.table('employees')\
                    .select('id, name, employee_id')\
                    .eq('id', subject['teacher_id'])\
                    .execute()
                if teacher_response.data:
                    subject['teachers'] = teacher_response.data[0]

        return jsonify({'success': True, 'subjects': subjects})
    except Exception as e:
        print(f"Error getting class subjects: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@subjects_bp.route('/api/assign', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def assign_subjects():
    """Batch add / update subjects for a class with auto-merge on name collision."""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400

    try:
        data = request.get_json() or {}
        class_id = data.get('class_id')
        subjects = data.get('subjects', [])

        if not class_id:
            return jsonify({'success': False, 'message': 'Please select a class'}), 400
        if not subjects:
            return jsonify({'success': False, 'message': 'Please add at least one subject'}), 400

        existing_response = supabase.table('class_subjects')\
            .select('id, subject_id')\
            .eq('class_id', class_id)\
            .eq('institute_id', institute_id)\
            .execute()
        existing = existing_response.data or []
        existing_by_id = {row['id']: row for row in existing}

        assigned_count = 0
        updated_count = 0
        merged_count = 0
        kept_ids = set()
        errors = []

        for subject_data in subjects:
            try:
                subject_name = (subject_data.get('name') or '').strip()
                marks_raw = subject_data.get('marks')
                teacher_id = subject_data.get('teacher_id')
                subject_id = subject_data.get('subject_id')
                class_subject_id = subject_data.get('class_subject_id')

                if not subject_name:
                    errors.append("Subject name is required")
                    continue
                try:
                    marks = float(marks_raw)
                except (TypeError, ValueError):
                    errors.append(f"Invalid marks for subject: {subject_name}")
                    continue
                if marks <= 0:
                    errors.append(f"Invalid marks for subject: {subject_name}")
                    continue
                if not teacher_id:
                    errors.append(f"Please select a teacher for subject: {subject_name}")
                    continue

                # ---------- UPDATE EXISTING (with merge on rename collision) ----------
                if subject_id and class_subject_id and class_subject_id in existing_by_id:
                    collision_ids = _find_collision_subjects(institute_id, subject_id, subject_name)
                    for cid in collision_ids:
                        merged_count += _merge_collision_subject(institute_id, subject_id, cid)

                    supabase.table('subjects')\
                        .update({'name': subject_name, 'updated_at': datetime.now().isoformat()})\
                        .eq('id', subject_id)\
                        .eq('institute_id', institute_id)\
                        .execute()

                    supabase.table('class_subjects')\
                        .update({
                            'marks': marks,
                            'teacher_id': teacher_id,
                            'updated_at': datetime.now().isoformat()
                        })\
                        .eq('id', class_subject_id)\
                        .execute()

                    kept_ids.add(class_subject_id)
                    updated_count += 1
                    continue

                # ---------- CREATE / ATTACH ----------
                # Reuse by case-insensitive name if it already exists
                existing_subject = supabase.table('subjects')\
                    .select('*')\
                    .eq('institute_id', institute_id)\
                    .ilike('name', subject_name)\
                    .execute()

                if existing_subject.data:
                    new_subject_id = existing_subject.data[0]['id']
                    # If extra orphan rows exist with the same name, merge them too
                    for extra in existing_subject.data[1:]:
                        merged_count += _merge_collision_subject(
                            institute_id, new_subject_id, extra['id']
                        )
                else:
                    new_subject_id = str(uuid.uuid4())
                    supabase.table('subjects').insert({
                        'id': new_subject_id,
                        'institute_id': institute_id,
                        'name': subject_name,
                        'created_at': datetime.now().isoformat(),
                        'updated_at': datetime.now().isoformat()
                    }).execute()

                existing_match = next(
                    (row for row in existing if row['subject_id'] == new_subject_id),
                    None
                )

                if existing_match:
                    supabase.table('class_subjects')\
                        .update({
                            'marks': marks,
                            'teacher_id': teacher_id,
                            'updated_at': datetime.now().isoformat()
                        })\
                        .eq('id', existing_match['id'])\
                        .execute()
                    kept_ids.add(existing_match['id'])
                    updated_count += 1
                else:
                    new_class_subject_id = str(uuid.uuid4())
                    supabase.table('class_subjects').insert({
                        'id': new_class_subject_id,
                        'institute_id': institute_id,
                        'class_id': class_id,
                        'subject_id': new_subject_id,
                        'marks': marks,
                        'teacher_id': teacher_id,
                        'created_at': datetime.now().isoformat(),
                        'updated_at': datetime.now().isoformat()
                    }).execute()
                    kept_ids.add(new_class_subject_id)
                    assigned_count += 1

            except Exception as e:
                errors.append(f"Error with subject {subject_data.get('name', 'unknown')}: {str(e)}")

        # Delete class_subjects that were NOT in this submission
        deleted_count = 0
        for row in existing:
            if row['id'] not in kept_ids:
                supabase.table('class_subjects').delete().eq('id', row['id']).execute()
                deleted_count += 1

        parts = []
        if assigned_count:
            parts.append(f"{assigned_count} added")
        if updated_count:
            parts.append(f"{updated_count} updated")
        if merged_count:
            parts.append(f"{merged_count} merged")
        if deleted_count:
            parts.append(f"{deleted_count} removed")
        summary = ", ".join(parts) if parts else "No changes"

        return jsonify({
            'success': True,
            'message': f'Done — {summary}',
            'assigned': assigned_count,
            'updated': updated_count,
            'merged': merged_count,
            'deleted': deleted_count,
            'errors': errors if errors else None
        })

    except Exception as e:
        print(f"Error assigning subjects: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


@subjects_bp.route('/api/subject/update', methods=['POST'])
@role_required(['owner', 'teacher', 'accountant'])
def update_subject():
    """Quick-edit one subject — auto-merges duplicates on rename collision."""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400

    try:
        data = request.get_json() or {}
        class_subject_id = data.get('class_subject_id')
        subject_id = data.get('subject_id')
        new_name = (data.get('name') or '').strip()
        teacher_id = data.get('teacher_id')

        if not class_subject_id or not subject_id:
            return jsonify({'success': False, 'message': 'Missing identifiers'}), 400
        if not new_name:
            return jsonify({'success': False, 'message': 'Subject name is required'}), 400
        if not teacher_id:
            return jsonify({'success': False, 'message': 'Teacher is required'}), 400
        try:
            marks = float(data.get('marks', 0))
        except (TypeError, ValueError):
            marks = 0
        if marks <= 0:
            return jsonify({'success': False, 'message': 'Invalid marks'}), 400

        # Verify ownership
        cs_response = supabase.table('class_subjects')\
            .select('id, subject_id')\
            .eq('id', class_subject_id)\
            .eq('institute_id', institute_id)\
            .eq('subject_id', subject_id)\
            .execute()
        if not cs_response.data:
            return jsonify({'success': False, 'message': 'Subject assignment not found'}), 404

        # ---- Auto-merge any collision ----
        collision_ids = _find_collision_subjects(institute_id, subject_id, new_name)
        merged_count = 0
        for cid in collision_ids:
            merged_count += _merge_collision_subject(institute_id, subject_id, cid)

        # ---- Rename + update ----
        supabase.table('subjects')\
            .update({'name': new_name, 'updated_at': datetime.now().isoformat()})\
            .eq('id', subject_id)\
            .eq('institute_id', institute_id)\
            .execute()

        supabase.table('class_subjects')\
            .update({
                'marks': marks,
                'teacher_id': teacher_id,
                'updated_at': datetime.now().isoformat()
            })\
            .eq('id', class_subject_id)\
            .execute()

        msg = 'Subject updated successfully'
        if merged_count:
            msg += f' ({merged_count} duplicate subject{"s" if merged_count > 1 else ""} merged)'

        return jsonify({'success': True, 'message': msg, 'merged': merged_count})

    except Exception as e:
        print(f"Error updating subject: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500


@subjects_bp.route('/api/subject/delete/<class_subject_id>', methods=['DELETE'])
@role_required(['owner', 'teacher', 'accountant'])
def delete_subject(class_subject_id):
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400
    try:
        result = supabase.table('class_subjects')\
            .delete()\
            .eq('id', class_subject_id)\
            .eq('institute_id', institute_id)\
            .execute()
        if result.data:
            return jsonify({'success': True, 'message': 'Subject removed successfully'})
        return jsonify({'success': False, 'message': 'Subject not found'}), 404
    except Exception as e:
        print(f"Error deleting subject: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500