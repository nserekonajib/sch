import requests
import re
import time
from bs4 import BeautifulSoup

def download_up4ever_file(url, output_filename=None):
    """
    Attempt to download a file from up-4ever.net.
    This handles the initial page request to extract the real download link.
    """
    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    print(f"[*] Requesting page: {url}")
    resp = session.get(url, headers=headers)
    if resp.status_code != 200:
        print(f"[-] Failed to get page. Status: {resp.status_code}")
        return False

    soup = BeautifulSoup(resp.text, "html.parser")

    # Look for the direct download link (often in a button or anchor tag)
    # Up-4ever sometimes places it in a `<a>` tag with specific classes or a JavaScript `onclick`.
    download_link = None

    # Method 1: Find any link containing the filename or .apk
    for link in soup.find_all("a", href=True):
        if ".apk" in link["href"] or "download" in link["href"].lower():
            download_link = link["href"]
            break

    # Method 2: Look for a form or button that triggers download
    if not download_link:
        # Some sites require parsing a script to find `window.location` or similar
        script_tags = soup.find_all("script")
        for script in script_tags:
            if script.string:
                match = re.search(r"(https?://[^\s\"']+\.apk[^\s\"']*)", script.string)
                if match:
                    download_link = match.group(1)
                    break

    if not download_link:
        print("[-] Could not find download link. The site may have anti-bot protection.")
        print("[*] Try opening the URL in a browser and copying the final .apk link manually.")
        return False

    # Resolve relative URLs
    if download_link.startswith("/"):
        from urllib.parse import urljoin
        download_link = urljoin(url, download_link)

    print(f"[*] Found download link: {download_link}")

    # Handle potential countdown/wait page
    wait_time = 0
    wait_text = soup.find(text=re.compile(r"wait|second|minute", re.I))
    if wait_text:
        # Try to extract numeric wait time (e.g., "wait 30 seconds")
        match = re.search(r"(\d+)\s*(second|minute)", wait_text, re.I)
        if match:
            wait_time = int(match.group(1))
            if "minute" in match.group(2).lower():
                wait_time *= 60
            print(f"[*] Waiting {wait_time} seconds as required by host...")
            time.sleep(wait_time)

    # Perform the actual download
    if not output_filename:
        output_filename = "Munowatch_3.3_Mod_Rolling_Mod.apk"

    print(f"[*] Downloading to {output_filename}")
    download_resp = session.get(download_link, headers=headers, stream=True)
    if download_resp.status_code == 200:
        with open(output_filename, "wb") as f:
            for chunk in download_resp.iter_content(chunk_size=8192):
                f.write(chunk)
        print(f"[+] Download complete: {output_filename}")
        return True
    else:
        print(f"[-] Download failed. Status: {download_resp.status_code}")
        return False


if __name__ == "__main__":
    # The URL you provided
    file_url = "https://www.up-4ever.net/y2m63oy8vdtx"
    download_up4ever_file(file_url)