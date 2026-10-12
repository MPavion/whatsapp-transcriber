# WhatsApp Transcriber

A Python GUI application that processes WhatsApp chat exports, transcribes voice messages using [Whisper](https://github.com/openai/whisper), and produces a single unified text transcript with all messages — including audio — in chronological order.

---

## Features

- **Automatic ZIP extraction** — point it at a folder of WhatsApp `.zip` exports; the app unpacks them automatically
- **Voice message transcription** — uses [faster-whisper](https://github.com/guillaumeklinvex/faster-whisper) (or `openai-whisper` as fallback) to transcribe `.opus`, `.m4a`, and other audio formats
- **Saved transcript reuse** — if you place a `.txt` file alongside an audio file (manual transcription), it is used as-is and Whisper is not called
- **Multi-account merging** — put multiple WhatsApp exports for the same person in one folder; all messages are merged into a single chronological output
- **Re-run friendly** — after each transcription, a `.txt` is saved next to the audio file; subsequent runs skip already-transcribed files
- **Scan statistics** — before committing to a full transcription run, see exactly how many audio files need processing vs. are already done
- **Model selection** — choose from `tiny` (fastest) through `large` (most accurate) Whisper models

---

## Requirements

### Python packages (auto-installed on first run)
- `faster-whisper` (preferred) or `openai-whisper`

### System dependency — FFmpeg (manual install required)

Whisper uses FFmpeg to decode audio. Install it and ensure it is on your system PATH before running the app.

- **Windows:** Download from [ffmpeg.org](https://ffmpeg.org/download.html), extract, and add the `bin/` folder to your PATH. Or install via `winget`:
  ```
  winget install --id Gyan.FFmpeg
  ```
- **macOS:** `brew install ffmpeg`
- **Linux:** `sudo apt install ffmpeg` (Debian/Ubuntu) or equivalent

---

## Installation

```bash
# Clone the repo
git clone https://github.com/MPavion/whatsapp-transcriber.git
cd whatsapp-transcriber

# (Optional) create a virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # macOS / Linux

# Install Python dependencies
pip install -r requirements.txt
```

Then run:

```bash
python transcriber.py
```

Python packages can also be left to the app — it will detect and offer to install `faster-whisper` automatically on first launch.

---

## Usage

### Step 1 — Prepare your source folder

Create a folder and place your WhatsApp export(s) inside it:

```
my_exports/
├── WhatsApp Chat with Alice.zip          # single account
├── WhatsApp Chat with Bob (phone 1).zip  # first of two accounts
└── WhatsApp Chat with Bob (phone 2).zip  # second account — will be merged
```

Sub-folders work too:

```
my_exports/
├── account_1/
│   └── WhatsApp Chat with Bob.zip
└── account_2/
    └── WhatsApp Chat with Bob.zip
```

All conversations in the source folder are merged chronologically into one output file.

### Step 2 — Scan

1. Launch the app: `python transcriber.py`
2. Click **Browse…** and select your source folder
3. Click **Scan** — the app shows:
   - How many conversations / exports were found
   - Total message count
   - Audio breakdown: already transcribed vs. needs transcription vs. file missing

### Step 3 — Run

1. Select a Whisper model size (see [Model sizes](#model-sizes))
2. Click **▶ Transcribe & Build Transcript**
3. Choose where to save the output `.txt` file
4. The app transcribes pending audio files and builds the unified transcript

---

## Manual transcriptions

If you have already transcribed an audio file by hand, place a plain `.txt` file alongside it with the same base name:

```
PTT-20231012-WA0001.opus
PTT-20231012-WA0001.opus.txt   ← manual transcript (preferred naming)
```

or

```
PTT-20231012-WA0001.opus
PTT-20231012-WA0001.txt        ← also accepted
```

The app detects these and inserts the saved text instead of calling Whisper. The log and output label the source as `(saved)`.

---

## Output format

```
================================================================
  Monday, 13 October 2025
================================================================
[09:14:22] Alice: Morning!
[09:15:01] Bob: [Voice message (whisper): Hey, just calling to say I'll be a bit late today.]
[09:15:44] Alice: No problem, see you soon.
[09:17:30] Bob: [Voice message (saved): Running about 10 minutes behind.]
```

- Date headers separate each day
- Voice messages are labelled `(whisper)` or `(saved)` so you can tell the source at a glance
- If an audio file is referenced in the chat but the file is not present in the export, it is noted as `[Voice message – file not found]`

---

## Model sizes

| Model  | Speed    | Accuracy | VRAM (approx.) |
|--------|----------|----------|----------------|
| tiny   | Fastest  | Basic    | ~1 GB          |
| base   | Fast     | Good     | ~1 GB          |
| small  | Moderate | Better   | ~2 GB          |
| medium | Slower   | Great    | ~5 GB          |
| large  | Slowest  | Best     | ~10 GB         |

`base` is the default and works well for clear voice messages. Models are downloaded automatically on first use and cached locally.

---

## Supported audio formats

`.opus` · `.m4a` · `.mp3` · `.ogg` · `.aac` · `.wav` · `.wma` · `.oga`

WhatsApp voice messages are typically `.opus` (Android) or `.m4a` (iOS).

---

## Supported WhatsApp export date formats

The parser handles all known WhatsApp timestamp formats across locales:

| Format | Example |
|--------|---------|
| `[DD/MM/YYYY, HH:MM:SS]` | `[13/10/2025, 09:14:22]` |
| `[DD/MM/YYYY, HH:MM]`    | `[13/10/2025, 09:14]` |
| `DD/MM/YYYY, HH:MM –`    | `13/10/2025, 09:14 – ` |
| `M/D/YY, H:MM AM/PM –`   | `10/13/25, 9:14 AM – ` |

---

## Project structure

```
whatsapp-transcriber/
├── transcriber.py     # entire application (single file)
├── requirements.txt   # Python dependencies
└── README.md
```

---

## Troubleshooting

**"FFmpeg not found in PATH"** — Install FFmpeg and restart the app. See [Requirements](#requirements).

**Whisper fails to install** — Run manually: `pip install faster-whisper` or `pip install openai-whisper`

**Garbled / wrong timestamps** — WhatsApp uses the phone's locale for date formatting. If dates are not parsing correctly, open an issue with a sample (anonymised) line from your `_chat.txt`.

**Audio transcribed but text is wrong language** — Whisper auto-detects language. If it guesses incorrectly on short clips, try a larger model (`small` or above).

---

## License

MIT
