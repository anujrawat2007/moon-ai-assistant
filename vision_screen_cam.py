import os
import gc
import time
import ctypes
from ctypes import wintypes
import threading
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

try:
    import mss
    MSS_AVAILABLE = True
except ImportError:
    MSS_AVAILABLE = False
    from PIL import ImageGrab

try:
    import uiautomation as auto
    UIA_AVAILABLE = True
except Exception:
    UIA_AVAILABLE = False

try:
    from pywinauto import Desktop
    PYWINAUTO_AVAILABLE = True
except Exception:
    PYWINAUTO_AVAILABLE = False

ASSETS_DIR = "moon_assets"
SPRITE_VERSION_FILE = os.path.join(ASSETS_DIR, "version_v6_prod.txt")


class VisionPrivacyAndCaptureManager:
    """
    Manages:
    1. Screen Vision On/Off privacy gate + ultra-fast `mss` screen capture
    2. Coordinate grid + Win32/UIA interactive element bounding-box overlay for Gemini 2.5 Flash Vision
    3. Webcam Access On/Off hardware-level privacy gate + zero-leak `cv2.VideoCapture` frame capture
    """

    def __init__(self, screen_vision_enabled=True, webcam_access_enabled=True, log_callback=None):
        self.screen_vision_enabled = bool(screen_vision_enabled)
        self.webcam_access_enabled = bool(webcam_access_enabled)
        self.log_callback = log_callback
        self._tls = threading.local()
        self._cam_lock = threading.Lock()

    def _log(self, msg, level="INFO"):
        if self.log_callback:
            try:
                self.log_callback(f"[Vision][{level}] {msg}")
            except Exception:
                pass

    def set_screen_vision_enabled(self, enabled: bool):
        self.screen_vision_enabled = bool(enabled)
        self._log(f"Screen Vision Toggle set to: {'ON' if self.screen_vision_enabled else 'OFF (Privacy Locked)'}")

    def set_webcam_access_enabled(self, enabled: bool):
        self.webcam_access_enabled = bool(enabled)
        self._log(f"Webcam Access Toggle set to: {'ON' if self.webcam_access_enabled else 'OFF (Hardware Blocked)'}")

    def _get_mss_instance(self):
        if not MSS_AVAILABLE:
            return None
        inst = getattr(self._tls, "mss_inst", None)
        if inst is None:
            inst = mss.mss()
            self._tls.mss_inst = inst
        return inst

    def capture_raw_screen(self, max_size=(1280, 720)):
        """Captures primary monitor using ultra-fast `mss`. Returns None if Screen Vision is disabled."""
        if not self.screen_vision_enabled:
            self._log("Screen capture blocked by Screen Vision Privacy Toggle.", "WARN")
            return None

        try:
            sct = self._get_mss_instance()
            if sct is not None:
                monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
                raw = sct.grab(monitor)
                img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
            else:
                img = ImageGrab.grab().convert("RGB")

            if max_size:
                img.thumbnail(max_size, Image.LANCZOS)
            return img
        except Exception as e:
            self._log(f"mss screen capture error: {e}", "ERROR")
            return None

    def extract_ui_accessibility_elements(self, max_elements=35):
        """
        Extracts interactive UI controls (buttons, input boxes, chat fields, tabs, list items)
        and their exact screen bounding boxes using `uiautomation`, `pywinauto`, and Win32 `EnumChildWindows`.
        """
        elements = []
        screen_w, screen_h = self.get_screen_resolution()

        # 1. Try pywinauto UIA backend for fast active window control tree
        if PYWINAUTO_AVAILABLE:
            try:
                desk = Desktop(backend="uia")
                active_win = desk.top_window()
                wrappers = active_win.descendants()
                for w in wrappers:
                    if len(elements) >= max_elements:
                        break
                    try:
                        if not w.is_visible() or not w.is_enabled():
                            continue
                        ctrl_type = str(w.element_info.control_type or "")
                        if ctrl_type not in ("Button", "Edit", "Document", "ListItem", "TabItem", "Hyperlink", "MenuItem", "ComboBox"):
                            continue
                        name = (w.window_text() or w.element_info.name or "").strip()
                        rect = w.rectangle()
                        if rect.width() < 12 or rect.height() < 10:
                            continue
                        cx = int((rect.left + rect.right) / 2)
                        cy = int((rect.top + rect.bottom) / 2)
                        if 0 <= cx <= screen_w and 0 <= cy <= screen_h:
                            elements.append({
                                "id": len(elements) + 1,
                                "type": ctrl_type,
                                "name": name[:45] if name else ctrl_type,
                                "rect": [rect.left, rect.top, rect.right, rect.bottom],
                                "center_xy": [cx, cy],
                                "norm_xy": [int(cx * 1000 / max(screen_w, 1)), int(cy * 1000 / max(screen_h, 1))]
                            })
                    except Exception:
                        continue
            except Exception:
                pass

        # 2. Supplement/Fallback with Win32 EnumChildWindows so we never miss standard Win32 controls
        if len(elements) < 8 and os.name == "nt":
            try:
                user32 = ctypes.windll.user32
                fg_hwnd = user32.GetForegroundWindow()
                if fg_hwnd:
                    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

                    def enum_child_cb(hwnd, lparam):
                        if len(elements) >= max_elements:
                            return False
                        if user32.IsWindowVisible(hwnd):
                            rect = wintypes.RECT()
                            user32.GetWindowRect(hwnd, ctypes.byref(rect))
                            w = rect.right - rect.left
                            h = rect.bottom - rect.top
                            if w >= 18 and h >= 14:
                                length = user32.GetWindowTextLengthW(hwnd)
                                buf = ctypes.create_unicode_buffer(length + 1)
                                if length > 0:
                                    user32.GetWindowTextW(hwnd, buf, length + 1)
                                cls_buf = ctypes.create_unicode_buffer(64)
                                user32.GetClassNameW(hwnd, cls_buf, 64)
                                name = buf.value.strip() or cls_buf.value.strip()
                                cx = int((rect.left + rect.right) / 2)
                                cy = int((rect.top + rect.bottom) / 2)
                                if 0 <= cx <= screen_w and 0 <= cy <= screen_h:
                                    elements.append({
                                        "id": len(elements) + 1,
                                        "type": cls_buf.value.strip(),
                                        "name": name[:45],
                                        "rect": [rect.left, rect.top, rect.right, rect.bottom],
                                        "center_xy": [cx, cy],
                                        "norm_xy": [int(cx * 1000 / max(screen_w, 1)), int(cy * 1000 / max(screen_h, 1))]
                                    })
                        return True

                    user32.EnumChildWindows(fg_hwnd, WNDENUMPROC(enum_child_cb), 0)
            except Exception:
                pass

        return elements

    def capture_annotated_screen_with_grid(self):
        """
        Captures screen with `mss`, extracts UI elements, and overlays:
        - A 10x10 normalized coordinate grid (0..1000)
        - Highlighted bounding boxes + `#ID (norm_x, norm_y)` tags for interactive UI elements
        Returns `(annotated_pil_image, ui_elements_list, ui_summary_text)`.
        """
        if not self.screen_vision_enabled:
            return None, [], "Screen Vision Disabled by User Privacy Toggle."

        base_img = self.capture_raw_screen(max_size=(1280, 720))
        if base_img is None:
            return None, [], "Screen capture unavailable."

        ui_elements = self.extract_ui_accessibility_elements(max_elements=30)
        screen_w, screen_h = self.get_screen_resolution()
        img_w, img_h = base_img.size
        scale_x = img_w / max(screen_w, 1)
        scale_y = img_h / max(screen_h, 1)

        annotated = base_img.convert("RGBA")
        overlay = Image.new("RGBA", annotated.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # Draw 0..1000 coordinate grid lines every 100 units (10% intervals)
        for step in range(1, 10):
            gx = int((step / 10.0) * img_w)
            gy = int((step / 10.0) * img_h)
            draw.line([(gx, 0), (gx, img_h)], fill=(0, 255, 220, 68), width=1)
            draw.line([(0, gy), (img_w, gy)], fill=(0, 255, 220, 68), width=1)
            coord_val = step * 100
            draw.rectangle([gx + 2, 2, gx + 34, 16], fill=(10, 12, 24, 175))
            draw.text((gx + 4, 3), f"X:{coord_val}", fill=(120, 255, 230, 240))
            draw.rectangle([2, gy + 2, 36, gy + 16], fill=(10, 12, 24, 175))
            draw.text((4, gy + 3), f"Y:{coord_val}", fill=(120, 255, 230, 240))

        # Draw UI element bounding boxes and coordinate tags
        summary_lines = []
        for el in ui_elements[:25]:
            l, t, r, b = el["rect"]
            sl, st, sr_px, sb = int(l * scale_x), int(t * scale_y), int(r * scale_x), int(b * scale_y)
            nx, ny = el["norm_xy"]
            draw.rectangle([sl, st, sr_px, sb], outline=(255, 80, 180, 210), width=2)
            tag = f"#{el['id']} ({nx},{ny})"
            draw.rectangle([sl, max(0, st - 14), sl + len(tag) * 6 + 6, st], fill=(35, 12, 48, 215))
            draw.text((sl + 3, max(0, st - 13)), tag, fill=(255, 210, 245, 255))
            summary_lines.append(
                f"[#{el['id']} {el['type']} '{el['name']}' at norm_xy=({nx},{ny}), pixel_xy={el['center_xy']}]"
            )

        combined = Image.alpha_composite(annotated, overlay).convert("RGB")
        ui_summary_text = "\n".join(summary_lines) if summary_lines else "No standard UIA child controls detected; use grid coordinates."
        return combined, ui_elements, ui_summary_text

    def capture_webcam_frame(self):
        """
        Captures 1 frame from the webcam with strict hardware release guarantee (`try...finally: cap.release()`).
        Hard-blocked if `webcam_access_enabled` is False.
        """
        if not self.webcam_access_enabled:
            self._log("Webcam capture hard-blocked by Webcam Access Toggle.", "WARN")
            return None

        with self._cam_lock:
            for cam_idx in (0, 1):
                cap = None
                try:
                    backend = cv2.CAP_DSHOW if os.name == "nt" else 0
                    cap = cv2.VideoCapture(cam_idx, backend)
                    if not cap or not cap.isOpened():
                        if cap:
                            cap.release()
                        cap = cv2.VideoCapture(cam_idx)
                    if cap and cap.isOpened():
                        ret, frame = False, None
                        for _ in range(4):
                            ret, frame = cap.read()
                            time.sleep(0.025)
                        if ret and frame is not None:
                            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                            pil_img = Image.fromarray(rgb)
                            pil_img.thumbnail((960, 720), Image.LANCZOS)
                            self._log("Captured 1 webcam frame and released camera hardware immediately.")
                            return pil_img
                except Exception as e:
                    self._log(f"Webcam capture error on index {cam_idx}: {e}", "WARN")
                finally:
                    if cap is not None:
                        try:
                            cap.release()
                        except Exception:
                            pass
        return None

    @staticmethod
    def get_screen_resolution():
        if os.name == "nt":
            try:
                user32 = ctypes.windll.user32
                return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))
            except Exception:
                pass
        return 1920, 1080


# =====================================================================
# EMOTION-DRIVEN ANIME AVATAR SPRITE BUILDER (ZERO MEMORY LEAK)
# =====================================================================
def remove_bg_clean(img_path):
    """Single-allocation floodfill background remover with soft Gaussian edge feathering."""
    img = cv2.imread(img_path)
    if img is None:
        raise FileNotFoundError(f"Cannot read character image: {img_path}")
    h, w, _ = img.shape
    mask = np.zeros((h + 2, w + 2), np.uint8)
    seeds = (
        [(0, y) for y in range(0, h, 10)]
        + [(w - 1, y) for y in range(0, h, 10)]
        + [(x, 0) for x in range(0, w, 10)]
    )
    bg_color = img[0, 0].astype(np.float32)
    work_img = img.copy()
    for sx, sy in seeds:
        if mask[sy + 1, sx + 1] == 0:
            if np.linalg.norm(img[sy, sx].astype(np.float32) - bg_color) < 25:
                cv2.floodFill(
                    work_img, mask, (sx, sy), (0, 0, 0),
                    (12, 12, 12), (12, 12, 12),
                    flags=4 | (255 << 8) | cv2.FLOODFILL_MASK_ONLY
                )
    diff = np.linalg.norm(img.astype(np.float32) - bg_color, axis=2)
    pocket_bg = (diff < 14).astype(np.uint8) * 255
    pocket_bg[int(h * 0.22):int(h * 0.50), int(w * 0.30):int(w * 0.66)] = 0
    final_bg = cv2.bitwise_or(mask[1:-1, 1:-1], pocket_bg)
    alpha = cv2.GaussianBlur(255 - final_bg, (3, 3), 0)
    rgba = cv2.cvtColor(img, cv2.COLOR_BGR2RGBA)
    rgba[:, :, 3] = alpha
    del work_img, mask, diff, pocket_bg, final_bg
    return Image.fromarray(rgba).resize((736, 900), Image.LANCZOS)


def build_all_emotion_sprites(source_img):
    """
    Generates and caches sprites for all required emotion tags:
    `["teasing", "happy", "focused", "sleepy", "angry_cute", "worried", "talking"]`
    plus 3 amplitude lip-sync mouth frames (`talking_1`, `talking_2`, `talking_3`), `idle`, `listening`, and `hanging`.
    """
    os.makedirs(ASSETS_DIR, exist_ok=True)
    required_files = [
        "idle.png", "teasing.png", "happy.png", "focused.png", "sleepy.png",
        "angry_cute.png", "worried.png", "talking.png",
        "talking_1.png", "talking_2.png", "talking_3.png",
        "listening.png", "hanging.png"
    ]
    if os.path.exists(SPRITE_VERSION_FILE) and all(os.path.exists(os.path.join(ASSETS_DIR, f)) for f in required_files):
        return True

    base = remove_bg_clean(source_img)
    skin_color = (245, 227, 225, 255)
    line_color = (82, 52, 60, 255)
    mouth_dark = (165, 72, 88, 255)
    tongue_pink = (242, 138, 152, 255)

    def erase_mouth(im):
        d = ImageDraw.Draw(im)
        d.ellipse([331, 385, 371, 398], fill=skin_color)
        return im, d

    def add_soft_blush(im, intensity=90):
        overlay = Image.new("RGBA", im.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        od.ellipse([235, 322, 305, 362], fill=(255, 105, 135, intensity))
        od.ellipse([395, 322, 465, 362], fill=(255, 105, 135, intensity))
        overlay = overlay.filter(ImageFilter.GaussianBlur(radius=14))
        return Image.alpha_composite(im, overlay)

    def draw_sparkle(d, cx, cy, size, color=(255, 230, 105, 255)):
        pts = [
            (cx, cy - size), (cx + size * 0.28, cy - size * 0.28),
            (cx + size, cy), (cx + size * 0.28, cy + size * 0.28),
            (cx, cy + size), (cx - size * 0.28, cy + size * 0.28),
            (cx - size, cy), (cx - size * 0.28, cy - size * 0.28),
        ]
        d.polygon(pts, fill=color, outline=(255, 255, 255, 240))

    # 1. IDLE
    base.save(os.path.join(ASSETS_DIR, "idle.png"))

    # 2. LIP-SYNC FRAMES (talking_1 = small, talking_2 = medium, talking_3 = wide)
    t1, d = erase_mouth(base.copy())
    d.ellipse([343, 387, 358, 396], fill=mouth_dark, outline=line_color, width=2)
    t1.save(os.path.join(ASSETS_DIR, "talking_1.png"))

    t2, d = erase_mouth(base.copy())
    d.chord([338, 384, 363, 400], start=0, end=180, fill=mouth_dark, outline=line_color, width=2)
    d.chord([341, 391, 360, 399], start=0, end=180, fill=tongue_pink)
    t2.save(os.path.join(ASSETS_DIR, "talking_2.png"))
    t2.save(os.path.join(ASSETS_DIR, "talking.png"))

    t3, d = erase_mouth(base.copy())
    t3 = add_soft_blush(t3, 75)
    d = ImageDraw.Draw(t3)
    d.chord([334, 380, 367, 406], start=0, end=180, fill=mouth_dark, outline=line_color, width=2)
    d.chord([338, 390, 363, 405], start=0, end=180, fill=tongue_pink)
    t3.save(os.path.join(ASSETS_DIR, "talking_3.png"))

    # 3. HAPPY
    hap, _ = erase_mouth(base.copy())
    hap = add_soft_blush(hap, 95)
    d = ImageDraw.Draw(hap)
    d.arc([334, 380, 367, 398], start=10, end=170, fill=line_color, width=3)
    draw_sparkle(d, 195, 195, 22)
    draw_sparkle(d, 525, 175, 18)
    hap.save(os.path.join(ASSETS_DIR, "happy.png"))

    # 4. TEASING (Smug cat-mouth ":3" + blush + playful heart/sparkle)
    teas, _ = erase_mouth(base.copy())
    teas = add_soft_blush(teas, 130)
    d = ImageDraw.Draw(teas)
    d.arc([335, 385, 351, 396], start=10, end=175, fill=line_color, width=3)
    d.arc([350, 385, 366, 396], start=5, end=170, fill=line_color, width=3)
    # Little playful tongue tip
    d.chord([348, 391, 358, 401], start=0, end=180, fill=tongue_pink, outline=line_color, width=1)
    hx, hy = 528, 192
    d.ellipse([hx - 15, hy - 13, hx + 2, hy + 4], fill=(255, 90, 150, 240))
    d.ellipse([hx - 2, hy - 13, hx + 15, hy + 4], fill=(255, 90, 150, 240))
    d.polygon([(hx - 15, hy - 2), (hx + 15, hy - 2), (hx, hy + 17)], fill=(255, 90, 150, 240))
    teas.save(os.path.join(ASSETS_DIR, "teasing.png"))

    # 5. FOCUSED (Determined mouth + glowing HUD/thought indicator)
    foc, d = erase_mouth(base.copy())
    d.line([(339, 391), (362, 390)], fill=line_color, width=3)
    draw_sparkle(d, 515, 170, 20, (110, 225, 255, 250))
    d.ellipse([520, 95, 645, 162], fill=(25, 22, 42, 235), outline=(120, 220, 255, 255), width=3)
    for dot_x in [555, 582, 609]:
        d.ellipse([dot_x - 6, 123, dot_x + 6, 135], fill=(120, 220, 255, 255))
    foc.save(os.path.join(ASSETS_DIR, "focused.png"))

    # 6. SLEEPY (Soft yawn mouth + floating "Zzz" bubbles)
    slp, _ = erase_mouth(base.copy())
    slp = add_soft_blush(slp, 70)
    d = ImageDraw.Draw(slp)
    d.ellipse([345, 387, 357, 399], fill=tongue_pink, outline=line_color, width=2)
    # Draw cute Zzz symbols
    for zx, zy, sz in [(505, 195, 16), (535, 160, 22), (570, 120, 28)]:
        d.line([(zx, zy), (zx + sz, zy), (zx, zy + sz), (zx + sz, zy + sz)], fill=(175, 155, 255, 245), width=4)
    slp.save(os.path.join(ASSETS_DIR, "sleepy.png"))

    # 7. ANGRY_CUTE (Pouting tsundere mouth + anime anger vein + blush)
    ang, _ = erase_mouth(base.copy())
    ang = add_soft_blush(ang, 115)
    d = ImageDraw.Draw(ang)
    d.polygon([(340, 394), (351, 386), (362, 394)], fill=tongue_pink, outline=line_color)
    vx, vy = 468, 190
    vein_col = (245, 50, 75, 255)
    d.arc([vx - 20, vy - 20, vx - 3, vy - 3], start=0, end=90, fill=vein_col, width=4)
    d.arc([vx + 3, vy - 20, vx + 20, vy - 3], start=90, end=180, fill=vein_col, width=4)
    d.arc([vx - 20, vy + 3, vx - 3, vy + 20], start=270, end=360, fill=vein_col, width=4)
    d.arc([vx + 3, vy + 3, vx + 20, vy + 20], start=180, end=270, fill=vein_col, width=4)
    ang.save(os.path.join(ASSETS_DIR, "angry_cute.png"))

    # 8. WORRIED (Concerned frown + anime sweatdrop)
    wor, d = erase_mouth(base.copy())
    d.arc([337, 390, 364, 402], start=200, end=340, fill=line_color, width=3)
    d.polygon([(245, 295), (236, 320), (254, 320)], fill=(120, 200, 255, 235))
    d.ellipse([236, 313, 254, 331], fill=(120, 200, 255, 235), outline=(70, 140, 220, 255), width=2)
    wor.save(os.path.join(ASSETS_DIR, "worried.png"))

    # 9. LISTENING & HANGING
    lst, d = erase_mouth(base.copy())
    d.arc([338, 384, 363, 396], start=15, end=165, fill=line_color, width=2)
    for r_off in [18, 32, 46]:
        d.arc([475 - r_off, 315 - r_off, 475 + r_off, 315 + r_off], start=-45, end=45, fill=(145, 110, 255, 235), width=4)
    lst.save(os.path.join(ASSETS_DIR, "listening.png"))

    hng, d = erase_mouth(base.copy())
    d.ellipse([345, 388, 357, 399], fill=mouth_dark, outline=line_color, width=2)
    for hx in [195, 525]:
        d.rounded_rectangle([hx - 36, 845, hx + 36, 895], radius=16, fill=skin_color, outline=line_color, width=3)
        for fx in [-12, 0, 12]:
            d.line([(hx + fx, 848), (hx + fx, 888)], fill=line_color, width=2)
    hng.save(os.path.join(ASSETS_DIR, "hanging.png"))

    with open(SPRITE_VERSION_FILE, "w", encoding="utf-8") as f:
        f.write("v6_prod")

    gc.collect()
    return True