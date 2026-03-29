#!/bin/bash
set -e

# Log everything
exec > /var/log/user-data.log 2>&1

echo "=== Starting setup ==="

# Install dependencies
dnf install -y docker git python3-pip
systemctl enable docker
systemctl start docker

# Install Caddy (reverse proxy with auto HTTPS)
dnf install -y 'dnf-command(copr)'
dnf copr enable -y @caddy/caddy epel-9-aarch64 || true
cat > /etc/yum.repos.d/caddy.repo << 'REPO'
[caddy]
name=Caddy
baseurl=https://download.caddy.org/rpm/
enabled=1
repo_gpgcheck=0
gpgcheck=0
REPO
dnf install -y caddy || {
  # Fallback: install caddy binary directly
  curl -o /usr/bin/caddy -L "https://caddyserver.com/api/download?os=linux&arch=arm64"
  chmod +x /usr/bin/caddy
}

# Configure Caddy
cat > /etc/caddy/Caddyfile << 'CADDY'
${domain} {
    reverse_proxy localhost:8080
}

www.${domain} {
    redir https://${domain}{uri}
}
CADDY

# Enable Caddy
systemctl enable caddy
systemctl start caddy || true

# Install and configure CloudWatch Agent for memory metrics
dnf install -y amazon-cloudwatch-agent

cat > /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json << 'CWA'
{
  "metrics": {
    "namespace": "Svetogled",
    "metrics_collected": {
      "mem": {
        "measurement": ["mem_used_percent", "mem_available_percent"],
        "metrics_collection_interval": 60
      },
      "disk": {
        "measurement": ["disk_used_percent"],
        "resources": ["/"],
        "metrics_collection_interval": 60
      }
    },
    "append_dimensions": {
      "InstanceId": "$${aws:InstanceId}"
    }
  }
}
CWA

/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
  -a fetch-config \
  -m ec2 \
  -c file:/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json \
  -s

systemctl enable amazon-cloudwatch-agent

# Clone the repo
cd /opt
git clone https://github.com/TsenkoTsenkov/svetogled-search.git
cd svetogled-search

# Install Meilisearch (pinned version — latest requires glibc 2.35, AL2023 has 2.34)
MEILI_VERSION="v1.6.2"
curl -L -o /usr/local/bin/meilisearch \
  "https://github.com/meilisearch/meilisearch/releases/download/$${MEILI_VERSION}/meilisearch-linux-aarch64"
chmod +x /usr/local/bin/meilisearch

# Install Python dependencies
pip3 install meilisearch

# Create systemd service for Meilisearch
cat > /etc/systemd/system/meilisearch.service << 'SVC'
[Unit]
Description=Meilisearch
After=network.target

[Service]
ExecStart=/usr/local/bin/meilisearch --db-path /var/lib/meilisearch/data --http-addr 127.0.0.1:7700 --master-key svetogled-search-key --env production --no-analytics
WorkingDirectory=/opt/svetogled-search
Restart=always
User=root

[Install]
WantedBy=multi-user.target
SVC

mkdir -p /var/lib/meilisearch/data
systemctl enable meilisearch
systemctl start meilisearch

# Wait for Meilisearch
sleep 5
for i in $(seq 1 30); do
  curl -sf http://127.0.0.1:7700/health && break
  sleep 2
done

# Index transcripts
cd /opt/svetogled-search
python3 index_to_meili.py --fresh

# Create systemd service for the search app
cat > /etc/systemd/system/svetogled.service << 'SVC'
[Unit]
Description=Svetogled Search App
After=meilisearch.service

[Service]
ExecStart=/usr/bin/python3 search_app.py
WorkingDirectory=/opt/svetogled-search
Restart=always
User=root
Environment=PORT=8080

[Install]
WantedBy=multi-user.target
SVC

systemctl enable svetogled
systemctl start svetogled

# Create update script (for GitHub Actions to trigger)
cat > /opt/svetogled-search/update.sh << 'UPDATE'
#!/bin/bash
cd /opt/svetogled-search
git pull
pip3 install -q meilisearch
python3 index_to_meili.py --fresh
systemctl restart svetogled
UPDATE
chmod +x /opt/svetogled-search/update.sh

echo "=== Setup complete ==="
