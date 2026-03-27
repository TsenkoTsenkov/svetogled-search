#!/bin/bash
# Called by GitHub Actions to deploy new code/transcripts to the EC2 instance.
# Flow: git pull → re-index Meilisearch → restart the app
set -e

cd /opt/svetogled-search
echo "=== Pulling latest code ==="
git pull

echo "=== Re-indexing transcripts ==="
python3 index_to_meili.py --fresh

echo "=== Restarting app ==="
systemctl restart svetogled

echo "=== Deploy complete ==="
