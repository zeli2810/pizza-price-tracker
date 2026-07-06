FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

# Domino's scraping needs a "headed" Chrome (headless=False) to dodge bot
# detection; Xvfb provides a virtual display so that works inside a container.
RUN apt-get update && apt-get install -y --no-install-recommends xvfb \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV DISPLAY=:99
EXPOSE 8000

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
