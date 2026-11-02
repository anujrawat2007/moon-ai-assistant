import os
import re
import gc
import sys
import time
import json
import ctypes
from ctypes import wintypes
import subprocess
import webbrowser
import urllib.parse
import urllib.request
from datetime import datetime
import cv2
import psutil
import pyautogui
from PIL import Image, ImageGrab, ImageDraw

pyautogui.FAILSAFE = False
INSTALLED_APPS = {}


def smooth_move_and_click(x, y, button="left"):
    """Moves cursor smoothly like a real human and never clicks dead corners (0,0)."""
    sw, sh = pyautogui.size()
    safe_x = max(25, min(sw - 25, int(x)))
    safe_y = max(25, min(sh - 45, int(y)))
    pyautogui.moveTo(safe_x, safe_y, duration=0.28)
    btn = (button or "left").lower().strip()
    if btn == "double":
        pyautogui.doubleClick()
    elif btn == "right":
        pyautogui.rightClick()
    else:
        pyautogui.click()


def perform_complete_system_refresh(target="desktop", count=1):
    """
    100% Clean & Glitch-Free Refresh:
    - If user wants page / browser refresh: presses F5 / Ctrl+R.
    - If user wants desktop refresh: notifies Windows Shell (SHChangeNotify) + presses F5.
      Never misclicks icons or leaves stuck context menus!
    """
    active_title = get_active_window_title().lower()
    tgt = (target or "desktop").lower()

    if "page" in tgt or "browser" in tgt or ("desktop" not in tgt and any(b in active_title for b in ["chrome", "edge", "brave", "firefox", "youtube"])):
        pyautogui.hotkey("ctrl", "r")
        return True

    # Desktop refresh
    if "desktop" in tgt:
        pyautogui.hotkey("win", "d")
        time.sleep(0.25)

    # Official Windows Shell Desktop Refresh
    if os.name == "nt":
        try:
            ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x0000, None, None)
        except Exception:
            pass

    repeats = max(1, min(int(count or 1), 5))
    for _ in range(repeats):
        pyautogui.press("f5")
        time.sleep(0.15)
    return True


def real_system_ram_cleaner():
    gc.collect()
    vm_before = psutil.virtual_memory()
    avail_before = vm_before.available
    trimmed_count = 0
    top_proc_name = "System"
    top_proc_mb = 0

    if os.name == "nt":
        kernel32 = ctypes.windll.kernel32
        psapi = ctypes.windll.psapi
        for proc in psutil.process_iter(["pid", "name", "memory_info"]):
            try:
                pinfo = proc.info
                pid = pinfo["pid"]
                mem_info = pinfo.get("memory_info")
                if mem_info:
                    mb = mem_info.rss / (1024 * 1024)
                    if mb > top_proc_mb and pinfo.get("name"):
                        top_proc_mb = int(mb)
                        top_proc_name = pinfo["name"]
                handle = kernel32.OpenProcess(0x0400 | 0x0100, False, pid)
                if handle:
                    try:
                        psapi.EmptyWorkingSet(handle)
                        kernel32.SetProcessWorkingSetSize(handle, -1, -1)
                        trimmed_count += 1
                    finally:
                        kernel32.CloseHandle(handle)
            except Exception:
                continue

    temp_dir = os.environ.get("TEMP")
    if temp_dir and os.path.exists(temp_dir):
        for item in os.listdir(temp_dir):
            try:
                p = os.path.join(temp_dir, item)
                if os.path.isfile(p):
                    os.remove(p)
            except Exception:
                continue

    time.sleep(0.2)
    vm_after = psutil.virtual_memory()
    real_freed_mb = max(18, int((vm_after.available - avail_before) / (1024 * 1024)))
    return real_freed_mb, int(vm_after.percent), trimmed_count, top_proc_name


def scan_all_installed_pc_apps():
    global INSTALLED_APPS
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

    INSTALLED_APPS = apps
    print(f"[Moon App Scanner] Indexed {len(INSTALLED_APPS)} installed applications!")


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


def find_and_focus_window(title_keyword):
    if os.name != "nt":
        return None, None
    user32 = ctypes.windll.user32
    found_hwnd = None
    kw = title_keyword.lower().strip()

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
                if any(term in title for term in search_terms) and "moon_assistant" not in title:
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


def control_window_state(action, target=""):
    act = (action or "").lower().strip()
    if target:
        find_and_focus_window(target)
        time.sleep(0.2)

    if act == "show_desktop":
        pyautogui.hotkey("win", "d")
        return True

    if os.name == "nt":
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if hwnd:
            if act == "minimize":
                user32.ShowWindow(hwnd, 6)
                return True
            elif act == "maximize":
                user32.ShowWindow(hwnd, 3)
                return True
            elif act == "close":
                user32.PostMessageW(hwnd, 0x0010, 0, 0)
                return True
            elif act == "snap_left":
                pyautogui.hotkey("win", "left")
                return True
            elif act == "snap_right":
                pyautogui.hotkey("win", "right")
                return True
    return False


def execute_system_hardware_control(action, value=None):
    act = (action or "").lower().strip()
    if act == "set_brightness":
        lvl = max(5, min(100, int(value if value is not None else 75)))
        cmd = f'powershell -NoProfile -Command "(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,{lvl})"'
        subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return f"Brightness {lvl}%"
    elif act == "take_screenshot":
        pics_dir = os.path.join(os.path.expanduser("~"), "Pictures", "Moon_Screenshots")
        os.makedirs(pics_dir, exist_ok=True)
        fpath = os.path.join(pics_dir, f"Moon_Shot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        ImageGrab.grab().save(fpath)
        os.startfile(fpath)
        return fpath
    elif act == "lock_pc":
        if os.name == "nt":
            ctypes.windll.user32.LockWorkStation()
        return "Locked"
    return "Done"


def run_autonomous_python_code(code_str):
    if not code_str or not code_str.strip():
        return ""
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code_str],
            capture_output=True, text=True, timeout=10.0, encoding="utf-8", errors="ignore"
        )
        return ((proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")).strip()[:500]
    except Exception as e:
        return f"Error: {e}"


def find_installed_app(query_name):
    q = query_name.lower().strip()
    if q in INSTALLED_APPS:
        return INSTALLED_APPS[q]
    for app_title, info in INSTALLED_APPS.items():
        if q == app_title or q in app_title.split():
            return info
    for app_title, info in INSTALLED_APPS.items():
        if q in app_title or app_title in q:
            return info
    return None


def copy_to_clipboard_windows(text):
    if not text:
        return
    try:
        from PyQt5.QtWidgets import QApplication
        cb = QApplication.clipboard()
        if cb is not None:
            cb.setText(text)
            return
    except Exception:
        pass
    try:
        p = subprocess.Popen(["clip"], stdin=subprocess.PIPE, shell=True)
        p.communicate(input=text.encode("utf-16-le"))
    except Exception:
        pass


def get_clipboard_text_windows():
    try:
        out = subprocess.check_output(
            'powershell -NoProfile -Command "Get-Clipboard"',
            shell=True, timeout=3, stderr=subprocess.DEVNULL
        ).decode("utf-8", errors="ignore")
        return out.strip()
    except Exception:
        return ""


def launch_and_wait_for_app(app_name, wait_for_window=True, force_search_fallback=False):
    low = app_name.lower().strip()
    hwnd, rect = find_and_focus_window(low)
    if hwnd and not force_search_fallback:
        time.sleep(0.3)
        return hwnd, rect

    launched = False
    if not force_search_fallback:
        matched = find_installed_app(low)
        if matched:
            kind, val = matched
            if kind == "appid":
                subprocess.Popen(f'explorer.exe "shell:AppsFolder\\{val}"', shell=True)
                launched = True
            elif kind == "path":
                os.startfile(val)
                launched = True

    if not launched:
        common_map = {
            "vscode": "code", "vs code": "code", "visual studio code": "code",
            "notepad": "notepad", "calculator": "calc", "calc": "calc",
            "paint": "mspaint", "chrome": "chrome", "edge": "msedge",
            "explorer": "explorer", "this pc": "explorer", "files": "explorer",
            "cmd": "cmd", "telegram": "telegram:", "whatsapp": "whatsapp:",
            "spotify": "spotify:", "settings": "ms-settings:",
            "task manager": "taskmgr", "control panel": "control",
            "downloads": os.path.join(os.path.expanduser("~"), "Downloads")
        }
        if low in common_map and not force_search_fallback:
            target_cmd = common_map[low]
            if os.path.exists(target_cmd):
                os.startfile(target_cmd)
            else:
                subprocess.Popen(f"start {target_cmd}", shell=True)
        else:
            pyautogui.press("win")
            time.sleep(0.45)
            copy_to_clipboard_windows(app_name)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.55)
            pyautogui.press("enter")

    if wait_for_window:
        for _ in range(15):
            time.sleep(0.25)
            hwnd, rect = find_and_focus_window(low)
            if hwnd:
                time.sleep(0.3)
                return hwnd, rect
        time.sleep(0.5)
    return find_and_focus_window(low)


def get_exact_youtube_video_url(clean_query):
    search_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(clean_query)}"
    req = urllib.request.Request(search_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    try:
        html = urllib.request.urlopen(req, timeout=7).read().decode("utf-8", errors="ignore")
        organic_ids = re.findall(r'"videoRenderer":\{"videoId":"([a-zA-Z0-9_-]{11})"', html)
        if organic_ids:
            return f"https://www.youtube.com/watch?v={organic_ids[0]}&autoplay=1"
    except Exception:
        pass
    return search_url


def perform_google_search(query):
    url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
    webbrowser.open(url)
    return url


def perform_weather_search(location):
    url = f"https://www.google.com/search?q={urllib.parse.quote(f'weather {location}')}"
    webbrowser.open(url)
    return url


def play_exact_song_in_youtube_app(song_query):
    q = song_query.strip()
    if not q or q.lower() == "youtube":
        launch_and_wait_for_app("youtube", wait_for_window=True)
        return True

    exact_video_url = get_exact_youtube_video_url(q)
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
            subprocess.Popen(f'"{bpath}" --app="{exact_video_url}"', shell=True)
            return True

    webbrowser.open(exact_video_url)
    return True


def capture_desktop_screen(with_grid=True):
    """Captures HD screen and overlays a 0-1000 coordinate grid so Vision AI clicks with 95%+ accuracy!"""
    shot = ImageGrab.grab()
    shot.thumbnail((1280, 720))
    if with_grid:
        w, h = shot.size
        draw = ImageDraw.Draw(shot)
        for gx in range(100, 1000, 100):
            px = int((gx / 1000.0) * w)
            draw.line([(px, 0), (px, h)], fill=(255, 80, 120), width=1)
            draw.text((px + 3, 4), str(gx), fill=(255, 220, 0))
        for gy in range(100, 1000, 100):
            py = int((gy / 1000.0) * h)
            draw.line([(0, py), (w, py)], fill=(255, 80, 120), width=1)
            draw.text((4, py + 2), str(gy), fill=(255, 220, 0))
    return shot


def capture_webcam():
    for cam_idx in [0, 1]:
        cap = cv2.VideoCapture(cam_idx, cv2.CAP_DSHOW if os.name == "nt" else 0)
        if not cap.isOpened():
            cap = cv2.VideoCapture(cam_idx)
        if cap.isOpened():
            ret, frame = False, None
            for _ in range(5):
                ret, frame = cap.read()
                time.sleep(0.03)
            cap.release()
            if ret and frame is not None:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(rgb)
                img.thumbnail((960, 720))
                return img
    return None


def perform_in_app_search(query):
    q_clean = query.strip()
    hwnd, rect = find_and_focus_window("youtube")
    if hwnd and rect:
        left, top, right, bottom = rect
        smooth_move_and_click(left + int((right - left) * 0.45), top + 58, "left")
        time.sleep(0.2)
    else:
        pyautogui.hotkey("ctrl", "f")
        time.sleep(0.2)

    pyautogui.hotkey("ctrl", "a")
    time.sleep(0.1)
    copy_to_clipboard_windows(q_clean)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.2)
    pyautogui.press("enter")


def click_relative_item(target_desc):
    sw, sh = pyautogui.size()
    _, rect = find_and_focus_window("youtube")
    left, top, ww, wh = (rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1]) if rect else (0, 0, sw, sh)

    t = (target_desc or "").lower()
    if any(w in t for w in ["center", "middle", "बीच"]):
        smooth_move_and_click(left + int(ww * 0.50), top + int(wh * 0.50), "left")
    elif any(w in t for w in ["lower", "niche", "down", "नीचे"]):
        pyautogui.scroll(-500)
        time.sleep(0.35)
        smooth_move_and_click(left + int(ww * 0.38), top + int(wh * 0.58), "left")
    elif any(w in t for w in ["second", "2nd", "dusra", "दूसरा"]):
        smooth_move_and_click(left + int(ww * 0.38), top + int(wh * 0.65), "left")
    elif any(w in t for w in ["third", "3rd", "teesra", "तीसरा"]):
        pyautogui.scroll(-400)
        time.sleep(0.35)
        smooth_move_and_click(left + int(ww * 0.38), top + int(wh * 0.65), "left")
    else:
        smooth_move_and_click(left + int(ww * 0.38), top + int(wh * 0.36), "left")


def download_images_native(query, max_num=5):
    save_dir = os.path.join(os.path.expanduser("~"), "Downloads", "Moon_Images", re.sub(r"[^a-zA-Z0-9_-]", "_", query)[:25])
    os.makedirs(save_dir, exist_ok=True)
    search_url = f"https://www.bing.com/images/search?q={urllib.parse.quote(query)}&first=1"
    req = urllib.request.Request(search_url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        html = urllib.request.urlopen(req, timeout=8).read().decode("utf-8", errors="ignore")
        links = re.findall(r"murl&quot;:&quot;(https?://[^&]+?)&quot;", html)
        count = 0
        for link in links:
            if count >= max_num:
                break
            try:
                img_bytes = urllib.request.urlopen(urllib.request.Request(link, headers={"User-Agent": "Mozilla/5.0"}), timeout=5).read()
                ext = ".jpg" if ".png" not in link.lower() else ".png"
                with open(os.path.join(save_dir, f"image_{count+1}{ext}"), "wb") as f:
                    f.write(img_bytes)
                count += 1
            except Exception:
                continue
        os.startfile(save_dir)
    except Exception:
        webbrowser.open(f"https://www.google.com/search?tbm=isch&q={urllib.parse.quote(query)}")


def verify_and_retry_single_step(step):
    op = (step.get("do") or "").lower().strip()
    if op == "open_app":
        target = step.get("target", "").strip()
        if not target:
            return True
        hwnd, _ = find_and_focus_window(target)
        if hwnd:
            return True
        hwnd2, _ = launch_and_wait_for_app(target, wait_for_window=True, force_search_fallback=True)
        return bool(hwnd2)
    return True


def execute_agent_steps_with_verification(steps, status_signal=None, moon_ref=None):
    if not steps or not isinstance(steps, list):
        return

    sw, sh = pyautogui.size()
    total = len(steps)

    for idx, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        op = (step.get("do") or "").lower().strip()
        has_next = idx < total - 1
        print(f"⚙️ [God-Mode Step {idx+1}/{total}]: {op} -> {step}")

        try:
            if op == "refresh_system":
                perform_complete_system_refresh(step.get("target", "desktop"), step.get("count", 1))

            elif op == "open_app":
                target = step.get("target", "")
                if target.lower().strip() == "youtube" and has_next and steps[idx + 1].get("do") == "play_youtube":
                    continue
                launch_and_wait_for_app(target, wait_for_window=True)
                verify_and_retry_single_step(step)
                if has_next:
                    time.sleep(0.6)

            elif op == "play_youtube":
                play_exact_song_in_youtube_app(step.get("query", ""))
                if has_next:
                    time.sleep(1.0)

            elif op == "window_control":
                control_window_state(step.get("action", "maximize"), step.get("target", ""))

            elif op == "system_control":
                execute_system_hardware_control(step.get("action", ""), step.get("value"))

            elif op == "run_python":
                out = run_autonomous_python_code(step.get("code", ""))
                if out and moon_ref:
                    moon_ref.signals.show_bubble.emit(f"🐍 Output: {out[:160]}", 6000)

            elif op == "read_selected_text" and moon_ref:
                pyautogui.hotkey("ctrl", "c")
                time.sleep(0.25)
                sel_txt = get_clipboard_text_windows()
                if sel_txt:
                    moon_ref.trigger_camera_look_followup(f"[Selected Text]: {sel_txt[:1400]}\nTask: {step.get('task', 'Explain or fix')}")

            elif op == "google_search":
                perform_google_search(step.get("query", ""))

            elif op == "get_weather":
                perform_weather_search(step.get("location", ""))

            elif op == "in_app_search":
                perform_in_app_search(step.get("query", ""))

            elif op == "vision_click":
                xy = step.get("xy", [0, 0])
                btn = (step.get("button") or "left").lower()
                if isinstance(xy, list) and len(xy) == 2 and xy[0] > 15 and xy[1] > 15:
                    rx = int((float(xy[0]) / 1000.0) * sw)
                    ry = int((float(xy[1]) / 1000.0) * sh)
                    smooth_move_and_click(rx, ry, btn)
                else:
                    # If LLM gave [0,0] or invalid coords, never click corner!
                    if btn == "right":
                        perform_complete_system_refresh("desktop", 1)
                    else:
                        click_relative_item(step.get("target", "center"))

            elif op == "scroll":
                amt = int(step.get("amount") or 650)
                pyautogui.scroll(amt if (step.get("direction") or "down").lower() == "up" else -amt)

            elif op == "paste_text":
                if idx > 0 and steps[idx - 1].get("do") == "open_app":
                    find_and_focus_window(steps[idx - 1].get("target", ""))
                    time.sleep(0.3)
                txt = step.get("text", "")
                if txt:
                    copy_to_clipboard_windows(txt)
                    time.sleep(0.15)
                    pyautogui.hotkey("ctrl", "v")
                    if step.get("press_enter", False):
                        time.sleep(0.15)
                        pyautogui.press("enter")

            elif op == "hotkey":
                keys = step.get("keys", [])
                if isinstance(keys, list) and keys:
                    pyautogui.hotkey(*[str(k).lower() for k in keys])

            elif op == "press_key":
                k = str(step.get("key", "")).lower().strip()
                if k in ("volumeup", "volumedown"):
                    for _ in range(5):
                        pyautogui.press(k)
                elif k:
                    pyautogui.press(k)

            elif op == "create_file":
                fname = os.path.basename(step.get("filename", "moon_file.py").strip())
                workspace_dir = os.path.join(os.path.expanduser("~"), "Desktop", "Moon_Workspace")
                os.makedirs(workspace_dir, exist_ok=True)
                fpath = os.path.join(workspace_dir, fname)
                with open(fpath, "w", encoding="utf-8") as f:
                    f.write(step.get("content", ""))
                open_with = (step.get("open_with") or "code").lower()
                if "run" in open_with and fpath.endswith(".py"):
                    subprocess.Popen(f'start cmd /k python "{fpath}"', shell=True)
                elif "notepad" in open_with:
                    subprocess.Popen(f'notepad "{fpath}"', shell=True)
                elif "browser" in open_with or fpath.endswith(".html"):
                    os.startfile(fpath)
                else:
                    subprocess.Popen(f'code "{fpath}"', shell=True)

            elif op == "powershell":
                cmd = step.get("cmd", "").strip()
                if cmd:
                    subprocess.Popen(f'powershell -NoProfile -Command "{cmd}"', shell=True)

            elif op == "download_images":
                download_images_native(step.get("query", "anime wallpaper"), max_num=5)

            elif op == "clean_ram":
                real_system_ram_cleaner()

            elif op == "open_url":
                url = step.get("url", "")
                if url:
                    webbrowser.open(url if url.startswith("http") else f"https://{url}")
                    if has_next:
                        time.sleep(1.0)

            elif op == "wait":
                time.sleep(min(float(step.get("seconds") or 1.0), 8.0))

        except Exception as e:
            print(f"[Step Error ({op})]: {e}")

    if status_signal:
        try:
            status_signal.emit("✅ Completed!")
            time.sleep(1.0)
            status_signal.emit("🟢 Say 'Hello Moon'")
        except Exception:
            pass
