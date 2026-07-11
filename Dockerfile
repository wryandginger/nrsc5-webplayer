FROM python:3.9-slim

# Set working directory
WORKDIR /app

# Install system dependencies AND udev/hwdata (Critical for lsusb/usbreset)
RUN apt-get update && apt-get install -y \
    git \
    build-essential \
    cmake \
    autoconf \
    libtool \
    libao-dev \
    libfftw3-dev \
    librtlsdr-dev \
    libusb-1.0-0-dev \
    pkg-config \
    ffmpeg \
    usbutils \
    udev \        # <--- ADDED: Installs the udev daemon
    hwdata \      # <--- ADDED: Installs USB ID database (fixes "unable to initialize usb spec")
    && rm -rf /var/lib/apt/lists/*

# Clone and compile libnrsc5
RUN git clone https://github.com/theori-io/nrsc5.git /tmp/nrsc5 \
    && cd /tmp/nrsc5 \
    && mkdir build && cd build \
    && cmake .. \
    && make \
    && make install \
    && ldconfig \
    && rm -rf /tmp/nrsc5

# Install Python dependencies
RUN pip install flask

# Copy the application code
COPY . .

# Expose the web player port
EXPOSE 7430

# Create a startup script to launch udevd BEFORE the python app
# We use a shell wrapper here instead of a separate file for simplicity
CMD ["sh", "-c", "udevd --daemon && sleep 2 && udevadm trigger && python3 webradio.py"]Copied!   
