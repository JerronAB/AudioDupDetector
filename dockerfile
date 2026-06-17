FROM python:3.14-slim-trixie
ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /app

#Provides a little extra safety for weird filenames:
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8

# System dependencies: ffmpeg and others
# Using a single RUN command and cleaning up apt cache to keep the image small
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg libchromaprint-tools && \ 
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip && \
    pip install --no-cache-dir pyacoustid

#RUN pip install --no-cache-dir openai-whisper

#RUN pip install --no-cache-dir nltk

#Forces logs to appear immediately
ENV PYTHONUNBUFFERED=1

# Copy application files
COPY * .

# Sets the default command to run your Python script
ENTRYPOINT ["/usr/bin/env", "bash", "/app/main.sh"]