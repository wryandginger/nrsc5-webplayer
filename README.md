# nrsc5-webplayer
a python webplayer for HDRadio FM Broadcasts

- This was vibecoded, but I did my best to clean up the code. Sorry.
   
# Requirements:
- An SDR Dongle (Nooelec smart nesdr, rtl-sdr, etc.)
- A server running debian linux, Python 3, ffmpeg, and Flask (i.e. python3-flask)
- A working install of [nrsc5](https://github.com/theori-io/nrsc5)
  
# How to:
- Run python3 webradio.py and go to YOUR_IP:7420
- Presets are for the Seattle market. Adjust the script to your area/tastes.

# Known bugs:
- TTN Traffic data only kinda works for iHeartRadio stations. The logic in this section needs to be rewritten. If you have bad reception, this will look wonky.
- HERE traffic data is very broken.
- Audio will occasionally cut out due to poor reception. Consider buying a better antenna for your SDR.
