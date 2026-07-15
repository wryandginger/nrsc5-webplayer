# nrsc5-webplayer
a python webplayer for HDRadio FM Broadcasts

- This was vibecoded, but I did my best to clean up the code. Sorry.
- This is an early work in progress. Any help is welcome.
   
# Requirements:
- A RTL2832U [SDR](https://www.amazon.com/RTL-SDR-Blog-RTL2832U-Software-Defined/dp/B0F6MM7MJ1) from most [brands](https://www.amazon.com/Nooelec-RTL-SDR-SDR-100kHz-1-75GHz-Enclosure/dp/B01HA642SW) work.
- An excellent antenna. I'm using [this](https://www.amazon.com/POBADY-Antenna-Magnetic-Omni-Direction-Raspberry/dp/B094MW1YMV/) because it is well-tuned for FM (and 433MHz)
- A server running debian linux, Python 3, ffmpeg, usbutils, and flask
- A working install of [nrsc5](https://github.com/theori-io/nrsc5)
- Alternatively, you can use docker and this will build it all for you.
  
# How to:
- Run python3 webradio.py and go to YOUR_IP:7420
- Alternatively, you can run this as a docker container (recommended for enhanced security).
- I use portainer and just put this as a repository stack with no other tweaks.
- Presets are for the Seattle market. Adjust the script to your area/tastes.
- This now let's a second user join in by pressing "Listen In"
- Anyone can tune to and listen to the current session live at: http://IP:7430/stream.mp3 

# Known bugs:
- Audio will occasionally cut out due to poor reception. Consider buying a better antenna for your SDR.
- No metadata/albumart is attached to the MP3 stream, but you get it on the lockscreen. 
