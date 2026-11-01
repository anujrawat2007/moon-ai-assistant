import os
import sys
import subprocess
import requests
import urllib.parse
from pathlib import Path
from PIL import Image

class PCTools:
    """
    Automated PC action engine inspired by 'browser-use' & 'Open-Interface'.
    Provides safe, lightweight desktop control, web crawling, app management,
    and messaging automation.
    """
    def __init__(self):
        self.desktop_dir = os.path.join(os.path.expanduser("~"), "Desktop")

    # -------------------------------------------------------------
    # 1. BROWSER & IMAGE CRAWLER (Inspired by browser-use / icrawler)
    # -------------------------------------------------------------
    def download_images_to_folder(self, query: str, folder_name: str = "Moon_Downloads", count: int = 5) -> str:
        """
        Crawls and downloads high-resolution images/wallpapers directly to a Desktop folder.
        Uses Wikimedia HD API for instant, reliable, and 100% free downloads.
        """
        try:
            target_folder = os.path.join(self.desktop_dir, folder_name)
            os.makedirs(target_folder, exist_ok=True)

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
            headers = {"User-Agent": "MoonAIAssistant/1.0 (Desktop companion)"}
            
            resp = requests.get(url, params=params, headers=headers, timeout=12)
            if resp.status_code != 200:
                return f"Image search error: HTTP {resp.status_code}"

            pages = resp.json().get("query", {}).get("pages", {})
            downloaded = 0

            for i, page in enumerate(pages.values()):
                img_url = page.get("imageinfo", [{}])[0].get("url")
                if not img_url:
                    continue
                try:
                    raw_data = requests.get(img_url, headers=headers, timeout=15).content
                    ext = img_url.split("?")[0].split(".")[-1].lower()
                    if ext not in ["jpg", "png", "webp", "jpeg"]:
                        ext = "jpg"
                    file_name = f"{query.replace(' ', '_')}_{i+1}.{ext}"
                    with open(os.path.join(target_folder, file_name), "wb") as f:
                        f.write(raw_data)
                    downloaded += 1
                except Exception:
                    continue

            return f"Success! {downloaded} images of '{query}' downloaded into '{target_folder}'."
        except Exception as e:
            return f"Error downloading images: {e}"

    # -------------------------------------------------------------
    # 2. SYSTEM & APPLICATION CONTROLLER (Open-Interface style)
    # -------------------------------------------------------------
    def open_application(self, app_name: str) -> str:
        """Launches desktop apps (VS Code, Notepad, Chrome, Telegram, Explorer, etc.)"""
        app_clean = app_name.lower().strip()
        cmd_map = {
            "vscode": "code",
            "vs code": "code",
            "notepad": "notepad",
            "chrome": "start chrome",
            "telegram": "start telegram",
            "calculator": "calc",
            "terminal": "start powershell",
            "explorer": "explorer",
            "task manager": "taskmgr"
        }
        cmd = cmd_map.get(app_clean, f"start {app_clean}")
        try:
            subprocess.Popen(cmd, shell=True)
            return f"Application '{app_name}' launched successfully."
        except Exception as e:
            return f"Failed to launch '{app_name}': {e}"

    def execute_command(self, powershell_command: str) -> str:
        """Executes a PowerShell command on Windows and returns stdout/stderr."""
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", powershell_command],
                capture_output=True,
                text=True,
                timeout=25
            )
            output = res.stdout or res.stderr or "Command executed successfully with no output."
            return output[:1000]
        except Exception as e:
            return f"Execution error: {e}"

    def write_code_file(self, file_path: str, code_content: str) -> str:
        """Creates or updates a programming/code file."""
        try:
            p = Path(file_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(code_content, encoding="utf-8")
            return f"Successfully saved code to: {file_path}"
        except Exception as e:
            return f"Failed to write file: {e}"

    # -------------------------------------------------------------
    # 3. MESSAGING AUTOMATION (TELEGRAM / WHATSAPP / GMAIL)
    # -------------------------------------------------------------
    def send_telegram(self, chat_id_or_user: str, message: str) -> str:
        """Sends a message via Telegram API."""
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not bot_token:
            return f"[Telegram Simulated] Delivered to '{chat_id_or_user}': '{message}' (Set TELEGRAM_BOT_TOKEN in .env for live API)."
        
        try:
            api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            resp = requests.post(api_url, json={"chat_id": chat_id_or_user, "text": message}, timeout=10)
            return "Telegram message delivered." if resp.status_code == 200 else f"Telegram API error: {resp.text}"
        except Exception as e:
            return f"Telegram error: {e}"

    def send_whatsapp(self, phone_number: str, message: str) -> str:
        """Opens WhatsApp Web with pre-drafted message."""
        try:
            encoded_msg = urllib.parse.quote(message)
            url = f"https://web.whatsapp.com/send?phone={phone_number}&text={encoded_msg}"
            subprocess.Popen(f"start {url}", shell=True)
            return f"WhatsApp opened for {phone_number} with drafted message."
        except Exception as e:
            return f"WhatsApp error: {e}"

    def send_email(self, recipient_email: str, subject: str, body: str) -> str:
        """Opens default mail client with pre-drafted email."""
        try:
            mailto_url = f"mailto:{recipient_email}?subject={urllib.parse.quote(subject)}&body={urllib.parse.quote(body)}"
            subprocess.Popen(f"start {mailto_url}", shell=True)
            return f"Email client opened for {recipient_email}."
        except Exception as e:
            return f"Email error: {e}"

if __name__ == "__main__":
    tools = PCTools()
    print("Testing PCTools image crawler...")
    res = tools.download_images_to_folder("anime scenery wallpaper", "Moon_Test_Wallpapers", 2)
    print(res)
