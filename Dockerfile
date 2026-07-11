FROM python:3.9-slim

# Set working directory
WORKDIR /app

# Install system dependencies required to build libnrsc5 and run python
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
    udev \
    hwdata \
    libudev1 \
    && rm -rf /var/lib/apt/lists/*

# Clone and compile libnrsc5 (The core C library)
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

# If no requirements.txt exists in the repo, uncomment the line below instead:
# RUN pip install --no-cache-dir flask

# Copy the application code
COPY . .

# Expose the web player port
EXPOSE 7430

# Run the specific script requested
CMD ["python3", "webradio.py"]   
