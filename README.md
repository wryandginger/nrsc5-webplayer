# nrsc5-webplayer
a python webplayer for HDRadio FM Broadcasts

- This was vibecoded, but I did my best to clean up the code. Sorry.
- This is an early work in progress. Any help is welcome.
   
# Requirements:
- An SDR Dongle (Nooelec smart nesdr, rtl-sdr, etc.)
- A server running debian linux, Python 3, ffmpeg, and Flask (i.e. python3-flask)
- A working install of [nrsc5](https://github.com/theori-io/nrsc5)
  
# How to:
- Run python3 webradio.py and go to YOUR_IP:7420
- Alternatively, you can run this as a docker container (recommended for enhanced security).
- I use portainer and just put this as a Repository stack with no other tweaks.
- Presets are for the Seattle market. Adjust the script to your area/tastes.

# Known bugs:
- Audio will occasionally cut out due to poor reception. Consider buying a better antenna for your SDR.
- This only works for one user. However, additional users can tune to http://IP:7430/stream.mp3 and listen to the stream.
- OR http://IP:7430/aas/stream.wav gives it to you in a WAV file, which is not IOS friendly.
- No metadata is attached to the MP3 stream.
