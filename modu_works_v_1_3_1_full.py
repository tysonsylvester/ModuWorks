"""
ModuWorks — Modern powerhouse
Version: 1.3.1
"""

import os
import json
import sqlite3
import subprocess
import tempfile
import time
import getpass
import logging
import threading
import queue
import re
import sys
import urllib.request
from pathlib import Path
from datetime import datetime
import hashlib
import secrets
import select

# Sound recording and audio conversion dependencies
try:
    import pyaudio
    import wave
    from pydub import AudioSegment
except ImportError as e:
    print(f"Warning: Audio dependencies (pyaudio, pydub) not available. Recording/Conversion will not work. Error: {e}")
    pyaudio = wave = AudioSegment = None

# Setup logging
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

# ----------- Paths & Config -----------
APP_NAME = "ModuWorks"
APP_DIR = Path.home() / f".{APP_NAME.lower()}"
DB_PATH = APP_DIR / "moduworks.db"
CONFIG_PATH = APP_DIR / "config.json"
DOCS_DIR = APP_DIR / "documents"
DOCS_DIR.mkdir(exist_ok=True)
APP_DIR.mkdir(exist_ok=True)

DEFAULT_CONFIG = {
    "auto_speak": False,
    "verbosity": "normal"
}
CONFIG = DEFAULT_CONFIG.copy()

__version__ = "1.3.1"

REMINDER_QUEUE = queue.Queue()

# ---------- Config Management ----------
def load_config():
    global CONFIG
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, 'r') as f:
                loaded_config = json.load(f)
                CONFIG.update(loaded_config)
            logging.info("Configuration loaded.")
        except Exception as e:
            logging.error(f"Failed to load config: {e}")
    save_config()

def save_config():
    try:
        with open(CONFIG_PATH, 'w') as f:
            json.dump(CONFIG, f, indent=4)
    except Exception as e:
        logging.error(f"Failed to save config: {e}")

# ---------- Database Initialization ----------
def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        salt TEXT NOT NULL,
        created_at REAL NOT NULL
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        filename TEXT NOT NULL,
        created_at REAL NOT NULL,
        modified_at REAL NOT NULL,
        reminder_time REAL NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )""")

    try:
        cur.execute("ALTER TABLE notes ADD COLUMN reminder_time REAL NULL")
        logging.info("Database migration: Added 'reminder_time' column to 'notes' table.")
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e):
            logging.warning(f"Unexpected DB migration error: {e}")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS tags (
        note_id INTEGER NOT NULL,
        tag TEXT NOT NULL,
        PRIMARY KEY (note_id, tag),
        FOREIGN KEY(note_id) REFERENCES notes(id) ON DELETE CASCADE
    )""")

    con.commit()
    con.close()

# ---------- Password Hashing and User Management ----------
def hash_password(password):
    salt = secrets.token_hex(16)
    pw_hash = hashlib.sha256((salt + password).encode('utf-8')).hexdigest()
    return pw_hash, salt

def verify_password(stored_hash, salt, password_attempt):
    attempt_hash = hashlib.sha256((salt + password_attempt).encode('utf-8')).hexdigest()
    return secrets.compare_digest(stored_hash, attempt_hash)

def get_user(username):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT id, username, password_hash, salt, created_at FROM users WHERE username = ?", (username.strip(),))
    row = cur.fetchone()
    con.close()
    if row:
        return {"id": row[0], "username": row[1], "password_hash": row[2], "salt": row[3], "created_at": row[4]}
    return None

# ---------- Helper Functions ----------
def speak_and_echo(text):
    print(text)
    if CONFIG.get("auto_speak"):
        pass

def shorten_title(title, maxlen=60):
    title = title.strip()
    return (title[:maxlen] + "...") if len(title) > maxlen else title

def open_editor(file_path):
    try:
        if sys.platform == 'win32':
            os.startfile(str(file_path))
        elif sys.platform == 'darwin':
            subprocess.run(['open', str(file_path)], check=True)
        else:
            editor = os.environ.get('EDITOR', 'vi')
            subprocess.run([editor, str(file_path)], check=True)
    except Exception as e:
        speak_and_echo(f"Error opening editor: {e}")
        return False
    return True

# ---------- Notes, Tags, Reminders (unchanged) ----------
# ... [Rest of note, tag, reminder code remains unchanged] ...

# ---------- Audio Recording Fix ----------
def get_input_non_blocking(timeout=0.01):
    try:
        if sys.stdin in select.select([sys.stdin], [], [], timeout)[0]:
            return sys.stdin.readline().strip()
    except Exception:
        return None

    return None


def record_audio_menu():
    if not (pyaudio and wave and AudioSegment):
        speak_and_echo("Audio recording/conversion dependencies not available.")
        return

    CHUNK = 4096
    FORMAT = pyaudio.paInt16
    RATE = 44100
    CHANNELS = 2

    filename_base = input("Enter filename for recording: ").strip() or f"recording_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    wav_file = DOCS_DIR / f"{filename_base}.wav"

    p = pyaudio.PyAudio()
    try:
        stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)
    except Exception as e:
        speak_and_echo(f"Failed to open audio stream: {e}")
        p.terminate()
        return

    frames_queue = queue.Queue()
    stop_event = threading.Event()
    paused = threading.Event()

    def audio_writer():
        try:
            wf = wave.open(str(wav_file), 'wb')
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(p.get_sample_size(FORMAT))
            wf.setframerate(RATE)
            while not stop_event.is_set() or not frames_queue.empty():
                try:
                    data = frames_queue.get(timeout=0.1)
                    wf.writeframes(data)
                    frames_queue.task_done()
                except queue.Empty:
                    continue
        except Exception as e:
            logging.error(f"Audio writer error: {e}")
        finally:
            if 'wf' in locals():
                wf.close()

    writer_thread = threading.Thread(target=audio_writer)
    writer_thread.start()

    speak_and_echo("Recording started. Type 'P' to pause/resume, 'S' to stop.")
    start_time = time.time()

    try:
        while not stop_event.is_set():
            cmd = get_input_non_blocking(timeout=0.01)
            if cmd:
                cmd = cmd.upper()
                if cmd == 'P':
                    if paused.is_set(): paused.clear(); print("Resumed")
                    else: paused.set(); print("Paused")
                elif cmd == 'S':
                    stop_event.set()

            if not paused.is_set():
                try:
                    data = stream.read(CHUNK, exception_on_overflow=False)
                    frames_queue.put(data)
                except Exception as e:
                    logging.error(f"Stream read error: {e}")
                    stop_event.set()
            else:
                time.sleep(0.05)

    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()
        stop_event.set()
        writer_thread.join()
        frames_queue.join()

        duration = time.time() - start_time
        speak_and_echo(f"Recording saved as '{wav_file.name}', duration: {duration:.2f} sec.")

        if duration > 1.0:
            convert = input("Convert to MP3 and delete WAV? (y/n): ").strip().lower()
            if convert == 'y':
                try:
                    mp3_path = wav_file.with_suffix('.mp3')
                    audio = AudioSegment.from_wav(str(wav_file))
                    audio.export(str(mp3_path), format='mp3')
                    os.unlink(wav_file)
                    speak_and_echo(f"Conversion successful: {mp3_path.name}")
                except Exception as e:
                    speak_and_echo(f"Conversion failed: {e}")

# ---------- Bootstrap and Main Menu ----------
# ... [Rest remains the same, integrating new version 1.3.1] ...
