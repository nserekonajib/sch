# library.py - Optimized International Library Blueprint
from flask import Blueprint, render_template, request, jsonify, session
from sms import Zlibrary
import random
from functools import wraps
import os
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

load_dotenv()

library_bp = Blueprint('library', __name__, url_prefix='/library')

# Z-Library credentials from environment variables
ZLIBRARY_EMAIL = os.getenv('ZLIBRARY_EMAIL', 'nserekonajib3@gmail.com')
ZLIBRARY_PASSWORD = os.getenv('ZLIBRARY_PASSWORD', 'Nabirah1@')

# Global Z-Library instance with thread safety
_zlib_instance = None
_zlib_lock = threading.Lock()

def get_zlibrary_instance():
    """Get singleton authenticated Z-Library instance"""
    global _zlib_instance
    if _zlib_instance is None:
        with _zlib_lock:
            if _zlib_instance is None:
                try:
                    Z = Zlibrary()
                    Z.login(
                        email=ZLIBRARY_EMAIL,
                        password=ZLIBRARY_PASSWORD
                    )
                    _zlib_instance = Z
                except Exception as e:
                    print(f"Error authenticating with Z-Library: {e}")
                    return None
    return _zlib_instance

def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': 'Please login'}), 401
        return f(*args, **kwargs)
    return decorated_function

@library_bp.route('/')
@login_required
def index():
    """Library Search Page"""
    return render_template('library/index.html')

@library_bp.route('/api/search', methods=['POST'])
@login_required
def search_books():
    """Search for books via Z-Library API"""
    try:
        data = request.get_json()
        query = data.get('query', '').strip()
        limit = min(int(data.get('limit', 20)), 50)
        
        if not query:
            return jsonify({'success': False, 'message': 'Please enter a search term'}), 400
        
        Z = get_zlibrary_instance()
        if not Z:
            return jsonify({'success': False, 'message': 'Unable to connect to library service'}), 500
        
        # Search for books
        results = Z.search(message=query, limit=limit)
        
        if not results or not results.get('books'):
            return jsonify({'success': True, 'books': [], 'total': 0, 'message': 'No books found'})
        
        # Batch fetch book details in parallel
        books_info = results.get('books', [])
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {}
            for book in books_info:
                future = executor.submit(
                    Z.getBookInfo, 
                    book.get('id'), 
                    book.get('hash', '')
                )
                futures[future] = book
            
            formatted_books = []
            base_url = "https://1lib.sk"
            
            for future in as_completed(futures):
                book = futures[future]
                try:
                    details = future.result()
                    full_details = details.get('book', {}) if details else {}
                except:
                    full_details = {}
                
                download_link = f"{base_url}{book.get('dl', '')}" if book.get('dl') else None
                
                formatted_books.append({
                    'id': book.get('id'),
                    'title': book.get('title', 'Unknown Title'),
                    'author': book.get('author', 'Unknown Author'),
                    'year': book.get('year', 'N/A'),
                    'publisher': book.get('publisher', 'N/A'),
                    'language': book.get('language', 'N/A'),
                    'pages': book.get('pages', 'N/A'),
                    'extension': book.get('extension', 'pdf'),
                    'file_size': book.get('filesizeString', 'N/A'),
                    'cover_url': book.get('cover', ''),
                    'description': full_details.get('description', book.get('description', 'No description available')),
                    'download_link': download_link,
                    'read_online_url': book.get('readOnlineUrl', ''),
                    'md5': book.get('md5', ''),
                    'sha256': book.get('sha256', '')
                })
        
        return jsonify({
            'success': True,
            'books': formatted_books,
            'total': len(formatted_books),
            'query': query
        })
        
    except Exception as e:
        print(f"Error searching books: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@library_bp.route('/api/random-books', methods=['GET'])
@login_required
def get_random_books():
    """Get random educational books for initial display - OPTIMIZED with parallel requests"""
    try:
        limit = min(int(request.args.get('limit', 20)), 50)
        
        # Educational subjects list
        subjects = [
            "mathematics textbook", "physics textbook", "chemistry textbook", 
            "biology textbook", "english grammar", "computer science",
            "programming", "data science", "artificial intelligence",
            "history", "geography", "economics", "business management",
            "psychology", "philosophy", "sociology", "law textbook",
            "medicine textbook", "engineering textbook", "architecture"
        ]
        
        Z = get_zlibrary_instance()
        if not Z:
            return jsonify({'success': False, 'message': 'Unable to connect to library service'}), 500
        
        # Calculate how many queries we need (aim for ~3x limit to account for duplicates)
        num_queries = min((limit // 10) + 3, len(subjects))
        selected_queries = random.sample(subjects, num_queries)
        
        # Search all queries in parallel
        with ThreadPoolExecutor(max_workers=10) as search_executor:
            search_futures = {
                search_executor.submit(Z.search, query, 15): query 
                for query in selected_queries
            }
            
            # Collect all books from all searches
            all_books = []
            seen_ids = set()
            
            for future in as_completed(search_futures):
                try:
                    results = future.result()
                    books = results.get('books', [])
                    
                    for book in books:
                        book_id = book.get('id')
                        if book_id and book_id not in seen_ids:
                            seen_ids.add(book_id)
                            all_books.append(book)
                            
                            if len(all_books) >= limit * 2:  # Get extra for filtering
                                break
                except Exception as e:
                    print(f"Search error: {e}")
                
                if len(all_books) >= limit * 2:
                    break
        
        # Take only needed amount
        all_books = all_books[:min(len(all_books), limit * 2)]
        
        if not all_books:
            return jsonify({'success': True, 'books': [], 'total': 0})
        
        # Batch fetch book details in parallel
        base_url = "https://1lib.sk"
        formatted_books = []
        
        with ThreadPoolExecutor(max_workers=20) as details_executor:
            future_to_book = {}
            for book in all_books:
                future = details_executor.submit(
                    Z.getBookInfo, 
                    book.get('id'), 
                    book.get('hash', '')
                )
                future_to_book[future] = book
            
            for future in as_completed(future_to_book):
                book = future_to_book[future]
                try:
                    details = future.result()
                    full_details = details.get('book', {}) if details else {}
                    
                    download_link = f"{base_url}{book.get('dl', '')}" if book.get('dl') else None
                    
                    formatted_books.append({
                        'id': book.get('id'),
                        'title': book.get('title', 'Unknown Title'),
                        'author': book.get('author', 'Unknown Author'),
                        'year': book.get('year', 'N/A'),
                        'publisher': book.get('publisher', 'N/A'),
                        'language': book.get('language', 'N/A'),
                        'pages': book.get('pages', 'N/A'),
                        'extension': book.get('extension', 'pdf'),
                        'file_size': book.get('filesizeString', 'N/A'),
                        'cover_url': book.get('cover', ''),
                        'description': full_details.get('description', book.get('description', 'No description available')),
                        'download_link': download_link,
                        'read_online_url': book.get('readOnlineUrl', ''),
                        'md5': book.get('md5', ''),
                        'sha256': book.get('sha256', '')
                    })
                    
                    if len(formatted_books) >= limit:
                        break
                        
                except Exception as e:
                    print(f"Error processing book: {e}")
                    continue
        
        # Shuffle for variety
        random.shuffle(formatted_books)
        formatted_books = formatted_books[:limit]
        
        return jsonify({
            'success': True,
            'books': formatted_books,
            'total': len(formatted_books)
        })
        
    except Exception as e:
        print(f"Error getting random books: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500