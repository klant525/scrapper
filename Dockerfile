FROM python:3.11-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# System deps + Google Chrome
RUN set -eux; \
    apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl gnupg unzip xvfb \
      fonts-liberation libasound2 libdrm2 libgbm1 libgtk-3-0 \
      libx11-6 libxcomposite1 libxdamage1 libxext6 libxi6 libxrandr2 \
    && install -d -m 0755 /etc/apt/keyrings \
    && curl -fsSL https://dl.google.com/linux/linux_signing_key.pub \
         | gpg --dearmor -o /etc/apt/keyrings/google-linux.gpg \
    && echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/google-linux.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
         > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

ENV CHROME_BIN=/usr/bin/google-chrome

# Non-root
RUN useradd -m -u 1000 appuser
USER appuser

WORKDIR /app

# ✅ Copy toàn bộ source (tránh COPY điều kiện gây lỗi)
COPY --chown=appuser:appuser . .

# Cài Python deps (nếu có requirements.txt) – dùng Selenium Manager
RUN set -eux; \
    python -m pip install --upgrade pip setuptools wheel; \
    if [ -f requirements.txt ]; then \
      python -m pip install -r requirements.txt; \
    else \
      python -m pip install "selenium>=4.17" "webdriver-manager==4.*"; \
    fi; \
    python - << 'PY'
from importlib.util import find_spec
from importlib.metadata import version, PackageNotFoundError
name = "selenium"
if find_spec(name) is None:
    raise SystemExit("Selenium not installed")
try:
    v = tuple(int(x) for x in version(name).split(".")[:2])
except PackageNotFoundError:
    raise SystemExit("Selenium not installed")
assert v >= (4, 6), f"Selenium >= 4.6 required, found {version(name)}"
print("Selenium version OK:", version(name))
PY

# CMD để docker-compose quy định
# CMD ["python", "-c", "print('container ready')"]