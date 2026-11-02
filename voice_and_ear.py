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

from config_and_sprites import VOICE_CACHE_DIR

try:
    import speech_recognition as sr
    import sounddevice as sd
    MIC_AVAILABLE = True
except Exception:
    MIC_AVAILABLE = False

LAST_MOON_SPOKE_TIME = 0.0


def mark_moon_finished_speaking():
    global LAST_MOON_SPOKE_TIME
    LAST_MOON_SPOKE_TIME = time.time()


def is_laptop_echo_active():
    return (time.time() - LAST_MOON_SPOKE_TIME) < 0.65


def get_gemini_keys_list(api_key_str):
    if not api_key_str:
        return []
    return [k.strip() for k in re.split(r"[,;\n]+", api_key_str) if k.strip()]


# STRICT "MOON" WAKE-WORD PATTERNS ONLY
WAKE_WORD_PATTERNS = [
    r"\bmoon\b", r"\bmun\b", r"\bmon\b", r"\bmonu\b", r"\bmona\b", r"\bmaun\b", r"\bnoon\b",
    r"मून", r"मुन", r"मोन", r"मोनू", r"मोना", r"मौन", r"नून"
]


def check_and_strip_wake_word(text):
    """
    STRICT WAKE-WORD CHECK:
    Triggers ONLY if the user actually says 'Moon' (or phonetic variations like मून/mun/mon)
    alone or with other words! Never triggers on random background talk.
    """
    if not text:
        return False, ""
    clean_in = text.strip()
    low = clean_in.lower()

    matched = False
    for pat in WAKE_WORD_PATTERNS:
        if re.search(pat, low, flags=re.I):
            matched = True
            break

    if not matched:
        return False, clean_in

    # Remove leading greeting + "Moon" if at the start of the sentence
    cleaned = re.sub(
        r"^(?:hello|hey|hi|suno|sun\s+na|sun|oye|are|अरे|हेलो|सुनो|हे|हाय|ओए)?\s*"
        r"(?:moon|मून|मुन|मोन|मोनू|मोना|मौन|mun|mon|monu|mona|maun|noon|नून)\s*"
        r"(?:yaar|यार|जी|ji|babe|baby)?\b[\s,.:!\-]*",
        "",
        clean_in,
        flags=re.I
    ).strip()

    # Also strip trailing "Moon" if user said e.g. "YouTube kholo Moon"
    cleaned = re.sub(
        r"[\s,.:!\-]*\b(?:moon|मून|मुन|मोन|mun|mon)\s*$",
        "",
        cleaned,
        flags=re.I
    ).strip()

    # If the user ONLY said "Moon" or "Hello Moon", greet them back warmly
    if not cleaned:
        return True, "हेलो मून! सुनो"

    return True, cleaned


# LOCKED TO ONLY GEMINI LEDA CUTE VOICE
VOICE_PROFILES = {
    "gemini_leda": {
        "label": "💎 Gemini Leda HD (Cute Emotional Anime Voice)",
        "type": "gemini_tts",
        "voice": "Leda",
        "fallback_voice": "hi-IN-SwaraNeural",
        "fallback_pitch": "+12Hz",
        "fallback_rate": "+8%",
        "fallback_script": "devanagari"
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
    10+ API KEY ROTATOR FOR GEMINI LEDA VOICE:
    Rotates across ALL healthy keys in your list (no 2-attempt limit!) so Leda voice never drops out.
    """
    global TTS_KEY_IDX
    api_keys = get_gemini_keys_list(api_keys_str)
    if not api_keys:
        return None

    os.makedirs(VOICE_CACHE_DIR, exist_ok=True)
    clean_text = text_to_speak.strip()
    cache_key = hashlib.md5(f"v19_leda::{voice_name}::{emotion}::{clean_text}".encode("utf-8")).hexdigest()
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
                "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Leda"}}
            }
        }
    }
    body_bytes = json.dumps(payload).encode("utf-8")
    now = time.time()

    healthy_keys = [k for k in api_keys if TTS_COOLDOWN.get(k, 0) < now]
    if not healthy_keys:
        healthy_keys = api_keys

    # Try across ALL available keys in the pool (up to 15 keys)
    for _ in range(len(healthy_keys)):
        cur_key = healthy_keys[TTS_KEY_IDX % len(healthy_keys)]
        TTS_KEY_IDX += 1

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:generateContent?key={cur_key}"
        req = urllib.request.Request(url, data=body_bytes, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=8.5) as resp:
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
            if he.code == 429:
                TTS_COOLDOWN[cur_key] = time.time() + 30.0
            elif he.code in (400, 401, 403):
                TTS_COOLDOWN[cur_key] = time.time() + 300.0
            continue
        except Exception:
            continue
    return None


def generate_edge_anime_tts_cached(text_to_speak, voice_name="hi-IN-SwaraNeural", pitch="+12Hz", rate="+8%"):
    os.makedirs(VOICE_CACHE_DIR, exist_ok=True)
    clean_text = text_to_speak.strip()
    cache_key = hashlib.md5(f"edge_v19::{voice_name}::{pitch}::{rate}::{clean_text}".encode("utf-8")).hexdigest()
    cached_mp3 = os.path.join(VOICE_CACHE_DIR, f"{cache_key}.mp3")
    if os.path.exists(cached_mp3) and os.path.getsize(cached_mp3) > 800:
        return cached_mp3

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        comm = edge_tts.Communicate(clean_text, voice=voice_name, pitch=pitch, rate=rate)
        loop.run_until_complete(asyncio.wait_for(comm.save(cached_mp3), timeout=6.0))
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


def play_audio_windows(file_path, max_wait_seconds=22.0):
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
# CLEAR OPEN-MIC VOICE DETECTOR (Works Without Earphones!)
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


def compute_speech_formant_rms(audio_int16, sample_rate=16000, ignore_typing=False):
    """
    Tuned for Laptop/PC Open Microphones (WITHOUT Earphones):
    Measures human vocal band energy (150Hz - 3800Hz) without crushing distant speech,
    while rejecting steady low-frequency fan hum (<130Hz).
    """
    if is_laptop_echo_active():
        return 0.0

    samples = audio_int16.astype(np.float32).flatten()
    if len(samples) == 0:
        return 0.0
    samples = samples - np.mean(samples)

    fft_mag = np.abs(np.fft.rfft(samples)) + 1e-6
    freqs = np.fft.rfftfreq(len(samples), d=1.0 / sample_rate)

    # Human voice band (150Hz to 3800Hz) vs Low fan rumble (<130Hz)
    voice_mask = (freqs >= 150.0) & (freqs <= 3800.0)
    band_mag = fft_mag[voice_mask]
    if len(band_mag) == 0:
        return 0.0

    # Compute RMS specifically in the human vocal frequency band
    vocal_rms = float(np.sqrt(np.mean(band_mag ** 2)) / np.sqrt(len(samples)))
    return vocal_rms


def normalize_and_clean_wav_bytes(audio_int16, sample_rate=16000):
    """
    Far-Field Open-Mic Voice Enhancer:
    - Removes fan rumble (<120Hz) and high-frequency hiss (>4200Hz)
    - Uses percentile-based Auto-Gain Control (98th percentile instead of single-sample peak)
      so a mouse click or tap doesn't make the user's voice quiet!
    """
    samples = audio_int16.astype(np.float32).flatten()
    if len(samples) == 0:
        return audio_int16, b""
    samples = samples - np.mean(samples)

    fft_vals = np.fft.rfft(samples)
    freqs = np.fft.rfftfreq(len(samples), d=1.0 / sample_rate)
    fft_vals[freqs < 120.0] *= 0.08
    fft_vals[freqs > 4400.0] *= 0.25
    clean = np.fft.irfft(fft_vals, n=len(samples))

    # Percentile AGC so open-mic voice is boosted clearly even if there was a click
    p98 = float(np.percentile(np.abs(clean), 98))
    if p98 > 8.0:
        gain = min(18000.0 / p98, 14.0)
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
    """Accurate Bilingual (Hinglish: hi-IN + en-IN) Speech-to-Text."""
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
            res_hi = fut_hi.result(timeout=4.5)
        except Exception:
            res_hi = None
        try:
            res_en = fut_en.result(timeout=4.5)
        except Exception:
            res_en = None

    # Prefer whichever transcript clearly captured the wake-word "Moon"
    if res_en and re.search(r"\b(moon|mun|mon|monu)\b", res_en, re.I):
        return res_en.strip()
    if res_hi and re.search(r"(मून|मुन|मोन|मोनू)", res_hi, re.I):
        return res_hi.strip()
    if res_hi and res_hi.strip():
        return res_hi.strip()
    if res_en and res_en.strip():
        return res_en.strip()
    return None


def volume_bar_string(vol, threshold):
    ratio = vol / max(threshold, 1.0)
    if ratio < 0.5:
        return "▂"
    elif ratio < 0.85:
        return "▂▄"
    elif ratio < 1.15:
        return "▂▄▆"
    return "▂▄▆█"