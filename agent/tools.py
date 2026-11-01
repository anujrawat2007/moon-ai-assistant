import os
import subprocess
import requests
import json
from pathlib import Path

def create_folder(folder_path: str) -> str:
    """Creates a directory if it does not exist."""
    try:
        os.makedirs(folder_path, exist_ok=True)
        return f"Successfully created folder: {folder_path}"
    except Exception as e:
        return f"Error creating folder: {e}"

def download_images(query: str, folder_name: str = "Downloaded_Images", count: int = 5) -> str:
    """
    Downloads high-resolution images matching a query (e.g., 'car') into a local folder on Desktop.
    Uses free public Wikimedia Commons HD image search - 100% free, fast, and reliable.
    """
    try:
        desktop_path = os.path.join(os.path.expanduser("~"), "Desktop", folder_name)
        os.makedirs(desktop_path, exist_ok=True)

        url = "https://commons.wikimedia.org/w/api.php"
        params = {
            "action": "query",
            "generator": "search",
            "gsrnamespace": "6",
            "gsrsearch": query,
            "gsrlimit": count,
            "prop": "imageinfo",
            "iiprop": "url",
            "format": "json"
        }
        headers = {"User-Agent": "MoonAssistant/1.0 (Desktop companion assistant)"}
        
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        if resp.status_code != 200:
            return f"Search error: HTTP {resp.status_code}"
            
        data = resp.json()
        pages = data.get("query", {}).get("pages", {})
        
        downloaded = 0
        for i, page in enumerate(pages.values()):
            img_info = page.get("imageinfo", [{}])[0]
            img_url = img_info.get("url")
            if not img_url:
                continue

            try:
                img_data = requests.get(img_url, headers=headers, timeout=15).content
                ext = img_url.split("?")[0].split(".")[-1].lower()
                if ext not in ["jpg", "jpeg", "png", "webp"]:
                    ext = "jpg"
                file_path = os.path.join(desktop_path, f"{query.replace(' ', '_')}_{i+1}.{ext}")
                with open(file_path, "wb") as f:
                    f.write(img_data)
                downloaded += 1
            except Exception as dl_err:
                print(f"[Download Error] Skipping {img_url}: {dl_err}")

        return f"Success! {downloaded} images of '{query}' saved to '{desktop_path}'."
    except Exception as e:
        return f"Failed to download images: {e}"

def open_application(app_name: str) -> str:
    """Opens a desktop application by name or executable."""
    try:
        app_map = {
            "telegram": "telegram",
            "vscode": "code",
            "chrome": "chrome",
            "notepad": "notepad",
            "calculator": "calc",
            "terminal": "powershell"
        }
        cmd = app_map.get(app_name.lower().strip(), app_name)
        subprocess.Popen(cmd, shell=True)
        return f"Application '{app_name}' launched successfully."
    except Exception as e:
        return f"Error launching application: {e}"

def run_command(command: str) -> str:
    """Executes a PowerShell command on the system and returns its output."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            timeout=30
        )
        output = result.stdout or result.stderr or "Command executed successfully with no output."
        return output[:1000]
    except Exception as e:
        return f"Execution error: {e}"

def write_code_file(file_path: str, content: str) -> str:
    """Creates or overwrites a code/text file with specified content."""
    try:
        p = Path(file_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Successfully saved code to: {file_path}"
    except Exception as e:
        return f"Failed to write file: {e}"

if __name__ == "__main__":
    print("Testing image download tool...")
    res = download_images("sports car", "Car_Photos", 3)
    print(res)
