from sms import Zlibrary
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class LibraryService:
    """
    ZLibrary service wrapper (optimized + aligned with API docs)
    """

    def __init__(self):
        self.Z = Zlibrary()
        self.logged_in = False
        self._init_login()

    # ---------------------------
    # LOGIN (ONLY ONCE)
    # ---------------------------
    def _init_login(self):
        try:
            self.Z.login(
                email="nserekonajib3@gmail.com",
                password="Nabirah1@"
            )
            self.logged_in = True
            logger.info("ZLibrary login successful")

        except Exception as e:
            self.logged_in = False
            logger.error(f"Login failed: {str(e)}")

    # ---------------------------
    # SEARCH BOOKS (FAST + PAGINATED)
    # ---------------------------
    def search_books(self, query: str, page: int = 1, limit: int = 50, subject: str = None) -> Dict:

        if not self.logged_in:
            return {"success": False, "books": [], "total": 0}

        try:
            search_query = self._apply_subject_filter(query, subject)

            results = self.Z.search(
                message=search_query,
                page=page,
                limit=limit
            )

            books = results.get("books", [])

            return {
                "success": True,
                "page": page,
                "limit": limit,
                "total": len(books),
                "has_more": len(books) == limit,
                "books": self._format_books(books)
            }

        except Exception as e:
            logger.error(f"Search error: {str(e)}")
            return {"success": False, "error": str(e), "books": []}

    # ---------------------------
    # GET BOOK DETAILS (CORRECT WAY)
    # ---------------------------
    def get_book(self, book_id: str, hash_id: str) -> Optional[Dict]:

        if not self.logged_in:
            return None

        try:
            return self.Z.getBookInfo(
                bookid=book_id,
                hashid=hash_id
            )

        except Exception as e:
            logger.error(f"Book fetch failed: {str(e)}")
            return None

    # ---------------------------
    # GET BOOK BY MD5
    # ---------------------------
    def get_by_md5(self, md5: str) -> Optional[Dict]:

        if not self.logged_in:
            return None

        try:
            results = self.Z.search(message="", limit=100)

            for b in results.get("books", []):
                if b.get("md5") == md5:
                    return self.get_book(b["id"], b["hash"])

            return None

        except Exception as e:
            logger.error(f"MD5 lookup failed: {str(e)}")
            return None

    # ---------------------------
    # DOWNLOAD BOOK
    # ---------------------------
    def download_book(self, book_id: str) -> Optional[Dict]:

        try:
            results = self.Z.search(message="", limit=100)

            for book in results.get("books", []):

                if str(book["id"]) == str(book_id):

                    filename, content = self.Z.downloadBook(book)

                    return {
                        "filename": filename,
                        "content": content
                    }

            return None

        except Exception as e:
            logger.error(f"Download error: {str(e)}")
            return None

    # ---------------------------
    # SUBJECT FILTER ENGINE
    # ---------------------------
    def _apply_subject_filter(self, query: str, subject: str) -> str:

        if not subject or subject == "all":
            return query

        subject_map = {
            "Mathematics": "math algebra geometry calculus",
            "Physics": "physics mechanics electricity",
            "Chemistry": "chemistry organic inorganic",
            "Biology": "biology zoology botany",
            "History": "history",
            "Geography": "geography",
            "Business Studies": "accounting business commerce economics",
            "Computer Science": "python programming coding software"
        }

        keywords = subject_map.get(subject, "")

        return f"{query} {keywords}".strip()

    # ---------------------------
    # FORMAT BOOKS
    # ---------------------------
    def _format_books(self, books: List[Dict]) -> List[Dict]:

        return [
            {
                "id": b.get("id"),
                "title": b.get("title"),
                "author": b.get("author"),
                "year": b.get("year"),
                "cover": b.get("cover"),
                "format": b.get("extension"),
                "size": b.get("filesizeString"),
                "md5": b.get("md5"),
                "hash": b.get("hash"),
            }
            for b in books
        ]