# Use the official Python base image
FROM python:3.12-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-eng \
    libtesseract-dev \
    libleptonica-dev \
    pkg-config \
    git \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user
RUN useradd -m -s /bin/bash vscode
USER vscode
WORKDIR /home/vscode

# Install Python packages
RUN pip install --user --no-cache-dir \
    jupyter \
    jupyterlab \
    ipykernel \
    pytesseract \
    Pillow \
    openai \
    pandas \
    numpy \
    matplotlib \
    seaborn \
    requests \
    beautifulsoup4 \
    selenium

# Set up Jupyter kernel
RUN python -m ipykernel install --user --name=python3

# Create workspace directory
RUN mkdir -p /home/vscode/workspace

# Set the working directory
WORKDIR /home/vscode/workspace

# Expose Jupyter port
EXPOSE 8888

# Start Jupyter Lab by default
CMD ["jupyter", "lab", "--ip=0.0.0.0", "--port=8888", "--no-browser", "--allow-root"]
