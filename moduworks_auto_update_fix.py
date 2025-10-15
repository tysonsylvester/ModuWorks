import urllib.request
import os
import re

__version__ = "1.3.1"

def auto_update():
    raw_url = "https://raw.githubusercontent.com/tysonsylvester/ModuWorks/main/ModuWorks.py"
    current_file = os.path.abspath(__file__)

    print("Checking for updates...")
    try:
        # Append timestamp to avoid caching
        url_with_ts = f"{raw_url}?t={int(time.time())}"
        with urllib.request.urlopen(url_with_ts, timeout=5) as response:
            latest_content = response.read().decode('utf-8')

        match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', latest_content, re.MULTILINE)
        if not match:
            print("Could not detect version in remote file. Update cancelled.")
            return

        latest_version = match.group(1)

        if latest_version != __version__:
            print(f"New version available: {latest_version}. Updating...")

            # Write to a temporary file first
            tmp_file = current_file + ".tmp"
            with open(tmp_file, 'w', encoding='utf-8') as f:
                f.write(latest_content)

            # Replace the current file safely
            os.replace(tmp_file, current_file)
            print("Update complete! Please restart the program.")
            exit()
        else:
            print("You are running the latest version.")

    except urllib.error.URLError as e:
        print(f"Auto-update failed: Could not reach server. Error: {e.reason}")
    except Exception as e:
        print(f"Auto-update failed: {e}")
