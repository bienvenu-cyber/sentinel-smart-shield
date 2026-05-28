FROM python:3.11-slim

# iputils-ping pour le test de connectivité réseau des caméras.
RUN apt-get update \
    && apt-get install -y --no-install-recommends iputils-ping \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY watcher.py .

CMD ["python3", "-u", "watcher.py"]