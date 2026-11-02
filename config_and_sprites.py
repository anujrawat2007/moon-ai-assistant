import os
import gc
import sys
import json
import ctypes
import subprocess

REQUIRED_PACKAGES = [
    ("PyQt5", "PyQt5"),
    ("cv2", "opencv-python"),
    ("PIL", "pillow"),
    ("numpy", "numpy"),
    ("edge_tts", "edge-tts"),
    ("pyautogui", "pyautogui"),
    ("psutil", "psutil"),
    ("speech_recognition", "SpeechRecognition"),
    ("sounddevice", "sounddevice"),
]

def ensure_dependencies():
    for mod, pkg in REQUIRED_PACKAGES:
        try:
            __import__(mod)
        except ImportError:
            print(f"[Moon Setup] Installing {pkg}...")
            subprocess.run([sys.executable, "-m", "pip", "install", pkg], check=False)

ensure_dependencies()

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ASSETS_DIR = "moon_assets"
VOICE_CACHE_DIR = os.path.join(ASSETS_DIR, "voice_cache_v14")
SPRITE_VERSION_FILE = os.path.join(ASSETS_DIR, "version_v4.txt")
CONFIG_FILE = "moon_config.json"

DEFAULT_CONFIG = {
    "api_key": "",
    "voice_profile": "gemini_leda",
    "show_subtitles": True,
    "wake_word_only": True,
    "proactive_mode": True,
    "save_gemini_for_voice": False,
    "mic_device_index": None
}

def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                cfg.update(saved)
        except Exception:
            pass
    return cfg

def save_config_file(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[Config Save Notice]: {e}")

def trim_own_memory():
    try:
        gc.collect()
        if os.name == "nt":
            ctypes.windll.kernel32.SetProcessWorkingSetSize(-1, -1, -1)
    except Exception:
        pass

def remove_bg(img_path):
    img = cv2.imread(img_path)
    if img is None:
        raise FileNotFoundError(f"Cannot read image: {img_path}")
    h, w, _ = img.shape
    mask = np.zeros((h + 2, w + 2), np.uint8)
    seeds = (
        [(0, y) for y in range(0, h, 10)]
        + [(w - 1, y) for y in range(0, h, 10)]
        + [(x, 0) for x in range(0, w, 10)]
    )
    bg_color = img[0, 0].astype(np.float32)
    for sx, sy in seeds:
        if np.linalg.norm(img[sy, sx].astype(np.float32) - bg_color) < 25:
            cv2.floodFill(
                img.copy(), mask, (sx, sy), (0, 0, 0),
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
    return Image.fromarray(rgba).resize((736, 900), Image.LANCZOS)

def build_sprites_if_needed(source_img):
    os.makedirs(ASSETS_DIR, exist_ok=True)
    os.makedirs(VOICE_CACHE_DIR, exist_ok=True)
    if os.path.exists(SPRITE_VERSION_FILE) and os.path.exists(os.path.join(ASSETS_DIR, "excited.png")):
        return True

    base = remove_bg(source_img)
    skin_color = (245, 227, 225, 255)
    line_color = (82, 52, 60, 255)
    mouth_dark = (165, 72, 88, 255)
    tongue_pink = (242, 138, 152, 255)

    def erase_mouth(im):
        d = ImageDraw.Draw(im)
        d.ellipse([331, 386, 370, 397], fill=skin_color)
        return im, d

    def add_soft_blush(im, intensity=80):
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

    base.save(os.path.join(ASSETS_DIR, "idle.png"))

    t1, d = erase_mouth(base.copy())
    d.chord([339, 385, 362, 399], start=0, end=180, fill=mouth_dark, outline=line_color, width=2)
    d.chord([342, 391, 359, 398], start=0, end=180, fill=tongue_pink)
    t1.save(os.path.join(ASSETS_DIR, "talking_1.png"))

    t2, d = erase_mouth(base.copy())
    d.chord([335, 381, 366, 405], start=0, end=180, fill=mouth_dark, outline=line_color, width=2)
    d.chord([339, 391, 362, 404], start=0, end=180, fill=tongue_pink)
    t2.save(os.path.join(ASSETS_DIR, "talking_2.png"))

    hap, _ = erase_mouth(base.copy())
    hap = add_soft_blush(hap, 85)
    d = ImageDraw.Draw(hap)
    d.arc([334, 380, 367, 397], start=12, end=168, fill=line_color, width=3)
    draw_sparkle(d, 195, 195, 22)
    draw_sparkle(d, 525, 175, 18)
    hap.save(os.path.join(ASSETS_DIR, "happy.png"))

    exc, _ = erase_mouth(base.copy())
    exc = add_soft_blush(exc, 105)
    d = ImageDraw.Draw(exc)
    d.chord([334, 381, 367, 403], start=0, end=180, fill=mouth_dark, outline=line_color, width=2)
    d.chord([338, 390, 363, 402], start=0, end=180, fill=tongue_pink)
    draw_sparkle(d, 185, 175, 26, (255, 215, 70, 255))
    draw_sparkle(d, 540, 165, 24, (255, 215, 70, 255))
    exc.save(os.path.join(ASSETS_DIR, "excited.png"))

    shy, _ = erase_mouth(base.copy())
    shy = add_soft_blush(shy, 135)
    d = ImageDraw.Draw(shy)
    d.arc([336, 386, 351, 395], start=10, end=175, fill=line_color, width=2)
    d.arc([350, 386, 365, 395], start=5, end=170, fill=line_color, width=2)
    hx, hy = 525, 195
    d.ellipse([hx - 16, hy - 14, hx + 2, hy + 4], fill=(255, 95, 145, 240))
    d.ellipse([hx - 2, hy - 14, hx + 16, hy + 4], fill=(255, 95, 145, 240))
    d.polygon([(hx - 16, hy - 2), (hx + 16, hy - 2), (hx, hy + 18)], fill=(255, 95, 145, 240))
    shy.save(os.path.join(ASSETS_DIR, "shy.png"))

    ang, d = erase_mouth(base.copy())
    d.polygon([(341, 394), (351, 387), (361, 394)], fill=tongue_pink, outline=line_color)
    vx, vy = 468, 190
    vein_col = (240, 45, 65, 255)
    d.arc([vx - 20, vy - 20, vx - 3, vy - 3], start=0, end=90, fill=vein_col, width=4)
    d.arc([vx + 3, vy - 20, vx + 20, vy - 3], start=90, end=180, fill=vein_col, width=4)
    d.arc([vx - 20, vy + 3, vx - 3, vy + 20], start=270, end=360, fill=vein_col, width=4)
    d.arc([vx + 3, vy + 3, vx + 20, vy + 20], start=180, end=270, fill=vein_col, width=4)
    ang.save(os.path.join(ASSETS_DIR, "angry.png"))

    sad, d = erase_mouth(base.copy())
    d.arc([337, 390, 364, 402], start=200, end=340, fill=line_color, width=2)
    d.polygon([(245, 305), (238, 324), (252, 324)], fill=(120, 195, 255, 230))
    d.ellipse([238, 318, 252, 332], fill=(120, 195, 255, 230), outline=(70, 140, 220, 255), width=2)
    sad.save(os.path.join(ASSETS_DIR, "sad.png"))

    thk, d = erase_mouth(base.copy())
    d.ellipse([346, 388, 356, 398], fill=mouth_dark, outline=line_color, width=2)
    d.ellipse([485, 195, 500, 210], fill=(255, 255, 255, 235), outline=line_color, width=2)
    d.ellipse([505, 165, 528, 188], fill=(255, 255, 255, 235), outline=line_color, width=2)
    d.ellipse([520, 95, 645, 165], fill=(255, 255, 255, 245), outline=line_color, width=3)
    for dot_x in [555, 582, 609]:
        d.ellipse([dot_x - 6, 125, dot_x + 6, 137], fill=(120, 100, 160, 255))
    thk.save(os.path.join(ASSETS_DIR, "thinking.png"))

    lst, d = erase_mouth(base.copy())
    d.arc([338, 384, 363, 396], start=15, end=165, fill=line_color, width=2)
    for r_off in [18, 32, 46]:
        d.arc([475 - r_off, 315 - r_off, 475 + r_off, 315 + r_off], start=-45, end=45, fill=(138, 105, 245, 230), width=4)
    lst.save(os.path.join(ASSETS_DIR, "listening.png"))

    hng, d = erase_mouth(base.copy())
    d.ellipse([345, 388, 357, 399], fill=mouth_dark, outline=line_color, width=2)
    for hx in [195, 525]:
        d.rounded_rectangle([hx - 36, 845, hx + 36, 895], radius=16, fill=skin_color, outline=line_color, width=3)
        for fx in [-12, 0, 12]:
            d.line([(hx + fx, 848), (hx + fx, 888)], fill=line_color, width=2)
    hng.save(os.path.join(ASSETS_DIR, "hanging.png"))

    with open(SPRITE_VERSION_FILE, "w") as f:
        f.write("v4")
    trim_own_memory()
    return True