import os
import signal
import re
import time
import shutil
import subprocess
import threading
from datetime import datetime
from flask import Flask, render_template_string, jsonify, send_from_directory, Response, request

# --- CONFIGURATION ---
PRESETS = {
    "1": ("95.7", "0", "The Jet"),
    "2": ("96.5", "0", "JackFM"),
    "3": ("102.5", "1", "TikTok Radio"),
    "4": ("107.7", "1", "Channel Q"),
    "5": ("106.1", "1", "Pride Radio"),
    "6": ("93.3", "1", "KUBE"),
    "7": ("97.3", "0", "KIRO News"),
    "8": ("99.9", "0", "KISW Rock"),
}

TMP_DIR = "/tmp/nrsc5_aas"
os.makedirs(TMP_DIR, exist_ok=True)
os.chmod(TMP_DIR, 0o777) 

app = Flask(__name__)

current_preset = "1"
nrsc5_process = None
latest_metadata = {
    "title": "Unknown Title",
    "artist": "Unknown Artist",
    "album": "Unknown Album",
    "genre": "Unknown Genre",
    "slogan": "",
    "bitrate": "Unknown Bitrate",
    "art_url": "",
    "raw_log": [],
    "tmt_files": [],
    "running": False
}

def parse_nrsc5_output(pipe):
    global latest_metadata

    title_regex = re.compile(r"Title:\s*(.*)")
    artist_regex = re.compile(r"Artist:\s*(.*)")
    album_regex = re.compile(r"Album:\s*(.*)")
    genre_regex = re.compile(r"Genre:\s*(.*)")
    slogan_regex = re.compile(r"Slogan:\s*(.*)")
    bitrate_regex = re.compile(r"Audio bit rate:\s*(.*)")

    lot_regex = re.compile(r"LOT file:\s+port=(\w+)\s+lot=(\d+)\s+name=([a-zA-Z0-9_\-\.]+)\s+size=(\d+)\s+mime=([0-9A-F]+)")
    tmt_regex = re.compile(r"LOT file:\s+port=(\w+)\s+lot=(\d+)\s+name=(TMT_[a-zA-Z0-9_\-\.]+)\s+size=(\d+)\s+mime=([0-9A-F]+)")
    here_regex = re.compile(r"HERE Image:\s+type=(\w+).*?name=(trafficMap_[0-3]_[0-3]_[^,\s]+).*?size=(\d+)")   

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

        g_match = slogan_regex.search(line)
        if g_match:
            latest_metadata["slogan"] = g_match.group(1).strip()

        br_match = bitrate_regex.search(line)
        if br_match:
            latest_metadata["bitrate"] = br_match.group(1).strip()

        # --- Helper Function to Identify Duplicates ---
        def get_semantic_key(filename):
            """
            Strips the leading lot number (digits + underscore) to find the base filename.
            Example: '330_TMT_...' becomes 'TMT_...'
                     '1782693289_trafficMap_...' becomes 'trafficMap_...'
            """
            match = re.match(r'^\d+_(.*)', filename)
            return match.group(1) if match else filename

        def add_file_deduplicated(file_list, new_file, max_limit=9):
            """
            Adds new_file to file_list, removing any existing file with the same 
            semantic key (treating the new one as the newer duplicate).
            """
            new_key = get_semantic_key(new_file)
    
            # Filter out any existing file that matches the new file's semantic key
            # This effectively removes the 'older' duplicate
            filtered_list = [f for f in file_list if get_semantic_key(f) != new_key]
    
            # Append the new (newer) file
            filtered_list.append(new_file)
    
            # Enforce the max limit (keep the most recent 9)
            if len(filtered_list) > max_limit:
                filtered_list.pop(0)
        
            return filtered_list

        # Check for TMT files (traffic/metadata files - keep for display)
        tmt_match = tmt_regex.search(line)
        if tmt_match:
            lot_num = tmt_match.group(2).strip()
            filename = tmt_match.group(3).strip()
            actual_filename = f"{lot_num}_{filename}"
    
            # Use the helper function instead of direct append
            latest_metadata["tmt_files"] = add_file_deduplicated(
                latest_metadata["tmt_files"], 
                actual_filename, 
                max_limit=9
            )

        # Checks for HERE traffic files --keep for display
        here_regex = re.compile(
            r"HERE Image:\s+type=(?P<type>\w+).*?"
            r"seq=(?P<seq>\d+).*?"  # seq is captured but NOT used in filename
            r"time=(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z).*?"
            r"name=(?P<filename>trafficMap_[0-3]_[0-3]_[^,\s]+).*?"
            r"size=(?P<size>\d+)",
            re.IGNORECASE
        )

        # Check for Traffic Map files
        tmt_match = here_regex.search(line)
        if tmt_match:
            # Convert ISO timestamp to Unix timestamp
            time_str = tmt_match.group("timestamp").strip()
            dt = datetime.strptime(time_str, "%Y-%m-%dT%H:%M:%SZ")
            unix_timestamp = int(dt.timestamp())

            # Get the base filename
            filename = tmt_match.group("filename").strip()
            # Construct the full filename with Unix timestamp prefix
            actual_filename = f"{unix_timestamp}_{filename}"

            # Use the helper function instead of direct append
            latest_metadata["tmt_files"] = add_file_deduplicated(
                latest_metadata["tmt_files"], 
                actual_filename, 
                max_limit=9
            )



        # Check for regular LOT files that are NOT TMT (album art candidates)
        lot_match = lot_regex.search(line)
        if lot_match and not tmt_match:
            lot_num = lot_match.group(2).strip()
            filename = lot_match.group(3).strip()

            # Only set as album art if filename has image extension
            if filename.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.bmp')):
                filename_lower = filename.lower()
                # Explicitly exclude 
                if ('tmt_' in filename_lower or 
                    'weather' in filename_lower or 
                    'traffic' in filename_lower or 
                    'dwro' in filename_lower):
                    continue  # Skip this file
                # File is stored as: <lot>_<filename>
                actual_filename = f"{lot_num}_{filename}"
                latest_metadata["art_url"] = f"/aas/{actual_filename}?t={int(time.time())}"

def _append_log_text(txt):
    global latest_metadata
    if not txt:
        return
    for ln in txt.splitlines():
        latest_metadata["raw_log"].append(ln.strip())
    # Keep last N lines
    if len(latest_metadata["raw_log"]) > 400:
        latest_metadata["raw_log"] = latest_metadata["raw_log"][-400:]

def start_nrsc5(preset_id=None, freq=None, program=None, name=None):

    global nrsc5_process, latest_metadata, current_preset

    # Ensure nrsc5 exists
    if not shutil.which("nrsc5"):
        latest_metadata.update({
            "title": "nrsc5 not found",
            "artist": "",
            "album": "",
            "genre": "",
            "slogan": "",
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
        "album": "",
        "genre": "",
        "slogan": "",
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

    out_path = os.path.join(TMP_DIR, "stream.wav")

    # Tries different devices for multiple SDRs.
    candidate_cmds = [
        ["nrsc5", "-d 0", freq, program, "-o", out_path, "--dump-aas-files", TMP_DIR],    # Device 0
        ["nrsc5", "-d 0", freq, program, "-o", out_path, "--dump-aas-files", TMP_DIR],    # Device 1
        ["nrsc5", freq, program, "-o", out_path, "--dump-aas-files", TMP_DIR],            # minimal
    ]

    started = False
    last_err_text = ""
    for cmd in candidate_cmds:
        _append_log_text(f"Trying: {' '.join(cmd)}")
        try:
            p = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,   
                stderr=subprocess.PIPE,
                text=False,
                bufsize=4096
            )
        except Exception as e:
            _append_log_text(f"Failed to spawn nrsc5: {e}")
            continue

        timeout = 0.6
        waited = 0.0
        interval = 0.05
        while waited < timeout:
            ret = p.poll()
            if ret is not None:
                break
            time.sleep(interval)
            waited += interval

        if p.poll() is None:
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
            "slogan": "",
            "bitrate": "",
            "art_url": "",
            "running": False
        })
        if last_err_text:
            _append_log_text("Last stderr from nrsc5:")
            _append_log_text(last_err_text)
        raise RuntimeError("nrsc5 failed to start; check raw_log for details")

def stop_nrsc5():
    global nrsc5_process, latest_metadata
    if not nrsc5_process:
        latest_metadata["running"] = False
        return

    try:
        nrsc5_process.terminate()
        nrsc5_process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            nrsc5_process.kill()
            nrsc5_process.communicate(timeout=2)
        except Exception:
            pass
    except Exception:
        pass
    finally:
        try:
            # Clean environment to remove Flask-specific FD variables
            env = os.environ.copy()
            env.pop('WERKZEUG_SERVER_FD', None)
            
            subprocess.run(
                ["sudo", "usbreset", "RTL2838UHIDIR"], 
                check=True,
                env=env,
                close_fds=True,  # CRITICAL: Closes inherited Flask file descriptors
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except subprocess.CalledProcessError:
            # Only log if the command actually fails (non-zero exit)
            print("Error: usbreset failed to execute.")
        except OSError as e:
            # Ignore Errno 9 if the command likely succeeded (race condition in cleanup)
            if e.errno != 9:
                print(f"OS Error during reset: {e}")
        except Exception as e:
            print(f"Unexpected error: {e}")

        latest_metadata["running"] = False

    if nrsc5_process.stdin:
        try: nrsc5_process.stdin.close()
        except: pass
    if nrsc5_process.stdout:
        try: nrsc5_process.stdout.close()
        except: pass
    if nrsc5_process.stderr:
        try: nrsc5_process.stderr.close()
        except: pass

    nrsc5_process = None
    latest_metadata.update({
        "title": "Stopped",
        "artist": "",
        "album": "",
        "genre": "",
        "slogan": "",
        "bitrate": "",
        "art_url": "",
        "running": False
    })
    _append_log_text("nrsc5 stopped by user.")

# --- AUDIO STREAMING GENERATOR ---
def stream_audio_mp3():
    out_path = os.path.join(TMP_DIR, "stream.wav")

    start_wait = 0.0
    while True:
        if os.path.exists(out_path):
            break
        if not latest_metadata.get("running"):
            return
        time.sleep(0.1)
        start_wait += 0.1
        if start_wait > 15:
            _append_log_text("Timeout waiting for stream.wav to appear.")
            return    
    try:
        ffmpeg_cmd = [
            'ffmpeg',
            '-f', 's16le',          # Input format: 16-bit signed little-endian PCM
            '-ar', '44100',         # Sample Rate (CHANGE THIS to match your WAV: 24000, 44100, etc.)
            '-ac', '2',             # Channels (CHANGE THIS: 1 for mono, 2 for stereo)
            '-i', 'pipe:0',         # Input from stdin
            '-f', 'mp3',            # Output format
            '-b:a', '128k',         # Bitrate
            'pipe:1'                # Output to stdout
        ]
        
        process = subprocess.Popen(
            ffmpeg_cmd, 
            stdin=subprocess.PIPE, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE
        )

        last_inode = None
        f = None
        
        def file_reader():
            nonlocal f, last_inode
            try:
                while latest_metadata.get("running") or (nrsc5_process is not None):
                    try:
                        st = os.stat(out_path)
                        
                        if f is None or st.st_ino != last_inode:
                            if f:
                                try: f.close()
                                except: pass
                            f = open(out_path, "rb")
                            last_inode = st.st_ino

                        chunk = f.read(4096)
                        if chunk:
                            process.stdin.write(chunk)
                        else:
                            time.sleep(0.05)
                    except FileNotFoundError:
                        if f:
                            try: f.close()
                            except: pass
                        f = None
                        time.sleep(0.1)
            except Exception as e:
                _append_log_text(f"Reader error: {e}")
            finally:
                if f:
                    try: f.close()
                    except: pass
                if process.stdin:
                    process.stdin.close()

        reader_thread = threading.Thread(target=file_reader, daemon=True)
        reader_thread.start()

        while True:
            output = process.stdout.read(4096)
            if not output:
                # Check if process died
                if process.poll() is not None:
                    break
                time.sleep(0.05)
                continue
            yield output

    finally:
        if process:
            process.terminate()
            process.wait()


# --- FLASK ROUTES ---
@app.route("/")
def index():
    html_template = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Web HD Radio</title>
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
                <h1>HD Radio Web Radio</h1>
                <div class="presets">
                    {% for id, details in presets.items() %}
                        <button id="btn-{{ id }}" onclick="tunePreset('{{ id }}')" class="{% if id == current_preset %}active{% endif %}">
                            {{ details[2] }} ({{ details[0] }} MHz)
                        </button>
                    {% endfor %}
                </div>

                <div class="manual">
                    <label style="color:#ccc">Freq:</label>
                    <input id="manual-freq" type="text" maxlength=5 size=5 placeholder="107.7" />
                    <label style="color:#ccc">Ch:</label>
                    <input id="manual-program" type="text" maxlength=1 size=1 placeholder="0" />
                    <button onclick="tuneManualStart()">Manually Tune</button>
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
                        <p id="track-slogan"></p>
                        <p id="track-bitrate"></p>
                    </div>
                    <!-- Audio element initially stopped; no autoplay -->
                    <audio id="radio-player" controls src=""></audio>
                </div>
            
                <div class="tmt-panel">
                <h3>Traffic</h3>
                <div class="tmt-gallery" id="tmt-container"></div>
            </div>
                <h3>Terminal Output</h3>
                <div class="terminal" id="log-container"></div>
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
                    alert("Select a preset or press 'Manually Tune' to play.");
                    return;
                }
                // call /tune/<preset> to start nrsc5 on server and then point the audio to the stream
                fetch('/tune/' + selectedPreset)
                    .then(response => response.json())
                    .then(data => {
                        if (data.status === 'success') {
                            const player = document.getElementById('radio-player');
                            // cache-bust param
                            player.src = '/stream.mp3?t=' + Date.now();
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
                            player.src = '/stream.mp3?t=' + Date.now();
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
                            document.getElementById('track-slogan').innerText = "";
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
                        document.getElementById('track-genre').innerText = data.genre ? "" + data.genre : "";
                        document.getElementById('track-slogan').innerText = data.slogan ? "" + data.slogan : "";
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
                            // Sort the array before rendering
                            data.tmt_files.sort((a, b) => {
                                const partsA = a.split('_');
                                const partsB = b.split('_');

                                let rowA, colA, rowB, colB;

                                // Detect format based on parts length or specific content
                                // New format: 1783727236_trafficMap_1_0_4t25.png (5+ parts usually, Row@2, Col@3)
                                // Old format: 640(0)_TMT(1)_02dgt3(2)_1(3)_3(4)_date... (Row@3, Col@4)
        
                                // Heuristic: If parts[1] contains "trafficMap", it's the new format
                                if (partsA[1] && partsA[1].includes('trafficMap')) {
                                    rowA = parseInt(partsA[2], 10);
                                    colA = parseInt(partsA[3], 10);
                                } else {
                                    // Fallback to original logic
                                    rowA = parseInt(partsA[3], 10);
                                    colA = parseInt(partsA[4], 10);
                                }

                                if (partsB[1] && partsB[1].includes('trafficMap')) {
                                    rowB = parseInt(partsB[2], 10);
                                    colB = parseInt(partsB[3], 10);
                                } else {
                                    // Fallback to original logic
                                    rowB = parseInt(partsB[3], 10);
                                    colB = parseInt(partsB[4], 10);
                                }

                                // Compare Rows first
                                if (rowA !== rowB) {
                                    return rowA - rowB;
                                }

                                // If Rows are equal, compare Columns
                                return colA - colB;
                            });

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

            setInterval(updateStatus, 2000);
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

@app.route('/stream.mp3')
def audio_stream():
    return Response(
        stream_audio_mp3(),
        mimetype='audio/mpeg',
        headers={
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache',
            'Expires': '0'
        }
    )

@app.route("/aas/<filename>")
def get_aas_file(filename):
    return send_from_directory(TMP_DIR, filename)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7430, debug=False)
