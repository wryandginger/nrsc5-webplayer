FROM python:3.9-alpine

# Enable community repo (needed for some dev packages like libao-dev)
RUN echo "http://dl-cdn.alpinelinux.org/alpine/edge/community" >> /etc/apk/repositories && \
    echo "http://dl-cdn.alpinelinux.org/alpine/edge/main" >> /etc/apk/repositories

WORKDIR /app

# Install build dependencies
RUN apk add --no-cache --virtual .build-deps \
    git \
    build-base \
    cmake \
    autoconf \
    automake \
    libtool \
    libao-dev \
    fftw-dev \
    libusb-dev \
    pkgconfig \
    ffmpeg-dev \
    eudev-dev \
    linux-headers \
    && \
    # 1. Build librtlsdr from source (Alpine's package is often incomplete for building)
    git clone https://github.com/osmocom/rtl-sdr.git /tmp/rtl-sdr && \
    cd /tmp/rtl-sdr && \
    mkdir build && cd build && \
    cmake .. -DDETACH_KERNEL_DRIVER=ON && \
    make && \
    make install && \
    cd /tmp && rm -rf rtl-sdr && \
    # 2. Build libnrsc5
    git clone https://github.com/theori-io/nrsc5.git /tmp/nrsc5 && \
    cd /tmp/nrsc5 && \
    mkdir build && cd build && \
    cmake .. && \
    make && \
    make install && \
    ldconfig && \
    rm -rf /tmp/nrsc5 && \
    # Remove build dependencies
    apk del .build-deps

# Install runtime dependencies
RUN apk add --no-cache \
    libusb-1.0 \
    librtlsdr \
    ffmpeg-libs \
    libao \
    eudev \
    usbutils

# Install Python dependencies
RUN pip install --no-cache-dir flask

# Copy application code
COPY . .

EXPOSE 7430

# Trigger udev and run
CMD ["sh", "-c", "udev-trigger || true && python3 webradio.py"]Copied!   
