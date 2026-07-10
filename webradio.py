import os
import re
import time
import subprocess
import threading
from flask import Flask, render_template_string, jsonify, send_from_directory, Response

# --- CONFIGURATION ---
PRESETS = {
    "1": ("95.7", "0", "The Jet"),
    "2": ("96.5", "0", "JackFM"),
    "3": ("102.5", "1", "TikTok Radio"),
    "4": ("107.7", "1", "Channel Q"),
    "5": ("106.1", "1", "Pride Radio"),
}

TMP_DIR = "/tmp/nrsc5_aas"
os.makedirs(TMP_DIR, exist_ok=True)

app = Flask(__name__)

# --- GLOBAL STATE ---
current_preset = "1"
nrsc5_process = None
latest_metadata = {
    "title": "Unknown Title",
    "artist": "Unknown Artist",
    "album": "Unknown Album",
    "art_url": "",
    "raw_log": []
}

# --- METADATA & PARSING LOGIC ---
def parse_nrsc5_output(pipe):
    """Reads nrsc5 stderr line by line to extract metadata and AAS updates."""
    global latest_metadata
    
    title_regex = re.compile(r"Title:\s*(.*)")
    artist_regex = re.compile(r"Artist:\s*(.*)")
    album_regex = re.compile(r"Album:\s*(.*)")
    lot_regex = re.compile(r"LOT file\s+([a-zA-Z0-9_\-\.]+)\s+\(type:.*mime: image/jpeg\)")

    for line in iter(pipe.readline, ""):
        if not line:
            break
        
        latest_metadata["raw_log"].append(line.strip())
        if len(latest_metadata["raw_log"]) > 50:
            latest_metadata["raw_log"].pop(0)

        t_match = title_regex.search(line)
        if t_match: latest_metadata["title"] = t_match.group(1).strip()
            
        ar_match = artist_regex.search(line)
        if ar_match: latest_metadata["artist"] = ar_match.group(1).strip()
            
        al_match = album_regex.search(line)
        if al_match: latest_metadata["album"] = al_match.group(1).strip()

        lot_match = lot_regex.search(line)
        if lot_match:
            filename = lot_match.group(1).strip()
            latest_metadata["art_url"] = f"/aas/{filename}?t={int(time.time())}"

def generate_wav_header(sample_rate=44100, bits_per_sample=16, channels=2):
    """Generates an infinite/flexible WAV header for live streaming."""
    # We use 0xFFFFFFFF for chunk sizes to imply an ongoing data stream
    o = b'RIFF'
    o += b'\xff\xff\xff\xff'  # ChunkSize (infinite stream)
    o += b'WAVE'
    o += b'fmt '
    o += b'\x10\x00\x00\x00'  # Subchunk1Size (16 for PCM)
    o += b'\x01\x00'          # AudioFormat (1 for PCM)
    o += channels.to_bytes(2, 'little')
    o += sample_rate.to_bytes(4, 'little')
    byte_rate = sample_rate * channels * bits_per_sample // 8
    o += byte_rate.to_bytes(4, 'little')
    block_align = channels * bits_per_sample // 8
    o += block_align.to_bytes(2, 'little')
    o += bits_per_sample.to_bytes(2, 'little')
    o += b'data'
    o += b'\xff\xff\xff\xff'  # Subchunk2Size (infinite stream)
    return o

def start_nrsc5(preset_id):
    """Stops any running instance of nrsc5 and starts a new one."""
    global nrsc5_process, latest_metadata, current_preset
    
    current_preset = preset_id
    freq, program, name = PRESETS[preset_id]

    if nrsc5_process:
        nrsc5_process.terminate()
        nrsc5_process.wait()

    latest_metadata = {
        "title": f"Connecting to {name}...",
        "artist": "Loading...",
        "album": "Loading...",
        "art_url": "",
        "raw_log": []
    }

    for f in os.listdir(TMP_DIR):
        try: os.remove(os.path.join(TMP_DIR, f))
        except Exception: pass

    # -o - instructs nrsc5 to output raw, uncompressed 147048 Hz PCM to stdout
    cmd = ["nrsc5", freq, program, "-o", "-", "-tmp", TMP_DIR]
    
    nrsc5_process = subprocess.Popen(
        cmd, 
        stdout=subprocess.PIPE, 
        stderr=subprocess.PIPE,
        text=False, # Must be False to read raw audio bytes from stdout
        bufsize=4096
    )

    # Wrap stderr into a text-mode reader thread for the log parser
    stderr_text_wrapper = os.fdopen(nrsc5_process.stderr.fileno(), 'r', errors='ignore')
    threading.Thread(target=parse_nrsc5_output, args=(stderr_text_wrapper,), daemon=True).start()

# --- AUDIO STREAMING GENERATOR ---
def stream_audio():
    """Generates the live audio response with a WAV container."""
    # Send WAV container header first
    # Note: nrsc5 outputs raw PCM at 147048 Hz stereo, 16-bit
    yield generate_wav_header(sample_rate=147048, bits_per_sample=16, channels=2)
    
    while True:
        if nrsc5_process and nrsc5_process.stdout:
            data = nrsc5_process.stdout.read(4096)
            if data:
                yield data
            else:
                time.sleep(0.01)
        else:
            time.sleep(0.1)

# --- FLASK ROUTES ---
@app.route("/")
def index():
    html_template = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>HD Radio Controller</title>
        <style>
            body { font-family: Arial, sans-serif; background: #222; color: #fff; text-align: center; padding: 20px; }
            .container { max-width: 600px; margin: 0 auto; background: #333; padding: 20px; border-radius: 10px; }
            .presets { margin-bottom: 20px; }
            button { background: #444; color: white; border: 1px solid #555; padding: 10px 15px; margin: 5px; cursor: pointer; border-radius: 5px; }
            button.active { background: #007bff; border-color: #0056b3; }
            .player { background: #111; padding: 20px; border-radius: 10px; margin-top: 10px; }
            .album-art { width: 200px; height: 200px; background: #444; margin: 0 auto 15px; display: flex; align-items: center; justify-content: center; border-radius: 5px; overflow: hidden; }
            .album-art img { width: 100%; height: 100%; object-fit: cover; }
            .track-info h2 { margin: 5px 0; font-size: 1.4em; }
            .track-info h3 { margin: 5px 0; color: #bbb; font-size: 1.1em; }
            audio { width: 100%; margin-top: 15px; }
            .terminal { background: #000; color: #0f0; text-align: left; padding: 10px; font-family: monospace; height: 150px; overflow-y: scroll; font-size: 11px; margin-top: 20px; border-radius: 5px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>HD Radio Controller</h1>
            <div class="presets">
                {% for id, details in presets.items() %}
                    <button id="btn-{{ id }}" onclick="changePreset('{{ id }}')" class="{% if id == current_preset %}active{% endif %}">
                        {{ details[2] }} ({{ details[0] }} MHz)
                    </button>
                {% endfor %}
            </div>
            
            <div class="player">
                <div class="album-art" id="art-container">No Art</div>
                <div class="track-info">
                    <h2 id="track-title">Loading...</h2>
                    <h3 id="track-artist">Loading...</h3>
                    <h3 id="track-album">Loading...</h3>
                </div>
                <!-- Native Audio Player Source points to live WAV endpoint -->
                <audio id="radio-player" controls autoplay src="/audio.wav"></audio>
            </div>

            <h3>Terminal Output</h3>
            <div class="terminal" id="log-container"></div>
        </div>

        <script>
            function changePreset(id) {
                fetch('/tune/' + id)
                    .then(response => response.json())
                    .then(data => {
                        if(data.status === 'success') {
                            document.querySelectorAll('.presets button').forEach(b => b.classList.remove('active'));
                            document.getElementById('btn-' + id).classList.add('active');
                            
                            // Reload audio element to sync stream with the newly chosen station
                            const player = document.getElementById('radio-player');
                            player.src = '/audio.wav?t=' + int(time.time());
                            player.load();
                            player.play();
                        }
                    });
            }

            function updateStatus() {
                fetch('/status')
                    .then(response => response.json())
                    .then(data => {
                        document.getElementById('track-title').innerText = data.title;
                        document.getElementById('track-artist').innerText = data.artist;
                        document.getElementById('track-album').innerText = data.album;
                        
                        const artContainer = document.getElementById('art-container');
                        if (data.art_url) {
                            artContainer.innerHTML = '<img src="' + data.art_url + '" />';
                        } else {
                            artContainer.innerHTML = 'No Art';
                        }

                        const logContainer = document.getElementById('log-container');
                        logContainer.innerHTML = data.raw_log.join('<br>');
                        logContainer.scrollTop = logContainer.scrollHeight;
                    });
            }

            setInterval(updateStatus, 1000);
            updateStatus();
        </script>
    </body>
    </html>
    """
    return render_template_string(html_template, presets=PRESETS, current_preset=current_preset)

@app.route("/tune/<preset_id>")
def tune(preset_id):
    if preset_id in PRESETS:
        start_nrsc5(preset_id)
        return jsonify({"status": "success", "preset": preset_id})
    return jsonify({"status": "error", "message": "Invalid preset"}), 400

@app.route("/status")
def status():
    return jsonify(latest_metadata)

@app.route("/audio.wav")
def audio_stream():
    # Returns chunked WAV audio stream directly to the web browser
    return Response(stream_audio(), mimetype="audio/wav")

@app.route("/aas/<filename>")
def get_aas_file(filename):
    # Safely serves parsed images from the tmp folder directly to the frontend
    return send_from_directory(TMP_DIR, filename)

if __name__ == "__main__":
    # Boot into the default preset immediately on launch
    start_nrsc5(current_preset)
    # Start the Flask web application
    app.run(host="0.0.0.0", port=7430, debug=False)
