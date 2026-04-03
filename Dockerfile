FROM python:3.12-slim

# Install curl for healthcheck and downloading meilisearch
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Install Meilisearch
RUN curl -L https://install.meilisearch.com | sh && mv ./meilisearch /usr/local/bin/

# Set up app directory
WORKDIR /app

# Copy application files
COPY search_app.py .
COPY index.html .
COPY index_to_meili.py .
COPY transcripts/ ./transcripts/
COPY static/ ./static/

# Install Python dependencies
RUN pip install --no-cache-dir meilisearch

# Startup script that launches Meilisearch and the app
COPY start.sh .
RUN chmod +x start.sh

# Cloud Run uses PORT env var
ENV PORT=8080

EXPOSE 8080

CMD ["./start.sh"]
