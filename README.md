# nrsc5-webplayer

📻 A Python webplayer for HD Radio FM Broadcasts. 📻

### ⚠️ Disclaimers:
* 🪄 **Vibe-coded:** The code has been cleaned up, but some rough edges remain.
* 🚧 **Work in progress:** This is an early build, but I think this is close to done.

### Preview:
<details>
  <summary>🔍 Click to expand:</summary>
<p align="center">
  <img src="https://github.com/wryandginger/nrsc5-webplayer/blob/main/screenshots/webradio.png?raw=true)" width="600">
</p>
</details>

# ⚠️ Requirements:
- A RTL2832U [SDR](https://www.amazon.com/RTL-SDR-Blog-RTL2832U-Software-Defined/dp/B0F6MM7MJ1) from most [brands](https://www.amazon.com/Nooelec-RTL-SDR-SDR-100kHz-1-75GHz-Enclosure/dp/B01HA642SW) work.
- An excellent antenna. I'm using [this](https://www.amazon.com/POBADY-Antenna-Magnetic-Omni-Direction-Raspberry/dp/B094MW1YMV/) because it is well-tuned for FM (and 433MHz)
- A server running debian linux, Python 3, ffmpeg, usbutils, and flask
- A working install of [nrsc5](https://github.com/theori-io/nrsc5)
- Alternatively, you can use docker and this will build it all for you.

## 🚀 Getting Started: 
- 1. Clone this repo
- 2. Run python3 webradio.py and go to YOUR_IP:7420
  
- Alternatively, you can run this as a Docker container!
  - I recommend using Docker 🐳 for security and sharing on your network.
  - I use Portainer and just put this as a repository stack with no other tweaks.

## 🎉 FYIs:
- Presets are for the Seattle market. Adjust the script to your area/tastes. I gave you all the presets in my area that my SDR can pull.
- Once a stream starts the green "Start" button becomes "Listen In" allowing new users to join the active stream
- Traffic data for HERE and TTN is available on supported stations
- Anyone can tune to and listen to the current session live at: http://IP:7430/stream.mp3 

# 🪲 Known bugs/issues:
- Any visitor to the webradio can stop the stream. (A killjoy switch was tested, but it worked too well.)
- Arbitrary code **might** be able to be injected in an http request to manually tune (currently investigating)
- No metadata/albumart is attached to the MP3 stream, (Working on iOS lockscreens tho!).
- Traffic maps and album art stay after stopping stream. (This is semi-intentional so active users keep loaded traffic maps until a new one generates)
- Some browsers/platforms don't show metadata.
- Bluetooth casting doesn't transmit album art.

## 🤝 Contributing
- Please feel free to contribute with a PR or issue!
- Feature requests welcome too.
