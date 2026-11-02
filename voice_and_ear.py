import os
import re
import io
import wave
import json
import time
import base64
import ctypes
import hashlib
import asyncio
import threading
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import edge_tts

from config_and_sprites import VOICE_CACHE_DIR, trim_own_memory
from ai_brain import get_gemini_keys_list

try:
    import speech_recognition as sr
    import sounddevice as sd
    MIC_AVAILABLE = True
except Exception:
    MIC_AVAILABLE = False

LAST_KEYBOARD_PRESS_TIME = 0.0
LAST_MOON_SPOKE_TIME = 0.0

def mark_moon_finished_speaking():
    global LAST_MOON_SPOKE_TIME
    LAST_MOON_SPOKE_TIME = time.time()

def is_laptop_echo_active():
    return (time.time() - LAST_MOON_SPOKE_TIME) < 0.55

def is_user_typing_on_keyboard():
    global LAST_KEYBOARD_PRESS_TIME
    if os.name != "nt":
        return False
    try:
        user32 = ctypes.windll.user32
        keys_to_check = [0x08, 0x09, 0x0D, 0x20] + list(range(0x30, 0x3A)) + list(range(0x41, 0x5B))
        for vk in keys_to_check:
            if user32.GetAsyncKeyState(vk) & 0x8000:
                LAST_KEYBOARD_PRESS_TIME = time.time()
                return True
    except Exception:
        pass
    return (time.time() - LAST_KEYBOARD_PRESS_TIME) < 0.30

WAKE_WORD_PATTERNS = [
    r"\bhello\s+moon\b", r"\bsuno\s+moon\b", r"\bhey\s+moon\b", r"\bhi\s+moon\b",
    r"\boye\s+moon\b", r"\bare\s+moon\b", r"\bmoon\b", r"\bmun\b", r"\bmon\b",
    r"\bmonu\b", r"\bmona\b", r"\bmaun\b", r"\bmood\b", r"\bnoon\b",
    r"हेलो\s*मून", r"सुनो\s*मून", r"हे\s*मून", r"हाय\s*मून",
    r"मून", r"मुन", r"मोन", r"मोनू", r"मोना", r"मौन", r"नून",
    r"^हेलो\b", r"^सुनो\b", r"^अरे\b", r"^ओए\b", r"^hello\b", r"^suno\b", r"^hey\b"
]

def check_and_strip_wake_word(text):
    if not text:
        return False, ""
    clean_in = text.strip()
    low = clean_in.lower()

    matched = False
    for pat in WAKE_WORD_PATTERNS:
        if re.search(pat, low, flags=re.I):
            matched = True
            break

    cleaned = re.sub(
        r"^(?:hello|hey|hi|suno|sun|oye|are|अरे|हेलो|सुनो|हे|हाय|ओए)?\s*(?:moon|मून|मुन|मोन|मोनू|मोना|मौन|mun|mon|monu|mona|maun|noon|नून)?\b[\s,.:!\-]*",
        "",
        clean_in,
        flags=re.I
    ).strip()

    if matched and not cleaned:
        return True, "हेलो मून! तुम कैसी हो?"

    if matched:
        return True, cleaned

    if len(clean_in.split()) >= 2:
        return True, clean_in

    return False, clean_in

VOICE_PROFILES = {
    "gemini_leda": {
        "label": "💎 Gemini Leda HD (Ultra-Natural Emotional Anime Voice - #1 Best!)",
        "type": "gemini_tts",
        "voice": "Leda",
        "fallback_voice": "hi-IN-SwaraNeural",
        "fallback_pitch": "+9Hz",
        "fallback_rate": "+8%",
        "fallback_script": "devanagari"
    },
    "gemini_aoede": {
        "label": "🌸 Gemini Aoede HD (Playful & Sweet Anime Girl Voice)",
        "type": "gemini_tts",
        "voice": "Aoede",
        "fallback_voice": "en-IN-NeerjaExpressiveNeural",
        "fallback_pitch": "+10Hz",
        "fallback_rate": "+8%",
        "fallback_script": "roman"
    },
    "gemini_kore": {
        "label": "🌙 Gemini Kore HD (Soft Caring Waifu Anime Voice)",
        "type": "gemini_tts",
        "voice": "Kore",
        "fallback_voice": "hi-IN-SwaraNeural",
        "fallback_pitch": "+8Hz",
        "fallback_rate": "+7%",
        "fallback_script": "devanagari"
    },
    "gemini_zephyr": {
        "label": "✨ Gemini Zephyr HD (Bright Energetic Anime Girl Voice)",
        "type": "gemini_tts",
        "voice": "Zephyr",
        "fallback_voice": "en-IN-NeerjaExpressiveNeural",
        "fallback_pitch": "+11Hz",
        "fallback_rate": "+9%",
        "fallback_script": "roman"
    },
    "neerja_anime": {
        "label": "🎀 Neerja Cute Anime Dub (Instant Hinglish Anime Voice)",
        "type": "edge",
        "voice": "en-IN-NeerjaExpressiveNeural",
        "pitch": "+10Hz",
        "rate": "+8%",
        "script": "roman"
    }
}

EMOTION_DIRECTIONS = {
    "happy": "Say in a super cute, warm, cheerful, and natural anime girl voice: ",
    "excited": "Say in an excited, bubbly, happy, and energetic anime girl voice: ",
    "shy": "Say in a soft, sweet, bashful, and slightly shy anime girl voice: ",
    "angry": "Say in a cute, playful, pouting tsundere anime girl voice: ",
    "sad": "Say in a gentle, caring, soft, and emotional anime girl voice: ",
    "thinking": "Say in a curious, cute, thoughtful anime girl voice: ",
}

TTS_COOLDOWN = {}
TTS_KEY_IDX = 0

def generate_gemini_hd_tts_multi_key(api_keys_str, text_to_speak, voice_name="Leda", emotion="happy"):
    """
    FAST MULTI-KEY TTS:
    Tries at most 2 healthy keys with a strict 5.5s timeout so voice generation NEVER lags!
    """
    global TTS_KEY_IDX
    api_keys = get_gemini_keys_list(api_keys_str)
    if not api_keys:
        return None

    os.makedirs(VOICE_CACHE_DIR, exist_ok=True)
    clean_text = text_to_speak.strip()
    cache_key = hashlib.md5(f"v16_gem::{voice_name}::{emotion}::{clean_text}".encode("utf-8")).hexdigest()
    cached_wav = os.path.join(VOICE_CACHE_DIR, f"{cache_key}.wav")
    if os.path.exists(cached_wav) and os.path.getsize(cached_wav) > 1000:
        return cached_wav

    direction = EMOTION_DIRECTIONS.get(emotion, EMOTION_DIRECTIONS["happy"])
    directed_text = f"{direction}{clean_text}"

    payload = {
        "contents": [{"parts": [{"text": directed_text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice_name}}
            }
        }
    }
    body_bytes = json.dumps(payload).encode("utf-8")
    now = time.time()

    healthy_keys = [k for k in api_keys if TTS_COOLDOWN.get(k, 0) < now]
    if not healthy_keys:
        return None

    attempts = 0
    for _ in range(len(healthy_keys)):
        if attempts >= 2:
            break
        cur_key = healthy_keys[TTS_KEY_IDX % len(healthy_keys)]
        TTS_KEY_IDX += 1
        attempts += 1

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:generateContent?key={cur_key}"
        req = urllib.request.Request(url, data=body_bytes, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5.5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                b64_pcm = data["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
                pcm_bytes = base64.b64decode(b64_pcm)
                with wave.open(cached_wav, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(24000)
                    wf.writeframes(pcm_bytes)
                return cached_wav
        except urllib.error.HTTPError as he:
            if he.code in (429, 403, 400):
                TTS_COOLDOWN[cur_key] = time.time() + 45.0
            continue
        except Exception:
            continue
    return None

def generate_edge_anime_tts_cached(text_to_speak, voice_name, pitch="+9Hz", rate="+8%"):
    os.makedirs(VOICE_CACHE_DIR, exist_ok=True)
    clean_text = text_to_speak.strip()
    cache_key = hashlib.md5(f"edge_v16::{voice_name}::{pitch}::{rate}::{clean_text}".encode("utf-8")).hexdigest()
    cached_mp3 = os.path.join(VOICE_CACHE_DIR, f"{cache_key}.mp3")
    if os.path.exists(cached_mp3) and os.path.getsize(cached_mp3) > 800:
        return cached_mp3

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        comm = edge_tts.Communicate(clean_text, voice=voice_name, pitch=pitch, rate=rate)
        loop.run_until_complete(asyncio.wait_for(comm.save(cached_mp3), timeout=5.0))
        if os.path.exists(cached_mp3) and os.path.getsize(cached_mp3) > 500:
            return cached_mp3
    except Exception:
        pass
    finally:
        try:
            loop.close()
        except Exception:
            pass
    return None

def play_wav_sounddevice(wav_path):
    try:
        with wave.open(wav_path, "rb") as wf:
            sr_rate = wf.getframerate()
            n_ch = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            raw_bytes = wf.readframes(wf.getnframes())
            dtype = np.int16 if sampwidth == 2 else np.uint8
            audio_np = np.frombuffer(raw_bytes, dtype=dtype)
            if n_ch > 1:
                audio_np = audio_np.reshape(-1, n_ch)
            sd.play(audio_np, samplerate=sr_rate)
            sd.wait()
            return True
    except Exception:
        return False

def play_audio_windows(file_path, max_wait_seconds=20.0):
    if not file_path or not os.path.exists(file_path):
        return
    abs_path = os.path.abspath(file_path)
    ext = os.path.splitext(abs_path)[1].lower()
    if ext == ".wav" and MIC_AVAILABLE:
        if play_wav_sounddevice(abs_path):
            mark_moon_finished_speaking()
            return

    alias = f"moon_snd_{int(time.time() * 1000)}_{threading.get_ident()}"
    winmm = ctypes.windll.winmm
    dev_type = "waveaudio" if ext == ".wav" else "mpegvideo"
    try:
        winmm.mciSendStringW(f'open "{abs_path}" type {dev_type} alias {alias}', None, 0, None)
        winmm.mciSendStringW(f'play {alias}', None, 0, None)

        buf = ctypes.create_unicode_buffer(128)
        start_t = time.time()
        while time.time() - start_t < max_wait_seconds:
            time.sleep(0.05)
            winmm.mciSendStringW(f'status {alias} mode', buf, 128, None)
            mode = buf.value.strip().lower()
            if mode not in ("playing", "seeking"):
                break
    except Exception:
        pass
    finally:
        try:
            winmm.mciSendStringW(f'close {alias}', None, 0, None)
        except Exception:
            pass
        mark_moon_finished_speaking()

# =====================================================================
# 4. HARMONIC HUMAN VOICE DETECTOR (Ignores Background Noise/Fans!)
# =====================================================================
def get_working_input_devices():
    devices = []
    if not MIC_AVAILABLE:
        return devices
    try:
        all_devs = sd.query_devices()
        for idx, d in enumerate(all_devs):
            if d.get("max_input_channels", 0) > 0 and d.get("hostapi", 0) == 0:
                name = d.get("name", f"Mic {idx}")
                if "stereo mix" not in name.lower():
                    devices.append((idx, name))
    except Exception:
        pass
    return devices

def compute_speech_formant_rms(audio_int16, sample_rate=16000, ignore_typing=True):
    """
    Distinguishes Close-Up Human Speech from Background Noise using:
    1) Vocal Band Energy (110Hz - 3400Hz)
    2) Spectral Flatness (Wiener Entropy): Background fan/room noise is flat across frequencies,
       whereas human voice has strong harmonic peaks!
    """
    if is_laptop_echo_active():
        return 0.0
    if ignore_typing and is_user_typing_on_keyboard():
        return 0.0

    samples = audio_int16.astype(np.float32).flatten()
    if len(samples) == 0:
        return 0.0
    samples = samples - np.mean(samples)

    fft_mag = np.abs(np.fft.rfft(samples)) + 1e-6
    freqs = np.fft.rfftfreq(len(samples), d=1.0 / sample_rate)
    voice_mask = (freqs >= 110.0) & (freqs <= 3400.0)
    band_mag = fft_mag[voice_mask]

    if len(band_mag) == 0:
        return 0.0

    # Spectral Flatness = Geometric Mean / Arithmetic Mean (0.0 = pure harmonic voice, 1.0 = white noise)
    geo_mean = float(np.exp(np.mean(np.log(band_mag))))
    arith_mean = float(np.mean(band_mag))
    flatness = geo_mean / max(arith_mean, 1e-6)

    raw_rms = float(np.sqrt(np.mean(samples ** 2)))

    # If the sound is broadband flat noise (flatness > 0.58), suppress its score by 70% so background noise is ignored!
    if flatness > 0.58:
        return raw_rms * 0.30
    return raw_rms

def normalize_and_clean_wav_bytes(audio_int16, sample_rate=16000):
    samples = audio_int16.astype(np.float32).flatten()
    samples = samples - np.mean(samples)

    fft_vals = np.fft.rfft(samples)
    freqs = np.fft.rfftfreq(len(samples), d=1.0 / sample_rate)
    fft_vals[freqs < 80.0] *= 0.1
    clean = np.fft.irfft(fft_vals, n=len(samples))

    peak = float(np.max(np.abs(clean)))
    if peak > 5.0:
        gain = min(24000.0 / peak, 10.0)
        clean = clean * gain

    clean_int16 = np.clip(clean, -32767, 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(clean_int16.tobytes())
    return clean_int16, buf.getvalue()

def recognize_bilingual_fast(recognizer, clean_int16, sample_rate=16000):
    """Fast 3.5-second parallel bilingual STT!"""
    audio_data = sr.AudioData(clean_int16.tobytes(), sample_rate, 2)

    def try_google(lang_code):
        try:
            return recognizer.recognize_google(audio_data, language=lang_code)
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=2) as ex:
        fut_hi = ex.submit(try_google, "hi-IN")
        fut_en = ex.submit(try_google, "en-IN")
        try:
            res_hi = fut_hi.result(timeout=3.5)
        except Exception:
            res_hi = None
        try:
            res_en = fut_en.result(timeout=3.5)
        except Exception:
            res_en = None

    if res_en and re.search(r"\b(moon|mun|mon|monu|hello|suno)\b", res_en, re.I):
        return res_en.strip()
    if res_hi and re.search(r"(मून|मुन|मोन|मोनू|हेलो|सुनो)", res_hi, re.I):
        return res_hi.strip()
    if res_hi and res_hi.strip():
        return res_hi.strip()
    if res_en and res_en.strip():
        return res_en.strip()
    return None

def volume_bar_string(vol, threshold):
    ratio = vol / max(threshold, 1.0)
    if ratio < 0.45:
        return "▂"
    elif ratio < 0.75:
        return "▂▄"
    elif ratio < 1.0:
        return "▂▄▆"
    return "▂▄▆█"