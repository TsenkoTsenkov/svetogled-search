#!/bin/bash
set -e

# Start Meilisearch in the background
meilisearch \
  --db-path /tmp/meili_data \
  --http-addr 127.0.0.1:7700 \
  --master-key "svetogled-search-key" \
  --env production \
  --no-analytics \
  &

# Wait for Meilisearch to be ready
echo "Waiting for Meilisearch..."
for i in $(seq 1 30); do
  if curl -sf http://127.0.0.1:7700/health > /dev/null 2>&1; then
    echo "Meilisearch ready."
    break
  fi
  sleep 1
done

# Index transcripts
echo "Indexing transcripts..."
python index_to_meili.py --fresh

# Start the search app on the Cloud Run PORT
echo "Starting search app on port ${PORT:-8080}..."
exec python -u search_app.py
