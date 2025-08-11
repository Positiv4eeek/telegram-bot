FROM python:3.11-slim

# ffmpeg для обрезки
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# .env подкинешь через docker run -v или docker compose env_file

CMD ["python", "main.py"]