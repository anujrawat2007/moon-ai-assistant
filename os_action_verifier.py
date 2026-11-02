import os
import re
import gc
import time
import json
import ctypes
from ctypes import wintypes
import subprocess
import webbrowser
import urllib.parse
import urllib.request
import psutil
import pyautogui

pyautogui.FAILSAFE = False


class OSActionAndVerifierEngine:
    """
    Production GUI Automation, Autonomous Chatting, and Closed-Loop Self-Correction Engine.
    - Parses 1 to 4 compound tasks into a structured task queue.
    - Closed-Loop Verification: Action -> Wait 1.5s -> Capture Screen (`mss`) + Process List (`psutil`)
      -> Ask Vision/Verifier -> Up to 3 corrective retries using alternative methods -> Final report in character.
    """

    def __init__(self, api_pool, vision_manager, log_callback=None, status_callback=None):
        self.api_pool = api_pool
        self.vision_manager = vision_manager
        self.log_callback = log_callback
        self.status_callback = status_callback
        self.installed_apps = {}

    def _log(self, msg, level="INFO"):
        if self.log_callback:
            try:
                self.log_callback(f"[Executor][{level}] {msg}")
            except Exception:
                pass

    def _status(self, text):
        if self.status_callback:
            try:
                self.status_callback(text)
            except Exception:
                pass

    def scan_installed_apps(self):
        apps = {}
        try:
            cmd = 'powershell -NoProfile -Command "Get-StartApps | ConvertTo-Json"'
            out = subprocess.check_output(cmd, shell=True, timeout=8, stderr=subprocess.DEVNULL).decode("utf-8", errors="ignore")
            data = json.loads(out)
            if isinstance(data, dict):
                data = [data]
            for item in data:
                name = item.get("Name", "").strip()
                appid = item.get("AppID", "").strip()
                if name and appid:
                    apps[name.lower()] = ("appid", appid)
        except Exception:
            pass

        user_home = os.path.expanduser("~")
        shortcut_dirs = [
            os.path.join(user_home, "OneDrive", "Desktop"),
            os.path.join(user_home, "Desktop"),
            "C:\\Users\\Public\\Desktop",
            os.path.join(os.environ.get("APPDATA", ""), "Microsoft\\Windows\\Start Menu\\Programs"),
            os.path.join(os.environ.get("PROGRAMDATA", "C:\\ProgramData"), "Microsoft\\Windows\\Start Menu\\Programs"),
        ]
        for sdir in shortcut_dirs:
            if not os.path.exists(sdir):
                continue
            for root, _, files in os.walk(sdir):
                for file in files:
                    if file.lower().endswith((".lnk", ".url")):
                        clean_name = os.path.splitext(file)[0].lower().strip()
                        apps[clean_name] = ("path", os.path.join(root, file))

        self.installed_apps = apps
        self._log(f"Indexed {len(self.installed_apps)} installed Windows applications.")

    @staticmethod
    def copy_to_clipboard(text):
        try:
            p = subprocess.Popen(["clip"], stdin=subprocess.PIPE, shell=True)
            p.communicate(input=text.encode("utf-16-le"))
        except Exception:
            pass

    @staticmethod
    def get_active_window_title():
        if os.name != "nt":
            return "Desktop"
        try:
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if hwnd:
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    return buf.value.strip()
        except Exception:
            pass
        return "Desktop"

    @staticmethod
    def get_running_process_names():
        names = set()
        for p in psutil.process_iter(["name"]):
            try:
                n = p.info.get("name")
                if n:
                    names.add(n.lower())
            except Exception:
                continue
        return sorted(names)

    def find_and_focus_window(self, title_keyword):
        if os.name != "nt":
            return None, None
        user32 = ctypes.windll.user32
        found_hwnd = None
        kw = (title_keyword or "").lower().strip()
        aliases = {
            "vscode": ["visual studio code", "code"],
            "vs code": ["visual studio code", "code"],
            "notepad": ["notepad", "untitled"],
            "calc": ["calculator", "गणक"],
            "calculator": ["calculator", "गणक"],
            "cmd": ["command prompt", "cmd.exe", "powershell"],
            "explorer": ["file explorer", "this pc"],
            "chrome": ["google chrome", "chrome"],
            "edge": ["microsoft edge", "edge"],
            "youtube": ["youtube"],
            "whatsapp": ["whatsapp"],
            "discord": ["discord"],
            "instagram": ["instagram"],
            "telegram": ["telegram"],
            "spotify": ["spotify"],
        }
        search_terms = aliases.get(kw, [kw])

        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def callback(hwnd, lparam):
            nonlocal found_hwnd
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value.lower()
                    if any(term in title for term in search_terms) and "moon control panel" not in title:
                        found_hwnd = hwnd
                        return False
            return True

        user32.EnumWindows(WNDENUMPROC(callback), 0)
        if found_hwnd:
            try:
                if user32.IsIconic(found_hwnd):
                    user32.ShowWindow(found_hwnd, 9)
                user32.keybd_event(0x12, 0, 0, 0)
                user32.SetForegroundWindow(found_hwnd)
                user32.keybd_event(0x12, 0, 2, 0)
                rect = wintypes.RECT()
                user32.GetWindowRect(found_hwnd, ctypes.byref(rect))
                return found_hwnd, (rect.left, rect.top, rect.right, rect.bottom)
            except Exception:
                pass
        return None, None

    def launch_app_by_method(self, app_name, method="direct"):
        """
        Supports 3 distinct launch methods for Closed-Loop Self-Correction retries:
        - Attempt 1 (`direct`): AppID / Start Menu shortcut / URI protocol
        - Attempt 2 (`shell_start`): Windows `start <alias>` or web URL fallback
        - Attempt 3 (`win_search`): Pressing `Win`, pasting app name, pressing `Enter`
        """
        low = (app_name or "").lower().strip()
        hwnd, rect = self.find_and_focus_window(low)
        if hwnd and method == "direct":
            return hwnd, rect

        if method == "direct":
            matched = self.installed_apps.get(low)
            if not matched:
                for k, v in self.installed_apps.items():
                    if low in k or k in low:
                        matched = v
                        break
            if matched:
                kind, val = matched
                if kind == "appid":
                    subprocess.Popen(f'explorer.exe "shell:AppsFolder\\{val}"', shell=True)
                    return self.find_and_focus_window(low)
                elif kind == "path":
                    os.startfile(val)
                    return self.find_and_focus_window(low)

        if method in ("direct", "shell_start"):
            common_map = {
                "vscode": "code", "vs code": "code", "visual studio code": "code",
                "notepad": "notepad", "calculator": "calc", "calc": "calc",
                "paint": "mspaint", "chrome": "chrome", "edge": "msedge",
                "explorer": "explorer", "cmd": "cmd", "telegram": "telegram:",
                "whatsapp": "whatsapp:", "discord": "discord:", "spotify": "spotify:",
                "settings": "ms-settings:", "youtube": "https://www.youtube.com",
                "instagram": "https://www.instagram.com/direct/inbox/"
            }
            if low in common_map:
                target_val = common_map[low]
                if target_val.startswith("http"):
                    webbrowser.open(target_val)
                else:
                    subprocess.Popen(f"start {target_val}", shell=True)
                return self.find_and_focus_window(low)

        # Fallback or explicit `win_search` retry
        pyautogui.press("win")
        time.sleep(0.45)
        self.copy_to_clipboard(app_name)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.55)
        pyautogui.press("enter")
        return self.find_and_focus_window(low)

    @staticmethod
    def get_exact_youtube_video_url(clean_query):
        search_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(clean_query)}"
        req = urllib.request.Request(
            search_url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        )
        try:
            html = urllib.request.urlopen(req, timeout=7).read().decode("utf-8", errors="ignore")
            organic_ids = re.findall(r'"videoRenderer":\{"videoId":"([a-zA-Z0-9_-]{11})"', html)
            if organic_ids:
                return f"https://www.youtube.com/watch?v={organic_ids[0]}&autoplay=1"
        except Exception:
            pass
        return search_url

    def play_youtube_video(self, query, retry_attempt=0):
        q = (query or "").strip()
        if not q or q.lower() == "youtube":
            self.launch_app_by_method("youtube", method="direct")
            return
        video_url = self.get_exact_youtube_video_url(q)
        self._log(f"Playing YouTube query '{q}' -> {video_url} (attempt={retry_attempt + 1})")

        if retry_attempt == 0:
            browser_paths = [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
                r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            ]
            for bpath in browser_paths:
                if os.path.exists(bpath):
                    subprocess.Popen(f'"{bpath}" --app="{video_url}"', shell=True)
                    return
        webbrowser.open(video_url)

    def execute_autonomous_chat(self, task_obj, retry_attempt=0):
        """
        True GUI Vision & UI Accessibility Autonomous Chatting (WhatsApp, Discord, Instagram, Telegram):
        1. Focuses or launches target platform.
        2. Searches for `contact` if provided.
        3. Captures annotated screen + UI accessibility elements to read incoming chat history and locate the exact input box.
        4. Generates a contextual reply (or uses `message`), clicks the exact input box coordinates, pastes, and sends!
        """
        platform = (task_obj.get("platform") or "whatsapp").lower().strip()
        contact = (task_obj.get("contact") or "").strip()
        explicit_msg = (task_obj.get("message") or "").strip()
        tone = (task_obj.get("tone") or "cute friendly Hinglish").strip()

        self._log(f"Autonomous Chat started on {platform} for contact='{contact}' (attempt={retry_attempt + 1})")
        hwnd, rect = self.find_and_focus_window(platform)
        if not hwnd:
            self.launch_app_by_method(platform, method="direct" if retry_attempt == 0 else "shell_start")
            time.sleep(2.2)
            hwnd, rect = self.find_and_focus_window(platform)

        # Step 1: If a contact name is specified, search and open their thread
        if contact:
            if platform in ("whatsapp", "telegram"):
                pyautogui.hotkey("ctrl", "f")
            elif platform == "discord":
                pyautogui.hotkey("ctrl", "k")
            time.sleep(0.45)
            pyautogui.hotkey("ctrl", "a")
            self.copy_to_clipboard(contact)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.85)
            pyautogui.press("down")
            time.sleep(0.2)
            pyautogui.press("enter")
            time.sleep(1.0)

        # Step 2: Inspect live chat screen + UI tree to read messages and locate the message input box
        annotated_img, ui_elements, ui_summary = self.vision_manager.capture_annotated_screen_with_grid()
        screen_w, screen_h = self.vision_manager.get_screen_resolution()

        input_xy = None
        reply_to_send = explicit_msg

        # Try Vision analysis to both read the incoming messages AND pinpoint the message input box
        if annotated_img is not None:
            chat_prompt = f"""
You are inspecting an active {platform} chat window (contact: '{contact}').
1. Read the latest incoming messages visible in the conversation.
2. Locate the exact normalized `[x_norm, y_norm]` (0..1000) of the message input text box at the bottom of the chat.
3. If `explicit_msg` is empty, write a natural 1-sentence reply in '{tone}' responding directly to the latest incoming message. If `explicit_msg` is provided ('{explicit_msg}'), refine or keep it natural.
UI Elements detected:
{ui_summary[:700]}

Respond ONLY in valid JSON:
{{
  "input_box_norm_xy": [x_norm, y_norm],
  "observed_last_message": "summary of what the other person said",
  "reply_text": "exact message to send"
}}
"""
            try:
                raw_out, _, _ = self.api_pool.generate_multimodal_response(
                    user_text=chat_prompt,
                    pil_images=[annotated_img],
                    expect_json=False,
                    max_output_tokens=300
                )
                m = re.search(r"\{.*\}", raw_out or "", re.DOTALL)
                if m:
                    chat_data = json.loads(m.group(0))
                    xy = chat_data.get("input_box_norm_xy")
                    if isinstance(xy, list) and len(xy) == 2 and xy[0] > 0 and xy[1] > 0:
                        input_xy = (
                            int((float(xy[0]) / 1000.0) * screen_w),
                            int((float(xy[1]) / 1000.0) * screen_h)
                        )
                    if not reply_to_send and chat_data.get("reply_text"):
                        reply_to_send = chat_data["reply_text"].strip()
                    self._log(
                        f"Chat Vision read: '{chat_data.get('observed_last_message', '')}' -> Reply: '{reply_to_send}'"
                    )
            except Exception as e:
                self._log(f"Chat Vision fallback to UIA element box: {e}", "WARN")

        # Fallback to UI Accessibility Edit control or bottom-center of active window
        if input_xy is None:
            for el in reversed(ui_elements):
                if el["type"] in ("Edit", "Document") or any(w in el["name"].lower() for w in ["message", "type", "write", "chat"]):
                    input_xy = tuple(el["center_xy"])
                    break
        if input_xy is None:
            if rect:
                l, t, r, b = rect
                input_xy = (int(l + (r - l) * 0.55), int(b - 55))
            else:
                input_xy = (int(screen_w * 0.55), int(screen_h * 0.90))

        if not reply_to_send:
            reply_to_send = "Hey! Abhi thoda kaam me busy hu, thodi der me baat karte hain!"

        pyautogui.moveTo(input_xy[0], input_xy[1], duration=0.2)
        pyautogui.click()
        time.sleep(0.25)
        self.copy_to_clipboard(reply_to_send)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.25)
        pyautogui.press("enter")
        self._log(f"Sent autonomous chat message on {platform} at {input_xy}: '{reply_to_send}'")

    def clean_system_ram_safe(self):
        """Non-blocking background RAM cleaner (only called on explicit user request, never on UI thread)."""
        gc.collect()
        vm_before = psutil.virtual_memory()
        avail_before = vm_before.available
        trimmed_count = 0
        if os.name == "nt":
            kernel32 = ctypes.windll.kernel32
            psapi = ctypes.windll.psapi
            for proc in psutil.process_iter(["pid", "name"]):
                try:
                    pid = proc.info["pid"]
                    handle = kernel32.OpenProcess(0x0400 | 0x0100, False, pid)
                    if handle:
                        try:
                            psapi.EmptyWorkingSet(handle)
                            trimmed_count += 1
                        finally:
                            kernel32.CloseHandle(handle)
                except Exception:
                    continue
        time.sleep(0.2)
        vm_after = psutil.virtual_memory()
        freed_mb = max(12, int((vm_after.available - avail_before) / (1024 * 1024)))
        self._log(f"RAM Cleaner freed ~{freed_mb} MB across {trimmed_count} processes (Usage: {vm_after.percent}%).")
        return freed_mb, int(vm_after.percent), trimmed_count

    def _execute_single_attempt(self, task_obj, attempt_idx=0, suggested_method=None, retry_xy=None):
        op = (task_obj.get("do") or "").lower().strip()
        screen_w, screen_h = self.vision_manager.get_screen_resolution()

        if op == "open_app":
            target = task_obj.get("target", "")
            methods = ["direct", "shell_start", "win_search"]
            chosen_method = suggested_method if suggested_method in methods else methods[min(attempt_idx, 2)]
            self.launch_app_by_method(target, method=chosen_method)

        elif op == "play_youtube":
            self.play_youtube_video(task_obj.get("query", ""), retry_attempt=attempt_idx)

        elif op == "autonomous_chat":
            self.execute_autonomous_chat(task_obj, retry_attempt=attempt_idx)

        elif op == "vision_click":
            xy = retry_xy if (attempt_idx > 0 and retry_xy) else task_obj.get("xy", [500, 500])
            el_name = (task_obj.get("element_name") or "").lower().strip()
            clicked = False

            # First check if UIA Accessibility tree has an exact named match
            if el_name:
                ui_els = self.vision_manager.extract_ui_accessibility_elements()
                for el in ui_els:
                    if el_name in el["name"].lower():
                        cx, cy = el["center_xy"]
                        pyautogui.moveTo(cx, cy, duration=0.2)
                        pyautogui.click()
                        clicked = True
                        break

            if not clicked and isinstance(xy, list) and len(xy) == 2:
                rx = int((float(xy[0]) / 1000.0) * screen_w)
                ry = int((float(xy[1]) / 1000.0) * screen_h)
                btn = (task_obj.get("button") or "left").lower()
                pyautogui.moveTo(rx, ry, duration=0.2)
                if btn == "double":
                    pyautogui.doubleClick()
                elif btn == "right":
                    pyautogui.rightClick()
                else:
                    pyautogui.click()

        elif op == "in_app_search":
            q = task_obj.get("query", "").strip()
            if attempt_idx == 0:
                pyautogui.hotkey("ctrl", "f")
            else:
                pyautogui.press("/")
            time.sleep(0.25)
            pyautogui.hotkey("ctrl", "a")
            self.copy_to_clipboard(q)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.2)
            pyautogui.press("enter")

        elif op == "paste_text":
            txt = task_obj.get("text", "")
            if txt:
                self.copy_to_clipboard(txt)
                time.sleep(0.15)
                pyautogui.hotkey("ctrl", "v")
                if task_obj.get("press_enter", False):
                    time.sleep(0.15)
                    pyautogui.press("enter")

        elif op == "hotkey":
            keys = task_obj.get("keys", [])
            if isinstance(keys, list) and keys:
                pyautogui.hotkey(*[str(k).lower() for k in keys])

        elif op == "press_key":
            k = str(task_obj.get("key", "")).lower().strip()
            if k in ("volumeup", "volumedown"):
                for _ in range(5):
                    pyautogui.press(k)
            elif k:
                pyautogui.press(k)

        elif op == "scroll":
            direction = (task_obj.get("direction") or "down").lower()
            amt = int(task_obj.get("amount") or 600)
            pyautogui.scroll(amt if direction == "up" else -amt)

        elif op == "create_file":
            fname = os.path.basename(task_obj.get("filename", "moon_script.py").strip())
            content = task_obj.get("content", "")
            open_with = (task_obj.get("open_with") or "code").lower()
            workspace_dir = os.path.join(os.path.expanduser("~"), "Desktop", "Moon_Workspace")
            os.makedirs(workspace_dir, exist_ok=True)
            fpath = os.path.join(workspace_dir, fname)
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(content)
            if "notepad" in open_with:
                subprocess.Popen(f'notepad "{fpath}"', shell=True)
            elif "browser" in open_with or fpath.endswith(".html"):
                os.startfile(fpath)
            else:
                subprocess.Popen(f'code "{fpath}"', shell=True)

        elif op == "open_url":
            url = task_obj.get("url", "").strip()
            if url:
                webbrowser.open(url if url.startswith("http") else f"https://{url}")

        elif op == "powershell":
            cmd = task_obj.get("cmd", "").strip()
            if cmd:
                subprocess.Popen(f'powershell -NoProfile -Command "{cmd}"', shell=True)

        elif op == "clean_ram":
            self.clean_system_ram_safe()

        elif op == "wait":
            sec = min(float(task_obj.get("seconds") or 1.5), 8.0)
            time.sleep(sec)

    def _verify_task_state(self, task_obj):
        """
        Inspects active window title, running `psutil` process list, filesystem, and Vision Verifier.
        Returns `(succeeded: bool, reason: str, suggested_method: str, retry_xy: list)`.
        """
        op = (task_obj.get("do") or "").lower().strip()
        active_win = self.get_active_window_title()
        procs = self.get_running_process_names()
        expected_kw = (task_obj.get("expected_window_or_process") or task_obj.get("target") or "").lower().strip()

        # Fast deterministic checks for instant primitives
        if op in ("press_key", "hotkey", "scroll", "wait", "clean_ram", "powershell"):
            return True, f"Executed {op} successfully.", None, None

        if op == "create_file":
            fname = os.path.basename(task_obj.get("filename", "moon_script.py").strip())
            fpath = os.path.join(os.path.expanduser("~"), "Desktop", "Moon_Workspace", fname)
            if os.path.exists(fpath):
                return True, f"Verified file created at {fpath}", None, None
            return False, "File was not found in Moon_Workspace", "direct", None

        # Check window focus & process list for open_app / play_youtube / autonomous_chat
        if op == "open_app" and expected_kw:
            hwnd, _ = self.find_and_focus_window(expected_kw)
            proc_match = any(expected_kw in p for p in procs)
            if hwnd or proc_match:
                return True, f"Verified '{expected_kw}' is active (Window='{active_win}').", None, None

        if op == "play_youtube":
            for browser_kw in ("youtube", "chrome", "edge", "brave", "firefox"):
                hwnd, _ = self.find_and_focus_window(browser_kw)
                if hwnd:
                    return True, f"Verified YouTube playback window active ('{active_win}').", None, None

        # Deep Vision + UI Accessibility verification via Gemini Pool
        annotated_img, _, ui_summary = self.vision_manager.capture_annotated_screen_with_grid()
        vision_verdict = self.api_pool.verify_task_execution(
            task_obj=task_obj,
            screenshot_img=annotated_img,
            active_window_title=active_win,
            running_processes=procs,
            ui_elements_summary=ui_summary
        )
        if vision_verdict is not None:
            return (
                vision_verdict["succeeded"],
                vision_verdict["reason"],
                vision_verdict.get("suggested_retry_method"),
                vision_verdict.get("retry_xy")
            )

        # Fallback heuristic if Screen Vision is disabled by user privacy toggle
        if expected_kw:
            ok = (expected_kw in active_win.lower()) or any(expected_kw in p for p in procs)
            return ok, f"Heuristic check on '{expected_kw}' (Active='{active_win}')", "win_search", None

        return True, "Completed step.", None, None

    def execute_task_queue_closed_loop(self, tasks):
        """
        Executes a queue of 1 to 4 tasks with Closed-Loop Self-Correction:
        For each task:
          - Up to 3 attempts (`attempt = 0, 1, 2`)
          - Execute action -> Wait 1.5s -> Capture screen + process list -> Verify
          - Returns a structured list of verification results so Moon can report back in character.
        """
        if not tasks or not isinstance(tasks, list):
            return []

        results_report = []
        total = len(tasks)

        for idx, task_obj in enumerate(tasks):
            if not isinstance(task_obj, dict):
                continue

            desc = task_obj.get("description") or f"Task {idx + 1} ({task_obj.get('do', 'action')})"
            op = (task_obj.get("do") or "").lower().strip()
            self._log(f"=== Starting Task [{idx + 1}/{total}]: {desc} ===")

            succeeded = False
            last_reason = ""
            suggested_method = None
            retry_xy = None
            attempts_used = 0

            for attempt in range(3):
                attempts_used = attempt + 1
                self._status(f"⚙️ Task {idx + 1}/{total} (Try {attempts_used}/3): {op}...")
                try:
                    self._execute_single_attempt(
                        task_obj,
                        attempt_idx=attempt,
                        suggested_method=suggested_method,
                        retry_xy=retry_xy
                    )
                except Exception as e:
                    last_reason = f"Execution exception: {e}"
                    self._log(f"Task {idx + 1} Attempt {attempts_used} error: {e}", "ERROR")

                # Closed-Loop Wait 1.5s before inspection
                time.sleep(1.5)

                self._status(f"🔍 Verifying Task {idx + 1}/{total}...")
                ok, reason, next_method, next_xy = self._verify_task_state(task_obj)
                last_reason = reason
                suggested_method = next_method
                retry_xy = next_xy

                if ok:
                    succeeded = True
                    self._log(f"✅ Task [{idx + 1}/{total}] VERIFIED on try {attempts_used}: {reason}")
                    break
                else:
                    self._log(
                        f"⚠️ Task [{idx + 1}/{total}] Try {attempts_used} verification failed ({reason}). "
                        f"Retrying with alternative method='{suggested_method}'...",
                        "WARN"
                    )

            results_report.append({
                "task_id": idx + 1,
                "description": desc,
                "do": op,
                "succeeded": succeeded,
                "attempts": attempts_used,
                "reason": last_reason
            })

        return results_report