# entertainment.py - Entertainment Blueprint for Movies
from flask import Blueprint, render_template, request, jsonify, session
from functools import wraps
import requests
import os
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed

load_dotenv()

entertainment_bp = Blueprint('entertainment', __name__, url_prefix='/entertainment')

# API Configuration
VJLUGA_API_BASE = os.getenv('VJLUGA_API_BASE', 'https://vjluga.com/api')

def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Please login'}), 401
        return f(*args, **kwargs)
    return decorated_function

def make_api_request(url, params=None):
    """Make API request to VJLuga with error handling"""
    try:
        response = requests.get(
            url,
            params=params,
            timeout=30,
            headers={'Accept': 'application/json'}
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"API request error: {e}")
        return None

@entertainment_bp.route('/')
@login_required
def index():
    """Entertainment homepage with movies"""
    return render_template('entertainment/index.html')

@entertainment_bp.route('/movies')
@login_required
def movies():
    """Movies listing page"""
    return render_template('entertainment/movies.html')

@entertainment_bp.route('/api/movies/popular', methods=['GET'])
@login_required
def get_popular_movies():
    """Get most liked movies"""
    try:
        limit = min(int(request.args.get('limit', 50)), 100)
        page = int(request.args.get('page', 1))
        
        url = f"{VJLUGA_API_BASE}/movies/most-liked"
        data = make_api_request(url, params={'limit': limit, 'page': page})
        
        if not data:
            return jsonify({'success': False, 'message': 'Failed to fetch movies'}), 500
        
        return jsonify({
            'success': True,
            'movies': data.get('movies', []),
            'pagination': data.get('pagination', {})
        })
        
    except Exception as e:
        print(f"Error fetching popular movies: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@entertainment_bp.route('/api/movies/search', methods=['GET'])
@login_required
def search_movies():
    """Search movies by query"""
    try:
        query = request.args.get('q', '').strip()
        if not query:
            return jsonify({'success': False, 'message': 'Search term required'}), 400
        
        url = f"{VJLUGA_API_BASE}/search-suggestions"
        results = make_api_request(url, params={'q': query})
        
        if not results:
            return jsonify({'success': False, 'message': 'Search failed'}), 500
        
        # Filter only movie results
        movies = [item for item in results if item.get('type') == 'movie']
        
        return jsonify({
            'success': True,
            'movies': movies,
            'total': len(movies),
            'query': query
        })
        
    except Exception as e:
        print(f"Error searching movies: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@entertainment_bp.route('/api/movies/<movie_id>', methods=['GET'])
@login_required
def get_movie_details(movie_id):
    """Get detailed information for a specific movie"""
    try:
        # Note: Adjust endpoint if VJLuga has single movie endpoint
        # For now, search through popular movies
        url = f"{VJLUGA_API_BASE}/movies/most-liked"
        data = make_api_request(url, params={'limit': 100})
        
        if data and data.get('movies'):
            movie = next(
                (m for m in data['movies'] if m.get('id') == movie_id),
                None
            )
            if movie:
                return jsonify({'success': True, 'movie': movie})
        
        return jsonify({'success': False, 'message': 'Movie not found'}), 404
        
    except Exception as e:
        print(f"Error fetching movie details: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500