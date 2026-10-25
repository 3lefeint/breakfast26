FROM node:22-slim AS frontend-builder
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim

WORKDIR /app

# ffmpeg is needed at runtime by tools/generate_voicepack.py's silence-trim
# step (regenerating the voice pack from the Settings tab).
# libhidapi-libusb0 is the USB layer of the Stream Deck keys (Settings > Stream Deck).
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libhidapi-libusb0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-streamdeck.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-streamdeck.txt

COPY main.py .
COPY CHANGELOG.md .
COPY breakfast/ ./breakfast/
COPY tools/ ./tools/
COPY --from=frontend-builder /breakfast/web/dist ./breakfast/web/dist

# All of the app's config/data defaults (config.toml, stats.db, sessions/,
# sounds/) are plain relative paths resolved against the process cwd — so
# running from here instead of /app means every one of them lands under a
# single mounted directory with zero Python code changes. main.py is still
# invoked by absolute path, so `from breakfast import ...` keeps resolving
# normally (Python adds the *script's* directory to sys.path, not the cwd).
WORKDIR /app/data

EXPOSE 8080

ENTRYPOINT ["python", "/app/main.py"]
