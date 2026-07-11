FROM python:3.9-alpine

# Set working directory
WORKDIR /app

# Install system build and runtime dependencies
RUN apk add --no-cache --virtual .build-deps \
    git \
    build-base \
    cmake \
    autoconf \
    automake \
    libtool \
    libao-dev \
    fftw-dev \
    librtlsdr-dev \
    libusb-dev \
    pkgconfig \
    ffmpeg-dev \
    eudev \
    usbutils \
    && \
    # Clone and compile libnrsc5
    git clone https://github.com/theori-io/nrsc5.git /tmp/nrsc5 && \
    cd /tmp/nrsc5 && \
    mkdir build && cd build && \
    cmake .. && \
    make && \
    make install && \
    ldconfig && \
    rm -rf /tmp/nrsc5 && \
    # Remove build dependencies to reduce image size
    apk del .build-deps && \
    # Install runtime dependencies
    apk add --no-cache \
    libusb-1.0 \
    librtlsdr \
    ffmpeg-libs \
    libao

# Install Python dependencies
RUN pip install --no-cache-dir flask

# Copy application code
COPY . .

# Expose the web player port
EXPOSE 7430

# Ensure USB devices are accessible (optional udev trigger)
CMD ["sh", "-c", "udev-trigger || true && python3 webradio.py"]   
