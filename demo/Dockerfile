FROM python:3.9-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    jq \
    git \
    build-essential \
    software-properties-common \
    python3-pip \
    python3-dev

# Upgrade pip and setuptools to ensure compatibility
RUN pip3 install --no-cache-dir --upgrade pip setuptools wheel

# Set working directory
WORKDIR /app

# Copy project files into the container
COPY . /app

# Copy the requirements.txt explicitly
COPY requirements.txt /app/requirements.txt

# Install Python dependencies with pip3
RUN pip3 install --no-cache-dir -r /app/requirements.txt

# Make scripts executable
RUN chmod +x ngrok-wait.sh run_demo

# Default command to start ACA-Py
CMD ["bash", "./run_demo"]
