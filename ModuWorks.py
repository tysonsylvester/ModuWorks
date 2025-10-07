"""
ModuWorks — Modern powerhouse
Version: 1.1.1
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

# Sound recording dependencies
try:
    import pyaudio
    import wave
    import keyboard
except ImportError:
    print("Warning: pyaudio, keyboard, or wave not available. Recording will not work.")
    pyaudio = wave = keyboard = None

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
# Global configuration dictionary, loaded from file at startup
CONFIG = DEFAULT_CONFIG.copy()

__version__ = "1.1.1" # UPDATED VERSION NUMBER

# ---------- Config Management ----------
def load_config():
    """Loads config from JSON file, merges with defaults."""
    global CONFIG
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, 'r') as f:
                loaded_config = json.load(f)
                CONFIG.update(loaded_config)
            logging.info("Configuration loaded.")
        except Exception as e:
            logging.error(f"Failed to load config: {e}")
    save_config() # Ensures config file exists with defaults if load failed

def save_config():
    """Saves current global config to JSON file."""
    try:
        with open(CONFIG_PATH, 'w') as f:
            json.dump(CONFIG, f, indent=4)
    except Exception as e:
        logging.error(f"Failed to save config: {e}")

# ---------- Database Initialization ----------
def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    # Users table
    try:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """)
    except sqlite3.OperationalError as e:
        logging.warning(f"Users table issue: {e}")
    # Notes table with ON DELETE CASCADE for better data integrity
    cur.execute("""
    CREATE TABLE IF NOT EXISTS notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        filename TEXT NOT NULL,
        created_at REAL NOT NULL,
        modified_at REAL NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)
    con.commit()
    con.close()

# ---------- Password Hashing ----------
def hash_password(password):
    salt = secrets.token_hex(16)
    pw_hash = hashlib.sha256((salt + password).encode('utf-8')).hexdigest()
    return pw_hash, salt

def verify_password(stored_hash, salt, password_attempt):
    attempt_hash = hashlib.sha256((salt + password_attempt).encode('utf-8')).hexdigest()
    # SECURITY FIX: Use compare_digest to mitigate timing attacks
    return secrets.compare_digest(stored_hash, attempt_hash)

# ---------- User Account Management ----------
def get_user(username):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT id, username, password_hash, salt, created_at FROM users WHERE username = ?", (username.strip(),))
    row = cur.fetchone()
    con.close()
    if row:
        return {
            "id": row[0],
            "username": row[1],
            "password_hash": row[2],
            "salt": row[3],
            "created_at": row[4]
        }
    return None

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

# ---------- Helper Functions ----------
def speak_and_echo(text):
    """Prints text and optionally speaks it based on config."""
    print(text)
    if CONFIG.get("auto_speak"):
        # Placeholder for actual TTS implementation
        pass

def shorten_title(title, maxlen=60):
    title = title.strip()
    return (title[:maxlen] + "...") if len(title) > maxlen else title

def open_editor(file_path):
    """
    Opens the specified file using a cross-platform method.
    """
    file_path = str(file_path)
    try:
        if sys.platform == 'win32':
            # Windows: use startfile to open with default editor (Notepad)
            os.startfile(file_path)
        elif sys.platform == 'darwin':
            # macOS: use 'open' command
            subprocess.run(['open', file_path], check=True)
        else:
            # Linux/other Unix: try common terminal editors
            editor = os.environ.get('EDITOR', 'vi') # Fallback to vi
            subprocess.run([editor, file_path], check=True)
    except FileNotFoundError:
        speak_and_echo(f"Error: Default editor or '{editor}' not found on system. You must edit the file manually at: {file_path}")
        return False
    except subprocess.CalledProcessError as e:
        speak_and_echo(f"Error opening editor: The editor process failed. {e}")
        return False
    except Exception as e:
        speak_and_echo(f"Unexpected error opening file: {e}")
        return False
    return True

# ---------- Notes Management ----------
def add_note(user_id):
    speak_and_echo("Creating a new note. Enter title:")
    title = input("Title: ").strip() or f"Untitled Note ({datetime.now().strftime('%Y-%m-%d')})"
    
    # Create a cleaner, unique filename
    safe_title = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '_')
    filename = DOCS_DIR / f"{safe_title}_{secrets.token_hex(4)}.txt"
    try:
        filename.write_text("", encoding="utf-8")
    except OSError as e:
        speak_and_echo(f"Error creating file on disk: {e}")
        return

    now = time.time()
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    
    try:
        cur.execute("""
            INSERT INTO notes (user_id, title, filename, created_at, modified_at)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, title, str(filename), now, now))
        con.commit()
    except sqlite3.Error as e:
        speak_and_echo(f"Database error creating note: {e}")
        # Clean up the file if DB insertion failed
        if os.path.exists(filename):
             os.unlink(filename)
        return
    finally:
        con.close()
        
    speak_and_echo(f"Note '{shorten_title(title)}' created. Opening editor.")
    
    if open_editor(str(filename)):
        # Only update modification time if the editor was successfully launched
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute("UPDATE notes SET modified_at=? WHERE filename=?", (time.time(), str(filename)))
        con.commit()
        con.close()
        speak_and_echo("Saved and updated timestamp.")
    else:
        speak_and_echo("Could not open editor. Note created, but file was not modified.")

def list_notes(user_id):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT id, title, filename, created_at, modified_at FROM notes WHERE user_id=? ORDER BY modified_at DESC", (user_id,))
    rows = cur.fetchall()
    con.close()
    # Return a list of dicts for easier consumption
    return [{
        "id": row[0], 
        "title": row[1], 
        "filename": row[2], 
        "created_at": row[3], 
        "modified_at": row[4]
    } for row in rows]

def open_note_file(user_id, note_id):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT filename, title FROM notes WHERE id=? AND user_id=?", (note_id, user_id))
    row = cur.fetchone()
    con.close()
    
    if not row:
        speak_and_echo("Note not found or does not belong to you.")
        return
        
    filename, title = row
    speak_and_echo(f"Opening note: {shorten_title(title)}")
    
    if open_editor(filename):
        # Update modification time after successful edit
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute("UPDATE notes SET modified_at=? WHERE id=?", (time.time(), note_id))
        con.commit()
        con.close()
        speak_and_echo("Saved and updated timestamp.")

def delete_note_file(user_id, note_id):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT filename, title FROM notes WHERE id=? AND user_id=?", (note_id, user_id))
    row = cur.fetchone()
    
    if not row:
        speak_and_echo("Note not found or does not belong to you.")
        con.close()
        return
        
    filename, title = row
    confirm = input(f"Type YES to delete '{shorten_title(title)}' (This cannot be undone): ").strip().upper()
    
    if confirm == "YES":
        try:
            # 1. Delete file from disk
            if Path(filename).exists():
                os.unlink(filename)
            
            # 2. Delete record from database
            cur.execute("DELETE FROM notes WHERE id=? AND user_id=?", (note_id, user_id))
            con.commit()
            speak_and_echo(f"Note '{shorten_title(title)}' deleted successfully.")
            
        except OSError as e:
            # Better Error Handling
            speak_and_echo(f"File deletion failed: Check permissions. Error: {e}")
        except sqlite3.Error as e:
            # Better Error Handling
            speak_and_echo(f"Database update failed. Error: {e}")
        except Exception:
             speak_and_echo("An unexpected error occurred during deletion.")
    else:
        speak_and_echo("Cancelled.")
        
    con.close()

# ---------- Sound Recorder ----------
def record_audio_menu():
    if not (pyaudio and wave and keyboard):
        speak_and_echo("Audio recording dependencies are not installed. Please check warnings at startup.")
        return
        
    CHUNK = 4096
    FORMAT = pyaudio.paInt16
    RATE = 44100
    CHANNELS = 2
    
    # Input for filename
    filename_base = input("Enter filename for recording: ").strip() or f"recording_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    output_file = DOCS_DIR / f"{filename_base}.wav"

    p = pyaudio.PyAudio()
    try:
        stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)
    except Exception as e:
        speak_and_echo(f"Failed to open audio stream (Mic error?): {e}")
        p.terminate()
        return

    frames_queue = queue.Queue()
    stop_event = threading.Event()
    paused = threading.Event() # Using Event for pause state

    def audio_writer():
        try:
            wf = wave.open(str(output_file), 'wb')
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(p.get_sample_size(FORMAT))
            wf.setframerate(RATE)
            while not stop_event.is_set() or not frames_queue.empty():
                try:
                    # Timeout prevents writer from blocking indefinitely
                    data = frames_queue.get(timeout=0.1) 
                    wf.writeframes(data)
                    frames_queue.task_done()
                except queue.Empty:
                    continue
        except Exception as e:
             logging.error(f"Audio writer error: {e}")
        finally:
            if 'wf' in locals() and wf:
                wf.close()

    writer_thread = threading.Thread(target=audio_writer)
    writer_thread.start()

    def toggle_pause():
        if paused.is_set():
            paused.clear()
            print("Resumed")
        else:
            paused.set()
            print("Paused")

    # Hook up hotkeys
    keyboard.add_hotkey('p', toggle_pause)
    keyboard.add_hotkey('s', lambda: stop_event.set())
    speak_and_echo("Recording started. Press 'P' to pause/resume, 'S' to stop.")
    start_time = time.time()

    try:
        while not stop_event.is_set():
            if not paused.is_set():
                # Read audio data
                data = stream.read(CHUNK, exception_on_overflow=False)
                frames_queue.put(data)
            else:
                # FIX: Prevents 100% CPU usage when paused.
                time.sleep(0.1) 
                
    except KeyboardInterrupt:
        stop_event.set()
    except Exception as e:
        speak_and_echo(f"Recording error: {e}")
        stop_event.set()
    finally:
        # Cleanup hotkeys and resources
        keyboard.remove_hotkey('p')
        keyboard.remove_hotkey('s')
        stream.stop_stream()
        stream.close()
        p.terminate()
        stop_event.set()
        writer_thread.join()
        frames_queue.join()
        speak_and_echo(f"Recording saved as '{output_file}' Duration: {time.time()-start_time:.2f} seconds.")

# ---------- Settings ----------
def settings_menu(user):
    while True:
        print("\n--- Settings ---")
        print(f"1) Auto Speak (currently: {'ON' if CONFIG.get('auto_speak') else 'OFF'})")
        print(f"2) Verbosity (currently: {CONFIG.get('verbosity').upper()})")
        print("3) Back")
        choice = input("Choice: ").strip()
        
        if choice == "1":
            CONFIG["auto_speak"] = not CONFIG.get("auto_speak")
            speak_and_echo(f"Auto speak set to {'ON' if CONFIG['auto_speak'] else 'OFF'}")
        elif choice == "2":
            cur = CONFIG.get("verbosity")
            # Simple cyclic switching
            nxt = {"short":"normal","normal":"verbose","verbose":"short"}.get(cur, "normal")
            CONFIG["verbosity"] = nxt
            speak_and_echo(f"Verbosity set to {nxt.upper()}")
        elif choice == "3" or choice == "":
            save_config() # Saves changes before exiting
            break
        else:
            speak_and_echo("Unknown choice.")

# ---------- Auto Update ----------
def auto_update():
    raw_url = "https://raw.githubusercontent.com/tysonsylvester/ModuWorks/main/ModuWorks.py"
    
    print("Checking for updates...")
    try:
        with urllib.request.urlopen(raw_url, timeout=5) as response:
            latest_content = response.read().decode('utf-8')
        
        # Check the explicit __version__ variable for the latest version
        match = re.search(r'^__version__\s*=\s*[\'"]([^\'"]+)[\'"]', latest_content, re.MULTILINE)
        
        if match:
            latest_version = match.group(1)
        else:
            print("Could not detect version in remote file. Update cancelled.")
            return

        if latest_version != __version__:
            print(f"New version available: {latest_version}. Your version: {__version__}. Updating...")
            
            # Critical: Get the path of the currently running file
            current_file_path = os.path.abspath(__file__)
            
            with open(current_file_path, 'w', encoding='utf-8') as f:
                f.write(latest_content)
                
            print("\n*** Update complete! Please restart the program to use the new version. ***")
            exit() # Force exit after successful update
        else:
            print("You are running the latest version.")
            
    except urllib.error.URLError as e:
        print(f"Auto-update failed: Could not reach server. Error: {e.reason}")
    except Exception as e:
        print(f"Auto-update failed: {e}")

# ---------- Main Menu ----------
def main_menu(user):
    while True:
        print(f"\n--- ModuWorks Main Menu (User: {user['username']}) | v{__version__} ---")
        print("1) New Note")
        print("2) List / Open Notes")
        print("3) Delete Note")
        print("4) Record Audio")
        print("5) Settings")
        print("6) Check for Updates")
        print("7) Logout")
        print("8) Exit")
        choice = input("Choice: ").strip()
        
        user_id = user['id']
        
        if choice == "1":
            add_note(user_id)
        
        # Combined List, Open, and Delete logic to avoid redundant queries
        elif choice == "2" or choice == "3":
            notes = list_notes(user_id)
            if not notes:
                speak_and_echo("No notes found.")
                continue
                
            print("\nAvailable Notes:")
            notes_dict = {}
            for n in notes:
                # Store notes in a dictionary for quick lookup by ID (string key)
                notes_dict[str(n['id'])] = n
                mod_time = datetime.fromtimestamp(n['modified_at']).strftime('%Y-%m-%d %H:%M')
                print(f"[{n['id']:<3}] {shorten_title(n['title'], 50):<52} (Modified: {mod_time})")

            if choice == "2":
                sub = input("Enter note ID to open or Enter to cancel: ").strip()
                if sub.isdigit() and sub in notes_dict:
                    open_note_file(user_id, int(sub))
                elif sub:
                     speak_and_echo("Invalid ID or cancelled.")
                     
            elif choice == "3":
                sub = input("Enter note ID to delete or Enter to cancel: ").strip()
                if sub.isdigit() and sub in notes_dict:
                    delete_note_file(user_id, int(sub))
                elif sub:
                    speak_and_echo("Invalid ID or cancelled.")

        elif choice == "4":
            record_audio_menu()
        elif choice == "5":
            settings_menu(user)
        elif choice == "6":
            auto_update()
        elif choice == "7":
            speak_and_echo("Logging out.")
            break
        elif choice == "8" or choice.lower() in ("q", "quit", "exit"):
            speak_and_echo("Goodbye.")
            exit()
        else:
            speak_and_echo("Unknown option.")

# ---------- Bootstrap ----------
def bootstrap():
    load_config()
    init_db()
    print(f"Welcome to {APP_NAME} v{__version__}")
    
    while True:
        print("\nPlease choose from one of the following options:")
        print("1) Login")
        print("2) Create Account")
        print("3) Check for Updates")
        print("4) Exit")
        choice = input("Choice: ").strip()
        
        if choice == "1":
            user = login_user()
            if user:
                main_menu(user)
        elif choice == "2":
            user = create_user()
            if user:
                main_menu(user)
        elif choice == "3":
            auto_update()
        elif choice == "4" or choice.lower() in ("q","exit"):
            print("Goodbye.")
            exit()
        else:
            print("Unknown choice.")

if __name__ == "__main__":
    bootstrap()