import os
import sys
import math
import time
import threading
from collections import deque
import numpy as np
import psutil
import sounddevice as sd
import speech_recognition as sr

from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit, QMenu, QActionGroup,
    QInputDialog, QFileDialog, QMessageBox
)
from PyQt5.QtCore import Qt, QTimer, QPoint, pyqtSignal, QObject
from PyQt5.QtGui import QPixmap, QFont

from config_and_sprites import (
    ASSETS_DIR, SPRITE_VERSION_FILE, load_config, save_config_file,
    build_sprites_if_needed, trim_own_memory
)
from system_tools import (
    real_system_ram_cleaner, scan_all_installed_pc_apps,
    capture_desktop_screen, capture_webcam,
    execute_agent_steps_with_verification, get_clipboard_text_windows
)
from ai_brain import (
    MODEL_COOLDOWN, KEY_COOLDOWN, needs_webcam_vision, needs_screen_vision,
    call_resilient_multi_brain, get_gemini_keys_list
)
from voice_and_ear import (
    MIC_AVAILABLE, VOICE_PROFILES, TTS_COOLDOWN,
    check_and_strip_wake_word, generate_gemini_hd_tts_multi_key,
    generate_edge_anime_tts_cached, play_audio_windows, stop_current_playback,
    get_working_input_devices, compute_speech_formant_rms,
    normalize_and_clean_wav_bytes, recognize_bilingual_fast,
    volume_bar_string, sanitize_tts_text
)


class MoonSignals(QObject):
    set_emotion = pyqtSignal(str)
    show_bubble = pyqtSignal(str, int)
    set_status = pyqtSignal(str)
    start_lipsync = pyqtSignal()
    stop_lipsync = pyqtSignal(str)


class MoonDesktopWidget(QWidget):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.api_key = config.get("api_key", "")
        v_prof = config.get("voice_profile", "gemini_zephyr")
        if v_prof not in VOICE_PROFILES:
            v_prof = "gemini_zephyr"
        self.voice_profile = v_prof
        self.show_subtitles = config.get("show_subtitles", True)
        self.wake_word_only = config.get("wake_word_only", True)
        self.proactive_mode = config.get("proactive_mode", False)
        self.save_gemini_for_voice = config.get("save_gemini_for_voice", False)
        self.mic_device_index = config.get("mic_device_index", None)

        self.chat_history = []
        self.pixmap_cache = {}
        self.speech_lock = threading.Lock()

        self.signals = MoonSignals()
        self.signals.set_emotion.connect(self.update_sprite)
        self.signals.show_bubble.connect(self.display_speech_bubble)
        self.signals.set_status.connect(self.update_status_pill)
        self.signals.start_lipsync.connect(self.begin_lipsync)
        self.signals.stop_lipsync.connect(self.end_lipsync)

        self.current_emotion = "idle"
        self.lip_frame = 0
        self.voice_enabled = not bool(config.get("mic_muted", False))
        self.is_speaking = False
        self.is_processing = False
        self.is_listening_active = False
        self.force_listen_now = False
        self.finish_listen_now = False
        self.restart_mic_flag = False
        self.state_lock_timestamp = 0.0
        self.last_mic_heartbeat = time.time()
        self.last_interaction_time = time.time()
        self.active_convo_until = 0.0
        self.breath_phase = 0.0
        self.base_sprite_y = 65

        self.press_global_pos = QPoint()
        self.window_start_pos = QPoint()
        self.is_dragging = False

        self.preload_sprite_cache()
        self.init_ui()

        threading.Thread(target=scan_all_installed_pc_apps, daemon=True).start()

        self.lip_timer = QTimer(self)
        self.lip_timer.timeout.connect(self.animate_mouth)

        self.breath_timer = QTimer(self)
        self.breath_timer.timeout.connect(self.animate_breathing)
        self.breath_timer.start(50)

        self.watchdog_timer = QTimer(self)
        self.watchdog_timer.timeout.connect(self.self_healing_watchdog)
        self.watchdog_timer.start(2000)

        self.health_timer = QTimer(self)
        self.health_timer.timeout.connect(self.check_pc_health_and_trim_ram)
        self.health_timer.start(60000)

        if MIC_AVAILABLE:
            self.start_mic_thread()

    def start_mic_thread(self):
        if hasattr(self, "mic_thread") and self.mic_thread is not None and self.mic_thread.is_alive():
            return
        self.last_mic_heartbeat = time.time()
        self.mic_thread = threading.Thread(target=self.voice_listen_loop, daemon=True)
        self.mic_thread.start()

    def is_moon_awake(self):
        if not self.wake_word_only:
            return True
        return time.time() < self.active_convo_until

    def self_healing_watchdog(self):
        now = time.time()
        if (self.is_speaking or self.is_processing) and self.state_lock_timestamp > 0:
            if now - self.state_lock_timestamp > 25.0:
                self.is_speaking = False
                self.is_processing = False
                self.is_listening_active = False
                self.state_lock_timestamp = 0.0
                self.lip_timer.stop()
                self.update_sprite("idle")
                self.update_status_pill(self.default_mic_label())

        if MIC_AVAILABLE and self.voice_enabled and not self.is_speaking and not self.is_processing:
            if now - self.last_mic_heartbeat > 12.0:
                self.start_mic_thread()

    def default_mic_label(self):
        if not self.voice_enabled:
            return "🔇 Mic Muted"
        if self.is_moon_awake():
            rem = int(max(1, self.active_convo_until - time.time())) if self.wake_word_only else 99
            return f"🟢 Awake ({rem}s) - बोलिए बॉस!" if self.wake_word_only else "🟢 Awake & Ready"
        return "💤 Sleeping (Say 'Hello Moon')"

    def trigger_camera_look_followup(self, prompt_text):
        threading.Thread(target=self.process_user_input, args=(prompt_text, False, False, None), daemon=True).start()

    def preload_sprite_cache(self):
        emotions = ["idle", "talking_1", "talking_2", "happy", "excited", "shy", "angry", "sad", "thinking", "listening", "hanging"]
        for em in emotions:
            path = os.path.join(ASSETS_DIR, f"{em}.png")
            if os.path.exists(path):
                self.pixmap_cache[em] = QPixmap(path).scaled(250, 305, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        # Preload semantic emotion aliases
        if "shy" in self.pixmap_cache:
            self.pixmap_cache["teasing"] = self.pixmap_cache["shy"]
        if "thinking" in self.pixmap_cache:
            self.pixmap_cache["focused"] = self.pixmap_cache["thinking"]
        if "idle" in self.pixmap_cache:
            self.pixmap_cache["sleepy"] = self.pixmap_cache["idle"]
        if "angry" in self.pixmap_cache:
            self.pixmap_cache["angry_cute"] = self.pixmap_cache["angry"]
        if "sad" in self.pixmap_cache:
            self.pixmap_cache["worried"] = self.pixmap_cache["sad"]
        if "talking_1" in self.pixmap_cache:
            self.pixmap_cache["talking"] = self.pixmap_cache["talking_1"]
        trim_own_memory()

    def init_ui(self):
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(290, 415)

        self.bubble = QLabel("", self)
        self.bubble.setWordWrap(True)
        self.bubble.setAlignment(Qt.AlignCenter)
        self.bubble.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.bubble.setStyleSheet("""
            QLabel {
                background-color: rgba(18, 16, 30, 232);
                color: #F8F4FF;
                border: 1.5px solid rgba(168, 130, 255, 215);
                border-radius: 13px;
                padding: 6px 10px;
            }
        """)
        self.bubble.setGeometry(10, 2, 270, 60)
        self.bubble.hide()

        self.sprite_label = QLabel(self)
        self.sprite_label.setGeometry(20, self.base_sprite_y, 250, 305)
        self.update_sprite("idle")

        self.status_pill = QLabel(self.default_mic_label(), self)
        self.status_pill.setAlignment(Qt.AlignCenter)
        self.status_pill.setFont(QFont("Segoe UI", 8, QFont.Bold))
        self.status_pill.setStyleSheet("""
            QLabel {
                background-color: rgba(20, 18, 34, 225);
                color: #D2C4FF;
                border: 1px solid rgba(155, 120, 255, 185);
                border-radius: 9px;
                padding: 2px 8px;
            }
        """)
        self.status_pill.setGeometry(20, 353, 250, 22)
        self.status_pill.show()

        self.quick_input = QLineEdit(self)
        self.quick_input.setPlaceholderText("⚡ Ask Moon or type command...")
        self.quick_input.setFont(QFont("Segoe UI", 8))
        self.quick_input.setStyleSheet("""
            QLineEdit {
                background-color: rgba(16, 14, 28, 220);
                color: #FFFFFF;
                border: 1px solid rgba(140, 100, 255, 175);
                border-radius: 9px;
                padding: 2px 8px;
            }
            QLineEdit:focus {
                border: 1.5px solid #B592FF;
                background-color: rgba(24, 20, 42, 245);
            }
        """)
        self.quick_input.setGeometry(20, 380, 250, 24)
        self.quick_input.returnPressed.connect(self.on_quick_command_submit)
        self.quick_input.show()

        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.width() - 300, screen.height() - 415)
        self.show()

    def on_quick_command_submit(self):
        cmd = self.quick_input.text().strip()
        if not cmd:
            return
        self.quick_input.clear()
        self.quick_input.clearFocus()
        if self.is_speaking:
            stop_current_playback()
        self.active_convo_until = time.time() + 45.0
        threading.Thread(target=self.process_user_input, args=(cmd, False, False, None), daemon=True).start()

    def save_config(self):
        self.config["api_key"] = self.api_key
        self.config["voice_profile"] = self.voice_profile
        self.config["show_subtitles"] = self.show_subtitles
        self.config["wake_word_only"] = self.wake_word_only
        self.config["proactive_mode"] = self.proactive_mode
        self.config["save_gemini_for_voice"] = self.save_gemini_for_voice
        self.config["mic_device_index"] = self.mic_device_index
        self.config["mic_muted"] = not self.voice_enabled
        save_config_file(self.config)

    def animate_breathing(self):
        if self.current_emotion == "hanging" or self.is_dragging:
            self.sprite_label.move(20, self.base_sprite_y)
            return
        self.breath_phase += 0.12
        offset_y = int(math.sin(self.breath_phase) * 3.0)
        self.sprite_label.move(20, self.base_sprite_y + offset_y)

    def update_status_pill(self, text):
        if not text:
            self.status_pill.hide()
        else:
            self.status_pill.setText(text)
            self.status_pill.show()

    def update_sprite(self, emotion):
        emotion_map = {
            "teasing": "shy",
            "focused": "thinking",
            "sleepy": "idle",
            "angry_cute": "angry",
            "worried": "sad",
            "talking": "talking_1",
        }
        mapped_em = emotion_map.get(str(emotion).lower().strip(), str(emotion).lower().strip())
        self.current_emotion = mapped_em
        pix = self.pixmap_cache.get(mapped_em) or self.pixmap_cache.get(emotion) or self.pixmap_cache.get("idle")
        if pix:
            self.sprite_label.setPixmap(pix)

    def display_speech_bubble(self, text, duration_ms=5500):
        if not self.show_subtitles or not text:
            self.bubble.hide()
            return
        self.bubble.setText(text)
        self.bubble.show()
        QTimer.singleShot(duration_ms, self.bubble.hide)

    def begin_lipsync(self):
        self.lip_timer.start(110)

    def end_lipsync(self, final_emotion):
        self.lip_timer.stop()
        self.update_sprite(final_emotion)
        QTimer.singleShot(3000, lambda: self.update_sprite("idle") if self.current_emotion != "hanging" else None)

    def animate_mouth(self):
        frames = ["talking_1", "talking_2", "idle", "talking_1"]
        self.lip_frame = (self.lip_frame + 1) % len(frames)
        pix = self.pixmap_cache.get(frames[self.lip_frame])
        if pix:
            self.sprite_label.setPixmap(pix)

    def trigger_instant_listen(self):
        if self.is_speaking:
            stop_current_playback()
            time.sleep(0.1)
        if self.is_processing:
            return
        self.active_convo_until = time.time() + 45.0
        if self.is_listening_active:
            self.finish_listen_now = True
        else:
            self.force_listen_now = True
            self.update_sprite("listening")
            self.update_status_pill("👂 बोलिए बॉस, मैं सुन रही हूँ...")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.press_global_pos = event.globalPos()
            self.window_start_pos = self.pos()
            self.is_dragging = False

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            dist = (event.globalPos() - self.press_global_pos).manhattanLength()
            if dist > 10:
                self.is_dragging = True
                self.move(self.window_start_pos + (event.globalPos() - self.press_global_pos))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.is_dragging:
                self.is_dragging = False
                screen = QApplication.primaryScreen().availableGeometry()
                if self.y() > screen.height() - 435:
                    self.move(self.x(), screen.height() - 415)
                    self.update_sprite("hanging")
                elif self.y() < 25:
                    self.move(self.x(), 0)
                    self.update_sprite("hanging")
                else:
                    if self.current_emotion == "hanging":
                        self.update_sprite("idle")
            else:
                self.trigger_instant_listen()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.is_dragging = False
            self.trigger_instant_listen()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background-color: #1A1726; color: #F2ECFF; border: 1px solid #7C5CFF; border-radius: 8px; padding: 4px; }
            QMenu::item { padding: 6px 20px; border-radius: 4px; }
            QMenu::item:selected { background-color: #6B4CE6; color: white; }
        """)

        act_talk = menu.addAction("🎙️ Wake Up & Speak to Moon Now")
        act_type = menu.addAction("⌨️ Type God-Mode Multi-Task Command...")
        act_ram = menu.addAction("🧹 Real System RAM & Temp Cleaner")
        menu.addSeparator()

        act_screen = menu.addAction("🖥️ Analyze My Screen / Fix Code Error (Grid HD Vision)")
        act_cam = menu.addAction("📷 Open Camera & Look at Me Now")
        act_clip = menu.addAction("📋 Explain / Fix Copied Clipboard Text")
        menu.addSeparator()

        act_test_voice = menu.addAction("💎 Test Cute Voice (Hindi + English)")

        voice_menu = menu.addMenu("🎀 Choose Moon's Anime Voice")
        voice_group = QActionGroup(self)
        voice_actions = {}
        for v_id, v_info in VOICE_PROFILES.items():
            va = voice_menu.addAction(v_info.get("label", v_id))
            va.setCheckable(True)
            if self.voice_profile == v_id:
                va.setChecked(True)
            voice_group.addAction(va)
            voice_actions[va] = v_id

        mic_menu = menu.addMenu("🎙️ Select Microphone Device (Laptop / Earphone)")
        mic_group = QActionGroup(self)
        mic_actions = {}
        act_default_mic = mic_menu.addAction("✨ Windows Default Active Mic (Laptop + Earphone Auto)")
        act_default_mic.setCheckable(True)
        if self.mic_device_index is None:
            act_default_mic.setChecked(True)
        mic_group.addAction(act_default_mic)
        mic_actions[act_default_mic] = None

        for dev_idx, dev_name in get_working_input_devices():
            m_act = mic_menu.addAction(f"🎤 [{dev_idx}] {dev_name[:38]}")
            m_act.setCheckable(True)
            if self.mic_device_index == dev_idx:
                m_act.setChecked(True)
            mic_group.addAction(m_act)
            mic_actions[m_act] = dev_idx

        act_wake = menu.addAction(f"💤 Auto-Sleep Mode (Wake on 'Hello Moon'): {'ON' if self.wake_word_only else 'OFF'}")
        act_sub = menu.addAction(f"💬 Subtitles Bubble: {'ON' if self.show_subtitles else 'OFF'}")
        act_mic = menu.addAction(f"🎧 Microphone Listening: {'ON (Unmuted)' if self.voice_enabled else 'OFF (Muted)'}")
        act_key = menu.addAction("🔑 Add/Update Gemini API Keys (AQ.Ab8... / AIza...)")
        act_panel = menu.addAction("🎛️ Open Control Panel & Live Settings")
        menu.addSeparator()
        act_quit = menu.addAction("💤 Exit Moon")

        chosen = menu.exec_(self.mapToGlobal(event.pos()))
        if not chosen:
            return
        if chosen in voice_actions:
            self.voice_profile = voice_actions[chosen]
            self.save_config()
            v_label = VOICE_PROFILES[self.voice_profile].get("label", self.voice_profile)
            self.display_speech_bubble(f"मेरी आवाज़ अब बदल गई है: {v_label[:28]} ✨", 3500)
        elif chosen == act_panel:
            try:
                from main_ui import MoonControlPanelWindow
                if not hasattr(self, "_ctrl_panel") or self._ctrl_panel is None:
                    self._ctrl_panel = MoonControlPanelWindow(self)
                self._ctrl_panel.show()
                self._ctrl_panel.raise_()
                self._ctrl_panel.activateWindow()
            except Exception as e:
                print(f"[Panel Launch Notice]: {e}")
        elif chosen == act_test_voice:
            threading.Thread(
                target=self.speak_text_and_execute,
                args=(
                    "हेहे boss! अब मैं आपकी हर बात बिल्कुल सही सुनूँगी और बिना किसी delay के जवाब दूँगी!",
                    "Hehe boss! Ab main aapki har baat bilkul sahi sunungi aur bina kisi delay ke jawaab dungi!",
                    "💎 Voice & Native Audio Ear Ready! 💖",
                    "excited",
                    []
                ),
                daemon=True
            ).start()
        elif chosen in mic_actions:
            self.mic_device_index = mic_actions[chosen]
            self.save_config()
            self.restart_mic_flag = True
            self.update_status_pill("🔄 Switching Mic...")
        elif chosen == act_wake:
            self.wake_word_only = not self.wake_word_only
            self.save_config()
            self.update_status_pill(self.default_mic_label())
        elif chosen == act_ram:
            def run_clean():
                freed_mb, ram_pct, proc_cnt, _ = real_system_ram_cleaner()
                self.speak_text_and_execute(
                    f"अरे वाह boss! मैंने {proc_cnt} apps की memory साफ़ कर दी है और {freed_mb} MB RAM free हो गई है!",
                    f"Are waah boss! Maine {proc_cnt} apps ki memory saaf kar di hai aur {freed_mb} MB RAM free ho gayi hai!",
                    f"🧹 Trimmed {proc_cnt} apps | Freed {freed_mb} MB | RAM: {ram_pct}%",
                    "excited", []
                )
            threading.Thread(target=run_clean, daemon=True).start()
        elif chosen == act_talk:
            self.trigger_instant_listen()
        elif chosen == act_type:
            cmd, ok = QInputDialog.getText(self, "Ask Moon God-Mode Agent", "Tell Moon any single or multi-step task:")
            if ok and cmd.strip():
                self.active_convo_until = time.time() + 45.0
                threading.Thread(target=self.process_user_input, args=(cmd.strip(), False, False, None), daemon=True).start()
        elif chosen == act_screen:
            threading.Thread(target=self.process_user_input, args=("मेरी screen देखो और बताओ क्या चल रहा है, अगर कोई coding error है तो ठीक कर दो!", True, False, None), daemon=True).start()
        elif chosen == act_cam:
            threading.Thread(target=self.process_user_input, args=("camera से मुझे देखो और बताओ मैं क्या कर रहा हूँ या मेरे हाथ में क्या है?", False, True, None), daemon=True).start()
        elif chosen == act_clip:
            clip_text = get_clipboard_text_windows()
            if clip_text:
                threading.Thread(target=self.process_user_input, args=(f"मैंने ये text copy किया है, इसे समझाओ या ठीक करो:\n{clip_text[:1500]}", False, False, None), daemon=True).start()
        elif chosen == act_sub:
            self.show_subtitles = not self.show_subtitles
            self.save_config()
            if not self.show_subtitles:
                self.bubble.hide()
        elif chosen == act_mic:
            self.voice_enabled = not self.voice_enabled
            self.save_config()
            self.update_status_pill(self.default_mic_label())
        elif chosen == act_key:
            new_key, ok = QInputDialog.getText(
                self,
                "Gemini API Keys Setup",
                "Paste Gemini keys (AQ.Ab8... or AIza...) separated by comma:",
                text=self.api_key
            )
            if ok:
                self.api_key = new_key.strip()
                MODEL_COOLDOWN.clear()
                KEY_COOLDOWN.clear()
                TTS_COOLDOWN.clear()
                self.save_config()
        elif chosen == act_quit:
            QApplication.quit()

    def check_pc_health_and_trim_ram(self):
        trim_own_memory()
        if psutil.virtual_memory().percent > 88:
            real_system_ram_cleaner()

    def speak_text_and_execute(self, voice_text, roman_text=None, display_text=None, emotion="happy", steps=None):
        with self.speech_lock:
            self.is_speaking = True
            self.state_lock_timestamp = time.time()
            self.last_interaction_time = time.time()
            if display_text is None:
                display_text = voice_text
            if roman_text is None:
                roman_text = voice_text

            voice_clean = sanitize_tts_text(voice_text) or voice_text

            self.signals.set_emotion.emit(emotion)
            self.signals.show_bubble.emit(display_text, max(len(display_text) * 95, 5000))
            self.signals.set_status.emit("🔊 Preparing Voice...")

            steps_executed = False
            step_thread = None

            def start_steps_worker(delay_s=0.28):
                nonlocal steps_executed
                if steps_executed or not steps or not isinstance(steps, list):
                    return None
                steps_executed = True

                def _delayed_exec():
                    if delay_s > 0:
                        time.sleep(delay_s)
                    execute_agent_steps_with_verification(steps, None, self)

                t = threading.Thread(target=_delayed_exec, daemon=True)
                t.start()
                return t

            try:
                prof = VOICE_PROFILES.get(self.voice_profile) or VOICE_PROFILES.get("gemini_zephyr") or list(VOICE_PROFILES.values())[0]
                audio_file = None
                if prof.get("type") == "gemini_tts":
                    audio_file = generate_gemini_hd_tts_multi_key(
                        self.api_key, voice_clean, prof.get("voice", "Zephyr"), emotion
                    )
                if not audio_file or not os.path.exists(audio_file):
                    fb_voice = prof.get("fallback_voice") or prof.get("voice", "hi-IN-SwaraNeural")
                    fb_pitch = prof.get("fallback_pitch") or prof.get("pitch", "+12Hz")
                    fb_rate = prof.get("fallback_rate") or prof.get("rate", "+8%")
                    audio_file = generate_edge_anime_tts_cached(
                        voice_clean, fb_voice, fb_pitch, fb_rate
                    )

                self.signals.set_status.emit("🔊 Speaking...")
                self.signals.start_lipsync.emit()

                step_thread = start_steps_worker(0.28)

                if audio_file and os.path.exists(audio_file):
                    play_audio_windows(audio_file, max_wait_seconds=22.0)

                if step_thread is not None and step_thread.is_alive():
                    self.signals.set_status.emit("⚙️ Finishing Task...")
                    step_thread.join(timeout=10.0)
                    self.signals.set_status.emit("✅ काम पूरा हो गया बॉस!")
                    time.sleep(0.6)

            except Exception as e:
                print(f"[TTS/Exec Error]: {e}")
                if not steps_executed and steps:
                    t_fb = start_steps_worker(0.0)
                    if t_fb:
                        t_fb.join(timeout=10.0)
            finally:
                self.is_speaking = False
                self.state_lock_timestamp = 0.0
                self.last_interaction_time = time.time()
                self.signals.set_status.emit(self.default_mic_label())
                self.signals.stop_lipsync.emit(emotion)
                trim_own_memory()

    # =====================================================================
    # FULL-SENTENCE VOICE LISTENER (Wait 1.1s pause so sentences never cut off!)
    # =====================================================================
    def voice_listen_loop(self):
        recognizer = sr.Recognizer()
        sample_rate = 16000
        chunk_duration = 0.08
        chunk_samples = int(sample_rate * chunk_duration)

        while True:
            self.restart_mic_flag = False
            self.last_mic_heartbeat = time.time()

            noise_floor = 10.0
            try:
                with sd.InputStream(
                    device=self.mic_device_index,
                    samplerate=sample_rate,
                    channels=1,
                    dtype="int16"
                ) as stream:
                    cal_vals = []
                    for _ in range(6):
                        self.last_mic_heartbeat = time.time()
                        data, _ = stream.read(chunk_samples)
                        cal_vals.append(compute_speech_formant_rms(data, sample_rate))
                    noise_floor = max(min(float(np.median(cal_vals)), 60.0), 3.0)
            except Exception as e:
                print(f"[Mic Open Warning]: {e}")
                if self.mic_device_index is not None:
                    self.mic_device_index = None
                    self.save_config()
                self.signals.set_status.emit("⚠️ Switching to Default Mic...")
                time.sleep(1.0)
                continue

            self.signals.set_status.emit(self.default_mic_label())
            print(f"[Moon Ear v45] Ready! Active Mic={self.mic_device_index} | Noise Floor={noise_floor:.1f}")

            while not self.restart_mic_flag:
                self.last_mic_heartbeat = time.time()
                if self.is_speaking or self.is_processing or (not self.voice_enabled and not self.force_listen_now):
                    time.sleep(0.05)
                    continue

                captured_frames = []
                has_spoken = False
                was_clicked = False

                try:
                    with sd.InputStream(
                        device=self.mic_device_index,
                        samplerate=sample_rate,
                        channels=1,
                        dtype="int16"
                    ) as stream:
                        pre_buffer = deque(maxlen=10)
                        recording = False
                        silence_chunks = 0
                        speech_chunks = 0
                        voice_peak = noise_floor * 1.8
                        max_speech_chunks = int(9.0 / chunk_duration)
                        ui_tick = 0

                        while not self.is_speaking and not self.is_processing and not self.restart_mic_flag:
                            self.last_mic_heartbeat = time.time()
                            if not self.voice_enabled and not self.force_listen_now and not recording:
                                break

                            data, _ = stream.read(chunk_samples)
                            vol = compute_speech_formant_rms(data, sample_rate)
                            start_threshold = min(max(noise_floor * 1.65 + 4.0, 7.0), 45.0)

                            ui_tick += 1
                            if not recording and ui_tick % 6 == 0:
                                bar = volume_bar_string(vol, start_threshold)
                                if self.is_moon_awake():
                                    rem = int(max(1, self.active_convo_until - time.time())) if self.wake_word_only else 99
                                    lbl = f"🟢 Awake ({rem}s) {bar}" if self.wake_word_only else f"🟢 Mic {bar}"
                                else:
                                    lbl = f"💤 'Hello Moon' {bar}"
                                self.signals.set_status.emit(lbl)

                            if not recording:
                                pre_buffer.append(data.copy())
                                if self.force_listen_now:
                                    recording = True
                                    was_clicked = True
                                    has_spoken = True
                                    self.is_listening_active = True
                                    self.force_listen_now = False
                                    self.finish_listen_now = False
                                    silence_chunks = 0
                                    speech_chunks = 3
                                    voice_peak = max(vol, start_threshold * 1.4)
                                    captured_frames.extend(pre_buffer)
                                    self.signals.set_emotion.emit("listening")
                                    self.signals.set_status.emit("👂 बोलिए बॉस...")
                                elif vol > start_threshold:
                                    recording = True
                                    was_clicked = False
                                    has_spoken = True
                                    self.is_listening_active = True
                                    self.finish_listen_now = False
                                    silence_chunks = 0
                                    speech_chunks = 1
                                    voice_peak = max(vol, start_threshold * 1.3)
                                    captured_frames.extend(pre_buffer)
                                    if self.is_moon_awake():
                                        self.signals.set_emotion.emit("listening")
                                        self.signals.set_status.emit("👂 सुन रही हूँ...")
                                else:
                                    if vol > 0.0:
                                        noise_floor = min(max(noise_floor * 0.90 + vol * 0.10, 2.5), 35.0)
                            else:
                                captured_frames.append(data.copy())
                                if vol > voice_peak:
                                    voice_peak = vol

                                stop_threshold = min(noise_floor * 1.25 + 2.5, start_threshold * 0.80)
                                if vol > stop_threshold:
                                    silence_chunks = max(0, silence_chunks - 1)
                                    speech_chunks += 1
                                else:
                                    silence_chunks += 1

                                min_chunks = 12 if was_clicked else 10
                                # Allow 1.12s (14 chunks) of natural breathing pause so "Hello Moon ... <command>" is NEVER cut off!
                                silence_needed = 11 if len(captured_frames) > 30 else 14
                                user_done = (
                                    (len(captured_frames) >= min_chunks and silence_chunks >= silence_needed)
                                    or len(captured_frames) >= max_speech_chunks
                                    or self.finish_listen_now
                                )
                                if user_done:
                                    self.is_listening_active = False
                                    self.finish_listen_now = False
                                    break

                    if (has_spoken and speech_chunks >= 3) or (was_clicked and len(captured_frames) >= 6):
                        raw_audio_np = np.concatenate(captured_frames, axis=0)
                        clean_int16, wav_bytes = normalize_and_clean_wav_bytes(raw_audio_np, sample_rate)
                        user_text = recognize_bilingual_fast(recognizer, clean_int16, sample_rate)

                        if user_text:
                            print(f"🎙️ [Heard Clean]: '{user_text}'")
                            currently_awake = self.is_moon_awake()
                            has_wake, cleaned_cmd = check_and_strip_wake_word(user_text)

                            if was_clicked or has_wake or currently_awake:
                                self.is_processing = True
                                self.state_lock_timestamp = time.time()
                                self.active_convo_until = time.time() + 45.0
                                final_cmd = cleaned_cmd if has_wake else user_text
                                short_preview = final_cmd[:24] + ("..." if len(final_cmd) > 24 else "")
                                self.signals.set_status.emit(f"🗣️ \"{short_preview}\"")
                                # Pass `wav_bytes` so Gemini Native Audio Ear hears the user's real voice!
                                threading.Thread(
                                    target=self.process_user_input,
                                    args=(final_cmd, False, False, wav_bytes),
                                    daemon=True
                                ).start()
                            else:
                                print(f"💤 [Ignored in Sleep Mode - Say 'Hello Moon' to wake]: '{user_text}'")
                                self.signals.set_emotion.emit("idle")
                                self.signals.set_status.emit(self.default_mic_label())
                        else:
                            if was_clicked:
                                self.signals.show_bubble.emit("आवाज़ साफ़ नहीं आई बॉस! फिर से बोलिए 💖", 2500)
                            self.signals.set_emotion.emit("idle")
                            self.signals.set_status.emit(self.default_mic_label())
                    else:
                        self.is_listening_active = False
                        if self.current_emotion == "listening":
                            self.signals.set_emotion.emit("idle")
                        self.signals.set_status.emit(self.default_mic_label())

                except Exception as e:
                    self.is_listening_active = False
                    self.is_processing = False
                    self.state_lock_timestamp = 0.0
                    print(f"[Mic Loop Notice]: {e}")
                    time.sleep(0.3)

    def process_user_input(self, user_text, force_screen=False, force_cam=False, wav_bytes=None):
        self.is_processing = True
        self.state_lock_timestamp = time.time()
        self.last_interaction_time = time.time()
        self.active_convo_until = time.time() + 45.0
        self.signals.set_emotion.emit("thinking")
        self.signals.set_status.emit("💭 Moon is Thinking...")

        images = []
        auto_cam = needs_webcam_vision(user_text)
        auto_screen = needs_screen_vision(user_text)

        try:
            if force_cam or auto_cam:
                self.signals.set_status.emit("📷 Opening Camera & Looking...")
                cam_img = capture_webcam()
                if cam_img:
                    images.append(cam_img)
                    user_text = f"[Webcam Photo Attached]: {user_text}"

            if force_screen or auto_screen:
                self.signals.set_status.emit("🖥️ Reading Screen (Grid HD)...")
                images.append(capture_desktop_screen(with_grid=True))

            self.config["api_key"] = self.api_key
            self.config["save_gemini_for_voice"] = self.save_gemini_for_voice
            data, provider_used = call_resilient_multi_brain(
                self.config, self.chat_history, user_text, images, wav_bytes
            )
            print(f"🧠 [Brain Provider]: {provider_used}")

            emotion = data.get("emotion", "happy")
            voice_text = data.get("voice_text") or data.get("display_text") or "Okay boss, अभी करती हूँ!"
            roman_text = data.get("roman_text") or voice_text
            display_text = data.get("display_text") or voice_text
            steps = data.get("steps", [])

            self.speak_text_and_execute(voice_text, roman_text, display_text, emotion, steps)
        except Exception as e:
            print(f"[Process Error]: {e}")
            self.speak_text_and_execute(
                "अरे boss, एक बार फिर से बोलो ना!",
                "Are boss, ek baar phir se bolo na!",
                "⏳ फिर से बोलिए बॉस!",
                "shy",
                []
            )
        finally:
            self.is_processing = False
            self.state_lock_timestamp = 0.0
            self.last_interaction_time = time.time()
            self.active_convo_until = time.time() + 45.0


def main():
    app = QApplication(sys.argv)

    default_img = "Suzune  Horikita.jpg"
    if not os.path.exists(SPRITE_VERSION_FILE):
        if not os.path.exists(default_img):
            candidates = [f for f in os.listdir(".") if f.lower().endswith((".jpg", ".jpeg", ".png"))]
            if candidates:
                default_img = candidates[0]
            else:
                QMessageBox.information(None, "Select Moon's Image", "Please select your character image!")
                default_img, _ = QFileDialog.getOpenFileName(None, "Select Character Image", "", "Images (*.jpg *.jpeg *.png)")
                if not default_img:
                    sys.exit(0)
        build_sprites_if_needed(default_img)

    config = load_config()
    moon = MoonDesktopWidget(config)
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()