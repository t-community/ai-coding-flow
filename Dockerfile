FROM python:3.13-slim

WORKDIR /app

# System packages + Node.js (required for opencode engine)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install opencode AI coding engine
RUN npm install -g opencode-ai

# Python dependencies (includes aider-chat which installs the aider binary)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN git config --global --add safe.directory /tmp/ai-coding-flow || true

EXPOSE 8000

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
