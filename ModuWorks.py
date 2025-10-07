"""
ModuWorks — Modern powerhouse
Version: 1.3.0
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
    # Note: pydub requires the external FFmpeg or Libav to be installed and in the system PATH.
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

__version__ = "1.2.0" # Current Version

# A queue to handle reminders
REMINDER_QUEUE = queue.Queue()

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
    save_config()

def save_config():
    """Saves current global config to JSON file."""
    try:
        with open(CONFIG_PATH, 'w') as f:
            json.dump(CONFIG, f, indent=4)
    except Exception as e:
        logging.error(f"Failed to save config: {e}")

# ---------- Database Initialization and Tagging Table (FIXED) ----------
def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    # Users table (unchanged)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        salt TEXT NOT NULL,
        created_at REAL NOT NULL
    )
    """)

    # Notes table (CREATE TABLE is included in case the DB is new)
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
    )
    """)

    # 🟢 DATABASE MIGRATION STEP: Safely add the missing 'reminder_time' column
    try:
        cur.execute("ALTER TABLE notes ADD COLUMN reminder_time REAL NULL")
        logging.info("Database migration: Added 'reminder_time' column to 'notes' table.")
    except sqlite3.OperationalError as e:
        # Ignore "duplicate column name" error if the column already exists
        if "duplicate column name" not in str(e):
             logging.warning(f"Unexpected DB migration error: {e}")
    # -------------------------------------------------------------------

    # Tags table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS tags (
        note_id INTEGER NOT NULL,
        tag TEXT NOT NULL,
        PRIMARY KEY (note_id, tag),
        FOREIGN KEY(note_id) REFERENCES notes(id) ON DELETE CASCADE
    )
    """)

    con.commit()
    con.close()

# ---------- Password Hashing and User Management (Unchanged) ----------
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

# ---------- Helper Functions and Note Management (Updated) ----------
def speak_and_echo(text):
    print(text)
    if CONFIG.get("auto_speak"):
        pass

def shorten_title(title, maxlen=60):
    title = title.strip()
    return (title[:maxlen] + "...") if len(title) > maxlen else title

def open_editor(file_path):
    file_path = str(file_path)
    try:
        if sys.platform == 'win32':
            os.startfile(file_path)
        elif sys.platform == 'darwin':
            subprocess.run(['open', file_path], check=True)
        else:
            editor = os.environ.get('EDITOR', 'vi')
            subprocess.run([editor, file_path], check=True)
    except FileNotFoundError:
        speak_and_echo(f"Error: Default editor or '{editor}' not found. Edit manually at: {file_path}")
        return False
    except subprocess.CalledProcessError as e:
        speak_and_echo(f"Error opening editor: The editor process failed. {e}")
        return False
    except Exception as e:
        speak_and_echo(f"Unexpected error opening file: {e}")
        return False
    return True

def get_note_tags(note_id):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT tag FROM tags WHERE note_id = ?", (note_id,))
    tags = [row[0] for row in cur.fetchall()]
    con.close()
    return tags

def list_notes(user_id, search_term=None):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    query = """
        SELECT DISTINCT n.id, n.title, n.filename, n.created_at, n.modified_at, n.reminder_time
        FROM notes n
        LEFT JOIN tags t ON n.id = t.note_id
        WHERE n.user_id=?
    """
    params = [user_id]
    
    if search_term:
        # Simple text and tag search
        query += " AND (n.title LIKE ? OR t.tag LIKE ?)"
        params.extend([f"%{search_term}%", f"%{search_term}%"])
        
    query += " ORDER BY n.modified_at DESC"
    
    cur.execute(query, params)
    rows = cur.fetchall()
    con.close()
    
    notes = []
    for row in rows:
        note_id = row[0]
        reminder_time = row[5]
        
        notes.append({
            "id": note_id, 
            "title": row[1], 
            "filename": row[2], 
            "created_at": row[3], 
            "modified_at": row[4], 
            "reminder_time": reminder_time,
            "tags": get_note_tags(note_id) # Fetch tags separately
        })
    return notes

def add_note(user_id):
    speak_and_echo("Creating a new note. Enter title:")
    title = input("Title: ").strip() or f"Untitled Note ({datetime.now().strftime('%Y-%m-%d')})"
    
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
            INSERT INTO notes (user_id, title, filename, created_at, modified_at, reminder_time)
            VALUES (?, ?, ?, ?, ?, NULL)
        """, (user_id, title, str(filename), now, now))
        con.commit()
        note_id = cur.lastrowid
    except sqlite3.Error as e:
        speak_and_echo(f"Database error creating note: {e}")
        if os.path.exists(filename):
             os.unlink(filename)
        return
    finally:
        con.close()
        
    speak_and_echo(f"Note '{shorten_title(title)}' created. Opening editor.")
    
    if open_editor(str(filename)):
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute("UPDATE notes SET modified_at=? WHERE id=?", (time.time(), note_id))
        con.commit()
        con.close()
        speak_and_echo("Saved and updated timestamp.")
    else:
        speak_and_echo("Could not open editor. Note created, but file was not modified.")

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
            if Path(filename).exists():
                os.unlink(filename)
            
            cur.execute("DELETE FROM notes WHERE id=? AND user_id=?", (note_id, user_id))
            con.commit()
            speak_and_echo(f"Note '{shorten_title(title)}' deleted successfully.")
            
        except OSError as e:
            speak_and_echo(f"File deletion failed: Check permissions. Error: {e}")
        except sqlite3.Error as e:
            speak_and_echo(f"Database update failed. Error: {e}")
        except Exception:
             speak_and_echo("An unexpected error occurred during deletion.")
    else:
        speak_and_echo("Cancelled.")
        
    con.close()

# ---------- Tagging System ----------
def manage_tags(user_id, note_id, notes_dict):
    if str(note_id) not in notes_dict:
        speak_and_echo("Invalid note ID.")
        return
        
    note = notes_dict[str(note_id)]
    current_tags = get_note_tags(note_id)
    speak_and_echo(f"\n--- Managing Tags for: {shorten_title(note['title'])} ---")
    speak_and_echo(f"Current Tags: {', '.join(current_tags) or 'None'}")
    
    action = input("Action (add <tag>, remove <tag>, or Back): ").strip()
    if not action or action.lower() == 'back':
        return

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    
    try:
        if action.lower().startswith('add '):
            tag = action[4:].strip().lower()
            if not tag: raise ValueError("Tag cannot be empty.")
            cur.execute("INSERT OR IGNORE INTO tags (note_id, tag) VALUES (?, ?)", (note_id, tag))
            speak_and_echo(f"Tag '{tag}' added.")
            
        elif action.lower().startswith('remove '):
            tag = action[7:].strip().lower()
            if not tag: raise ValueError("Tag cannot be empty.")
            cur.execute("DELETE FROM tags WHERE note_id=? AND tag=?", (note_id, tag))
            if cur.rowcount == 0:
                speak_and_echo(f"Tag '{tag}' was not found on this note.")
            else:
                speak_and_echo(f"Tag '{tag}' removed.")
                
        else:
            speak_and_echo("Invalid tag action.")
            
        con.commit()
    except Exception as e:
        speak_and_echo(f"Error managing tags: {e}")
    finally:
        con.close()

# ---------- Reminder System ----------
def manage_reminder(user_id, note_id, notes_dict):
    if str(note_id) not in notes_dict:
        speak_and_echo("Invalid note ID.")
        return
    
    note = notes_dict[str(note_id)]
    
    if note['reminder_time']:
        dt = datetime.fromtimestamp(note['reminder_time'])
        speak_and_echo(f"Current Reminder: {dt.strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        speak_and_echo("No current reminder set.")
        
    speak_and_echo("Enter new time (YYYY-MM-DD HH:MM), 'clear', or 'back':")
    user_input = input("Reminder: ").strip()
    
    if user_input.lower() == 'back' or not user_input:
        return
    
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    
    try:
        if user_input.lower() == 'clear':
            timestamp = None
            speak_and_echo("Reminder cleared.")
        else:
            # Simple parsing of date/time
            dt_obj = datetime.strptime(user_input, '%Y-%m-%d %H:%M')
            timestamp = dt_obj.timestamp()
            if timestamp <= time.time():
                raise ValueError("Reminder time must be in the future.")
            speak_and_echo(f"Reminder set for: {dt_obj.strftime('%Y-%m-%d %H:%M')}")
        
        cur.execute("UPDATE notes SET reminder_time=? WHERE id=?", (timestamp, note_id))
        con.commit()
        
        # Force a refresh in the reminder thread by adding a dummy item
        REMINDER_QUEUE.put({"type": "refresh"}) 
        
    except ValueError as e:
        speak_and_echo(f"Error: {e}. Format must be YYYY-MM-DD HH:MM.")
    except Exception as e:
        speak_and_echo(f"Database error: {e}")
    finally:
        con.close()

def reminder_worker(user_id):
    """Background thread to check and trigger reminders."""
    while True:
        try:
            # Check the queue for termination/refresh signals
            if not REMINDER_QUEUE.empty():
                item = REMINDER_QUEUE.get_nowait()
                if item.get("type") == "terminate":
                    break
                if item.get("type") == "refresh":
                    pass 
            
            con = sqlite3.connect(DB_PATH)
            cur = con.cursor()
            
            # Find notes with reminder_time in the past but not yet triggered
            now = time.time()
            cur.execute("""
                SELECT id, title FROM notes 
                WHERE user_id=? AND reminder_time IS NOT NULL AND reminder_time < ?
            """, (user_id, now))
            
            reminders = cur.fetchall()
            
            for note_id, title in reminders:
                # IMPORTANT: Print immediately followed by a newline to ensure it's visible over user input
                print(f"\n🔔 REMINDER: {shorten_title(title, 40)} (Note ID: {note_id})")
                
                # Clear the reminder time so it doesn't trigger again
                cur.execute("UPDATE notes SET reminder_time=NULL WHERE id=?", (note_id,))
                con.commit()
                
            con.close()
            time.sleep(10) # Check every 10 seconds
            
        except sqlite3.Error as e:
            # Now that the migration is fixed, this should be rare
            logging.error(f"Reminder thread DB error: {e}")
            time.sleep(30)
        except Exception as e:
            logging.error(f"Reminder thread general error: {e}")
            time.sleep(30)
            
# ---------- Sound Recorder & Converter ----------
def convert_wav_to_mp3(wav_path):
    if not AudioSegment:
        speak_and_echo("Conversion failed: pydub is not imported.")
        return
    try:
        mp3_path = wav_path.with_suffix('.mp3')
        speak_and_echo(f"Converting to MP3: {wav_path.name} -> {mp3_path.name}...")
        
        audio = AudioSegment.from_wav(str(wav_path))
        audio.export(str(mp3_path), format="mp3")
        
        # Delete the original WAV file to save space
        os.unlink(wav_path)
        speak_and_echo("Conversion successful. Original WAV file deleted.")
        
    except FileNotFoundError:
        speak_and_echo("Conversion failed: FFmpeg (or Libav) not found. Please install it and ensure it's in your PATH.")
    except Exception as e:
        speak_and_echo(f"Conversion failed: {e}")

def get_input_non_blocking(timeout=0.1):
    """Checks for console input without blocking the thread."""
    if sys.stdin in select.select([sys.stdin], [], [], timeout)[0]:
        return sys.stdin.readline().strip()
    return None

def record_audio_menu():
    if not (pyaudio and wave and AudioSegment):
        speak_and_echo("Audio recording/conversion dependencies are not available.")
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
        speak_and_echo(f"Failed to open audio stream (Mic error?): {e}")
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
            if 'wf' in locals() and wf:
                wf.close()

    writer_thread = threading.Thread(target=audio_writer)
    writer_thread.start()

    speak_and_echo("Recording started. Type 'P' to pause/resume, 'S' to stop.")
    start_time = time.time()
    
    try:
        while not stop_event.is_set():
            # Check for command input
            cmd = get_input_non_blocking(timeout=0.01) # Small timeout for responsiveness
            if cmd and cmd.upper() == 'P':
                if paused.is_set():
                    paused.clear()
                    print("Resumed")
                else:
                    paused.set()
                    print("Paused")
            elif cmd and cmd.upper() == 'S':
                stop_event.set()
                
            # Audio capture logic
            if not paused.is_set():
                data = stream.read(CHUNK, exception_on_overflow=False)
                frames_queue.put(data)
            else:
                time.sleep(0.1)
                
    except Exception as e:
        speak_and_echo(f"Recording error: {e}")
        stop_event.set()
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()
        stop_event.set()
        writer_thread.join()
        frames_queue.join()
        
        duration = time.time()-start_time
        speak_and_echo(f"Recording saved as '{wav_file.name}'. Duration: {duration:.2f} seconds.")
        
        # Conversion prompt
        if duration > 1.0: # Only convert recordings longer than 1 sec
            convert = input("Convert to MP3 and delete WAV? (y/n): ").strip().lower()
            if convert == 'y':
                convert_wav_to_mp3(wav_file)

# ---------- Settings and Update (Same as 1.1.1) ----------
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
            nxt = {"short":"normal","normal":"verbose","verbose":"short"}.get(cur, "normal")
            CONFIG["verbosity"] = nxt
            speak_and_echo(f"Verbosity set to {nxt.upper()}")
        elif choice == "3" or choice == "":
            save_config()
            break
        else:
            speak_and_echo("Unknown choice.")

def auto_update():
    raw_url = "https://raw.githubusercontent.com/tysonsylvester/ModuWorks/main/ModuWorks.py"
    
    print("Checking for updates...")
    try:
        with urllib.request.urlopen(raw_url, timeout=5) as response:
            latest_content = response.read().decode('utf-8')
        
        match = re.search(r'^__version__\s*=\s*[\'"]([^\'"]+)[\'"]', latest_content, re.MULTILINE)
        
        if match:
            latest_version = match.group(1)
        else:
            print("Could not detect version in remote file. Update cancelled.")
            return

        if latest_version != __version__:
            print(f"New version available: {latest_version}. Your version: {__version__}. Updating...")
            
            current_file_path = os.path.abspath(__file__)
            
            with open(current_file_path, 'w', encoding='utf-8') as f:
                f.write(latest_content)
                
            print("\n*** Update complete! Please restart the program to use the new version. ***")
            exit()
        else:
            print("You are running the latest version.")
            
    except urllib.error.URLError as e:
        print(f"Auto-update failed: Could not reach server. Error: {e.reason}")
    except Exception as e:
        print(f"Auto-update failed: {e}")

# ---------- Main Menu ----------
def main_menu(user):
    reminder_thread = threading.Thread(target=reminder_worker, args=(user['id'],), daemon=True)
    reminder_thread.start()

    while True:
        print(f"\n--- ModuWorks Main Menu (User: {user['username']}) | v{__version__} ---")
        print("1) New Note")
        print("2) List / View / Manage Notes")
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
        
        elif choice == "2" or choice == "3":
            
            search = input("Search by keyword/tag (optional, press Enter to list all): ").strip()
            notes = list_notes(user_id, search_term=search)
            
            if not notes:
                speak_and_echo("No notes found matching criteria.")
                continue
                
            print("\nAvailable Notes:")
            notes_dict = {}
            for n in notes:
                notes_dict[str(n['id'])] = n
                mod_time = datetime.fromtimestamp(n['modified_at']).strftime('%Y-%m-%d %H:%M')
                reminder = datetime.fromtimestamp(n['reminder_time']).strftime('⏰ %m/%d %H:%M') if n['reminder_time'] else ''
                tags = f"[{', '.join(n['tags'])}]" if n['tags'] else ''
                
                print(f"[{n['id']:<3}] {shorten_title(n['title'], 40):<42} {tags:<20} {reminder:<15} (Mod: {mod_time})")

            if choice == "2":
                sub = input("Enter note ID to (O)pen, (T)ag, (R)emind, or Enter to cancel: ").strip().lower()
                if not sub:
                    continue
                    
                parts = sub.split()
                note_id_str = parts[0]
                action = parts[1] if len(parts) > 1 else 'o' # Default to open
                
                if note_id_str.isdigit() and note_id_str in notes_dict:
                    note_id = int(note_id_str)
                    if action == 'o':
                        open_note_file(user_id, note_id)
                    elif action == 't':
                        manage_tags(user_id, note_id, notes_dict)
                    elif action == 'r':
                        manage_reminder(user_id, note_id, notes_dict)
                    else:
                        speak_and_echo("Invalid action. Use O, T, or R.")
                else:
                    speak_and_echo("Invalid ID or action.")
                     
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
            # Signal the reminder thread to terminate gracefully
            REMINDER_QUEUE.put({"type": "terminate"})
            speak_and_echo("Logging out.")
            break
        elif choice == "8" or choice.lower() in ("q", "quit", "exit"):
            # Signal the reminder thread to terminate gracefully
            REMINDER_QUEUE.put({"type": "terminate"})
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