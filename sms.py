# sms.py - Optimized Z-Library Client with Caching and Parallel Requests
import requests
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from datetime import datetime, timedelta
import threading

class Zlibrary:
    def __init__(
        self,
        email: str = None,
        password: str = None,
        remix_userid: [int, str] = None,
        remix_userkey: str = None,
    ):
        self.__email: str = None
        self.__name: str = None
        self.__kindle_email: str = None
        self.__remix_userid: [int, str] = None
        self.__remix_userkey: str = None
        self.__domain = "1lib.sk"
        self.__api_version = "eapi"
        self.__loggedin = False
        
        # Cache for API responses (5 minute TTL)
        self._cache = {}
        self._cache_ttl = {}
        self._cache_lock = threading.Lock()
        
        self.__headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "accept": "application/json, text/plain, */*",
            "accept-language": "en-US,en;q=0.9",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "x-requested-with": "XMLHttpRequest"
        }
        self.__cookies = {
            "siteLanguageV2": "en",
        }

        if email is not None and password is not None:
            self.login(email, password)
        elif remix_userid is not None and remix_userkey is not None:
            self.loginWithToken(remix_userid, remix_userkey)
        
        # Thread pool for parallel requests
        self._executor = ThreadPoolExecutor(max_workers=10)

    def _get_cache_key(self, url, params=None, data=None):
        """Generate cache key for request"""
        key = url
        if params:
            key += str(sorted(params.items()))
        if data:
            key += str(sorted(data.items()))
        return key

    def _get_from_cache(self, key):
        """Get cached response if still valid"""
        with self._cache_lock:
            if key in self._cache and key in self._cache_ttl:
                if datetime.now() < self._cache_ttl[key]:
                    return self._cache[key]
                else:
                    # Remove expired
                    del self._cache[key]
                    del self._cache_ttl[key]
        return None

    def _save_to_cache(self, key, value, ttl_seconds=300):
        """Save response to cache with TTL"""
        with self._cache_lock:
            self._cache[key] = value
            self._cache_ttl[key] = datetime.now() + timedelta(seconds=ttl_seconds)

    def __setValues(self, response) -> dict[str, str]:
        if not response.get("success", False):
            return response
        self.__email = response["user"]["email"]
        self.__name = response["user"]["name"]
        self.__kindle_email = response["user"].get("kindle_email")
        self.__remix_userid = str(response["user"]["id"])
        self.__remix_userkey = response["user"]["remix_userkey"]
        self.__cookies["remix_userid"] = self.__remix_userid
        self.__cookies["remix_userkey"] = self.__remix_userkey
        self.__loggedin = True
        return response

    def __login(self, email, password) -> dict[str, str]:
        return self.__setValues(
            self.__makePostRequest(
                f"/{self.__api_version}/user/login",
                data={"email": email, "password": password},
                override=True,
            )
        )

    def __checkIDandKey(self, remix_userid, remix_userkey) -> dict[str, str]:
        return self.__setValues(
            self.__makeGetRequest(
                f"/{self.__api_version}/user/profile",
                cookies={
                    "siteLanguageV2": "en",
                    "remix_userid": str(remix_userid),
                    "remix_userkey": remix_userkey,
                },
            )
        )

    def login(self, email: str, password: str) -> dict[str, str]:
        return self.__login(email, password)

    def loginWithToken(self, remix_userid: [int, str], remix_userkey: str) -> dict[str, str]:
        return self.__checkIDandKey(remix_userid, remix_userkey)

    def __makePostRequest(self, url: str, data: dict = {}, override=False):
        if not self.isLoggedIn() and override is False:
            return {"success": False, "error": "Not logged in"}

        cache_key = self._get_cache_key(url, data=data)
        cached = self._get_from_cache(cache_key)
        if cached:
            return cached

        try:
            response = requests.post(
                "https://" + self.__domain + url,
                data=data,
                cookies=self.__cookies,
                headers=self.__headers,
                timeout=30
            )
            result = response.json()
            # Cache successful GET requests
            if result.get("success", False):
                self._save_to_cache(cache_key, result, 300)
            return result
        except Exception as e:
            return {"success": False, "error": str(e)}

    def __makeGetRequest(self, url: str, params: dict = {}, cookies=None):
        if not self.isLoggedIn() and cookies is None:
            return {"success": False, "error": "Not logged in"}

        cache_key = self._get_cache_key(url, params=params)
        cached = self._get_from_cache(cache_key)
        if cached:
            return cached

        try:
            response = requests.get(
                "https://" + self.__domain + url,
                params=params,
                cookies=self.__cookies if cookies is None else cookies,
                headers=self.__headers,
                timeout=30
            )
            result = response.json()
            # Cache successful GET requests
            if result.get("success", False):
                self._save_to_cache(cache_key, result, 300)
            return result
        except Exception as e:
            return {"success": False, "error": str(e)}

    def getProfile(self) -> dict[str, str]:
        return self.__makeGetRequest(f"/{self.__api_version}/user/profile")

    def getMostPopular(self, switch_language: str = None, limit: int = 20) -> dict[str, str]:
        """Get most popular books with limit"""
        params = {"limit": limit}
        if switch_language:
            params["switch-language"] = switch_language
        return self.__makeGetRequest(f"/{self.__api_version}/book/most-popular", params)

    def getRecently(self, limit: int = 20) -> dict[str, str]:
        return self.__makeGetRequest(f"/{self.__api_version}/book/recently", {"limit": limit})

    def getUserRecommended(self, limit: int = 20) -> dict[str, str]:
        return self.__makeGetRequest(f"/{self.__api_version}/user/book/recommended", {"limit": limit})

    def getBookInfo(self, bookid: [int, str], hashid: str, switch_language: str = None) -> dict[str, str]:
        """Get book information - CACHED for 1 hour"""
        cache_key = f"book_{bookid}_{hashid}"
        cached = self._get_from_cache(cache_key)
        if cached:
            return cached
        
        params = {}
        if switch_language:
            params["switch-language"] = switch_language
        
        result = self.__makeGetRequest(f"/{self.__api_version}/book/{bookid}/{hashid}", params)
        if result.get("success", False):
            self._save_to_cache(cache_key, result, 3600)  # Cache for 1 hour
        return result

    def search(self, message: str = None, limit: int = 20, page: int = 1) -> dict[str, str]:
        """Optimized search with fewer parameters"""
        return self.__makePostRequest(
            f"/{self.__api_version}/book/search",
            {
                "message": message,
                "page": page,
                "limit": min(limit, 50)
            },
        )

    def search_batch(self, queries: list, limit: int = 10) -> list:
        """Search multiple queries in parallel"""
        results = []
        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_query = {
                executor.submit(self.search, query, limit): query 
                for query in queries
            }
            for future in as_completed(future_to_query):
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    results.append({"success": False, "error": str(e)})
        return results

    def get_books_batch(self, books_info: list) -> list:
        """Get multiple books information in parallel"""
        results = []
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_book = {
                executor.submit(
                    self.getBookInfo, 
                    book["id"], 
                    book.get("hash", "")
                ): book for book in books_info
            }
            for future in as_completed(future_to_book):
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    results.append({"success": False, "error": str(e)})
        return results

    def isLoggedIn(self) -> bool:
        return self.__loggedin

    def clear_cache(self):
        """Clear all cached responses"""
        with self._cache_lock:
            self._cache.clear()
            self._cache_ttl.clear()

    def getDownloadsLeft(self) -> int:
        """Get remaining downloads for today"""
        user_profile = self.getProfile()
        if user_profile.get("success"):
            user = user_profile.get("user", {})
            return user.get("downloads_limit", 10) - user.get("downloads_today", 0)
        return 0
    
    # Add these methods to your sms.py Zlibrary class for even better performance

    def get_books_batch_optimized(self, books: list) -> dict:
        """Get multiple books information in parallel with optimized batching"""
        if not books:
            return {}
        
        results = {}
        batch_size = 20  # Process in batches to avoid overwhelming
        
        with ThreadPoolExecutor(max_workers=20) as executor:
            for i in range(0, len(books), batch_size):
                batch = books[i:i+batch_size]
                futures = {}
                
                for book in batch:
                    future = executor.submit(
                        self.getBookInfo, 
                        book.get('id'), 
                        book.get('hash', '')
                    )
                    futures[future] = book.get('id')
                
                for future in as_completed(futures):
                    book_id = futures[future]
                    try:
                        results[book_id] = future.result()
                    except Exception as e:
                        results[book_id] = {"success": False, "error": str(e)}
        
        return results

    def prefetch_popular_books(self, limit: int = 50):
        """Prefetch popular books and cache them"""
        cache_key = "popular_books_prefetch"
        cached = self._get_from_cache(cache_key)
        if cached:
            return cached
        
        popular = self.getMostPopular(limit=limit)
        if popular.get('success'):
            books = popular.get('books', [])
            # Prefetch details for popular books
            self.get_books_batch_optimized(books)
            self._save_to_cache(cache_key, popular, 3600)  # Cache for 1 hour
        
        return popular