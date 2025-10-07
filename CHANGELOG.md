# 🧾 ModuWorks — Changelog (Honest + Complete)

This changelog documents notable changes, improvements, and real-world failures during ModuWorks development.
I include failures intentionally — they show what I learned while building this project.

---

## Version 1.3.0 — Current Stable Release
**Date:** 2025-10-07

### Highlights
- Auto-update system (fetches the main script from GitHub and replaces the local copy).
- Database migrations added so older DBs are upgraded safely.
- Reminder system (per-note reminders with background worker).
- Tagging system for notes (tags stored in `tags` table).
- Non-blocking, robust audio recording with optional WAV → MP3 conversion.
- Cross-platform editor launching (uses default OS editor; falls back to `$EDITOR` on Unix).
- Persistent configuration saved in `~/.moduworks/config.json`.

### Security & Reliability
- Password hashing with per-user salt; `secrets.compare_digest` used to mitigate timing attacks.
- Better error handling around file I/O, DB operations, audio I/O.
- Config file read/write with fail-safe defaults.

---

## Failures, Breaks, and Lessons Learned (Yes — the real stuff)
> I’m deliberately listing these so contributors know what was tried, why it failed, and what I learned.

### GUI attempt — failed spectacularly
- **What I tried:** Built a GUI prototype (PyQt / Qt) to make ModuWorks more "GUI friendly".
- **What happened:** The GUI introduced accessibility, focus, and hotkey conflicts; screenreader and keyboard-hook integration became unstable. The GUI version crashed or misbehaved under real-world usage.
- **Lesson:** Accessibility-first GUI work requires purpose-built design and testing with assistive tech. For now, terminal-first is more robust and predictable.

### Low-level Braille / HID key capture — not reliable
- **What I tried:** Capture chorded braille input at a low level (HID/driver hooks) to emulate a braille device.
- **What happened:** Permission issues, driver differences, race conditions, and focus problems made this approach brittle across OSes.
- **Lesson:** Rely on standard screen-reader / braille-display integrations or user-definable key maps rather than raw low-level hooks.

### Tolk / NVDA integration — removed (for now)
- **What I tried:** Add `tolk` wrappers for TTS and braille output.
- **What happened:** Behavior was inconsistent between machines and introduced extra installation friction.
- **Lesson:** Keep the core terminal experience stable; provide optional plugins for TTS that users can enable if they want.

### Audio conversion & FFmpeg problems
- **What I tried:** Use `pydub` to convert WAV → MP3 automatically.
- **What happened:** Conversion fails on systems without FFmpeg/Libav in PATH; sometimes silent failures.
- **Lesson:** Must document FFmpeg requirement clearly and check for it at startup; provide user prompt and graceful fallback.

### Hotkey handling / `keyboard` module issues
- **What I tried:** Use global keyboard hotkeys for pausing/stopping recordings.
- **What happened:** On some systems `keyboard` needs elevated privileges or behaves differently; binding/unbinding had edge-case failures.
- **Lesson:** Provide alternative non-blocking stdin controls (already added), and avoid global hooks as the only control path.

### Auto-update parsing / robustness
- **What I tried:** Naïve version parsing from remote file.
- **What happened:** Small formatting differences prevented detection (caused update to fail).
- **Lesson:** Use robust parsing (regex) and, ideally, signed releases / hash verification. A hash/ signature check should be added later.

### DB schema mismatch (users table)
- **What happened:** Early versions caused `OperationalError` because the schema changed (missing columns).
- **Lesson:** Add DB migration steps and test migrations. Always write migration code that tolerates "already applied" errors.

---

## Version History (short)
- **1.3.0** — Reminders, tags, migrations, robust audio + conversion, auto-update improvements (current).
- **1.2.0** — Audio recording, tags, reminders, editor improvements.
- **1.1.0** — User accounts, secure password storage, core DB.
- **1.0.0** — Initial CLI prototype.

---

## Notes & Next Steps (for contributors)
- **Where data lives:** `~/.moduworks/`  
  - DB: `moduworks.db`  
  - Documents: `documents/`  
  - Config: `config.json`
- **Dependencies to document prominently:** `pyaudio`, `pydub` + **FFmpeg** (system), `keyboard` (optional).  
- **Suggested future improvements:** signed auto-updates (hashes/signatures), automated tests, GUI-with-accessibility plan (if GUI is desired), CI build that validates auto-update integrity.

---

## Author’s note (real)
I spent a *very* long day on this. There were many blind alleys. I’m including the failures because they’re real — they show the work, the decisions, and the path forward. If you use this code and find a new failure, add it here so the project history stays honest.

