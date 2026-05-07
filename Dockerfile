FROM registry.access.redhat.com/ubi9/python-311:latest

WORKDIR /app

# Install deps first for layer caching.
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

# Source.
COPY agent ./agent
COPY indexer ./indexer
COPY chatbot ./chatbot
COPY config ./config

# OpenShift assigns a random non-root UID; group must be 0 with g+rwX.
USER 1001
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CHAT_HOST=0.0.0.0 \
    CHAT_PORT=8080

EXPOSE 8080
CMD ["python", "-m", "chatbot.app"]
