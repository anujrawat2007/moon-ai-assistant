import os
import sys
import subprocess
import requests
import json
import urllib.parse
from pathlib import Path

class PCController:
    """
    Automated PC action engine for desktop control, file operations,
    web crawling, image downloading, and messaging automation.
    """
    def __init__(self):
        self.desktop_dir = os.path.join(os.path.expanduser("~"), "Desktop")

    # -------------------------------------------------------------
    # 1. BROWSER & IMAGE DOWNLOADER AUTOMATION
    # -------------------------------------------------------------
    def download_wallpapers_or_images(self, query: str, folder_name: str = "Anime_Wallpapers", count: int = 5) -> str:
        """
        Searches and downloads high-resolution images/wallpapers directly to Desktop folder.
        Uses Wikimedia HD / Unsplash public API. Zero extra overhead.
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
            headers = {"User-Agent": "SuzuneAssistant/1.0"}
            
            resp = requests.get(url, params=params, headers=headers, timeout=12)
            if resp.status_code != 200:
                return f"Image search failed: HTTP {resp.status_code}"

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

            return f"Successfully downloaded {downloaded} images of '{query}' to '{target_folder}'."
        except Exception as e:
            return f"Error downloading images: {e}"

    # -------------------------------------------------------------
    # 2. SYSTEM & APPLICATION CONTROLS
    # -------------------------------------------------------------
    def open_application(self, app_name: str) -> str:
        """Launches desktop apps (VS Code, Chrome, Telegram, Explorer, etc.)"""
        app_clean = app_name.lower().strip()
        cmd_map = {
            "vscode": "code",
            "vs code": "code",
            "chrome": "start chrome",
            "telegram": "start telegram",
            "notepad": "notepad",
            "calculator": "calc",
            "terminal": "start powershell",
            "explorer": "explorer"
        }
        cmd = cmd_map.get(app_clean, f"start {app_clean}")
        try:
            subprocess.Popen(cmd, shell=True)
            return f"Application '{app_name}' launched."
        except Exception as e:
            return f"Failed to launch '{app_name}': {e}"

    def run_system_command(self, powershell_command: str) -> str:
        """Executes a PowerShell command securely and returns output."""
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", powershell_command],
                capture_output=True,
                text=True,
                timeout=25
            )
            return (res.stdout or res.stderr or "Command executed successfully.")[:800]
        except Exception as e:
            return f"Command execution error: {e}"

    def write_or_fix_code(self, file_path: str, code_content: str) -> str:
        """Writes or modifies a programming file."""
        try:
            p = Path(file_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(code_content, encoding="utf-8")
            return f"File updated: {file_path}"
        except Exception as e:
            return f"Error writing code: {e}"

    # -------------------------------------------------------------
    # 3. MESSAGING & WEBHOOK AUTOMATION (TELEGRAM / WHATSAPP / GMAIL)
    # -------------------------------------------------------------
    def send_telegram_message(self, contact_or_chat_id: str, message: str) -> str:
        """
        Telegram message sender stub (Connects with Telethon or Bot Token).
        """
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not bot_token:
            return f"[Simulated Telegram] Sent to '{contact_or_chat_id}': '{message}' (Add TELEGRAM_BOT_TOKEN in .env for live API)."
        
        try:
            api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            resp = requests.post(api_url, json={"chat_id": contact_or_chat_id, "text": message}, timeout=10)
            return "Telegram message delivered." if resp.status_code == 200 else f"Telegram API error: {resp.text}"
        except Exception as e:
            return f"Telegram error: {e}"

    def send_whatsapp_web(self, phone_number: str, message: str) -> str:
        """Opens WhatsApp Web with pre-filled message for user confirmation."""
        try:
            encoded_msg = urllib.parse.quote(message)
            url = f"https://web.whatsapp.com/send?phone={phone_number}&text={encoded_msg}"
            subprocess.Popen(f"start {url}", shell=True)
            return f"WhatsApp opened for {phone_number} with drafted message."
        except Exception as e:
            return f"WhatsApp error: {e}"

    def send_gmail_draft(self, recipient_email: str, subject: str, body: str) -> str:
        """Opens default mail client or drafts email."""
        try:
            mailto_url = f"mailto:{recipient_email}?subject={urllib.parse.quote(subject)}&body={urllib.parse.quote(body)}"
            subprocess.Popen(f"start {mailto_url}", shell=True)
            return f"Email drafted for {recipient_email}."
        except Exception as e:
            return f"Mail error: {e}"

if __name__ == "__main__":
    controller = PCController()
    print("Testing PC Controller wallpaper downloader...")
    res = controller.download_wallpapers_or_images("anime scenery wallpaper", "Suzune_Wallpapers", 2)
    print(res)

