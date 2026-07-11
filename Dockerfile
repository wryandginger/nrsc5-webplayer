FROM python:3.9-slim

# Set working directory
WORKDIR /app

# Install dependencies including udev and hwdata
# We explicitly install 'libudev1' as well to ensure runtime libraries are present
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

# run it plain
CMD ["python3", "webradio.py"]
