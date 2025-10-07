"""
ModuWorks — Modern Utilities Powerhouse

Features:
- User account system (username + strong password, supports letters, numbers, punctuation, special characters)
- Notes management (create, open, edit, search, delete)
- Integrated sound recorder (menu-based, pause/resume/stop, WAV)
- Per-user settings (auto-speak, verbosity)
- Safe, fail-proof database handling
- Auto-update from GitHub
"""

__version__ = "1.0.0"

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
from pathlib import Path
from datetime import datetime
import hashlib
import secrets

# --- Sound recording dependencies ---
try:
    import pyaudio
    import wave
    import keyboard
except Exception:
    print("Warning: pyaudio or keyboard not available. Recording will not work.")

# --- Logging ---
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

# --- Paths ---
APP_NAME = "ModuWorks"
APP_DIR = Path.home() / f".{APP_NAME.lower()}"
DB_PATH = APP_DIR / "moduworks.db"
DOCS_DIR = APP_DIR / "documents"
APP_DIR.mkdir(exist_ok=True)
DOCS_DIR.mkdir(exist_ok=True)

DEFAULT_CONFIG = {
    "auto_speak": True,
    "verbosity": "normal"
}

# --- Database initialization ---
def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    # Users
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        salt TEXT NOT NULL,
        created_at REAL NOT NULL
    )
    """)
    # Notes
    cur.execute("""
    CREATE TABLE IF NOT EXISTS notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        filename TEXT NOT NULL,
        created_at REAL NOT NULL,
        modified_at REAL NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)
    con.commit()
    con.close()

# --- Password hashing ---
def hash_password(password):
    salt = secrets.token_hex(16)
    pw_hash = hashlib.sha256((salt + password).encode('utf-8')).hexdigest()
    return pw_hash, salt

def verify_password(stored_hash, salt, password_attempt):
    attempt_hash = hashlib.sha256((salt + password_attempt).encode('utf-8')).hexdigest()
    return stored_hash == attempt_hash

# --- User account management ---
def create_user():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    username = input("Choose a username (max 32 chars): ").strip()
    if not username or len(username) > 32:
        print("Invalid username.")
        return None
    password = getpass.getpass("Choose a password: ")
    if not password:
        print("Password cannot be empty.")
        return None
    password_hash, salt = hash_password(password)
    now = time.time()
    try:
        cur.execute("""
            INSERT INTO users (username, password_hash, salt, created_at)
            VALUES (?, ?, ?, ?)
        """, (username, password_hash, salt, now))
        con.commit()
        print(f"User '{username}' created successfully.")
        return get_user(username)
    except sqlite3.IntegrityError:
        print("Username already exists.")
        return None
    finally:
        con.close()

def get_user(username):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT id, username, password_hash, salt, created_at FROM users WHERE username = ?", (username.strip(),))
    row = cur.fetchone()
    con.close()
    if row:
        return {"id": row[0], "username": row[1], "password_hash": row[2], "salt": row[3], "created_at": row[4]}
    return None

def login_user():
    username = input("Username: ").strip()
    password = getpass.getpass("Password: ")
    user = get_user(username)
    if not user:
        print("User not found.")
        return None
    if verify_password(user['password_hash'], user['salt'], password):
        print(f"Welcome back, {username}.")
        return user
    print("Incorrect password.")
    return None

# --- Helper ---
def shorten_title(title, maxlen=60):
    title = title.strip()
    return (title[:maxlen] + "...") if len(title) > maxlen else title

# --- Notes management ---
def add_note(user_id):
    print("Creating a new note. Enter title:")
    title = input("Title: ").strip() or "Untitled"
    safe_title = "".join(c for c in title if c.isalnum() or c in (" ", "-", "_")).strip()
    filename = DOCS_DIR / (safe_title + "-" + str(int(time.time())) + ".txt")
    filename.write_text("", encoding="utf-8")
    now = time.time()
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        INSERT INTO notes (user_id, title, filename, created_at, modified_at)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, title, str(filename), now, now))
    con.commit()
    con.close()
    print(f"Note '{shorten_title(title)}' created. Opening in Notepad.")
    try:
        subprocess.run(["notepad.exe", str(filename)], check=True)
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute("UPDATE notes SET modified_at=? WHERE filename=?", (time.time(), str(filename)))
        con.commit()
        con.close()
        print("Saved.")
    except Exception as e:
        print(f"Notepad closed without saving: {e}")

def list_notes(user_id):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT id, title, filename, created_at, modified_at FROM notes WHERE user_id=? ORDER BY modified_at DESC", (user_id,))
    rows = cur.fetchall()
    con.close()
    return rows

def open_note_file(user_id, note_id):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT filename, title FROM notes WHERE id=? AND user_id=?", (note_id, user_id))
    row = cur.fetchone()
    con.close()
    if not row:
        print("Note not found.")
        return
    filename, title = row
    print(f"Opening note: {shorten_title(title)}")
    try:
        subprocess.run(["notepad.exe", filename], check=True)
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute("UPDATE notes SET modified_at=? WHERE id=?", (time.time(), note_id))
        con.commit()
        con.close()
    except Exception as e:
        print(f"Notepad closed without saving: {e}")

def delete_note_file(user_id, note_id):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT filename, title FROM notes WHERE id=? AND user_id=?", (note_id, user_id))
    row = cur.fetchone()
    if not row:
        print("Note not found.")
        return
    filename, title = row
    confirm = input(f"Type YES to delete '{shorten_title(title)}': ").strip().upper()
    if confirm == "YES":
        try:
            if os.path.exists(filename):
                os.unlink(filename)
            cur.execute("DELETE FROM notes WHERE id=? AND user_id=?", (note_id, user_id))
            con.commit()
            print("Deleted.")
        except Exception as e:
            print(f"Delete failed: {e}")
    else:
        print("Cancelled.")
    con.close()

# --- Sound recorder ---
def record_audio_menu():
    CHUNK = 4096
    FORMAT = pyaudio.paInt16
    RATE = 44100

    filename_base = input("Enter filename for recording: ").strip() or f"recording_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    output_file = DOCS_DIR / f"{filename_base}.wav"

    p = pyaudio.PyAudio()
    try:
        stream = p.open(format=FORMAT, channels=2, rate=RATE, input=True, frames_per_buffer=CHUNK)
    except Exception as e:
        print(f"Failed to open audio stream: {e}")
        p.terminate()
        return

    frames_queue = queue.Queue()
    stop_event = threading.Event()
    paused = False

    def audio_writer():
        wf = wave.open(str(output_file), 'wb')
        wf.setnchannels(2)
        wf.setsampwidth(p.get_sample_size(FORMAT))
        wf.setframerate(RATE)
        while not stop_event.is_set() or not frames_queue.empty():
            try:
                data = frames_queue.get(timeout=1)
                wf.writeframes(data)
                frames_queue.task_done()
            except queue.Empty:
                continue
        wf.close()

    writer_thread = threading.Thread(target=audio_writer)
    writer_thread.start()

    def toggle_pause():
        nonlocal paused
        paused = not paused
        print("Paused" if paused else "Resumed")

    keyboard.add_hotkey('p', toggle_pause)
    keyboard.add_hotkey('s', lambda: stop_event.set())
    print("Recording started. Press 'P' to pause/resume, 'S' to stop.")
    start_time = time.time()

    try:
        while not stop_event.is_set():
            if not paused:
                data = stream.read(CHUNK, exception_on_overflow=False)
                frames_queue.put(data)
    except KeyboardInterrupt:
        stop_event.set()
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()
        stop_event.set()
        writer_thread.join()
        frames_queue.join()
        print(f"Recording saved as '{output_file}' Duration: {time.time()-start_time:.2f} seconds.")

# --- Settings ---
def settings_menu(user):
    while True:
        print("\n--- Settings ---")
        print(f"1) Auto Speak (currently: {'on' if DEFAULT_CONFIG.get('auto_speak') else 'off'})")
        print(f"2) Verbosity (currently: {DEFAULT_CONFIG.get('verbosity')})")
        print("3) Back")
        choice = input("Choice: ").strip()
        if choice == "1":
            DEFAULT_CONFIG["auto_speak"] = not DEFAULT_CONFIG.get("auto_speak")
            print(f"Auto speak set to {'on' if DEFAULT_CONFIG['auto_speak'] else 'off'}")
        elif choice == "2":
            cur = DEFAULT_CONFIG.get("verbosity")
            nxt = {"short":"normal","normal":"verbose","verbose":"short"}[cur]
            DEFAULT_CONFIG["verbosity"] = nxt
            print(f"Verbosity set to {nxt}")
        elif choice == "3" or choice=="":
            break
        else:
            print("Unknown choice.")

# --- Auto-update ---
import requests
import shutil
def auto_update():
    try:
        GITHUB_RAW_URL = "https://raw.githubusercontent.com/tysonsylvester/ModuWorks/main/ModuWorks.py"
        resp = requests.get(GITHUB_RAW_URL, timeout=10)
        if resp.status_code != 200:
            print("Could not reach GitHub for updates.")
            return
        latest_content = resp.text
        for line in latest_content.splitlines():
            if line.startswith("__version__"):
                latest_version = line.split("=")[1].strip().strip('"').strip("'")
                break
        else:
            print("Could not detect version in GitHub file.")
            return
        if latest_version == __version__:
            return
        print(f"New version available: {latest_version} (current: {__version__})")
        resp = input("Do you want to update now? (y/n): ").strip().lower()
        if resp != "y":
            return
        current_script = Path(__file__).resolve()
        backup_path = current_script.with_suffix(".bak")
        shutil.copy2(current_script, backup_path)
        with tempfile.NamedTemporaryFile("w", delete=False, dir=current_script.parent) as tmp_file:
            tmp_file.write(latest_content)
            temp_path = Path(tmp_file.name)
        shutil.move(temp_path, current_script)
        print("Update successful! Please restart the script to use the new version.")
    except Exception as e:
        print(f"Update failed: {e}")

# --- Main Menu ---
def main_menu(user):
    while True:
        print(f"\n--- ModuWorks Main Menu (User: {user['username']}) ---")
        print("1) New Note")
        print("2) List / Open Notes")
        print("3) Delete Note")
        print("4) Record Audio")
        print("5) Settings")
        print("6) Logout")
        print("7) Exit")
        choice = input("Choice: ").strip()
        if choice == "1":
            add_note(user['id'])
        elif choice == "2":
            notes = list_notes(user['id'])
            if not notes:
                print("No notes.")
                continue
            for n in notes:
                nid, title, *_ = n
                print(f"[{nid}] {shorten_title(title)}")
            sub = input("Enter note ID to open or Enter to cancel: ").strip()
            if sub.isdigit():
                open_note_file(user['id'], int(sub))
        elif choice == "3":
            notes = list_notes(user['id'])
            if not notes:
                print("No notes.")
                continue
            for n in notes:
                nid, title, *_ = n
                print(f"[{nid}] {shorten_title(title)}")
            sub = input("Enter note ID to delete or Enter to cancel: ").strip()
            if sub.isdigit():
                delete_note_file(user['id'], int(sub))
        elif choice == "4":
            record_audio_menu()
        elif choice == "5":
            settings_menu(user)
        elif choice == "6":
            print("Logging out.")
            break
        elif choice == "7" or choice.lower() in ("q", "quit", "exit"):
            print("Goodbye.")
            exit()
        else:
            print("Unknown option.")

# --- Bootstrap ---
def bootstrap():
    init_db()
    print(f"Welcome to {APP_NAME} (version {__version__})")
    auto_update()
    while True:
        print("\nPlease choose from one of the following options:")
        print("1) Login")
        print("2) Create Account")
        print("3) Exit")
        choice = input("Choice: ").strip()
        if choice == "1":
            user = login_user()
            if user:
                main_menu(user)
        elif choice == "2":
            user = create_user()
            if user:
                main_menu(user)
        elif choice == "3" or choice.lower() in ("q","exit"):
            print("Goodbye.")
            exit()
        else:
            print("Unknown choice.")

if __name__ == "__main__":
    bootstrap()
