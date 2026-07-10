import os
import re
import time
import shutil
import subprocess
import threading
from flask import Flask, render_template_string, jsonify, send_from_directory, Response, request

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
os.chmod(TMP_DIR, 0o777)  # Ensure readable

app = Flask(__name__)

# --- GLOBAL STATE ---
current_preset = "1"
nrsc5_process = None
latest_metadata = {
    "title": "Unknown Title",
    "artist": "Unknown Artist",
    "album": "Unknown Album",
    "genre": "Unknown Genre",
    "bitrate": "Unknown Bitrate",
    "art_url": "",
    "raw_log": [],
    "tmt_files": [],
    "running": False
}

# --- METADATA & PARSING LOGIC ---
def parse_nrsc5_output(pipe):
    """Reads nrsc5 stderr line by line to extract metadata and AAS updates."""
    global latest_metadata

    title_regex = re.compile(r"Title:\s*(.*)")
    artist_regex = re.compile(r"Artist:\s*(.*)")
    album_regex = re.compile(r"Album:\s*(.*)")
    genre_regex = re.compile(r"Genre:\s*(.*)")
    bitrate_regex = re.compile(r"Audio bit rate:\s*(.*)")
    # Capture port, lot, and name - lot is prepended to filename on disk
    lot_regex = re.compile(r"LOT file:\s+port=(\w+)\s+lot=(\d+)\s+name=([a-zA-Z0-9_\-\.]+)\s+size=(\d+)\s+mime=([0-9A-F]+)")
    tmt_regex = re.compile(r"LOT file:\s+port=(\w+)\s+lot=(\d+)\s+name=(TMT_[a-zA-Z0-9_\-\.]+)\s+size=(\d+)\s+mime=([0-9A-F]+)")

    # pipe is a text-mode file object (os.fdopen on stderr fileno)
    for line in iter(pipe.readline, ""):
        if not line:
            break

        latest_metadata["raw_log"].append(line.strip())
        if len(latest_metadata["raw_log"]) > 300:
            latest_metadata["raw_log"].pop(0)

        t_match = title_regex.search(line)
        if t_match:
            latest_metadata["title"] = t_match.group(1).strip()

        ar_match = artist_regex.search(line)
        if ar_match:
            latest_metadata["artist"] = ar_match.group(1).strip()

        al_match = album_regex.search(line)
        if al_match:
            latest_metadata["album"] = al_match.group(1).strip()

        g_match = genre_regex.search(line)
        if g_match:
            latest_metadata["genre"] = g_match.group(1).strip()

        br_match = bitrate_regex.search(line)
        if br_match:
            latest_metadata["bitrate"] = br_match.group(1).strip()

        # Check for TMT files (traffic/metadata files - keep for display)
        tmt_match = tmt_regex.search(line)
        if tmt_match:
            lot_num = tmt_match.group(2).strip()
            filename = tmt_match.group(3).strip()
            # File is stored as: <lot>_<filename>
            actual_filename = f"{lot_num}_{filename}"
            latest_metadata["tmt_files"].append(actual_filename)
            # Keep only last 9 TMT files
            if len(latest_metadata["tmt_files"]) > 9:
                latest_metadata["tmt_files"].pop(0)

        # Check for regular LOT files that are NOT TMT (album art candidates)
        lot_match = lot_regex.search(line)
        if lot_match and not tmt_match:
            lot_num = lot_match.group(2).strip()
            filename = lot_match.group(3).strip()
            # Only set as album art if filename has image extension
            if filename.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.bmp')):
                # File is stored as: <lot>_<filename>
                actual_filename = f"{lot_num}_{filename}"
                latest_metadata["art_url"] = f"/aas/{actual_filename}?t={int(time.time())}"

def _append_log_text(txt):
    """Helper to append multi-line text to raw_log safely."""
    global latest_metadata
    if not txt:
        return
    for ln in txt.splitlines():
        latest_metadata["raw_log"].append(ln.strip())
    # Keep last N lines
    if len(latest_metadata["raw_log"]) > 400:
        latest_metadata["raw_log"] = latest_metadata["raw_log"][-400:]

def start_nrsc5(preset_id=None, freq=None, program=None, name=None):
    """
    Stops any running instance of nrsc5 and starts a new one.
    - If preset_id is provided and known, use that preset.
    - Otherwise freq and program (channel) must be provided.
    The implementation writes a WAV file to TMP_DIR/stream.wav and tails it for clients.
    """
    global nrsc5_process, latest_metadata, current_preset

    # Ensure nrsc5 exists
    if not shutil.which("nrsc5"):
        latest_metadata.update({
            "title": "nrsc5 not found",
            "artist": "",
            "album": "",
            "genre": "",
            "bitrate": "",
            "art_url": "",
            "running": False
        })
        _append_log_text("ERROR: nrsc5 executable not found on PATH.")
        raise FileNotFoundError("nrsc5 not found on PATH")

    # Resolve parameters
    if preset_id:
        if preset_id not in PRESETS:
            raise ValueError("Unknown preset")
        freq, program, name = PRESETS[preset_id]
        current_preset = preset_id
    else:
        # manual tune: ensure freq and program exist
        if not freq or program is None:
            raise ValueError("freq and program are required for manual tuning")
        name = name or f"{freq} / ch {program}"
        current_preset = None

    # Gracefully stop any existing process first
    if nrsc5_process:
        try:
            nrsc5_process.terminate()
            nrsc5_process.wait(timeout=5)
        except Exception:
            try:
                nrsc5_process.kill()
            except Exception:
                pass
        nrsc5_process = None

    latest_metadata.update({
        "title": f"Connecting to {name}...",
        "artist": "Loading...",
        "album": "Loading...",
        "genre": "",
        "bitrate": "",
        "art_url": "",
        "raw_log": [],
        "tmt_files": [],
        "running": True
    })

    # Clear TMP_DIR (remove old AAS images, old stream file)
    for f in os.listdir(TMP_DIR):
        try:
            os.remove(os.path.join(TMP_DIR, f))
        except Exception:
            pass

    # Use a fixed filename so we can stream it while nrsc5 writes
    out_path = os.path.join(TMP_DIR, "stream.wav")

    # Try a sequence of candidate commands; if one fails quickly, log stderr and try the next.
    candidate_cmds = [
        ["nrsc5", freq, program, "-o", out_path, "--dump-aas-files", TMP_DIR],                 # your working form with long option
        ["nrsc5", freq, program, "-o", out_path, "-t", "wav", "--dump-aas-files", TMP_DIR],    # explicit type
        ["nrsc5", freq, program, "-o", out_path],                                            # minimal
    ]

    started = False
    last_err_text = ""
    for cmd in candidate_cmds:
        _append_log_text(f"Trying: {' '.join(cmd)}")
        try:
            p = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,   # nrsc5 writes the WAV file instead of stdout
                stderr=subprocess.PIPE,
                text=False,
                bufsize=4096
            )
        except Exception as e:
            _append_log_text(f"Failed to spawn nrsc5: {e}")
            continue

        # Wait briefly to see if process exits immediately (bad args)
        timeout = 0.6
        waited = 0.0
        interval = 0.05
        while waited < timeout:
            ret = p.poll()
            if ret is not None:
                # process exited quickly
                break
            time.sleep(interval)
            waited += interval

        if p.poll() is None:
            # process still running -> success; hook up stderr parser and adopt this process
            nrsc5_process = p
            try:
                stderr_text_wrapper = os.fdopen(nrsc5_process.stderr.fileno(), 'r', errors='ignore')
                threading.Thread(target=parse_nrsc5_output, args=(stderr_text_wrapper,), daemon=True).start()
            except Exception:
                _append_log_text("Warning: failed to spawn stderr parser thread")
            started = True
            _append_log_text("nrsc5 started successfully.")
            break
        else:
            # process died; collect stderr for diagnostics
            try:
                err = p.stderr.read() or b""
            except Exception:
                err = b""
            try:
                err_text = err.decode(errors='ignore') if isinstance(err, (bytes, bytearray)) else str(err)
            except Exception:
                err_text = str(err)
            last_err_text = err_text
            _append_log_text(f"nrsc5 exited: {err_text.strip()}")
            # ensure cleanup
            try:
                p.stderr.close()
            except Exception:
                pass
            try:
                p.kill()
            except Exception:
                pass
            # try next candidate

    if not started:
        latest_metadata.update({
            "title": "Failed to start nrsc5",
            "artist": "",
            "album": "",
            "genre": "",
            "bitrate": "",
            "art_url": "",
            "running": False
        })
        if last_err_text:
            _append_log_text("Last stderr from nrsc5:")
            _append_log_text(last_err_text)
        raise RuntimeError("nrsc5 failed to start; check raw_log for details")

def stop_nrsc5():
    """Gracefully stop the nrsc5 process (terminate -> wait -> kill) and mark not running."""
    global nrsc5_process, latest_metadata
    if not nrsc5_process:
        latest_metadata["running"] = False
        return

    try:
        nrsc5_process.terminate()
        nrsc5_process.wait(timeout=5)
    except Exception:
        try:
            nrsc5_process.kill()
        except Exception:
            pass

    nrsc5_process = None
    latest_metadata.update({
        "title": "Stopped",
        "artist": "",
        "album": "",
        "genre": "",
        "bitrate": "",
        "art_url": "",
        "running": False
    })
    _append_log_text("nrsc5 stopped by user.")

# --- AUDIO STREAMING GENERATOR ---
def stream_audio():
    """Streams the TMP_DIR/stream.wav file as it is written by nrsc5 (follows file growth)."""
    out_path = os.path.join(TMP_DIR, "stream.wav")

    # Wait until the file exists or until not running
    start_wait = 0.0
    while True:
        if os.path.exists(out_path):
            break
        if not latest_metadata.get("running"):
            # nothing to stream
            return
        time.sleep(0.1)
        start_wait += 0.1
        # safety: if it's taking too long, yield nothing
        if start_wait > 15 and not os.path.exists(out_path):
            _append_log_text("Timeout waiting for stream.wav to appear.")
            return

    # Open and tail the file. If nrsc5 replaces/truncates the file, reopen it.
    last_inode = None
    f = None
    try:
        while latest_metadata.get("running") or (nrsc5_process is not None):
            try:
                st = os.stat(out_path)
                if f is None:
                    f = open(out_path, "rb")
                    last_inode = st.st_ino
                else:
                    # If file was replaced/rotated, reopen
                    if st.st_ino != last_inode:
                        try:
                            f.close()
                        except Exception:
                            pass
                        f = open(out_path, "rb")
                        last_inode = st.st_ino

                chunk = f.read(4096)
                if chunk:
                    yield chunk
                else:
                    # No new data yet
                    time.sleep(0.05)
            except FileNotFoundError:
                # Wait until nrsc5 creates it again
                if f:
                    try:
                        f.close()
                    except Exception:
                        pass
                    f = None
                time.sleep(0.1)
    finally:
        if f:
            try:
                f.close()
            except Exception:
                pass

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
            .container { max-width: 900px; margin: 0 auto; display: grid; grid-template-columns: 1fr 300px; gap: 20px; }
            .main-panel { background: #333; padding: 20px; border-radius: 10px; }
            .tmt-panel { background: #333; padding: 20px; border-radius: 10px; height: fit-content; }
            .presets { margin-bottom: 10px; }
            button { background: #444; color: white; border: 1px solid #555; padding: 10px 15px; margin: 5px; cursor: pointer; border-radius: 5px; }
            button.active { background: #007bff; border-color: #0056b3; }
            button#start-btn { background: #28a745; border-color: #1e7e34; }
            button#start-btn:hover { background: #218838; }
            button#stop-btn { background: #dc3545; border-color: #bd2130; }
            button#stop-btn:hover { background: #c82333; }
            .controls { margin-top: 10px; }
            .player { background: #111; padding: 20px; border-radius: 10px; margin-top: 10px; }
            .album-art { width: 200px; height: 200px; background: #444; margin: 0 auto 15px; display: flex; align-items: center; justify-content: center; border-radius: 5px; overflow: hidden; }
            .album-art img { width: 100%; height: 100%; object-fit: cover; }
            .track-info h2 { margin: 5px 0; font-size: 1.4em; }
            .track-info h3 { margin: 5px 0; color: #bbb; font-size: 1.1em; }
            .track-info p { margin: 3px 0; color: #999; font-size: 0.9em; }
            audio { width: 100%; margin-top: 15px; }
            .terminal { background: #000; color: #0f0; text-align: left; padding: 10px; font-family: monospace; height: 180px; overflow-y: scroll; font-size: 11px; margin-top: 20px; border-radius: 5px; }
            .manual { margin-top: 12px; display:flex; justify-content:center; gap:8px; align-items:center; flex-wrap: wrap; }
            input[type="text"] { padding:6px 8px; border-radius:4px; border:1px solid #666; background:#222; color:#fff; }
            .tmt-panel h3 { margin-top: 0; color: #fff; }
            .tmt-gallery { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0px; padding: 0px; background: #000; border-radius: 0px; max-height: 512px; overflow-y: auto; }
            .tmt-item { width: 100%; aspect-ratio: 1 / 1; background: #222; border-radius: 0px; overflow: hidden; display: flex; align-items: center; justify-content: center; }
            .tmt-item img { width: 100%; height: 100%; object-fit: cover; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="main-panel">
                <h1>HD Radio Controller</h1>
                <div class="presets">
                    {% for id, details in presets.items() %}
                        <button id="btn-{{ id }}" onclick="tunePreset('{{ id }}')" class="{% if id == current_preset %}active{% endif %}">
                            {{ details[2] }} ({{ details[0] }} MHz)
                        </button>
                    {% endfor %}
                </div>

                <div class="manual">
                    <label style="color:#ccc">Freq:</label>
                    <input id="manual-freq" type="text" placeholder="e.g. 96.5" />
                    <label style="color:#ccc">Ch:</label>
                    <input id="manual-program" type="text" placeholder="e.g. 0" />
                    <button onclick="tuneManualStart()">Tune & Start</button>
                </div>

                <div class="controls">
                    <button id="start-btn" onclick="startCurrent()">Start</button>
                    <button id="stop-btn" onclick="stopStream()">Stop</button>
                </div>

                <div class="player">
                    <div class="album-art" id="art-container">No Art</div>
                    <div class="track-info">
                        <h2 id="track-title">Stopped</h2>
                        <h3 id="track-artist"></h3>
                        <h3 id="track-album"></h3>
                        <p id="track-genre"></p>
                        <p id="track-bitrate"></p>
                    </div>
                    <!-- Audio element initially stopped; no autoplay -->
                    <audio id="radio-player" controls src=""></audio>
                </div>

                <h3>Terminal Output</h3>
                <div class="terminal" id="log-container"></div>
            </div>

            <div class="tmt-panel">
                <h3>Traffic</h3>
                <div class="tmt-gallery" id="tmt-container"></div>
            </div>
        </div>

        <script>
            let selectedPreset = "{{ current_preset if current_preset is not none else '' }}";

            function tunePreset(id) {
                // Just select the preset locally; does NOT start the stream
                selectedPreset = id;
                document.querySelectorAll('.presets button').forEach(b => b.classList.remove('active'));
                const btn = document.getElementById('btn-' + id);
                if (btn) btn.classList.add('active');
                // Update title to indicate selected
                const label = btn ? btn.innerText : id;
                document.getElementById('track-title').innerText = "Selected: " + label;
            }

            function startCurrent() {
                if (!selectedPreset) {
                    alert("Select a preset or use Tune & Start for manual tuning.");
                    return;
                }
                // call /tune/<preset> to start nrsc5 on server and then point the audio to the stream
                fetch('/tune/' + selectedPreset)
                    .then(response => response.json())
                    .then(data => {
                        if (data.status === 'success') {
                            const player = document.getElementById('radio-player');
                            // cache-bust param
                            player.src = '/audio.wav?t=' + Date.now();
                            player.load();
                            player.play().catch(()=>{});
                        } else {
                            alert("Failed to start: " + (data.message || "unknown"));
                        }
                    });
            }

            function tuneManualStart() {
                const freq = document.getElementById('manual-freq').value.trim();
                const program = document.getElementById('manual-program').value.trim();

                if (!freq || !program) {
                    alert("Please enter both frequency and channel.");
                    return;
                }

                // GET endpoint for convenience: /tune_manual?freq=...&program=...
                const url = '/tune_manual?freq=' + encodeURIComponent(freq) + '&program=' + encodeURIComponent(program);
                fetch(url)
                    .then(response => response.json())
                    .then(data => {
                        if (data.status === 'success') {
                            // Make selectedPreset empty (it's a manual tune)
                            selectedPreset = '';
                            // Start the audio element
                            const player = document.getElementById('radio-player');
                            player.src = '/audio.wav?t=' + Date.now();
                            player.load();
                            player.play().catch(()=>{});
                        } else {
                            alert("Failed to start manual tune: " + (data.message || "unknown"));
                        }
                    });
            }

            function stopStream() {
                fetch('/stop')
                    .then(response => response.json())
                    .then(data => {
                        if (data.status === 'success') {
                            const player = document.getElementById('radio-player');
                            player.pause();
                            player.removeAttribute('src');
                            player.load();
                            document.getElementById('track-title').innerText = "Stopped";
                            document.getElementById('track-artist').innerText = "";
                            document.getElementById('track-album').innerText = "";
                            document.getElementById('track-genre').innerText = "";
                            document.getElementById('track-bitrate').innerText = "";
                            const artContainer = document.getElementById('art-container');
                            artContainer.innerHTML = 'No Art';
                        } else {
                            alert("Failed to stop: " + (data.message || "unknown"));
                        }
                    });
            }

            function updateStatus() {
                fetch('/status')
                    .then(response => response.json())
                    .then(data => {
                        document.getElementById('track-title').innerText = data.title || "";
                        document.getElementById('track-artist').innerText = data.artist || "";
                        document.getElementById('track-album').innerText = data.album || "";
                        document.getElementById('track-genre').innerText = data.genre ? "Genre: " + data.genre : "";
                        document.getElementById('track-bitrate').innerText = data.bitrate ? "Bitrate: " + data.bitrate : "";

                        const artContainer = document.getElementById('art-container');
                        if (data.art_url) {
                            artContainer.innerHTML = '<img src="' + data.art_url + '" />';
                        } else {
                            artContainer.innerHTML = 'No Art';
                        }

                        const logContainer = document.getElementById('log-container');
                        logContainer.innerHTML = (data.raw_log || []).join('<br>');
                        logContainer.scrollTop = logContainer.scrollHeight;

                        // Render TMT files as a 3x3 image gallery
                        const tmtContainer = document.getElementById('tmt-container');
                        tmtContainer.innerHTML = '';
                        if (data.tmt_files && data.tmt_files.length > 0) {
                            data.tmt_files.forEach(filename => {
                                const item = document.createElement('div');
                                item.className = 'tmt-item';
                                const img = document.createElement('img');
                                img.src = '/aas/' + encodeURIComponent(filename);
                                img.alt = filename;
                                item.appendChild(img);
                                tmtContainer.appendChild(item);
                            });
                        }

                        // Update Start/Stop UI
                        document.getElementById('start-btn').disabled = data.running;
                        document.getElementById('stop-btn').disabled = !data.running;
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
        try:
            start_nrsc5(preset_id=preset_id)
            return jsonify({"status": "success", "preset": preset_id})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
    return jsonify({"status": "error", "message": "Invalid preset"}), 400

@app.route("/tune_manual")
def tune_manual():
    # Manual tuning using query parameters: ?freq=96.5&program=0
    freq = request.args.get("freq", "").strip()
    program = request.args.get("program", "").strip()

    if not freq or program == "":
        return jsonify({"status": "error", "message": "freq and program are required"}), 400

    try:
        # program can be integer-like; pass as string to nrsc5 as original script did
        start_nrsc5(preset_id=None, freq=freq, program=program, name=None)
        return jsonify({"status": "success", "freq": freq, "program": program})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/stop")
def stop():
    stop_nrsc5()
    return jsonify({"status": "success"})

@app.route("/status")
def status():
    return jsonify(latest_metadata)

@app.route("/audio.wav")
def audio_stream():
    # Returns chunked WAV audio stream directly to the web browser
    # We stream the stream.wav file that nrsc5 is writing into TMP_DIR
    return Response(stream_audio(), mimetype="audio/wav")

@app.route("/aas/<filename>")
def get_aas_file(filename):
    # Safely serves parsed images from the tmp folder directly to the frontend
    return send_from_directory(TMP_DIR, filename)

if __name__ == "__main__":
    # Do NOT start nrsc5 here — page starts stopped. Press Start on the web UI to connect.
    app.run(host="0.0.0.0", port=7430, debug=False)
