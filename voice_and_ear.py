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

if os.name == "nt":
    import winsound

from config_and_sprites import VOICE_CACHE_DIR

try:
    import speech_recognition as sr
    import sounddevice as sd
    MIC_AVAILABLE = True
except Exception:
    MIC_AVAILABLE = False

LAST_MOON_SPOKE_TIME = 0.0
STOP_AUDIO_FLAG = False
GEMINI_TTS_PROJECT_EXHAUSTED_UNTIL = 0.0
_STT_EXECUTOR = ThreadPoolExecutor(max_workers=2)

# =====================================================================
# SMART HINGLISH & WAKE-WORD AUTO-CORRECTOR
# Fixes Google STT turning "Hello Moon" into "Hello Google" / "Hello मोहन"
# =====================================================================
PHONETIC_CORRECTIONS = {
    r"\b(hello|hey|hi|oye|suno|are)\s+(?:google|mohan|mona|monu|mun|mon|noon|room|phone|poon|mahal|mool)\b": r"\1 moon",
    r"(हेलो|हे|हाय|ओए|सुनो|अरे)\s*(?:गूगल|मोहन|मोना|मोनू|मुन|मोन|नून|रूम|फोन)": r"\1 मून",
    r"\b(mun|mon|monu|mona|maun|noon)\b": "moon",
    r"(मुन|मोन|मोनू|मोना|मौन|नून)": "मून",
    r"\b(ri\s*fresh|re\s*fresh|refesh|rifresh)\b": "refresh",
    r"(रिफ्रेश|री\s*फ्रेश|रेफ्रेश)": "refresh",
    r"\b(vs\s*kod|v\s*s\s*code|visual\s*code)\b": "vscode",
    r"\b(krom|krome|crome)\b": "chrome",
    r"\b(u\s*tube|you\s*tube|utube)\b": "youtube",
}


def autocorrect_hinglish_stt(raw_text):
    if not raw_text:
        return ""
    txt = raw_text.strip()
    for pat, repl in PHONETIC_CORRECTIONS.items():
        txt = re.sub(pat, repl, txt, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", txt).strip()


def extract_valid_gemini_keys(api_keys_str):
    keys = []
    if api_keys_str:
        for k in re.split(r"[,;\n\s]+", api_keys_str.strip()):
            k = k.strip()
            if len(k) >= 25 and not k.startswith("YOUR_") and not k.startswith(("gsk_", "sk-")):
                keys.append(k)
    if not keys and os.path.exists("api_pool.json"):
        try:
            with open("api_pool.json", "r", encoding="utf-8") as f:
                pdata = json.load(f)
                for item in pdata.get("keys", []):
                    k = item.get("key", "").strip()
                    if len(k) >= 25 and k not in keys:
                        keys.append(k)
        except Exception:
            pass
    return keys


def stop_current_playback():
    global STOP_AUDIO_FLAG
    STOP_AUDIO_FLAG = True
    if os.name == "nt":
        try:
            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass
        try:
            ctypes.windll.winmm.mciSendStringW("stop all", None, 0, None)
        except Exception:
            pass


def mark_moon_finished_speaking():
    global LAST_MOON_SPOKE_TIME
    LAST_MOON_SPOKE_TIME = time.time()


def is_laptop_echo_active():
    return (time.time() - LAST_MOON_SPOKE_TIME) < 0.65


# Require 'moon' or explicit wake phrase so random words never false-trigger!
WAKE_WORD_PATTERNS = [
    r"\bhello\s+moon\b", r"\bsuno\s+moon\b", r"\bhey\s+moon\b", r"\bhi\s+moon\b",
    r"\boye\s+moon\b", r"\bare\s+moon\b", r"\bmoon\b", r"\bsuzune\b",
    r"हेलो\s*मून", r"सुनो\s*मून", r"हे\s*मून", r"हाय\s*मून", r"मून", r"सुजुने"
]


def check_and_strip_wake_word(text):
    if not text:
        return False, ""
    clean_in = autocorrect_hinglish_stt(text)
    low = clean_in.lower()
    if not any(re.search(pat, low, flags=re.I) for pat in WAKE_WORD_PATTERNS):
        return False, clean_in

    cleaned = re.sub(
        r"^(?:hello|hey|hi|suno|sun|oye|are|अरे|हेलो|सुनो|हे|हाय|ओए)?\s*(?:moon|मून|suzune|सुजुने)\b[\s,.:!\-]*",
        "", clean_in, flags=re.I
    ).strip()
    return True, (cleaned if cleaned else "हेलो मून")


# =====================================================================
# RICH MULTI-VOICE PROFILES (Gemini HD Neural + Edge Waifu Voices)
# =====================================================================
VOICE_PROFILES = {
    "gemini_zephyr": {
        "label": "🌸 Gemini Zephyr HD (Warm & Playful Anime Friend)",
        "type": "gemini_tts",
        "voice": "Zephyr",
        "fallback_voice": "hi-IN-SwaraNeural",
        "fallback_pitch": "+12Hz",
        "fallback_rate": "+8%",
        "fallback_script": "devanagari"
    },
    "gemini_leda": {
        "label": "💎 Gemini Leda HD (Cute Natural Hindi + English Anime Voice)",
        "type": "gemini_tts",
        "voice": "Leda",
        "fallback_voice": "hi-IN-SwaraNeural",
        "fallback_pitch": "+6Hz",
        "fallback_rate": "+6%",
        "fallback_script": "devanagari"
    },
    "gemini_aoede": {
        "label": "✨ Gemini Aoede HD (Sweet High-Energy Anime Voice)",
        "type": "gemini_tts",
        "voice": "Aoede",
        "fallback_voice": "hi-IN-SwaraNeural",
        "fallback_pitch": "+14Hz",
        "fallback_rate": "+10%",
        "fallback_script": "devanagari"
    },
    "swara_anime": {
        "label": "🎀 Swara Neural Anime (Ultra-Fast Natural Hindi TTS)",
        "type": "edge_tts",
        "voice": "hi-IN-SwaraNeural",
        "pitch": "+12Hz",
        "rate": "+8%",
        "script": "devanagari"
    },
    "ana_cute": {
        "label": "🍭 Ana Sweet Waifu (Cute English + Anime Accent)",
        "type": "edge_tts",
        "voice": "en-US-AnaNeural",
        "pitch": "+10Hz",
        "rate": "+8%",
        "script": "roman"
    },
    "nanami_waifu": {
        "label": "🎌 Nanami Waifu (Japanese Anime Girl Accent)",
        "type": "edge_tts",
        "voice": "ja-JP-NanamiNeural",
        "pitch": "+10Hz",
        "rate": "+5%",
        "script": "roman"
    }
}


def sanitize_tts_text(text):
    if not text:
        return ""
    txt = re.sub(r"^(?:say|speak)(?:\s+in\b)?\s*.*?:", "", text, flags=re.IGNORECASE).strip()
    txt = re.sub(r"\*\*([^*]+)\*\*", r"\1", txt)
    txt = re.sub(r"\*([^*]+)\*", r"\1", txt)
    txt = re.sub(r"\[[^\]]+\]|\([^\)]+\)", "", txt).strip()
    emoji_pattern = re.compile(
        "[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]|[\u2b50-\u2b55]|[\ufe0f]",
        flags=re.UNICODE
    )
    txt = emoji_pattern.sub("", txt)
    return re.sub(r"\s+", " ", txt).strip()


TTS_COOLDOWN = {}
TTS_KEY_IDX = 0


def generate_gemini_hd_tts_multi_key(api_keys_str, text_to_speak, voice_name="Zephyr", emotion="happy"):
    """
    Ultra-resilient Gemini Neural TTS with seamless multi-key load balancing.
    Never blocks all keys when a single key is rate-limited!
    """
    global TTS_KEY_IDX
    now = time.time()

    api_keys = extract_valid_gemini_keys(api_keys_str)
    if not api_keys:
        return None

    os.makedirs(VOICE_CACHE_DIR, exist_ok=True)
    clean_text = sanitize_tts_text(text_to_speak) or text_to_speak.strip()
    target_voice = voice_name or "Zephyr"
    cache_key = hashlib.md5(f"v46_gemini::{target_voice}::{clean_text}".encode("utf-8")).hexdigest()
    cached_wav = os.path.join(VOICE_CACHE_DIR, f"{cache_key}.wav")
    if os.path.exists(cached_wav) and os.path.getsize(cached_wav) > 1000:
        return cached_wav

    payload = {
        "contents": [{"parts": [{"text": clean_text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": target_voice}}
            }
        }
    }
    body_bytes = json.dumps(payload).encode("utf-8")
    healthy_keys = [k for k in api_keys if TTS_COOLDOWN.get(k, 0) < now]
    if not healthy_keys:
        return None

    keys_to_attempt = [healthy_keys[(TTS_KEY_IDX + i) % len(healthy_keys)] for i in range(len(healthy_keys))]
    TTS_KEY_IDX = (TTS_KEY_IDX + 1) % len(healthy_keys)

    models_to_try = ["gemini-2.5-flash-preview-tts", "gemini-2.0-flash"]

    for cur_key in keys_to_attempt:
        for model_name in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={cur_key}"
            req = urllib.request.Request(url, data=body_bytes, headers={"Content-Type": "application/json"}, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=6.0) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    cand = data.get("candidates", [{}])[0]
                    parts = cand.get("content", {}).get("parts", [{}])
                    inline = parts[0].get("inlineData", {})
                    b64_pcm = inline.get("data")
                    if b64_pcm:
                        pcm_bytes = base64.b64decode(b64_pcm)
                        with wave.open(cached_wav, "wb") as wf:
                            wf.setnchannels(1)
                            wf.setsampwidth(2)
                            wf.setframerate(24000)
                            wf.writeframes(pcm_bytes)
                        print(f"💎 [Gemini {target_voice} HD Voice]: Key ...{cur_key[-4:]}")
                        return cached_wav
            except urllib.error.HTTPError as he:
                if he.code in (400, 401, 403, 429):
                    TTS_COOLDOWN[cur_key] = time.time() + 180.0
                    break
                continue
            except Exception:
                continue
    return None


def generate_edge_anime_tts_cached(text_to_speak, voice_name="hi-IN-SwaraNeural", pitch="+12Hz", rate="+8%"):
    os.makedirs(VOICE_CACHE_DIR, exist_ok=True)
    clean_text = sanitize_tts_text(text_to_speak) or text_to_speak.strip()
    cache_key = hashlib.md5(f"edge_v46_nat::{voice_name}::{pitch}::{rate}::{clean_text}".encode("utf-8")).hexdigest()
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


def play_audio_windows(file_path, max_wait_seconds=22.0):
    global STOP_AUDIO_FLAG
    STOP_AUDIO_FLAG = False
    if not file_path or not os.path.exists(file_path):
        return
    abs_path = os.path.abspath(file_path)
    ext = os.path.splitext(abs_path)[1].lower()

    if ext == ".wav" and os.name == "nt":
        try:
            with wave.open(abs_path, "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                duration_s = frames / float(max(rate, 1))

            winsound.PlaySound(abs_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
            start_t = time.perf_counter()
            while (time.perf_counter() - start_t) < min(duration_s + 0.15, max_wait_seconds):
                if STOP_AUDIO_FLAG:
                    winsound.PlaySound(None, winsound.SND_PURGE)
                    break
                time.sleep(0.03)
            mark_moon_finished_speaking()
            return
        except Exception as e:
            print(f"[winsound Notice]: {e}")

    # Use Short Path for MCI so spaces in Windows paths never cause MCI 259 error
    mci_path = abs_path
    if os.name == "nt":
        try:
            buf = ctypes.create_unicode_buffer(512)
            if ctypes.windll.kernel32.GetShortPathNameW(abs_path, buf, 512) > 0:
                mci_path = buf.value
        except Exception:
            mci_path = abs_path

    alias = f"moon_snd_{int(time.time() * 1000)}_{threading.get_ident()}"
    winmm = ctypes.windll.winmm
    dev_type = "waveaudio" if ext == ".wav" else "mpegvideo"
    try:
        winmm.mciSendStringW(f'open "{mci_path}" type {dev_type} alias {alias}', None, 0, None)
        winmm.mciSendStringW(f"setaudio {alias} volume to 1000", None, 0, None)
        winmm.mciSendStringW(f"play {alias}", None, 0, None)
        buf = ctypes.create_unicode_buffer(128)
        start_t = time.time()
        while time.time() - start_t < max_wait_seconds:
            if STOP_AUDIO_FLAG:
                winmm.mciSendStringW(f"stop {alias}", None, 0, None)
                break
            time.sleep(0.04)
            winmm.mciSendStringW(f"status {alias} mode", buf, 128, None)
            if buf.value.strip().lower() not in ("playing", "seeking"):
                break
    except Exception:
        pass
    finally:
        try:
            winmm.mciSendStringW(f"close {alias}", None, 0, None)
        except Exception:
            pass
        mark_moon_finished_speaking()


def get_working_input_devices():
    devices = []
    if not MIC_AVAILABLE:
        return devices
    try:
        for idx, d in enumerate(sd.query_devices()):
            if d.get("max_input_channels", 0) > 0 and d.get("hostapi", 0) == 0:
                name = d.get("name", f"Mic {idx}")
                if "stereo mix" not in name.lower():
                    devices.append((idx, name))
    except Exception:
        pass
    return devices


def compute_speech_formant_rms(audio_int16, sample_rate=16000, ignore_typing=False):
    if is_laptop_echo_active():
        return 0.0
    samples = audio_int16.astype(np.float32).flatten()
    if len(samples) < 32:
        return 0.0
    samples = samples - np.mean(samples)
    return float(np.sqrt(np.mean(samples ** 2)))


def normalize_and_clean_wav_bytes(audio_int16, sample_rate=16000):
    samples = audio_int16.astype(np.float32).flatten()
    samples = samples - np.mean(samples)

    peak = float(np.max(np.abs(samples)))
    if peak > 8.0:
        gain = min(24000.0 / peak, 9.0)
        samples = samples * gain

    clean_int16 = np.clip(samples, -32767, 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(clean_int16.tobytes())
    return clean_int16, buf.getvalue()


def recognize_bilingual_fast(recognizer, clean_int16, sample_rate=16000):
    audio_data = sr.AudioData(clean_int16.tobytes(), sample_rate, 2)

    def try_google(lang_code):
        try:
            return recognizer.recognize_google(audio_data, language=lang_code)
        except Exception:
            return None

    fut_hi = _STT_EXECUTOR.submit(try_google, "hi-IN")
    fut_en = _STT_EXECUTOR.submit(try_google, "en-IN")
    try:
        res_hi = fut_hi.result(timeout=3.2)
    except Exception:
        res_hi = None
    try:
        res_en = fut_en.result(timeout=3.2)
    except Exception:
        res_en = None

    res_en_clean = autocorrect_hinglish_stt(res_en) if res_en else ""
    res_hi_clean = autocorrect_hinglish_stt(res_hi) if res_hi else ""

    if res_en_clean and re.search(r"\b(moon|suzune)\b", res_en_clean, re.I):
        return res_en_clean
    if res_hi_clean and re.search(r"(मून|सुजुने)", res_hi_clean, re.I):
        return res_hi_clean
    if res_hi_clean:
        return res_hi_clean
    if res_en_clean:
        return res_en_clean
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