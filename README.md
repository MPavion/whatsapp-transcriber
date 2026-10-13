# WhatsApp Transcriber

A Python desktop application that processes WhatsApp chat exports, transcribes voice messages using [Whisper](https://github.com/openai/whisper), and produces a single unified text transcript with all messages — including audio — in chronological order.

---

## Features

| Feature | Detail |
|---------|--------|
| **ZIP or folder input** | Open a WhatsApp `.zip` export directly, or point to a folder |
| **Voice message transcription** | Uses [faster-whisper](https://github.com/guillaumeklinvex/faster-whisper) (or `openai-whisper` as fallback) |
| **GPU acceleration** | Auto-detects CUDA; runs significantly faster on an NVIDIA GPU |
| **Language selection** | 30+ languages, or leave on Auto-detect |
| **Saved transcript reuse** | `.srt` or `.txt` sidecars next to audio files are used as-is — Whisper is not called again |
| **Multi-account merging** | Put multiple exports in one folder; all messages are merged chronologically |
| **Non-standard filenames** | Recognises exports where the chat file isn't named `_chat.txt` |
| **Transcript header** | Output includes participants, date range, and message counts |
| **Date separators** | Output is divided into clearly labelled day sections |
| **Re-run safe** | Transcriptions are saved alongside audio; subsequent runs skip completed files |
| **Remembered settings** | Last path, model, language, and device are saved between sessions |

---

## Requirements

### Python packages (auto-installed on first run)
- `faster-whisper` (preferred) or `openai-whisper`

### System dependency — FFmpeg

Whisper uses FFmpeg to decode audio. Install it and ensure it is on your PATH **before** running the app.

**Windows**
```
winget install --id Gyan.FFmpeg
```
Or download from [ffmpeg.org](https://ffmpeg.org/download.html), extract, and add the `bin/` folder to your PATH.

**macOS**
```
brew install ffmpeg
```

**Linux**
```
sudo apt install ffmpeg
```

---

## Installation

```bash
git clone https://github.com/MPavion/whatsapp-transcriber.git
cd whatsapp-transcriber

# Optional: create a virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # macOS / Linux

pip install -r requirements.txt
```

Run the app:
```bash
python transcriber.py
```

The app will auto-install `faster-whisper` if it's not already present.

### Desktop shortcut (Windows)

```bash
python make_icon.py        # generates icon.ico (already committed, only needed if you change the icon)
python create_shortcut.py  # creates a .lnk on your Desktop
```

---

## Usage

### Step 1 — Prepare your source

**Option A — Single ZIP export**
Select the `.zip` file WhatsApp creates when you export a chat. The app extracts it automatically.

**Option B — Folder of exports**
Create a folder and place one or more WhatsApp exports inside it. Useful when you want to merge two accounts for the same contact:

```
my_exports/
├── WhatsApp Chat with Alice.zip
├── WhatsApp Chat with Bob (phone 1).zip   # first of two accounts
└── WhatsApp Chat with Bob (phone 2).zip   # second account — merged automatically
```

Sub-folders work too:

```
my_exports/
├── account_1/
│   └── WhatsApp Chat with Bob.zip
└── account_2/
    └── WhatsApp Chat with Bob.zip
```

### Step 2 — Scan

1. Click **Browse Folder...** or **Browse ZIP...**, or type the path directly
2. Click **Scan**

The log shows what was found and the stats panel updates:

- How many conversations / exports detected
- Total message count
- Audio breakdown: already transcribed vs. needs transcription vs. file missing

### Step 3 — Configure and run

| Option | Description |
|--------|-------------|
| **Model** | `tiny` = fastest; `large` = most accurate. `base` is a good starting point. |
| **Language** | Set if you know the language; `Auto-detect` works well for most single-language chats. Setting an explicit language is faster and more accurate for short voice messages. |
| **Device** | `GPU (CUDA)` is shown if an NVIDIA GPU is detected — significantly faster than CPU. |

Click **Transcribe & Build Transcript**, choose where to save, and the app will:

1. Transcribe any pending audio files
2. Assemble the full unified transcript
3. Offer to open the output file immediately

---

## Saved transcripts

Any `.srt` or `.txt` file placed alongside an audio file is used directly without calling Whisper:

```
PTT-20231012-WA0001.opus
PTT-20231012-WA0001.opus.srt   ← preferred (WisprFlow / subtitle format)
PTT-20231012-WA0001.opus.txt   ← also accepted (plain text)
PTT-20231012-WA0001.srt        ← also accepted (without audio extension)
```

After transcription, the app saves a `.txt` sidecar next to each newly transcribed file, so re-running is instant.

---

## Output format

```
================================================================
  WhatsApp Conversation Transcript
================================================================
  Participants : Alice, Bob
  From         : 01 January 2023
  To           : 13 October 2025
  Messages     : 17,935  (4,893 voice, 4,893 transcribed)
  Generated    : 13 October 2025 at 15:30
================================================================


================================================================
  Monday, 01 January 2023
================================================================

[09:14:22] Alice: Happy New Year!
[09:15:01] Bob: [Voice message (saved): Same to you, hope it's a good one!]
[09:15:44] Alice: [Voice message (whisper): Thanks, you too. Let's catch up soon.]


================================================================
  Tuesday, 02 January 2023
================================================================

[10:00:00] Alice: Are you free this week?
```

- `(saved)` — transcript came from an existing `.srt` or `.txt` file
- `(whisper)` — transcribed by Whisper during this run

---

## Whisper model sizes

| Model | Speed | Accuracy | VRAM |
|-------|-------|----------|------|
| tiny | Fastest | Basic | ~1 GB |
| base | Fast | Good | ~1 GB |
| small | Moderate | Better | ~2 GB |
| medium | Slower | Great | ~5 GB |
| large | Slowest | Best | ~10 GB |

Models are downloaded automatically on first use and cached locally. `base` is the default.

---

## Supported audio formats

`.opus` · `.m4a` · `.mp3` · `.ogg` · `.aac` · `.wav` · `.wma` · `.oga`

WhatsApp voice messages are typically `.opus` (Android) or `.m4a` (iOS).

---

## Supported WhatsApp export date formats

| Format | Example |
|--------|---------|
| `[DD/MM/YYYY, HH:MM:SS]` | `[13/10/2025, 09:14:22]` |
| `[DD/MM/YYYY, HH:MM]` | `[13/10/2025, 09:14]` |
| `DD/MM/YYYY, HH:MM –` | `13/10/2025, 09:14 –` |
| `M/D/YY, H:MM AM/PM –` | `10/13/25, 9:14 AM –` |
| `[DD/MM/YYYY, H:MM AM/PM]` | `[13/10/2025, 9:14 AM]` |

---

## Project structure

```
whatsapp-transcriber/
├── transcriber.py      # entire application
├── make_icon.py        # generates icon.ico / icon.png (Pillow required)
├── create_shortcut.py  # creates a Windows desktop shortcut
├── icon.ico            # multi-resolution icon (16–256 px)
├── icon.png            # 512 px PNG
├── requirements.txt
└── README.md
```

---

## Troubleshooting

**"FFmpeg not found in PATH"** — Install FFmpeg and restart. See [Requirements](#requirements).

**Whisper fails to install** — Run manually: `pip install faster-whisper` or `pip install openai-whisper`.

**GPU selected but transcription runs slowly** — CUDA may not be set up correctly. Try switching to CPU and check your CUDA / cuDNN installation.

**Transcription is in the wrong language** — Set an explicit language in Step 3. Auto-detect can misidentify very short clips.

**Chat dates not parsed** — WhatsApp uses the phone's locale for date formatting. If lines are being skipped, open an issue with a (sanitised) sample line from your `_chat.txt`.

---

## Contributing

Bug reports, language-format samples, and pull requests are welcome. Please open an issue before starting significant work so we can discuss the approach.

---

## License

MIT
