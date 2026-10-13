#!/usr/bin/env python3
"""
WhatsApp Transcriber
Transcribes audio voice messages from WhatsApp exports and produces
a single unified chronological text transcript.

Supports:
  - ZIP exports (open directly) and pre-extracted folders
  - Multiple sub-folders / accounts merged by timestamp
  - Existing .srt or .txt transcript sidecars are reused as-is
  - Whisper transcription via faster-whisper (preferred) or openai-whisper
  - GPU (CUDA) acceleration when available
  - Per-session settings persisted to ~/.whatsapp_transcriber.json
"""

# ─── stdlib ────────────────────────────────────────────────────────────────────
import sys
import os
import re
import json
import zipfile
import threading
import shutil
import subprocess
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Optional, Callable, Tuple

# ─── tkinter ───────────────────────────────────────────────────────────────────
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext


# ══════════════════════════════════════════════════════════════════════════════
# Constants
# ══════════════════════════════════════════════════════════════════════════════

CONFIG_PATH = Path.home() / ".whatsapp_transcriber.json"

# Ordered: display name → Whisper language code (None = auto-detect)
WHISPER_LANGUAGES: dict = {
    "Auto-detect": None,
    "Afrikaans": "af",
    "Arabic": "ar",
    "Chinese": "zh",
    "Czech": "cs",
    "Danish": "da",
    "Dutch": "nl",
    "English": "en",
    "Finnish": "fi",
    "French": "fr",
    "German": "de",
    "Greek": "el",
    "Hebrew": "he",
    "Hindi": "hi",
    "Hungarian": "hu",
    "Indonesian": "id",
    "Italian": "it",
    "Japanese": "ja",
    "Korean": "ko",
    "Malay": "ms",
    "Norwegian": "no",
    "Polish": "pl",
    "Portuguese": "pt",
    "Romanian": "ro",
    "Russian": "ru",
    "Slovak": "sk",
    "Spanish": "es",
    "Swedish": "sv",
    "Thai": "th",
    "Turkish": "tr",
    "Ukrainian": "uk",
    "Vietnamese": "vi",
}


# ══════════════════════════════════════════════════════════════════════════════
# Config helpers
# ══════════════════════════════════════════════════════════════════════════════

def _load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_config(data: dict) -> None:
    try:
        CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# Dependency helpers
# ══════════════════════════════════════════════════════════════════════════════

def _pip_install(spec: str) -> None:
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", spec, "--quiet"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def _has_whisper() -> bool:
    for mod in ("faster_whisper", "whisper"):
        try:
            __import__(mod)
            return True
        except ImportError:
            pass
    return False


def _cuda_available() -> bool:
    """Return True if a CUDA-capable GPU can be used for inference."""
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        pass
    try:
        import ctranslate2
        return bool(ctranslate2.get_supported_compute_types("cuda"))
    except Exception:
        pass
    return False


def check_dependencies() -> List[str]:
    issues = []
    if not _has_ffmpeg():
        issues.append(
            "FFmpeg is not in PATH — audio transcription will fail.\n"
            "Download from https://ffmpeg.org/download.html, install it, and "
            "add it to your system PATH, then restart this app."
        )
    if not _has_whisper():
        issues.append("No Whisper package installed (will auto-install).")
    return issues


def install_whisper(log: Callable[[str], None]) -> bool:
    for pkg in ("faster-whisper", "openai-whisper"):
        log(f"Installing {pkg} ...")
        try:
            _pip_install(pkg)
            log(f"  OK  {pkg} installed.")
            return True
        except Exception as exc:
            log(f"  FAIL  {pkg}: {exc}")
    return False


# ══════════════════════════════════════════════════════════════════════════════
# Data classes
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class Message:
    timestamp: datetime
    sender: str
    content: str
    is_audio: bool = False
    audio_filename: Optional[str] = None
    audio_path: Optional[Path] = None
    transcript: Optional[str] = None
    from_saved_file: bool = False

    def format_line(self) -> str:
        ts = self.timestamp.strftime("%H:%M:%S")
        if self.is_audio:
            if self.transcript:
                tag = "saved" if self.from_saved_file else "whisper"
                return f"[{ts}] {self.sender}: [Voice message ({tag}): {self.transcript}]"
            if self.audio_path is None:
                return f"[{ts}] {self.sender}: [Voice message – file not found]"
            return f"[{ts}] {self.sender}: [Voice message – not transcribed]"
        return f"[{ts}] {self.sender}: {self.content.replace(chr(10), chr(10) + '    ')}"


@dataclass
class ScanResult:
    source_folder: Path
    messages: List[Message] = field(default_factory=list)
    conversations_found: int = 0
    total_audio: int = 0
    already_transcribed: int = 0
    needs_transcription: int = 0
    missing_audio: int = 0


# ══════════════════════════════════════════════════════════════════════════════
# WhatsApp chat parser
# ══════════════════════════════════════════════════════════════════════════════

_LINE_PATTERNS: List[re.Pattern] = [
    # [DD/MM/YYYY, HH:MM:SS] Name: text
    re.compile(r"^\[(\d{1,2}/\d{1,2}/\d{2,4}),\s+(\d{1,2}:\d{2}:\d{2})\]\s+([^:]+):\s(.*)$"),
    # [DD/MM/YYYY, HH:MM] Name: text
    re.compile(r"^\[(\d{1,2}/\d{1,2}/\d{2,4}),\s+(\d{1,2}:\d{2})\]\s+([^:]+):\s(.*)$"),
    # DD/MM/YYYY, HH:MM - Name: text
    re.compile(r"^(\d{1,2}/\d{1,2}/\d{2,4}),\s+(\d{1,2}:\d{2})\s+-\s+([^:]+):\s(.*)$"),
    # M/D/YY, H:MM AM/PM - Name: text  (US locale)
    re.compile(r"^(\d{1,2}/\d{1,2}/\d{2,4}),\s+(\d{1,2}:\d{2}\s+[AP]M)\s+-\s+([^:]+):\s(.*)$"),
    # [DD/MM/YYYY, H:MM AM/PM] Name: text
    re.compile(r"^\[(\d{1,2}/\d{1,2}/\d{2,4}),\s+(\d{1,2}:\d{2}\s+[AP]M)\]\s+([^:]+):\s(.*)$"),
]

_TS_FORMATS = [
    "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M",
    "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M",
    "%d/%m/%y %H:%M:%S", "%d/%m/%y %H:%M",
    "%m/%d/%y %H:%M:%S", "%m/%d/%y %H:%M",
    "%d/%m/%Y %I:%M %p", "%d/%m/%y %I:%M %p",
    "%m/%d/%Y %I:%M %p", "%m/%d/%y %I:%M %p",
    "%d/%m/%Y %I:%M:%S %p", "%m/%d/%Y %I:%M:%S %p",
]

_AUDIO_EXTS = {".opus", ".m4a", ".mp3", ".ogg", ".aac", ".wav", ".wma", ".oga"}
_SIDECAR_EXTS = tuple(e + s for e in (".opus", ".m4a", ".mp3", ".ogg", ".aac", ".wav", ".wma", ".oga")
                      for s in (".srt", ".txt"))

_AUDIO_RE = re.compile(
    r"(?:<attached:\s*|^)([^\s<>]+\.(?:opus|m4a|mp3|ogg|aac|wav|wma|oga))(?:\s*>|\s*\(file attached\)|$)",
    re.IGNORECASE,
)
_SRT_INDEX = re.compile(r"^\d+$")
_SRT_TS    = re.compile(r"^\d{2}:\d{2}:\d{2}[,\.]\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}")


def _parse_ts(date_s: str, time_s: str) -> Optional[datetime]:
    combined = f"{date_s.strip()} {time_s.strip()}"
    for fmt in _TS_FORMATS:
        try:
            return datetime.strptime(combined, fmt)
        except ValueError:
            pass
    return None


def _extract_audio_name(content: str) -> Optional[str]:
    m = _AUDIO_RE.search(content)
    if m:
        return m.group(1)
    stripped = content.strip()
    if Path(stripped).suffix.lower() in _AUDIO_EXTS:
        return stripped
    return None


def _parse_srt(path: Path) -> str:
    parts: List[str] = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line and not _SRT_INDEX.match(line) and not _SRT_TS.match(line):
                parts.append(line)
    except Exception:
        pass
    return " ".join(parts).strip()


def _read_transcript(path: Path) -> str:
    if path.suffix.lower() == ".srt":
        return _parse_srt(path)
    return path.read_text(encoding="utf-8", errors="replace").strip()


def _find_saved_transcript(audio_path: Path) -> Optional[Path]:
    """Return the best available transcript sidecar (.srt preferred, then .txt)."""
    for candidate in (
        audio_path.parent / (audio_path.name + ".srt"),
        audio_path.with_suffix(".srt"),
        audio_path.parent / (audio_path.name + ".txt"),
        audio_path.with_suffix(".txt"),
    ):
        if candidate.exists() and candidate.stat().st_size > 0:
            return candidate
    return None


def parse_chat_file(chat_path: Path, media_dir: Path) -> List[Message]:
    messages: List[Message] = []
    current: Optional[Message] = None

    with open(chat_path, encoding="utf-8", errors="replace") as fh:
        lines = fh.readlines()

    for raw in lines:
        line = raw.rstrip("\n").lstrip("﻿‎‏").rstrip()

        matched = False
        for pattern in _LINE_PATTERNS:
            m = pattern.match(line)
            if m:
                date_s, time_s, sender, body = (
                    m.group(1), m.group(2), m.group(3).strip(), m.group(4)
                )
                ts = _parse_ts(date_s, time_s)
                if ts is None:
                    break

                if current:
                    messages.append(current)

                audio_name = _extract_audio_name(body)
                audio_p: Optional[Path] = None
                saved_tx: Optional[str] = None
                from_saved = False

                if audio_name:
                    candidate = media_dir / audio_name
                    if candidate.exists():
                        audio_p = candidate
                        txp = _find_saved_transcript(candidate)
                        if txp:
                            saved_tx = _read_transcript(txp)
                            from_saved = True

                current = Message(
                    timestamp=ts,
                    sender=sender,
                    content=body,
                    is_audio=audio_name is not None,
                    audio_filename=audio_name,
                    audio_path=audio_p,
                    transcript=saved_tx,
                    from_saved_file=from_saved,
                )
                matched = True
                break

        if not matched and current:
            current.content += "\n" + line

    if current:
        messages.append(current)

    return messages


# ══════════════════════════════════════════════════════════════════════════════
# Folder / ZIP scanner
# ══════════════════════════════════════════════════════════════════════════════

def _extract_zip(zip_path: Path) -> Path:
    out = zip_path.parent / zip_path.stem
    if not out.exists():
        out.mkdir(parents=True)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(out)
    return out


def _looks_like_whatsapp_chat(path: Path) -> bool:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for _ in range(20):
                raw = fh.readline()
                if not raw:
                    break
                line = raw.lstrip("﻿‎‏").rstrip()
                if line and any(p.match(line) for p in _LINE_PATTERNS):
                    return True
    except Exception:
        pass
    return False


def _find_chat_file(directory: Path) -> Optional[Path]:
    standard = directory / "_chat.txt"
    if standard.exists():
        return standard
    for txt in sorted(directory.glob("*.txt")):
        if txt.name.lower().endswith(_SIDECAR_EXTS):
            continue
        if _looks_like_whatsapp_chat(txt):
            return txt
    return None


def _find_chat_dirs(
    root: Path,
    log: Optional[Callable[[str], None]] = None,
) -> List[Path]:
    def _l(msg: str) -> None:
        if log:
            log(msg)

    dirs: List[Path] = []

    # Pass 1: ZIPs
    zips = sorted(root.rglob("*.zip"))
    if zips:
        _l(f"  Found {len(zips)} ZIP file(s)")
    for z in zips:
        try:
            extracted = _extract_zip(z)
            cf = _find_chat_file(extracted)
            if cf:
                _l(f"  ZIP export: {z.relative_to(root)}  [{cf.name}]")
                if extracted not in dirs:
                    dirs.append(extracted)
            else:
                _l(f"  ZIP skipped (no chat file inside): {z.name}")
        except Exception as exc:
            _l(f"  ZIP error — {z.name}: {exc}")

    # Pass 2: standard _chat.txt
    for cf in sorted(root.rglob("_chat.txt")):
        d = cf.parent
        if d not in dirs:
            _l(f"  Export: {cf.relative_to(root)}")
            dirs.append(d)

    # Pass 3: non-standard chat filenames
    if not dirs:
        _l("  _chat.txt not found — scanning for other WhatsApp chat files...")
        for txt in sorted(root.rglob("*.txt")):
            if txt.name.lower().endswith(_SIDECAR_EXTS):
                continue
            if _looks_like_whatsapp_chat(txt):
                d = txt.parent
                _l(f"  Export (alt name): {txt.relative_to(root)}")
                if d not in dirs:
                    dirs.append(d)

    # Diagnostic when nothing found
    if not dirs:
        _l(f"  No WhatsApp exports found under: {root}")
        _l("  Folder contents (2 levels):")
        try:
            for item in sorted(root.iterdir()):
                tag = "/" if item.is_dir() else f"  [{item.suffix or 'no ext'}]"
                _l(f"    {item.name}{tag}")
                if item.is_dir():
                    try:
                        children = sorted(item.iterdir())
                        for child in children[:12]:
                            ctag = "/" if child.is_dir() else f"  [{child.suffix or 'no ext'}]"
                            _l(f"      {child.name}{ctag}")
                        if len(children) > 12:
                            _l(f"      ... and {len(children) - 12} more")
                    except Exception:
                        _l("      (unable to list)")
        except Exception:
            pass

    return dirs


def scan_source_folder(
    source: Path,
    log: Optional[Callable[[str], None]] = None,
) -> ScanResult:
    result = ScanResult(source_folder=source)
    all_messages: List[Message] = []

    chat_dirs = _find_chat_dirs(source, log=log)
    result.conversations_found = len(chat_dirs)

    for chat_dir in chat_dirs:
        chat_file = _find_chat_file(chat_dir)
        if chat_file is None:
            if log:
                log(f"  Skipping {chat_dir.name}: chat file disappeared")
            continue
        try:
            msgs = parse_chat_file(chat_file, chat_dir)
        except Exception as exc:
            if log:
                log(f"  Parse error in {chat_dir.name}: {exc}")
            msgs = []

        if log:
            log(f"  {chat_dir.name}: {len(msgs)} messages [{chat_file.name}]")

        all_messages.extend(msgs)

        for msg in msgs:
            if not msg.is_audio:
                continue
            result.total_audio += 1
            if msg.transcript is not None:
                result.already_transcribed += 1
            elif msg.audio_path is not None:
                result.needs_transcription += 1
            else:
                result.missing_audio += 1

    all_messages.sort(key=lambda m: m.timestamp)
    result.messages = all_messages
    return result


# ══════════════════════════════════════════════════════════════════════════════
# Whisper transcription
# ══════════════════════════════════════════════════════════════════════════════

def _build_transcribe_fn(
    model_name: str,
    language: Optional[str] = None,
    device: str = "cpu",
) -> Callable[[Path], str]:
    lang = language or None

    try:
        from faster_whisper import WhisperModel
        try:
            compute = "float16" if device == "cuda" else "int8"
            model = WhisperModel(model_name, device=device, compute_type=compute)
        except Exception:
            # GPU requested but unavailable — fall back silently
            model = WhisperModel(model_name, device="cpu", compute_type="int8")

        def _fw(path: Path) -> str:
            segments, _ = model.transcribe(str(path), language=lang)
            return " ".join(s.text.strip() for s in segments).strip()

        return _fw
    except ImportError:
        pass

    import whisper
    model = whisper.load_model(model_name)

    def _ow(path: Path) -> str:
        return model.transcribe(str(path), language=lang)["text"].strip()

    return _ow


def transcribe_messages(
    messages: List[Message],
    model_name: str,
    language: Optional[str] = None,
    device: str = "cpu",
    on_progress: Optional[Callable[[int, int, Optional[Message]], None]] = None,
    is_cancelled: Optional[Callable[[], bool]] = None,
    save_alongside: bool = True,
) -> None:
    pending = [m for m in messages if m.is_audio and m.audio_path and m.transcript is None]
    total = len(pending)
    if total == 0:
        if on_progress:
            on_progress(0, 0, None)
        return

    transcribe = _build_transcribe_fn(model_name, language=language, device=device)

    for i, msg in enumerate(pending):
        if is_cancelled and is_cancelled():
            break
        if on_progress:
            on_progress(i, total, msg)
        try:
            text = transcribe(msg.audio_path)
            msg.transcript = text
            msg.from_saved_file = False
            if save_alongside:
                sidecar = msg.audio_path.parent / (msg.audio_path.name + ".txt")
                sidecar.write_text(text, encoding="utf-8")
        except Exception as exc:
            msg.transcript = f"[Transcription error: {exc}]"

    if on_progress:
        on_progress(total, total, None)


# ══════════════════════════════════════════════════════════════════════════════
# Output builder
# ══════════════════════════════════════════════════════════════════════════════

def build_transcript_file(messages: List[Message], out_path: Path) -> None:
    lines: List[str] = []

    if messages:
        participants = sorted(set(m.sender for m in messages))
        n_audio = sum(1 for m in messages if m.is_audio)
        n_tx    = sum(1 for m in messages if m.is_audio and m.transcript)
        lines += [
            "=" * 64,
            "  WhatsApp Conversation Transcript",
            "=" * 64,
            f"  Participants : {', '.join(participants)}",
            f"  From         : {messages[0].timestamp.strftime('%d %B %Y')}",
            f"  To           : {messages[-1].timestamp.strftime('%d %B %Y')}",
            f"  Messages     : {len(messages):,}  ({n_audio:,} voice, {n_tx:,} transcribed)",
            f"  Generated    : {datetime.now().strftime('%d %B %Y at %H:%M')}",
            "=" * 64,
            "",
            "",
        ]

    current_date = None
    for msg in messages:
        d = msg.timestamp.date()
        if d != current_date:
            if current_date is not None:
                lines.append("")
                lines.append("")
            lines.append("=" * 64)
            lines.append(f"  {d.strftime('%A, %d %B %Y')}")
            lines.append("=" * 64)
            lines.append("")
            current_date = d
        lines.append(msg.format_line())

    out_path.write_text("\n".join(lines), encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════════
# GUI
# ══════════════════════════════════════════════════════════════════════════════

WA_DARK   = "#075E54"
WA_MED    = "#128C7E"
WA_BRIGHT = "#25D366"
BG        = "#f4f4f4"
WHITE     = "#ffffff"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("WhatsApp Transcriber")
        self.geometry("900x720")
        self.minsize(740, 580)
        self.configure(bg=BG)
        try:
            ttk.Style(self).theme_use("vista")
        except Exception:
            pass

        self._scan_result: Optional[ScanResult] = None
        self._cancelled = False
        self._last_out_path: Optional[Path] = None

        cfg = _load_config()
        self._cfg = cfg

        self._build_ui(cfg)
        threading.Thread(target=self._check_deps_bg, daemon=True).start()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self, cfg: dict) -> None:
        # Header
        hdr = tk.Frame(self, bg=WA_DARK, padx=16, pady=10)
        hdr.pack(fill="x")
        tk.Label(
            hdr, text="WhatsApp Transcriber",
            font=("Segoe UI", 15, "bold"), fg=WHITE, bg=WA_DARK,
        ).pack(side="left")
        self._dep_lbl = tk.Label(
            hdr, text="Checking dependencies...",
            font=("Segoe UI", 8), fg="#aaffcc", bg=WA_DARK,
        )
        self._dep_lbl.pack(side="right")

        # ── Step 1: source ────────────────────────────────────────────────────
        f1 = ttk.LabelFrame(self, text="  Step 1  ·  Select Source (folder or ZIP)", padding=10)
        f1.pack(fill="x", padx=14, pady=(12, 4))

        self._src_var = tk.StringVar(value=cfg.get("last_path", ""))
        ttk.Entry(f1, textvariable=self._src_var, font=("Segoe UI", 9)).pack(
            side="left", fill="x", expand=True, padx=(0, 6),
        )
        ttk.Button(f1, text="Browse Folder...", command=self._browse_folder).pack(side="left")
        ttk.Button(f1, text="Browse ZIP...",    command=self._browse_zip).pack(side="left", padx=(4, 0))
        self._scan_btn = ttk.Button(f1, text="  Scan  ", command=self._start_scan)
        self._scan_btn.pack(side="left", padx=(6, 0))

        # ── Step 2: stats ────────────────────────────────────────────────────
        f2 = ttk.LabelFrame(self, text="  Step 2  ·  Scan Results", padding=10)
        f2.pack(fill="x", padx=14, pady=4)

        self._stat_vars: dict = {}
        stat_rows: List[Tuple[str, str]] = [
            ("conversations", "Conversations / exports found"),
            ("total_msg",     "Total messages"),
            ("total_audio",   "Audio (voice) messages"),
            ("saved_tx",      "Already transcribed (saved)"),
            ("needs_tx",      "Needs transcription"),
            ("missing",       "Audio file missing"),
        ]
        for idx, (key, label) in enumerate(stat_rows):
            row, col = divmod(idx, 2)
            tk.Label(f2, text=label + ":", font=("Segoe UI", 9), bg=BG).grid(
                row=row, column=col * 2, sticky="w", padx=(6, 0), pady=2,
            )
            var = tk.StringVar(value="–")
            tk.Label(f2, textvariable=var, font=("Segoe UI", 9, "bold"),
                     fg=WA_MED, width=8, anchor="w").grid(
                row=row, column=col * 2 + 1, sticky="w", padx=(4, 24), pady=2,
            )
            self._stat_vars[key] = var
        for c in (1, 3):
            f2.columnconfigure(c, weight=1)

        # ── Step 3: options & run ─────────────────────────────────────────────
        f3 = ttk.LabelFrame(self, text="  Step 3  ·  Options & Run", padding=10)
        f3.pack(fill="x", padx=14, pady=4)

        # Row 0: model / language / device dropdowns
        opt_row = tk.Frame(f3, bg=BG)
        opt_row.pack(fill="x", pady=(0, 8))

        tk.Label(opt_row, text="Model:", font=("Segoe UI", 9)).pack(side="left")
        self._model_var = tk.StringVar(value=cfg.get("model", "base"))
        ttk.Combobox(
            opt_row, textvariable=self._model_var, width=8, state="readonly",
            values=["tiny", "base", "small", "medium", "large"],
        ).pack(side="left", padx=(4, 16))

        tk.Label(opt_row, text="Language:", font=("Segoe UI", 9)).pack(side="left")
        self._lang_var = tk.StringVar(value=cfg.get("language", "Auto-detect"))
        ttk.Combobox(
            opt_row, textvariable=self._lang_var, width=16, state="readonly",
            values=list(WHISPER_LANGUAGES.keys()),
        ).pack(side="left", padx=(4, 16))

        tk.Label(opt_row, text="Device:", font=("Segoe UI", 9)).pack(side="left")
        gpu_available = _cuda_available()
        default_device = cfg.get("device", "GPU (CUDA)" if gpu_available else "CPU")
        self._device_var = tk.StringVar(value=default_device)
        ttk.Combobox(
            opt_row, textvariable=self._device_var, width=12, state="readonly",
            values=["CPU", "GPU (CUDA)"],
        ).pack(side="left", padx=(4, 8))
        if gpu_available:
            tk.Label(opt_row, text="GPU detected", font=("Segoe UI", 8),
                     fg=WA_MED).pack(side="left")
        else:
            tk.Label(opt_row, text="no GPU found", font=("Segoe UI", 8),
                     fg="gray").pack(side="left")

        # Row 1: action buttons
        btn_row = tk.Frame(f3, bg=BG)
        btn_row.pack(fill="x")

        self._cancel_btn = ttk.Button(
            btn_row, text="Cancel", command=self._cancel, state="disabled",
        )
        self._cancel_btn.pack(side="right")
        self._run_btn = ttk.Button(
            btn_row, text="  Transcribe & Build Transcript  ",
            command=self._start_run, state="disabled",
        )
        self._run_btn.pack(side="right", padx=(0, 6))
        self._open_btn = ttk.Button(
            btn_row, text="Open Output File", command=self._open_output, state="disabled",
        )
        self._open_btn.pack(side="left")

        # Progress
        pf = tk.Frame(self, bg=BG)
        pf.pack(fill="x", padx=14, pady=(2, 0))
        self._prog_var = tk.DoubleVar()
        ttk.Progressbar(pf, variable=self._prog_var, maximum=100).pack(fill="x")
        self._status_var = tk.StringVar(value="Select a source folder or ZIP and click Scan.")
        tk.Label(
            pf, textvariable=self._status_var,
            font=("Segoe UI", 8), fg="gray", bg=BG, anchor="w",
        ).pack(fill="x", pady=(2, 0))

        # Log
        lf = ttk.LabelFrame(self, text="  Log", padding=(5, 4))
        lf.pack(fill="both", expand=True, padx=14, pady=(4, 12))
        self._log_box = scrolledtext.ScrolledText(
            lf, height=8, font=("Consolas", 8), state="disabled", bg=WHITE, relief="flat",
        )
        self._log_box.pack(fill="both", expand=True)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _log(self, text: str) -> None:
        def _w():
            self._log_box.configure(state="normal")
            self._log_box.insert("end", text + "\n")
            self._log_box.see("end")
            self._log_box.configure(state="disabled")
        self.after(0, _w)

    def _set_status(self, text: str) -> None:
        self.after(0, lambda: self._status_var.set(text))

    def _set_stat(self, key: str, value) -> None:
        self.after(0, lambda: self._stat_vars[key].set(str(value)))

    def _set_prog(self, pct: float) -> None:
        self.after(0, lambda: self._prog_var.set(pct))

    def _set_dep_label(self, text: str, color: str = "#aaffcc") -> None:
        self.after(0, lambda: self._dep_lbl.configure(text=text, fg=color))

    def _save_current_config(self) -> None:
        _save_config({
            "last_path": self._src_var.get(),
            "model":     self._model_var.get(),
            "language":  self._lang_var.get(),
            "device":    self._device_var.get(),
        })

    # ── Dependency check ──────────────────────────────────────────────────────

    def _check_deps_bg(self) -> None:
        issues = check_dependencies()
        if any("Whisper" in i for i in issues):
            self._set_dep_label("Installing Whisper...", "#ffee88")
            ok = install_whisper(self._log)
            issues = check_dependencies() if ok else issues

        if any("FFmpeg" in i for i in issues):
            self._set_dep_label("FFmpeg missing — see log", "#ffcc44")
            for msg in issues:
                if "FFmpeg" in msg:
                    self._log("WARNING: " + msg)
        else:
            self._set_dep_label("Dependencies OK", "#aaffcc")
            self._log("All dependencies satisfied.")

    # ── Browse ────────────────────────────────────────────────────────────────

    def _browse_folder(self) -> None:
        d = filedialog.askdirectory(title="Select folder containing WhatsApp exports")
        if d:
            self._src_var.set(d)

    def _browse_zip(self) -> None:
        f = filedialog.askopenfilename(
            title="Select WhatsApp export ZIP file",
            filetypes=[("ZIP files", "*.zip"), ("All files", "*.*")],
        )
        if f:
            self._src_var.set(f)

    # ── Scan ──────────────────────────────────────────────────────────────────

    def _start_scan(self) -> None:
        raw = self._src_var.get().strip()
        if not raw:
            messagebox.showerror("Error", "Please select a source folder or ZIP file.")
            return

        src = Path(raw)

        if src.is_file() and src.suffix.lower() == ".zip":
            scan_root = None   # will extract in background
        elif src.is_dir():
            scan_root = src
        else:
            messagebox.showerror("Error", f"Path not found:\n{raw}")
            return

        self._run_btn.configure(state="disabled")
        self._open_btn.configure(state="disabled")
        self._scan_result = None
        for key in self._stat_vars:
            self._stat_vars[key].set("–")
        self._set_status("Scanning...")
        self._log(f"Source: {raw}")
        self._save_current_config()

        def _do():
            try:
                nonlocal scan_root
                if scan_root is None:
                    self._log("  Extracting ZIP...")
                    scan_root = _extract_zip(src)
                    self._log(f"  Extracted to: {scan_root}")
                result = scan_source_folder(scan_root, log=self._log)
                self.after(0, self._on_scan_done, result)
            except Exception as exc:
                self._log(f"Scan error: {exc}")
                self._set_status("Scan failed — see log.")

        threading.Thread(target=_do, daemon=True).start()

    def _on_scan_done(self, result: ScanResult) -> None:
        self._scan_result = result
        self._set_stat("conversations", result.conversations_found)
        self._set_stat("total_msg",     len(result.messages))
        self._set_stat("total_audio",   result.total_audio)
        self._set_stat("saved_tx",      result.already_transcribed)
        self._set_stat("needs_tx",      result.needs_transcription)
        self._set_stat("missing",       result.missing_audio)

        self._log(
            f"Scan complete — {result.conversations_found} conversation(s), "
            f"{len(result.messages):,} messages, "
            f"{result.total_audio:,} audio "
            f"({result.already_transcribed:,} done, "
            f"{result.needs_transcription:,} to transcribe, "
            f"{result.missing_audio:,} missing)."
        )

        if result.conversations_found == 0:
            self._set_status("No WhatsApp exports found — check the log for details.")
            return
        if not result.messages:
            self._set_status("Exports found but no messages could be parsed.")
            return

        self._run_btn.configure(state="normal")
        n = result.needs_transcription
        if n:
            self._set_status(
                f"Ready — {n:,} audio file(s) to transcribe. "
                "Select model / language / device and click Run."
            )
        else:
            self._set_status("Ready — all audio already transcribed. Click Run to build the transcript.")

    # ── Run ───────────────────────────────────────────────────────────────────

    def _start_run(self) -> None:
        if not self._scan_result or not self._scan_result.messages:
            return

        src_name = Path(self._src_var.get()).stem
        out_path_str = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text file", "*.txt")],
            title="Save transcript as...",
            initialfile=f"{src_name}_transcript.txt",
        )
        if not out_path_str:
            return

        self._cancelled = False
        self._last_out_path = None
        self._run_btn.configure(state="disabled")
        self._open_btn.configure(state="disabled")
        self._cancel_btn.configure(state="normal")
        self._set_prog(0)

        model_name  = self._model_var.get()
        lang_name   = self._lang_var.get()
        language    = WHISPER_LANGUAGES.get(lang_name)
        device      = "cuda" if "GPU" in self._device_var.get() else "cpu"
        messages    = self._scan_result.messages
        out_path    = Path(out_path_str)

        self._save_current_config()

        def _on_progress(current: int, total: int, msg: Optional[Message]) -> None:
            if total == 0:
                self._set_prog(100)
                return
            self._set_prog(current / total * 100)
            if msg:
                self._set_status(f"Transcribing {current + 1}/{total}: {msg.audio_filename}")
                self._log(f"  [{current + 1}/{total}] {msg.audio_filename}")

        def _do():
            try:
                n_pending = sum(
                    1 for m in messages
                    if m.is_audio and m.audio_path and m.transcript is None
                )
                if n_pending:
                    self._log(
                        f"Loading Whisper '{model_name}' "
                        f"[lang={lang_name}, device={device.upper()}] ..."
                    )
                    self._set_status("Loading Whisper model — this may take a moment...")

                transcribe_messages(
                    messages,
                    model_name,
                    language=language,
                    device=device,
                    on_progress=_on_progress,
                    is_cancelled=lambda: self._cancelled,
                )

                if self._cancelled:
                    self._log("Cancelled by user.")
                    self._set_status("Cancelled.")
                    return

                self._log("Building transcript...")
                build_transcript_file(messages, out_path)
                self._last_out_path = out_path
                self._log(f"Saved: {out_path}")
                self._set_status("Done! Transcript saved.")
                self._set_prog(100)
                self._set_stat("needs_tx", 0)
                self.after(0, lambda: self._open_btn.configure(state="normal"))
                self.after(0, self._done_dialog, out_path)

            except Exception as exc:
                self._log(f"Error: {exc}")
                self._set_status("Error — see log.")
            finally:
                self.after(0, lambda: self._run_btn.configure(state="normal"))
                self.after(0, lambda: self._cancel_btn.configure(state="disabled"))

        threading.Thread(target=_do, daemon=True).start()

    def _done_dialog(self, out_path: Path) -> None:
        if messagebox.askyesno(
            "Done",
            f"Transcript saved:\n{out_path}\n\nOpen the file now?",
        ):
            self._open_output()

    def _open_output(self) -> None:
        if self._last_out_path and self._last_out_path.exists():
            try:
                os.startfile(self._last_out_path)
            except Exception as exc:
                messagebox.showerror("Error", f"Could not open file:\n{exc}")

    # ── Cancel ────────────────────────────────────────────────────────────────

    def _cancel(self) -> None:
        self._cancelled = True
        self._set_status("Cancelling after current file...")


# ══════════════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    App().mainloop()
