# studyresources.py

import re
import logging
from urllib.parse import quote
from functools import wraps

import requests
from flask import Blueprint, jsonify, request, render_template, session
from routes.auth.auth import role_required
from routes.accounts.accounts import get_institute_id

studyresource_bp = Blueprint(
    'studyresource',
    __name__,
    url_prefix='/study-resources'
)

# =========================================================
# CONFIG
# =========================================================

API_BASE_URL = "https://shule.artytechcreators.com/api"
API_TIMEOUT = 30

logger = logging.getLogger(__name__)

# =========================================================
# API ENDPOINTS
# =========================================================

API_ENDPOINTS = {
    "classes": "api_get_classes",
    "subjects": "api_get_class_subjects",
    "terms": "api_get_terms",
    "topics": "api_get_topics",
    "lessons": "api_get_topic_lessons",
    "resources": "api_get_resources",
    "resource_types": "api_get_resource_types",
}

# =========================================================
# HELPERS
# =========================================================

def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Please login'}), 401
        return f(*args, **kwargs)
    return decorated_function

def api_headers():
    return {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded"
    }


def build_url(endpoint: str) -> str:
    return f"{API_BASE_URL}/{endpoint}"


def post_api(endpoint: str, payload=None):
    """
    Make POST request safely.
    Always returns:
    {
        "success": bool,
        "data": list|dict|None,
        "error": str|None
    }
    """

    payload = payload or {}

    try:
        response = requests.post(
            build_url(endpoint),
            data=payload,
            headers=api_headers(),
            timeout=API_TIMEOUT
        )

        logger.info(f"{endpoint} -> {response.status_code}")

        if response.status_code != 200:
            return {
                "success": False,
                "data": None,
                "error": f"API returned {response.status_code}"
            }

        try:
            json_data = response.json()
        except Exception as e:
            logger.error(f"JSON decode error: {e}")

            return {
                "success": False,
                "data": None,
                "error": "Invalid JSON response"
            }

        return {
            "success": True,
            "data": json_data,
            "error": None
        }

    except requests.exceptions.Timeout:
        return {
            "success": False,
            "data": None,
            "error": "Request timeout"
        }

    except requests.exceptions.RequestException as e:
        logger.error(str(e))

        return {
            "success": False,
            "data": None,
            "error": str(e)
        }


def ensure_list(api_response):
    """
    Ensure response data is always a list
    """

    if not api_response["success"]:
        logger.warning(api_response["error"])
        return []

    data = api_response["data"]

    if isinstance(data, list):
        return data

    logger.warning(f"Expected list but got {type(data)}")

    return []


def create_pdf_url(filename):
    """
    Convert:
    1765336809_1752100240_P.7 MTC BOT 1.pdf

    To:
    https://shule.artytechcreators.com/images/1765336809_1752100240_P.7%20MTC%20BOT%201.pdf
    """

    if not filename:
        return None

    encoded = quote(filename)

    return f"https://shule.artytechcreators.com/images/{encoded}"


def extract_youtube_embed(url):
    """
    Convert youtube links to embeddable links
    """

    if not url:
        return None

    try:

        # youtu.be
        if "youtu.be/" in url:
            video_id = url.split("/")[-1].split("?")[0]
            return f"https://www.youtube.com/embed/{video_id}"

        # youtube.com/watch?v=
        if "youtube.com/watch" in url:
            match = re.search(r"v=([a-zA-Z0-9_-]+)", url)

            if match:
                return f"https://www.youtube.com/embed/{match.group(1)}"

        return url

    except Exception:
        return url


# =========================================================
# PAGES
# =========================================================

@studyresource_bp.route('/')
@login_required
@role_required(['owner', 'teacher', 'accountant', 'student'])
def index():
    """Study resources page - accessible to all authenticated users"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return render_template('study_resources/index.html', error='Institute not found')
    
    return render_template('study_resources/index.html')


# =========================================================
# CLASSES
# =========================================================

@studyresource_bp.route('/api/classes', methods=['GET'])
@login_required
@role_required(['owner', 'teacher', 'accountant', 'student'])
def get_classes():
    """Get all classes from external API"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400

    response = post_api(API_ENDPOINTS["classes"])

    classes = ensure_list(response)

    return jsonify({
        "success": True,
        "count": len(classes),
        "data": classes
    })


# =========================================================
# SUBJECTS
# =========================================================

@studyresource_bp.route('/api/subjects', methods=['POST'])
@login_required
@role_required(['owner', 'teacher', 'accountant', 'student'])
def get_subjects():
    """Get subjects for a specific class"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400

    data = request.get_json(silent=True) or {}

    class_id = data.get("class_id")

    if not class_id:
        return jsonify({
            "success": False,
            "message": "class_id is required",
            "data": []
        }), 400

    payload = {
        "level_class_id": class_id
    }

    response = post_api(
        API_ENDPOINTS["subjects"],
        payload
    )

    subjects = ensure_list(response)

    return jsonify({
        "success": True,
        "count": len(subjects),
        "data": subjects
    })


# =========================================================
# TERMS
# =========================================================

@studyresource_bp.route('/api/terms', methods=['GET'])
@login_required
@role_required(['owner', 'teacher', 'accountant', 'student'])
def get_terms():
    """Get all terms"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400

    response = post_api(API_ENDPOINTS["terms"])

    terms = ensure_list(response)

    return jsonify({
        "success": True,
        "count": len(terms),
        "data": terms
    })


# =========================================================
# TOPICS
# =========================================================

@studyresource_bp.route('/api/topics', methods=['POST'])
@login_required
@role_required(['owner', 'teacher', 'accountant', 'student'])
def get_topics():
    """Get topics for a specific class and subject"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400

    data = request.get_json(silent=True) or {}

    class_id = data.get("class_id")
    subject_id = data.get("subject_id")
    term_id = data.get("term_id")

    if not class_id:
        return jsonify({
            "success": False,
            "message": "class_id is required",
            "data": []
        }), 400

    if not subject_id:
        return jsonify({
            "success": False,
            "message": "subject_id is required",
            "data": []
        }), 400

    payload = {
        "level_class_id": class_id,
        "subject_id": subject_id
    }

    # Optional
    if term_id:
        payload["term_id"] = term_id

    response = post_api(
        API_ENDPOINTS["topics"],
        payload
    )

    topics = ensure_list(response)

    return jsonify({
        "success": True,
        "count": len(topics),
        "data": topics
    })


# =========================================================
# LESSONS
# =========================================================

@studyresource_bp.route('/api/lessons', methods=['POST'])
@login_required
@role_required(['owner', 'teacher', 'accountant', 'student'])
def get_lessons():
    """Get lessons for a specific topic"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400

    data = request.get_json(silent=True) or {}

    topic_id = data.get("topic_id")

    if not topic_id:
        return jsonify({
            "success": False,
            "message": "topic_id is required",
            "data": []
        }), 400

    payload = {
        "topic_id": topic_id
    }

    response = post_api(
        API_ENDPOINTS["lessons"],
        payload
    )

    lessons = ensure_list(response)

    processed_lessons = []

    for lesson in lessons:

        processed_lessons.append({
            "id": lesson.get("id"),
            "name": lesson.get("name"),
            "slug": lesson.get("slug"),
            "teacher_name": lesson.get("teacher_name"),
            "topic_id": lesson.get("topic_id"),
            "youtube_url": lesson.get("link"),
            "embed_url": extract_youtube_embed(
                lesson.get("link")
            ),
            "views": lesson.get("count_views"),
            "likes": lesson.get("count_likes"),
            "tags": lesson.get("tags"),
            "created_at": lesson.get("created_at"),
            "updated_at": lesson.get("updated_at")
        })

    return jsonify({
        "success": True,
        "count": len(processed_lessons),
        "data": processed_lessons
    })


# =========================================================
# RESOURCES / PDFs
# =========================================================

@studyresource_bp.route('/api/resources', methods=['POST'])
@login_required
@role_required(['owner', 'teacher', 'accountant', 'student'])
def get_resources():
    """Get study resources (PDFs, documents)"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400

    data = request.get_json(silent=True) or {}

    payload = {}

    if data.get("resource_type_id"):
        payload["resource_type_id"] = data.get("resource_type_id")

    if data.get("class_id"):
        payload["level_class_id"] = data.get("class_id")

    if data.get("subject_id"):
        payload["subject_id"] = data.get("subject_id")

    if data.get("term_id"):
        payload["term_id"] = data.get("term_id")

    response = post_api(
        API_ENDPOINTS["resources"],
        payload
    )

    resources = ensure_list(response)

    processed_resources = []

    for resource in resources:

        pdf_url = None

        if resource.get("file"):
            pdf_url = create_pdf_url(
                resource.get("file")
            )

        processed_resources.append({
            "id": resource.get("id"),
            "name": resource.get("name"),
            "description": resource.get("description"),
            "type": resource.get("type"),
            "subject_id": resource.get("subject_id"),
            "term_id": resource.get("term_id"),
            "class_id": resource.get("level_class_id"),
            "resource_type_id": resource.get("resource_type_id"),
            "file": resource.get("file"),
            "pdf_url": pdf_url,
            "downloadable": resource.get("is_downloadable"),
            "views": resource.get("count_views"),
            "created_at": resource.get("created_at")
        })

    return jsonify({
        "success": True,
        "count": len(processed_resources),
        "data": processed_resources
    })


# =========================================================
# RESOURCE TYPES
# =========================================================

@studyresource_bp.route('/api/resource-types', methods=['GET'])
@login_required
@role_required(['owner', 'teacher', 'accountant', 'student'])
def get_resource_types():
    """Get all resource types"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400

    response = post_api(
        API_ENDPOINTS["resource_types"]
    )

    resource_types = ensure_list(response)

    return jsonify({
        "success": True,
        "count": len(resource_types),
        "data": resource_types
    })


# =========================================================
# FILTER DATA
# =========================================================

@studyresource_bp.route('/api/filter-data', methods=['GET'])
@login_required
@role_required(['owner', 'teacher', 'accountant', 'student'])
def filter_data():
    """Get filter data (classes and terms)"""
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400

    classes_response = post_api(
        API_ENDPOINTS["classes"]
    )

    terms_response = post_api(
        API_ENDPOINTS["terms"]
    )

    classes = ensure_list(classes_response)
    terms = ensure_list(terms_response)

    return jsonify({
        "success": True,
        "data": {
            "classes": classes,
            "terms": terms
        }
    })


# =========================================================
# QUICK FULL FLOW
# =========================================================

@studyresource_bp.route('/api/full-lessons-flow', methods=['POST'])
@login_required
@role_required(['owner', 'teacher', 'accountant', 'student'])
def full_lessons_flow():
    """
    Complete flow: class -> subjects -> topics -> lessons
    """
    user = session.get('user')
    institute_id = get_institute_id(user['id'])
    
    if not institute_id:
        return jsonify({'success': False, 'message': 'Institute not found'}), 400

    data = request.get_json(silent=True) or {}

    class_id = data.get("class_id")
    subject_id = data.get("subject_id")
    term_id = data.get("term_id")
    topic_id = data.get("topic_id")

    response_data = {}

    # SUBJECTS
    if class_id:

        subjects_response = post_api(
            API_ENDPOINTS["subjects"],
            {
                "level_class_id": class_id
            }
        )

        response_data["subjects"] = ensure_list(
            subjects_response
        )

    # TOPICS
    if class_id and subject_id:

        topic_payload = {
            "level_class_id": class_id,
            "subject_id": subject_id
        }

        if term_id:
            topic_payload["term_id"] = term_id

        topics_response = post_api(
            API_ENDPOINTS["topics"],
            topic_payload
        )

        response_data["topics"] = ensure_list(
            topics_response
        )

    # LESSONS
    if topic_id:

        lessons_response = post_api(
            API_ENDPOINTS["lessons"],
            {
                "topic_id": topic_id
            }
        )

        lessons = ensure_list(lessons_response)

        for lesson in lessons:
            lesson["embed_url"] = extract_youtube_embed(
                lesson.get("link")
            )

        response_data["lessons"] = lessons

    return jsonify({
        "success": True,
        "data": response_data
    })