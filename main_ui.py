import os
import sys
import math
import json
import time
import threading
import traceback
from datetime import datetime

from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QGridLayout, QGroupBox, QSlider, QCheckBox, QComboBox, QLineEdit,
    QTextEdit, QListWidget, QListWidgetItem, QMenu, QInputDialog,
    QFileDialog, QMessageBox, QFrame
)
from PyQt5.QtCore import Qt, QTimer, QPoint, pyqtSignal, QObject
from PyQt5.QtGui import QPixmap, QFont, QColor

from gemini_api_pool import (
    CONFIG_FILE, VALID_EMOTIONS, AllKeysExhaustedError, GeminiAPIPoolManager
)
from vision_screen_cam import (
    ASSETS_DIR, SPRITE_VERSION_FILE, VisionPrivacyAndCaptureManager,
    build_all_emotion_sprites
)
from audio_ear_tts import (
    VOICE_PROFILES, get_working_input_devices, AudioEarAndTTSManager
)
from os_action_verifier import OSActionAndVerifierEngine
from proactive_daemon import ProactiveIdleDaemon

DEFAULT_CONFIG = {
    "api_key": "",
    "voice_profile": "gemini_zephyr",
    "tts_pitch_hz": 15,
    "tts_rate_pct": 10,
    "masti_level": 75,
    "show_subtitles": True,
    "wake_word_only": True,
    "mic_muted": False,
    "screen_vision_enabled": True,
    "webcam_access_enabled": True,
    "proactive_mode": False,
    "proactive_idle_minutes": 5,
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
    if cfg.get("voice_profile") not in VOICE_PROFILES:
        cfg["voice_profile"] = "gemini_zephyr"
    return cfg


def save_config_file(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[Config Save Warning]: {e}")


def needs_webcam_capture(user_text):
    low = (user_text or "").lower()
    patterns = [
        "पहचान", "pehchan", "जानती हो", "jaanti ho", "isko dekho", "ise dekho",
        "ye dekho", "ye kya hai", "what is this", "who is this", "ye kaun hai",
        "mere haath", "mere hath", "in my hand", "holding", "mujhe dekho",
        "look at me", "main kaisa", "how do i look", "camera", "webcam", "चेहरा", "face"
    ]
    return any(p in low for p in patterns)


def needs_screen_capture(user_text):
    low = (user_text or "").lower()
    patterns = [
        "screen", "स्क्रीन", "click", "क्लिक", "select", "niche wala",
        "dusra", "teesra", "error", "bug", "fix", "button", "दिख रहा",
        "whatsapp", "discord", "instagram", "telegram", "reply", "message", "chat"
    ]
    return any(p in low for p in patterns)


class UIBridgeSignals(QObject):
    set_emotion = pyqtSignal(str)
    show_bubble = pyqtSignal(str, int)
    set_status = pyqtSignal(str)
    set_amplitude = pyqtSignal(float)
    append_log = pyqtSignal(str)
    update_pool_badges = pyqtSignal(list)
    sync_toggles = pyqtSignal()


class MoonControlPanelWindow(QWidget):
    """
    Production Control Panel & Collapsible Live Execution Terminal / Debug Drawer.
    Every single toggle, slider, button, and API Vault badge is wired to real backend state.
    """

    def __init__(self, moon_widget):
        super().__init__()
        self.moon = moon_widget
        self.setWindowTitle("🌙 Moon AI — Production Control Panel & Live Telemetry")
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
        self.resize(760, 740)
        self.setStyleSheet("""
            QWidget {
                background-color: #13111C;
                color: #EFEAFF;
                font-family: 'Segoe UI';
                font-size: 12px;
            }
            QGroupBox {
                border: 1px solid #3B2D64;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
                font-weight: bold;
                color: #C7B3FF;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QPushButton {
                background-color: #5639B8;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 6px 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #6E4CE0;
            }
            QPushButton:pressed {
                background-color: #432A96;
            }
            QLineEdit, QComboBox, QListWidget, QTextEdit {
                background-color: #1D192B;
                border: 1px solid #4A397E;
                border-radius: 6px;
                padding: 5px;
                color: #F4F0FF;
            }
            QSlider::groove:horizontal {
                height: 6px;
                background: #2C2542;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #9E7BFF;
                width: 16px;
                margin: -5px 0;
                border-radius: 8px;
            }
            QCheckBox {
                spacing: 8px;
                font-weight: bold;
            }
        """)
        self._build_layout()
        self.refresh_from_state()

    def _build_layout(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(8)

        # 1. HARDWARE & PRIVACY TOGGLES GROUP
        grp_toggles = QGroupBox("🛡️ 1–4. Live Privacy, Hardware & Proactive Toggles")
        grid_toggles = QGridLayout(grp_toggles)

        self.chk_mic_mute = QCheckBox("🔇 Mute Microphone (Halt Audio Buffer)")
        self.chk_mic_mute.toggled.connect(self._on_mic_mute_toggled)

        self.chk_wake_word = QCheckBox("🗣️ Fuzzy Wake-Word ('Moon' / 'Oye Moon')")
        self.chk_wake_word.toggled.connect(self._on_wake_word_toggled)

        self.chk_screen_vision = QCheckBox("🖥️ Screen Vision ON (`mss` + UI Grid)")
        self.chk_screen_vision.toggled.connect(self._on_screen_vision_toggled)

        self.chk_webcam = QCheckBox("📷 Webcam Access ON (`cv2` Auto-Release)")
        self.chk_webcam.toggled.connect(self._on_webcam_toggled)

        self.chk_subtitles = QCheckBox("💬 Show Floating Subtitle Bubble")
        self.chk_subtitles.toggled.connect(self._on_subtitles_toggled)

        self.chk_proactive = QCheckBox("💖 Proactive Idle Check-In (Screen + Cam)")
        self.chk_proactive.toggled.connect(self._on_proactive_toggled)

        grid_toggles.addWidget(self.chk_mic_mute, 0, 0)
        grid_toggles.addWidget(self.chk_wake_word, 0, 1)
        grid_toggles.addWidget(self.chk_screen_vision, 1, 0)
        grid_toggles.addWidget(self.chk_webcam, 1, 1)
        grid_toggles.addWidget(self.chk_subtitles, 2, 0)
        grid_toggles.addWidget(self.chk_proactive, 2, 1)

        # Proactive Idle Slider + Instant Trigger Button
        pro_row = QHBoxLayout()
        self.lbl_idle_slider = QLabel("⏰ Proactive Idle Timer: 5 mins")
        self.slider_idle = QSlider(Qt.Horizontal)
        self.slider_idle.setRange(1, 30)
        self.slider_idle.valueChanged.connect(self._on_idle_slider_changed)
        self.btn_trigger_proactive = QPushButton("✨ Test Proactive Peek Now")
        self.btn_trigger_proactive.clicked.connect(lambda: self.moon.proactive_daemon.trigger_proactive_check_in(True))
        pro_row.addWidget(self.lbl_idle_slider)
        pro_row.addWidget(self.slider_idle, 1)
        pro_row.addWidget(self.btn_trigger_proactive)
        grid_toggles.addLayout(pro_row, 3, 0, 1, 2)

        main_layout.addWidget(grp_toggles)

        # 2. SMART GEMINI API KEY VAULT & LIVE HEALTH DASHBOARD
        grp_api = QGroupBox("🔑 5. Smart Gemini API Key Pool & Live Load-Balancer Health")
        api_layout = QVBoxLayout(grp_api)

        self.list_keys = QListWidget()
        self.list_keys.setFixedHeight(110)
        api_layout.addWidget(self.list_keys)

        add_key_row = QHBoxLayout()
        self.input_new_key = QLineEdit()
        self.input_new_key.setPlaceholderText("Paste 1 or more Gemini API keys (comma-separated, e.g. AIzaSy...)")
        self.btn_add_key = QPushButton("➕ Add Key(s)")
        self.btn_add_key.clicked.connect(self._on_add_keys_clicked)
        self.btn_del_key = QPushButton("🗑️ Delete Selected")
        self.btn_del_key.setStyleSheet("background-color: #9E2A4A;")
        self.btn_del_key.clicked.connect(self._on_delete_key_clicked)
        self.btn_test_keys = QPushButton("⚡ Test All Keys (Ping Latency)")
        self.btn_test_keys.setStyleSheet("background-color: #1E7E5A;")
        self.btn_test_keys.clicked.connect(self._on_test_all_keys_clicked)

        add_key_row.addWidget(self.input_new_key, 1)
        add_key_row.addWidget(self.btn_add_key)
        add_key_row.addWidget(self.btn_del_key)
        add_key_row.addWidget(self.btn_test_keys)
        api_layout.addLayout(add_key_row)

        main_layout.addWidget(grp_api)

        # 3. VOICE & PERSONA TUNER
        grp_voice = QGroupBox("🎀 6. Expressive Anime Voice & Persona Tuner")
        voice_grid = QGridLayout(grp_voice)

        voice_grid.addWidget(QLabel("🎤 Voice Profile:"), 0, 0)
        self.combo_voice = QComboBox()
        for v_key, v_info in VOICE_PROFILES.items():
            self.combo_voice.addItem(v_info["label"], v_key)
        self.combo_voice.currentIndexChanged.connect(self._on_voice_settings_changed)
        voice_grid.addWidget(self.combo_voice, 0, 1)

        voice_grid.addWidget(QLabel("🎙️ Input Mic Device:"), 0, 2)
        self.combo_mic = QComboBox()
        self.combo_mic.addItem("✨ Windows Default Mic", None)
        for dev_idx, dev_name in get_working_input_devices():
            self.combo_mic.addItem(f"[{dev_idx}] {dev_name[:32]}", dev_idx)
        self.combo_mic.currentIndexChanged.connect(self._on_mic_device_changed)
        voice_grid.addWidget(self.combo_mic, 0, 3)

        self.lbl_pitch = QLabel("🎵 TTS Pitch: +15Hz")
        self.slider_pitch = QSlider(Qt.Horizontal)
        self.slider_pitch.setRange(-10, 30)
        self.slider_pitch.valueChanged.connect(self._on_voice_settings_changed)

        self.lbl_rate = QLabel("⚡ TTS Speed: +10%")
        self.slider_rate = QSlider(Qt.Horizontal)
        self.slider_rate.setRange(-20, 35)
        self.slider_rate.valueChanged.connect(self._on_voice_settings_changed)

        voice_grid.addWidget(self.lbl_pitch, 1, 0)
        voice_grid.addWidget(self.slider_pitch, 1, 1)
        voice_grid.addWidget(self.lbl_rate, 1, 2)
        voice_grid.addWidget(self.slider_rate, 1, 3)

        self.lbl_masti = QLabel("🔥 Masti / Teasing Level: 75% (Full Anime Masti-khor)")
        self.slider_masti = QSlider(Qt.Horizontal)
        self.slider_masti.setRange(1, 100)
        self.slider_masti.valueChanged.connect(self._on_masti_slider_changed)
        self.btn_test_voice = QPushButton("🔊 Preview Voice")
        self.btn_test_voice.clicked.connect(self._on_preview_voice_clicked)

        voice_grid.addWidget(self.lbl_masti, 2, 0, 1, 2)
        voice_grid.addWidget(self.slider_masti, 2, 2)
        voice_grid.addWidget(self.btn_test_voice, 2, 3)

        main_layout.addWidget(grp_voice)

        # QUICK MULTI-TASK COMMAND DISPATCH BAR
        cmd_row = QHBoxLayout()
        self.input_quick_cmd = QLineEdit()
        self.input_quick_cmd.setPlaceholderText(
            "Type a compound command (e.g. 'VS Code kholo, WhatsApp pe Rahul ko bol do busy hu, aur lo-fi music chala do')..."
        )
        self.input_quick_cmd.returnPressed.connect(self._on_send_quick_command)
        self.btn_send_cmd = QPushButton("🚀 Execute Multi-Task")
        self.btn_send_cmd.clicked.connect(self._on_send_quick_command)
        cmd_row.addWidget(self.input_quick_cmd, 1)
        cmd_row.addWidget(self.btn_send_cmd)
        main_layout.addLayout(cmd_row)

        # 4. COLLAPSIBLE LIVE EXECUTION TERMINAL / DEBUG DRAWER
        drawer_header = QHBoxLayout()
        self.btn_toggle_drawer = QPushButton("▼ 7. Hide Live Execution Terminal / Debug Drawer")
        self.btn_toggle_drawer.setStyleSheet("background-color: #26203A; text-align: left; padding: 6px 10px;")
        self.btn_toggle_drawer.clicked.connect(self._on_toggle_debug_drawer)
        self.btn_clear_logs = QPushButton("🧹 Clear Logs")
        self.btn_clear_logs.setFixedWidth(105)
        self.btn_clear_logs.clicked.connect(lambda: self.txt_terminal.clear())
        drawer_header.addWidget(self.btn_toggle_drawer, 1)
        drawer_header.addWidget(self.btn_clear_logs)
        main_layout.addLayout(drawer_header)

        self.txt_terminal = QTextEdit()
        self.txt_terminal.setReadOnly(True)
        self.txt_terminal.setFont(QFont("Consolas", 9))
        self.txt_terminal.setStyleSheet("""
            QTextEdit {
                background-color: #0B0911;
                color: #70F8BA;
                border: 1px solid #352A56;
                border-radius: 6px;
            }
        """)
        main_layout.addWidget(self.txt_terminal, 1)

    def refresh_from_state(self):
        cfg = self.moon.config
        self.chk_mic_mute.blockSignals(True)
        self.chk_wake_word.blockSignals(True)
        self.chk_screen_vision.blockSignals(True)
        self.chk_webcam.blockSignals(True)
        self.chk_subtitles.blockSignals(True)
        self.chk_proactive.blockSignals(True)
        self.slider_idle.blockSignals(True)
        self.slider_pitch.blockSignals(True)
        self.slider_rate.blockSignals(True)
        self.slider_masti.blockSignals(True)
        self.combo_voice.blockSignals(True)

        self.chk_mic_mute.setChecked(bool(cfg.get("mic_muted", False)))
        self.chk_wake_word.setChecked(bool(cfg.get("wake_word_only", True)))
        self.chk_screen_vision.setChecked(bool(cfg.get("screen_vision_enabled", True)))
        self.chk_webcam.setChecked(bool(cfg.get("webcam_access_enabled", True)))
        self.chk_subtitles.setChecked(bool(cfg.get("show_subtitles", True)))
        self.chk_proactive.setChecked(bool(cfg.get("proactive_mode", False)))

        idle_m = int(cfg.get("proactive_idle_minutes", 5))
        self.slider_idle.setValue(idle_m)
        self.lbl_idle_slider.setText(f"⏰ Proactive Idle Timer: {idle_m} min(s)")

        pitch = int(cfg.get("tts_pitch_hz", 15))
        rate = int(cfg.get("tts_rate_pct", 10))
        masti = int(cfg.get("masti_level", 75))
        self.slider_pitch.setValue(pitch)
        self.lbl_pitch.setText(f"🎵 TTS Pitch: {pitch:+d}Hz")
        self.slider_rate.setValue(rate)
        self.lbl_rate.setText(f"⚡ TTS Speed: {rate:+d}%")
        self.slider_masti.setValue(masti)
        self._update_masti_label(masti)

        vp = cfg.get("voice_profile", "swara_anime")
        idx = self.combo_voice.findData(vp)
        if idx >= 0:
            self.combo_voice.setCurrentIndex(idx)

        self.chk_mic_mute.blockSignals(False)
        self.chk_wake_word.blockSignals(False)
        self.chk_screen_vision.blockSignals(False)
        self.chk_webcam.blockSignals(False)
        self.chk_subtitles.blockSignals(False)
        self.chk_proactive.blockSignals(False)
        self.slider_idle.blockSignals(False)
        self.slider_pitch.blockSignals(False)
        self.slider_rate.blockSignals(False)
        self.slider_masti.blockSignals(False)
        self.combo_voice.blockSignals(False)

        self.render_pool_badges(self.moon.api_pool.get_pool_snapshot())

    def render_pool_badges(self, snapshot):
        self.list_keys.clear()
        for item in snapshot:
            status = item.get("status", "healthy")
            is_act = item.get("is_active", False)
            lat = int(item.get("latency_ms", 0))
            succ = item.get("success_count", 0)
            err = item.get("error_count", 0)
            cd = item.get("cooldown_remaining_s", 0)
            last_err = item.get("last_error", "")

            if status == "healthy":
                badge = "🟢 HEALTHY"
                col = QColor("#183E2B")
            elif status == "rate_limited":
                badge = f"🟡 RATE_LIMITED ({cd}s)"
                col = QColor("#4A3B12")
            else:
                badge = f"🔴 {status.upper()}"
                col = QColor("#4E1C26")

            active_tag = " ⭐ [ACTIVE]" if is_act else ""
            err_tail = f" | Err: {last_err[:45]}" if last_err else ""
            line = f"{badge}{active_tag}  |  Key: {item['masked']}  |  Latency: {lat}ms  |  OK:{succ} Fail:{err}{err_tail}"

            lw_item = QListWidgetItem(line)
            lw_item.setData(Qt.UserRole, item["key"])
            lw_item.setBackground(col)
            self.list_keys.addItem(lw_item)

    def _on_mic_mute_toggled(self, checked):
        self.moon.config["mic_muted"] = checked
        self.moon.audio_manager.set_mic_muted(checked)
        self.moon.save_all_config()

    def _on_wake_word_toggled(self, checked):
        self.moon.config["wake_word_only"] = checked
        self.moon.audio_manager.wake_word_only = checked
        self.moon.update_status_pill(self.moon.audio_manager.default_mic_label())
        self.moon.save_all_config()

    def _on_screen_vision_toggled(self, checked):
        self.moon.config["screen_vision_enabled"] = checked
        self.moon.vision_manager.set_screen_vision_enabled(checked)
        self.moon.save_all_config()

    def _on_webcam_toggled(self, checked):
        self.moon.config["webcam_access_enabled"] = checked
        self.moon.vision_manager.set_webcam_access_enabled(checked)
        self.moon.save_all_config()

    def _on_subtitles_toggled(self, checked):
        self.moon.config["show_subtitles"] = checked
        self.moon.show_subtitles = checked
        if not checked:
            self.moon.bubble.hide()
        self.moon.save_all_config()

    def _on_proactive_toggled(self, checked):
        idle_m = self.slider_idle.value()
        self.moon.config["proactive_mode"] = checked
        self.moon.proactive_daemon.set_proactive_config(checked, idle_m)
        self.moon.save_all_config()

    def _on_idle_slider_changed(self, val):
        self.lbl_idle_slider.setText(f"⏰ Proactive Idle Timer: {val} min(s)")
        self.moon.config["proactive_idle_minutes"] = val
        self.moon.proactive_daemon.set_proactive_config(self.chk_proactive.isChecked(), val)
        self.moon.save_all_config()

    def _on_voice_settings_changed(self):
        pitch = self.slider_pitch.value()
        rate = self.slider_rate.value()
        vp = self.combo_voice.currentData()
        self.lbl_pitch.setText(f"🎵 TTS Pitch: {pitch:+d}Hz")
        self.lbl_rate.setText(f"⚡ TTS Speed: {rate:+d}%")
        self.moon.config["tts_pitch_hz"] = pitch
        self.moon.config["tts_rate_pct"] = rate
        self.moon.config["voice_profile"] = vp
        self.moon.audio_manager.set_voice_tuning(pitch, rate, vp)
        self.moon.save_all_config()

    def _update_masti_label(self, val):
        if val >= 70:
            mode_txt = "Full Teasing Anime Mode 🔥"
        elif val >= 35:
            mode_txt = "Sweet & Playful Balanced 🌸"
        else:
            mode_txt = "Crisp & Professional 💼"
        self.lbl_masti.setText(f"🔥 Masti Level: {val}% ({mode_txt})")

    def _on_masti_slider_changed(self, val):
        self._update_masti_label(val)
        self.moon.config["masti_level"] = val
        self.moon.save_all_config()

    def _on_mic_device_changed(self):
        dev_idx = self.combo_mic.currentData()
        self.moon.config["mic_device_index"] = dev_idx
        self.moon.audio_manager.mic_device_index = dev_idx
        self.moon.audio_manager.restart_mic_flag = True
        self.moon.save_all_config()

    def _on_preview_voice_clicked(self):
        threading.Thread(
            target=self.moon.speak_response,
            args=(
                "हेहे बॉस! मेरी ये नई ट्यूनिंग और मस्ती लेवल आपको कैसा लग रहा है?",
                "Hehe boss! Meri ye nayi tuning aur masti level aapko kaisa lag raha hai?",
                "🎀 मेरी आवाज़ और मस्ती लेवल कैसा लगा बॉस? 💖",
                "teasing"
            ),
            daemon=True
        ).start()

    def _on_add_keys_clicked(self):
        raw = self.input_new_key.text().strip()
        if not raw:
            return
        self.moon.api_pool.add_keys(raw)
        self.input_new_key.clear()
        self.moon.config["api_key"] = self.moon.api_pool.sync_keys_to_config_str()
        self.moon.save_all_config()
        self.render_pool_badges(self.moon.api_pool.get_pool_snapshot())

    def _on_delete_key_clicked(self):
        cur = self.list_keys.currentItem()
        if not cur:
            return
        key_str = cur.data(Qt.UserRole)
        self.moon.api_pool.remove_key(key_str)
        self.moon.config["api_key"] = self.moon.api_pool.sync_keys_to_config_str()
        self.moon.save_all_config()
        self.render_pool_badges(self.moon.api_pool.get_pool_snapshot())

    def _on_test_all_keys_clicked(self):
        self.btn_test_keys.setEnabled(False)
        self.btn_test_keys.setText("⏳ Testing Keys...")

        def _worker():
            try:
                self.moon.api_pool.test_all_keys()
            finally:
                self.moon.signals.update_pool_badges.emit(self.moon.api_pool.get_pool_snapshot())
                QTimer.singleShot(0, lambda: (
                    self.btn_test_keys.setEnabled(True),
                    self.btn_test_keys.setText("⚡ Test All Keys (Ping Latency)")
                ))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_send_quick_command(self):
        cmd = self.input_quick_cmd.text().strip()
        if not cmd:
            return
        self.input_quick_cmd.clear()
        self.moon.dispatch_user_command_async(cmd)

    def _on_toggle_debug_drawer(self):
        vis = self.txt_terminal.isVisible()
        self.txt_terminal.setVisible(not vis)
        if vis:
            self.btn_toggle_drawer.setText("▶ 7. Show Live Execution Terminal / Debug Drawer")
            self.resize(self.width(), 510)
        else:
            self.btn_toggle_drawer.setText("▼ 7. Hide Live Execution Terminal / Debug Drawer")
            self.resize(self.width(), 740)

    def append_terminal_line(self, line):
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.txt_terminal.append(f"[{ts}] {line}")


class MoonDesktopWidget(QWidget):
    """
    Non-Blocking Floating Anime Companion Widget on the Windows Desktop.
    - Synchronizes emotion state tags (`teasing`, `happy`, `focused`, `sleepy`, `angry_cute`, `worried`, `talking`)
      and real-time audio amplitude lip-sync (`talking_1`, `talking_2`, `talking_3`).
    - Provides 1-click access to the Control Panel (`⚙️`) and Barge-In voice interaction.
    """

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.show_subtitles = bool(config.get("show_subtitles", True))
        self.chat_history = []
        self.pixmap_cache = {}
        self.current_emotion = "idle"
        self.current_amplitude = 0.0
        self.breath_phase = 0.0
        self.base_sprite_y = 65
        self.is_executing_tasks = False

        self.press_global_pos = QPoint()
        self.window_start_pos = QPoint()
        self.is_dragging = False

        self.signals = UIBridgeSignals()
        self.signals.set_emotion.connect(self.update_sprite)
        self.signals.show_bubble.connect(self.display_speech_bubble)
        self.signals.set_status.connect(self.update_status_pill)
        self.signals.set_amplitude.connect(self.on_audio_amplitude)
        self.signals.append_log.connect(self._route_log_to_panel)
        self.signals.update_pool_badges.connect(self._route_badges_to_panel)
        self.signals.sync_toggles.connect(self._route_sync_toggles)

        # Initialize modular backend subsystems
        self.api_pool = GeminiAPIPoolManager(
            log_callback=self.emit_log,
            status_callback=lambda snap: self.signals.update_pool_badges.emit(snap)
        )
        self.vision_manager = VisionPrivacyAndCaptureManager(
            screen_vision_enabled=config.get("screen_vision_enabled", True),
            webcam_access_enabled=config.get("webcam_access_enabled", True),
            log_callback=self.emit_log
        )
        self.os_executor = OSActionAndVerifierEngine(
            api_pool=self.api_pool,
            vision_manager=self.vision_manager,
            log_callback=self.emit_log,
            status_callback=lambda st: self.signals.set_status.emit(st)
        )
        self.audio_manager = AudioEarAndTTSManager(
            api_pool=self.api_pool,
            config=self.config,
            on_speech_recognized=self.dispatch_user_command_async,
            on_barge_in=self._on_user_barge_in,
            on_status_update=lambda st: self.signals.set_status.emit(st),
            on_emotion_update=lambda em: self.signals.set_emotion.emit(em),
            on_amplitude_update=lambda amp: self.signals.set_amplitude.emit(amp),
            on_activity_reset=self._reset_proactive_timer,
            log_callback=self.emit_log
        )
        self.proactive_daemon = ProactiveIdleDaemon(
            api_pool=self.api_pool,
            vision_manager=self.vision_manager,
            os_executor=self.os_executor,
            config=self.config,
            is_busy_callback=lambda: (
                self.audio_manager.is_speaking
                or self.audio_manager.is_processing
                or self.is_executing_tasks
            ),
            on_proactive_speak_callback=self._handle_proactive_output,
            log_callback=self.emit_log
        )

        self.preload_sprite_cache()
        self.init_ui()
        self.control_panel = MoonControlPanelWindow(self)

        # Start background threads
        threading.Thread(target=self.os_executor.scan_installed_apps, daemon=True).start()
        self.audio_manager.start_ear_daemon()
        self.proactive_daemon.start_daemon()

        # Smooth 50ms breathing physics timer
        self.breath_timer = QTimer(self)
        self.breath_timer.timeout.connect(self.animate_breathing)
        self.breath_timer.start(50)

        self.emit_log("Moon Production AI Assistant initialized successfully.")

    def emit_log(self, text):
        print(text)
        self.signals.append_log.emit(str(text))

    def _route_log_to_panel(self, line):
        if hasattr(self, "control_panel") and self.control_panel is not None:
            self.control_panel.append_terminal_line(line)

    def _route_badges_to_panel(self, snapshot):
        if hasattr(self, "control_panel") and self.control_panel is not None:
            self.control_panel.render_pool_badges(snapshot)

    def _route_sync_toggles(self):
        if hasattr(self, "control_panel") and self.control_panel is not None:
            self.control_panel.refresh_from_state()

    def _reset_proactive_timer(self):
        if hasattr(self, "proactive_daemon"):
            self.proactive_daemon.reset_idle_timer()

    def _on_user_barge_in(self):
        self.emit_log("User Barge-In triggered! Halting speech playback and listening.")

    def save_all_config(self):
        save_config_file(self.config)

    def preload_sprite_cache(self):
        sprite_names = [
            "idle", "teasing", "happy", "focused", "sleepy",
            "angry_cute", "worried", "talking",
            "talking_1", "talking_2", "talking_3",
            "listening", "hanging"
        ]
        for name in sprite_names:
            p = os.path.join(ASSETS_DIR, f"{name}.png")
            if os.path.exists(p):
                self.pixmap_cache[name] = QPixmap(p).scaled(250, 305, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def init_ui(self):
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(295, 390)

        self.bubble = QLabel("", self)
        self.bubble.setWordWrap(True)
        self.bubble.setAlignment(Qt.AlignCenter)
        self.bubble.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.bubble.setStyleSheet("""
            QLabel {
                background-color: rgba(18, 15, 30, 232);
                color: #F8F4FF;
                border: 1.5px solid rgba(175, 130, 255, 215);
                border-radius: 13px;
                padding: 6px 10px;
            }
        """)
        self.bubble.setGeometry(10, 2, 275, 60)
        self.bubble.hide()

        self.sprite_label = QLabel(self)
        self.sprite_label.setGeometry(22, self.base_sprite_y, 250, 305)
        self.update_sprite("idle")

        # Floating Control Panel Gear Button (`⚙️`) right on Moon's widget
        self.btn_gear = QPushButton("⚙️", self)
        self.btn_gear.setToolTip("Open Moon Control Panel & Live Debug Drawer")
        self.btn_gear.setGeometry(242, 72, 34, 34)
        self.btn_gear.setStyleSheet("""
            QPushButton {
                background-color: rgba(28, 22, 48, 225);
                color: #E5D8FF;
                border: 1px solid rgba(165, 125, 255, 190);
                border-radius: 17px;
                font-size: 15px;
            }
            QPushButton:hover {
                background-color: rgba(110, 76, 230, 240);
            }
        """)
        self.btn_gear.clicked.connect(self.toggle_control_panel)

        self.status_pill = QLabel(self.audio_manager.default_mic_label(), self)
        self.status_pill.setAlignment(Qt.AlignCenter)
        self.status_pill.setFont(QFont("Segoe UI", 8, QFont.Bold))
        self.status_pill.setStyleSheet("""
            QLabel {
                background-color: rgba(20, 18, 34, 225);
                color: #D6C8FF;
                border: 1px solid rgba(155, 120, 255, 185);
                border-radius: 9px;
                padding: 2px 8px;
            }
        """)
        self.status_pill.setGeometry(22, 358, 250, 24)
        self.status_pill.show()

        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.width() - 305, screen.height() - 395)
        self.show()

    def toggle_control_panel(self):
        if self.control_panel.isVisible():
            self.control_panel.hide()
        else:
            self.control_panel.refresh_from_state()
            self.control_panel.show()
            self.control_panel.raise_()
            self.control_panel.activateWindow()

    def animate_breathing(self):
        if self.current_emotion == "hanging" or self.is_dragging:
            self.sprite_label.move(22, self.base_sprite_y)
            return
        speed = 0.18 if self.audio_manager.is_speaking else 0.11
        self.breath_phase += speed
        amp_boost = int(self.current_amplitude * 4.0)
        offset_y = int(math.sin(self.breath_phase) * 3.0) - amp_boost
        self.sprite_label.move(22, self.base_sprite_y + offset_y)

    def on_audio_amplitude(self, amp: float):
        """Real-time audio envelope lip-sync: maps voice amplitude (0..1) to mouth opening frames."""
        self.current_amplitude = amp
        if not self.audio_manager.is_speaking or amp <= 0.04:
            if self.current_emotion != "hanging":
                pix = self.pixmap_cache.get(self.current_emotion) or self.pixmap_cache.get("idle")
                if pix:
                    self.sprite_label.setPixmap(pix)
            return

        if amp < 0.28:
            frame_key = "talking_1"
        elif amp < 0.62:
            frame_key = "talking_2"
        else:
            frame_key = "talking_3"

        pix = self.pixmap_cache.get(frame_key)
        if pix:
            self.sprite_label.setPixmap(pix)

    def update_status_pill(self, text):
        if not text:
            self.status_pill.hide()
        else:
            self.status_pill.setText(text)
            self.status_pill.show()

    def update_sprite(self, emotion):
        self.current_emotion = emotion if emotion in self.pixmap_cache else "happy"
        pix = self.pixmap_cache.get(self.current_emotion) or self.pixmap_cache.get("idle")
        if pix:
            self.sprite_label.setPixmap(pix)

    def display_speech_bubble(self, text, duration_ms=5500):
        if not self.show_subtitles or not text:
            self.bubble.hide()
            return
        self.bubble.setText(text)
        self.bubble.show()
        QTimer.singleShot(duration_ms, self.bubble.hide)

    def speak_response(self, voice_text, roman_text=None, display_text=None, emotion="happy"):
        self.audio_manager.speak_synchronously(
            voice_text=voice_text,
            roman_text=roman_text,
            display_text=display_text,
            emotion=emotion,
            show_bubble_cb=lambda txt, dur: self.signals.show_bubble.emit(txt, dur)
        )

    def _handle_proactive_output(self, parsed_data):
        emotion = parsed_data.get("emotion", "teasing")
        voice_text = parsed_data.get("voice_text") or parsed_data.get("display_text")
        roman_text = parsed_data.get("roman_text") or voice_text
        display_text = parsed_data.get("display_text") or voice_text
        if voice_text:
            self.speak_response(voice_text, roman_text, display_text, emotion)

    def dispatch_user_command_async(self, user_text, force_screen=False, force_cam=False):
        threading.Thread(
            target=self._process_user_command_worker,
            args=(user_text, force_screen, force_cam),
            daemon=True,
            name="CommandProcessorThread"
        ).start()

    def _process_user_command_worker(self, user_text, force_screen=False, force_cam=False):
        self.is_executing_tasks = True
        self._reset_proactive_timer()
        self.signals.set_emotion.emit("focused")
        self.signals.set_status.emit("💭 Moon is Thinking...")
        self.emit_log(f"User Input -> '{user_text}'")

        images = []
        ui_context = ""

        try:
            want_cam = force_cam or needs_webcam_capture(user_text)
            want_screen = force_screen or needs_screen_capture(user_text)

            if want_cam:
                self.signals.set_status.emit("📷 Capturing Webcam Frame...")
                cam_img = self.vision_manager.capture_webcam_frame()
                if cam_img is not None:
                    images.append(cam_img)
                    user_text = f"[Webcam Photo Attached]: {user_text}"

            if want_screen:
                self.signals.set_status.emit("🖥️ Parsing Screen & UI Grid...")
                ann_img, _, ui_summary = self.vision_manager.capture_annotated_screen_with_grid()
                if ann_img is not None:
                    images.append(ann_img)
                    ui_context = f"\n[Active Window]: {self.os_executor.get_active_window_title()}\n[UI Elements]:\n{ui_summary[:650]}"

            full_prompt = user_text + ui_context
            masti_level = int(self.config.get("masti_level", 75))

            parsed, key_used, lat = self.api_pool.generate_multimodal_response(
                user_text=full_prompt,
                chat_history=self.chat_history,
                pil_images=images,
                masti_level=masti_level,
                expect_json=True
            )

            self.chat_history.append({"role": "user", "parts": [{"text": user_text}]})
            self.chat_history.append({"role": "model", "parts": [{"text": json.dumps(parsed, ensure_ascii=False)}]})
            if len(self.chat_history) > 8:
                del self.chat_history[:2]

            emotion = parsed.get("emotion", "happy")
            voice_text = parsed.get("voice_text") or parsed.get("display_text") or "अरे वाह बॉस, अभी करती हूँ!"
            roman_text = parsed.get("roman_text") or voice_text
            display_text = parsed.get("display_text") or voice_text
            tasks = parsed.get("tasks", [])

            self.emit_log(
                f"Gemini Plan ({key_used}, {lat}ms) | Emotion={emotion} | Tasks={len(tasks)} -> {json.dumps(tasks, ensure_ascii=False)}"
            )

            if not tasks:
                self.speak_response(voice_text, roman_text, display_text, emotion)
            else:
                # 1. Speak brief initial acknowledgment
                self.speak_response(voice_text, roman_text, display_text, emotion)

                # 2. Run Closed-Loop Multi-Task Queue & Self-Correction Verifier
                verification_results = self.os_executor.execute_task_queue_closed_loop(tasks)
                self.emit_log(f"Closed-Loop Verification Summary: {json.dumps(verification_results, ensure_ascii=False)}")

                # 3. Report back to the user in character after verifying all tasks in the queue!
                ok_cnt = sum(1 for r in verification_results if r["succeeded"])
                total_cnt = len(verification_results)
                if ok_cnt == total_cnt:
                    done_v = f"बॉस, आपके सारे {total_cnt} काम मैंने वेरीफाई करके पूरे कर दिए हैं!"
                    done_r = f"Boss, aapke saare {total_cnt} kaam maine verify karke poore kar diye hain!"
                    done_d = f"✅ Verified {ok_cnt}/{total_cnt} Tasks Complete!"
                    self.speak_response(done_v, done_r, done_d, "happy")
                else:
                    failed_names = ", ".join(r["description"] for r in verification_results if not r["succeeded"])
                    warn_v = f"बॉस, {total_cnt} में से {ok_cnt} काम हो गए, पर '{failed_names}' में थोड़ी दिक्कत आई!"
                    warn_r = f"Boss, {total_cnt} me se {ok_cnt} kaam ho gaye, par '{failed_names}' me thodi dikkat aayi!"
                    warn_d = f"⚠️ Verified {ok_cnt}/{total_cnt} (Check Terminal)"
                    self.speak_response(warn_v, warn_r, warn_d, "worried")

        except AllKeysExhaustedError as ake:
            diag = ake.diagnostics
            self.emit_log(f"ALL API KEYS FAILED: {json.dumps(diag, ensure_ascii=False)}")
            self.speak_response(
                diag.get("voice_text", str(ake)),
                diag.get("roman_text", str(ake)),
                diag.get("display_text", "⚠️ All Gemini API Keys Failed!"),
                "worried"
            )
        except Exception as e:
            tb = traceback.format_exc()
            self.emit_log(f"Unhandled Command Exception:\n{tb}")
            self.speak_response(
                "अरे बॉस, इस कमांड को चलाते वक़्त एक छोटा सा एरर आ गया, मैंने Debug Terminal में लॉग लिख दिया है!",
                "Are boss, is command ko chalate waqt ek chhota sa error aa gaya, maine Debug Terminal me log likh diya hai!",
                "⚠️ Error logged in Debug Terminal",
                "worried"
            )
        finally:
            self.is_executing_tasks = False
            self._reset_proactive_timer()
            self.signals.set_status.emit(self.audio_manager.default_mic_label())

    def trigger_manual_listen_or_barge_in(self):
        if self.audio_manager.is_speaking:
            self.audio_manager.stop_tts_playback()
        if self.audio_manager.mic_muted:
            self.config["mic_muted"] = False
            self.audio_manager.set_mic_muted(False)
            self.signals.sync_toggles.emit()
        self.audio_manager.force_listen_now = True
        self.update_sprite("listening")
        self.update_status_pill("👂 बोलिए, मैं सुन रही हूँ...")

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
                delta = event.globalPos() - self.press_global_pos
                self.move(self.window_start_pos + delta)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.is_dragging:
                self.is_dragging = False
                screen = QApplication.primaryScreen().availableGeometry()
                if self.y() > screen.height() - 415:
                    self.move(self.x(), screen.height() - 385)
                    self.update_sprite("hanging")
                elif self.y() < 25:
                    self.move(self.x(), 0)
                    self.update_sprite("hanging")
                else:
                    if self.current_emotion == "hanging":
                        self.update_sprite("idle")
            else:
                self.trigger_manual_listen_or_barge_in()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background-color: #1A1726; color: #F2ECFF; border: 1px solid #7C5CFF; border-radius: 8px; padding: 4px; }
            QMenu::item { padding: 6px 20px; border-radius: 4px; }
            QMenu::item:selected { background-color: #6B4CE6; color: white; }
        """)

        act_panel = menu.addAction("⚙️ Open Control Panel & Live Debug Drawer")
        act_talk = menu.addAction("🎙️ Speak to Moon Now (Click / Barge-In)")
        act_type = menu.addAction("⌨️ Type Multi-Task Command...")
        menu.addSeparator()

        act_screen = menu.addAction("🖥️ Inspect Screen & UI Tree Now")
        act_cam = menu.addAction("📷 Open Camera & Look at Me Now")
        act_proactive = menu.addAction("✨ Trigger Proactive Screen+Cam Peek Now")
        act_ram = menu.addAction("🧹 Clean System RAM (Background Worker)")
        menu.addSeparator()

        expr_menu = menu.addMenu("🎭 Preview Emotion States")
        expr_actions = {}
        for em_name in VALID_EMOTIONS + ["idle", "listening", "hanging"]:
            ea = expr_menu.addAction(f"✨ {em_name}")
            expr_actions[ea] = em_name

        menu.addSeparator()
        act_quit = menu.addAction("💤 Put Moon to Sleep (Exit)")

        chosen = menu.exec_(self.mapToGlobal(event.pos()))
        if not chosen:
            return
        if chosen == act_panel:
            self.toggle_control_panel()
        elif chosen == act_talk:
            self.trigger_manual_listen_or_barge_in()
        elif chosen == act_type:
            cmd, ok = QInputDialog.getText(self, "Moon Multi-Task Queue", "Enter 1 to 4 compound tasks:")
            if ok and cmd.strip():
                self.dispatch_user_command_async(cmd.strip())
        elif chosen == act_screen:
            self.dispatch_user_command_async("मेरी स्क्रीन देखो और बताओ क्या चल रहा है, कोई एरर हो तो बताओ!", force_screen=True)
        elif chosen == act_cam:
            self.dispatch_user_command_async("कैमरे से मुझे देखो और बताओ मैं कैसा लग रहा हूँ या क्या कर रहा हूँ!", force_cam=True)
        elif chosen == act_proactive:
            self.proactive_daemon.trigger_proactive_check_in(manual_trigger=True)
        elif chosen == act_ram:
            def _clean_worker():
                freed_mb, ram_pct, cnt = self.os_executor.clean_system_ram_safe()
                self.speak_response(
                    f"अरे वाह बॉस! मैंने {cnt} प्रोसेसेज़ की मेमोरी ट्रिम करके {freed_mb} MB RAM फ्री कर दी है!",
                    f"Are waah boss! Maine {cnt} processes ki memory trim karke {freed_mb} MB RAM free kar di hai!",
                    f"🧹 Freed {freed_mb} MB | RAM: {ram_pct}%",
                    "happy"
                )
            threading.Thread(target=_clean_worker, daemon=True).start()
        elif chosen in expr_actions:
            self.update_sprite(expr_actions[chosen])
        elif chosen == act_quit:
            QApplication.quit()


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
        build_all_emotion_sprites(default_img)

    config = load_config()
    moon = MoonDesktopWidget(config)
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()