FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN mkdir -p /app/logs

COPY . .

CMD ["python3", "wapiway_bridge.py"]
