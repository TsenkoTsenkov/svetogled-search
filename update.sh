#!/bin/bash
# Manual deploy entry point on the on-prem Mac. CI does the same thing via
# .github/workflows/deploy.yml (sync checkout → mac/deploy-mac.sh). The EC2
# flow this replaced lived at /opt/svetogled-search and was driven over SSH.
set -euo pipefail
cd "$(dirname "$0")"
git pull --ff-only && exec bash mac/deploy-mac.sh
