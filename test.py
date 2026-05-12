# zlibrary_fixed.py - Fixed version with proper authentication
import requests
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import threading
import time
import os
from typing import Optional, List, Dict, Any

class ZLibraryAPI:
    def __init__(
        self,
        email: str = None,
        password: str = None,
        remix_userid: str = None,
        remix_userkey: str = None,
        domain: str = "1lib.sk",
    ):
        self.__email: str = None
        self.__name: str = None
        self.__kindle_email: str = None
        self.__remix_userid: str = None
        self.__remix_userkey: str = None
        self.__domain = domain
        self.__api_version = "eapi"
        self.__loggedin = False
        
        # Cache for API responses
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

        # Try to login if credentials provided
        if email is not None and password is not None:
            self.login(email, password)
        elif remix_userid is not None and remix_userkey is not None:
            self.loginWithToken(remix_userid, remix_userkey)
    
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
                    del self._cache[key]
                    del self._cache_ttl[key]
        return None

    def _save_to_cache(self, key, value, ttl_seconds=300):
        """Save response to cache with TTL"""
        with self._cache_lock:
            self._cache[key] = value
            self._cache_ttl[key] = datetime.now() + timedelta(seconds=ttl_seconds)

    def __setValues(self, response) -> dict:
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

    def login(self, email: str, password: str) -> dict:
        """Login with email and password"""
        result = self.__makePostRequest(
            f"/{self.__api_version}/user/login",
            data={"email": email, "password": password},
            override=True,
        )
        return self.__setValues(result)

    def loginWithToken(self, remix_userid: str, remix_userkey: str) -> dict:
        """Login using existing token"""
        result = self.__makeGetRequest(
            f"/{self.__api_version}/user/profile",
            cookies={
                "siteLanguageV2": "en",
                "remix_userid": str(remix_userid),
                "remix_userkey": remix_userkey,
            },
        )
        return self.__setValues(result)

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
            if result.get("success", False):
                self._save_to_cache(cache_key, result)
            return result
        except Exception as e:
            return {"success": False, "error": str(e)}

    def __makeGetRequest(self, url: str, params: dict = {}, cookies=None, cache_ttl=None):
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
            if result.get("success", False):
                self._save_to_cache(cache_key, result, cache_ttl)
            return result
        except Exception as e:
            return {"success": False, "error": str(e)}

    def getProfile(self) -> dict:
        """Get user profile information"""
        return self.__makeGetRequest(f"/{self.__api_version}/user/profile")

    def getMostPopular(self, switch_language: str = None, limit: int = 20) -> dict:
        """Get most popular books (requires login)"""
        params = {"limit": limit}
        if switch_language:
            params["switch-language"] = switch_language
        return self.__makeGetRequest(f"/{self.__api_version}/book/most-popular", params)

    def getRecently(self, limit: int = 20) -> dict:
        """Get recently added books (requires login)"""
        return self.__makeGetRequest(f"/{self.__api_version}/book/recently", {"limit": limit})

    def search(self, message: str = None, limit: int = 20, page: int = 1, 
               extensions: List[str] = None, year_from: int = None, 
               year_to: int = None, language: str = None) -> dict:
        """Advanced search with multiple filters (requires login)"""
        data = {
            "message": message,
            "page": page,
            "limit": min(limit, 50)
        }
        
        if extensions:
            data["extensions"] = ",".join(extensions)
        if year_from:
            data["year_from"] = year_from
        if year_to:
            data["year_to"] = year_to
        if language:
            data["language"] = language
        
        return self.__makePostRequest(f"/{self.__api_version}/book/search", data)

    def getBookInfo(self, bookid: [int, str], hashid: str = None) -> dict:
        """Get detailed book information (requires login)"""
        if hashid:
            url = f"/{self.__api_version}/book/{bookid}/{hashid}"
        else:
            url = f"/{self.__api_version}/book/{bookid}"
        
        return self.__makeGetRequest(url, cache_ttl=3600)

    def getDownloadLink(self, bookid: [int, str], hashid: str, extension: str = None) -> Optional[str]:
        """Get direct download link for a book"""
        book_info = self.getBookInfo(bookid, hashid)
        
        if not book_info.get("success"):
            return None
        
        book = book_info.get("book", {})
        
        # Check if user has downloads left
        if self.getDownloadsLeft() <= 0:
            print("No downloads left for today")
            return None
        
        # Get download links
        download_links = book.get("download_links", [])
        
        if extension:
            for link in download_links:
                if link.get("extension") == extension:
                    return link.get("url")
        elif download_links:
            return download_links[0].get("url")
        
        return None

    def downloadBook(self, bookid: [int, str], hashid: str, 
                     output_dir: str = "downloads", 
                     extension: str = None,
                     filename: str = None) -> Optional[str]:
        """Download a book directly"""
        download_url = self.getDownloadLink(bookid, hashid, extension)
        
        if not download_url:
            print("Failed to get download link")
            return None
        
        book_info = self.getBookInfo(bookid, hashid)
        book = book_info.get("book", {})
        
        if not filename:
            title = book.get("title", "unknown")
            author = book.get("author", "unknown")
            ext = extension or book.get("extension", "pdf")
            filename = f"{author} - {title}.{ext}"
            filename = "".join(c for c in filename if c.isalnum() or c in ' .-_')
        
        os.makedirs(output_dir, exist_ok=True)
        filepath = os.path.join(output_dir, filename)
        
        try:
            response = requests.get(download_url, stream=True, timeout=60)
            if response.status_code == 200:
                total_size = int(response.headers.get('content-length', 0))
                downloaded = 0
                
                with open(filepath, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total_size:
                                progress = (downloaded / total_size) * 100
                                print(f"\rDownloading: {progress:.1f}%", end='')
                
                print(f"\n✓ Downloaded: {filepath}")
                return filepath
            else:
                print(f"Download failed: {response.status_code}")
                return None
        except Exception as e:
            print(f"Download error: {e}")
            return None

    def getDownloadsLeft(self) -> int:
        """Get remaining downloads for today"""
        user_profile = self.getProfile()
        if user_profile.get("success"):
            user = user_profile.get("user", {})
            return user.get("downloads_limit", 10) - user.get("downloads_today", 0)
        return 0

    def isLoggedIn(self) -> bool:
        return self.__loggedin

    def clear_cache(self):
        """Clear all cached responses"""
        with self._cache_lock:
            self._cache.clear()
            self._cache_ttl.clear()

    def getUserInfo(self) -> dict:
        """Get user information summary"""
        profile = self.getProfile()
        if profile.get("success"):
            user = profile.get("user", {})
            return {
                "name": user.get("name"),
                "email": user.get("email"),
                "member_since": user.get("registered"),
                "downloads_today": user.get("downloads_today", 0),
                "downloads_limit": user.get("downloads_limit", 10),
                "downloads_left": self.getDownloadsLeft(),
                "favorites_count": user.get("favorites_count", 0),
            }
        return {"success": False, "error": profile.get("error")}


# Main execution with proper login first
def main():
    print("=" * 60)
    print("Z-Library API Client")
    print("=" * 60)
    
    # Get credentials
    print("\nPlease login to access the library:")
    email = input("Email: ").strip()
    password = input("Password: ").strip()
    
    # Initialize and login
    client = ZLibraryAPI(email=email, password=password)
    
    if not client.isLoggedIn():
        print("Login failed! Please check your credentials.")
        return
    
    user_info = client.getUserInfo()
    print(f"\n✓ Logged in as: {user_info.get('name')}")
    print(f"  Downloads left today: {user_info.get('downloads_left')}/{user_info.get('downloads_limit')}")
    
    # Now fetch popular books
    print("\n" + "=" * 60)
    print("1. Fetching most popular books...")
    popular = client.getMostPopular(limit=10)
    
    if popular.get("success"):
        books = popular.get("books", [])
        print(f"  Found {len(books)} popular books:")
        for i, book in enumerate(books[:10], 1):
            print(f"  {i}. {book.get('title')} by {book.get('author')}")
            print(f"     ID: {book.get('id')}, Format: {book.get('extension')}")
    else:
        print(f"  Error: {popular.get('error')}")
    
    # Search for books
    print("\n" + "=" * 60)
    search_query = input("2. Enter search term (or press Enter for 'python'): ").strip()
    if not search_query:
        search_query = "python"
    
    print(f"\nSearching for '{search_query}'...")
    results = client.search(search_query, limit=10)
    
    if results.get("success"):
        books = results.get("books", [])
        print(f"\n  Found {len(books)} results:")
        for i, book in enumerate(books[:5], 1):
            print(f"\n  {i}. {book.get('title')}")
            print(f"     Author: {book.get('author')}")
            print(f"     Year: {book.get('year', 'N/A')}")
            print(f"     Format: {book.get('extension', 'N/A')}")
            print(f"     Size: {book.get('filesize', 'N/A')}")
            print(f"     ID: {book.get('id')}")
            print(f"     Hash: {book.get('hash', 'N/A')}")
        
        # Option to download
        if books:
            print("\n" + "=" * 60)
            download_choice = input("Download a book? (y/n): ").strip().lower()
            if download_choice == 'y':
                book_num = int(input(f"Enter book number (1-{min(5, len(books))}): ").strip())
                if 1 <= book_num <= len(books):
                    book = books[book_num - 1]
                    print(f"\nDownloading: {book.get('title')}")
                    client.downloadBook(book.get("id"), book.get("hash", ""))
                else:
                    print("Invalid book number")
    else:
        print(f"  Error: {results.get('error')}")
    
    print("\n" + "=" * 60)
    print(f"Remaining downloads: {client.getDownloadsLeft()}")


if __name__ == "__main__":
    main()