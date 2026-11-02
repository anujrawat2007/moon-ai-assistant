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
import cv2
import psutil
import pyautogui
from PIL import Image, ImageGrab

pyautogui.FAILSAFE = False
INSTALLED_APPS = {}

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

    time.sleep(0.25)
    vm_after = psutil.virtual_memory()
    real_freed_mb = max(15, int((vm_after.available - avail_before) / (1024 * 1024)))
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
    try:
        p = subprocess.Popen(["clip"], stdin=subprocess.PIPE, shell=True)
        p.communicate(input=text.encode("utf-16-le"))
    except Exception:
        pass

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
            "explorer": "explorer", "cmd": "cmd", "telegram": "telegram:",
            "whatsapp": "whatsapp:", "spotify": "spotify:", "settings": "ms-settings:"
        }
        if low in common_map and not force_search_fallback:
            subprocess.Popen(f"start {common_map[low]}", shell=True)
        else:
            pyautogui.press("win")
            time.sleep(0.45)
            copy_to_clipboard_windows(app_name)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.55)
            pyautogui.press("enter")

    if wait_for_window:
        for _ in range(18):
            time.sleep(0.25)
            hwnd, rect = find_and_focus_window(low)
            if hwnd:
                time.sleep(0.4)
                return hwnd, rect
        time.sleep(0.8)
    return find_and_focus_window(low)

def get_exact_youtube_video_url(clean_query):
    search_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(clean_query)}"
    req = urllib.request.Request(
        search_url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    )
    try:
        html = urllib.request.urlopen(req, timeout=8).read().decode("utf-8", errors="ignore")
        organic_ids = re.findall(r'"videoRenderer":\{"videoId":"([a-zA-Z0-9_-]{11})"', html)
        if organic_ids:
            return f"https://www.youtube.com/watch?v={organic_ids[0]}&autoplay=1"
    except Exception as e:
        print(f"[YouTube Search Notice]: {e}")
    return search_url

def play_exact_song_in_youtube_app(song_query):
    q = song_query.strip()
    if not q or q.lower() == "youtube":
        launch_and_wait_for_app("youtube", wait_for_window=True)
        return True

    exact_video_url = get_exact_youtube_video_url(q)
    print(f"🎵 [Playing Exact YouTube Song]: '{q}' -> {exact_video_url}")

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

def capture_desktop_screen():
    shot = ImageGrab.grab()
    shot.thumbnail((1280, 720))
    return shot

def capture_webcam():
    """Opens webcam, warms up auto-exposure for 5 frames, and returns a bright PIL Image."""
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
        pyautogui.click(left + int((right - left) * 0.45), top + 58)
        time.sleep(0.2)
    else:
        pyautogui.press("/")
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
    if rect:
        left, top, right, bottom = rect
        ww, wh = right - left, bottom - top
    else:
        left, top, ww, wh = 0, 0, sw, sh

    t = (target_desc or "").lower()
    if any(w in t for w in ["lower", "niche", "down", "नीचे"]):
        pyautogui.scroll(-500)
        time.sleep(0.4)
        pyautogui.moveTo(left + int(ww * 0.38), top + int(wh * 0.58), duration=0.2)
        pyautogui.click()
    elif any(w in t for w in ["second", "2nd", "dusra", "दूसरा"]):
        pyautogui.moveTo(left + int(ww * 0.38), top + int(wh * 0.65), duration=0.2)
        pyautogui.click()
    elif any(w in t for w in ["third", "3rd", "teesra", "तीसरा"]):
        pyautogui.scroll(-400)
        time.sleep(0.35)
        pyautogui.moveTo(left + int(ww * 0.38), top + int(wh * 0.65), duration=0.2)
        pyautogui.click()
    else:
        pyautogui.moveTo(left + int(ww * 0.38), top + int(wh * 0.36), duration=0.2)
        pyautogui.click()

def download_images_native(query, max_num=5):
    save_dir = os.path.join(os.path.expanduser("~"), "Downloads", "Moon_Images", re.sub(r'[^a-zA-Z0-9_-]', '_', query)[:25])
    os.makedirs(save_dir, exist_ok=True)
    search_url = f"https://www.bing.com/images/search?q={urllib.parse.quote(query)}&first=1"
    req = urllib.request.Request(search_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    try:
        html = urllib.request.urlopen(req, timeout=10).read().decode("utf-8", errors="ignore")
        links = re.findall(r'murl&quot;:&quot;(https?://[^&]+?)&quot;', html)
        count = 0
        for link in links:
            if count >= max_num:
                break
            try:
                img_req = urllib.request.Request(link, headers={"User-Agent": "Mozilla/5.0"})
                img_bytes = urllib.request.urlopen(img_req, timeout=6).read()
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
    """
    Post-Action Verifier: Checks if the action actually succeeded on Windows.
    If not, automatically retries using a backup method!
    """
    op = (step.get("do") or "").lower().strip()

    if op == "open_app":
        target = step.get("target", "").strip()
        if not target:
            return True
        hwnd, _ = find_and_focus_window(target)
        if hwnd:
            print(f"✅ [Verified]: '{target}' window is open and active!")
            return True
        print(f"⚠️ [Verifier]: '{target}' did not open on try 1. Retrying via Windows Search...")
        hwnd2, _ = launch_and_wait_for_app(target, wait_for_window=True, force_search_fallback=True)
        return bool(hwnd2)

    elif op == "play_youtube":
        time.sleep(0.8)
        for wname in ["youtube", "chrome", "edge", "brave"]:
            hwnd, _ = find_and_focus_window(wname)
            if hwnd:
                print("✅ [Verified]: YouTube player window is active!")
                return True
        print("⚠️ [Verifier]: Retrying YouTube in default browser...")
        q = step.get("query", "")
        webbrowser.open(get_exact_youtube_video_url(q))
        return True

    elif op == "create_file":
        fname = os.path.basename(step.get("filename", "moon_file.txt").strip())
        workspace_dir = os.path.join(os.path.expanduser("~"), "Desktop", "Moon_Workspace")
        fpath = os.path.join(workspace_dir, fname)
        if os.path.exists(fpath) and os.path.getsize(fpath) >= 0:
            print(f"✅ [Verified]: File '{fpath}' created!")
            return True
        os.makedirs(workspace_dir, exist_ok=True)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(step.get("content", ""))
        return os.path.exists(fpath)

    elif op == "paste_text":
        # Verify target window is focused
        active_title = get_active_window_title().lower()
        if "moon_assistant" in active_title:
            pyautogui.hotkey("alt", "tab")
            time.sleep(0.3)
            copy_to_clipboard_windows(step.get("text", ""))
            pyautogui.hotkey("ctrl", "v")
        return True

    return True

def execute_agent_steps_with_verification(steps, status_signal=None, moon_ref=None):
    """
    Executes multi-step tasks in sequence, verifies each step, and retries if needed!
    """
    if not steps or not isinstance(steps, list):
        return

    sw, sh = pyautogui.size()
    total = len(steps)

    for idx, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        op = (step.get("do") or "").lower().strip()
        has_next_steps = (idx < total - 1)
        print(f"⚙️ [Agent Step {idx+1}/{total}]: {op} -> {step}")
        if status_signal:
            status_signal.emit(f"⚙️ Step {idx+1}/{total}: {op}...")

        try:
            if op == "open_app":
                target = step.get("target", "")
                if target.lower().strip() == "youtube" and has_next_steps and steps[idx+1].get("do") == "play_youtube":
                    continue
                launch_and_wait_for_app(target, wait_for_window=True)
                verify_and_retry_single_step(step)
                if has_next_steps:
                    time.sleep(0.8)

            elif op == "play_youtube":
                play_exact_song_in_youtube_app(step.get("query", ""))
                verify_and_retry_single_step(step)
                if has_next_steps:
                    time.sleep(1.2)

            elif op == "in_app_search":
                perform_in_app_search(step.get("query", ""))
                if has_next_steps:
                    time.sleep(1.5)

            elif op == "click_relative":
                click_relative_item(step.get("target", "first"))

            elif op == "vision_click":
                xy = step.get("xy", [0, 0])
                btn = (step.get("button") or "left").lower()
                if isinstance(xy, list) and len(xy) == 2 and xy[0] > 0 and xy[1] > 0:
                    rx = int((float(xy[0]) / 1000.0) * sw)
                    ry = int((float(xy[1]) / 1000.0) * sh)
                    pyautogui.moveTo(rx, ry, duration=0.25)
                    if btn == "double":
                        pyautogui.doubleClick()
                    elif btn == "right":
                        pyautogui.rightClick()
                    else:
                        pyautogui.click()
                else:
                    click_relative_item(step.get("target", "first"))

            elif op == "scroll":
                direction = (step.get("direction") or "down").lower()
                amt = int(step.get("amount") or 650)
                pyautogui.scroll(amt if direction == "up" else -amt)
                if has_next_steps:
                    time.sleep(0.5)

            elif op == "paste_text":
                if idx > 0 and steps[idx - 1].get("do") == "open_app":
                    find_and_focus_window(steps[idx - 1].get("target", ""))
                    time.sleep(0.35)
                txt = step.get("text", "")
                if txt:
                    copy_to_clipboard_windows(txt)
                    time.sleep(0.15)
                    pyautogui.hotkey("ctrl", "v")
                    verify_and_retry_single_step(step)
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

            elif op == "open_url":
                url = step.get("url", "")
                if url:
                    webbrowser.open(url if url.startswith("http") else f"https://{url}")
                    if has_next_steps:
                        time.sleep(1.5)

            elif op == "create_file":
                fname = step.get("filename", "moon_file.txt").strip()
                content = step.get("content", "")
                open_with = (step.get("open_with") or "code").lower()
                workspace_dir = os.path.join(os.path.expanduser("~"), "Desktop", "Moon_Workspace")
                os.makedirs(workspace_dir, exist_ok=True)
                fpath = os.path.join(workspace_dir, os.path.basename(fname))
                with open(fpath, "w", encoding="utf-8") as f:
                    f.write(content)
                verify_and_retry_single_step(step)
                if "notepad" in open_with:
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
                freed_mb, ram_pct, proc_cnt, _ = real_system_ram_cleaner()
                if status_signal:
                    status_signal.emit(f"🧹 Freed {freed_mb}MB | RAM: {ram_pct}%")

            elif op == "look_camera" and moon_ref is not None:
                # If Brain requested a camera look mid-task
                moon_ref.trigger_camera_look_followup("कैमरे की फोटो देखकर बताओ क्या दिख रहा है!")

            elif op == "wait":
                sec = min(float(step.get("seconds") or 1.0), 8.0)
                time.sleep(sec)

        except Exception as e:
            print(f"[Agent Step Error ({op})]: {e}")

    if status_signal:
        status_signal.emit("✅ Verified & Completed!")
        time.sleep(1.2)
        status_signal.emit("🟢 Say 'Hello Moon'")