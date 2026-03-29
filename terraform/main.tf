terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region  = var.aws_region
  profile = "tsenko-master"
}

# --- Data sources ---

data "aws_route53_zone" "main" {
  name = "svetogled-arhiv.com"
}

data "aws_ami" "amazon_linux" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-arm64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# --- Security Group ---

resource "aws_security_group" "svetogled" {
  name        = "svetogled-search"
  description = "Allow HTTP, HTTPS, and SSH"

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "svetogled-search"
  }
}

# --- IAM Role for CloudWatch Agent ---

resource "aws_iam_role" "svetogled" {
  name = "svetogled-ec2-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ec2.amazonaws.com"
      }
    }]
  })

  tags = {
    Name = "svetogled-ec2-role"
  }
}

resource "aws_iam_role_policy_attachment" "cloudwatch_agent" {
  role       = aws_iam_role.svetogled.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

resource "aws_iam_role_policy_attachment" "ssm_managed" {
  role       = aws_iam_role.svetogled.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "svetogled" {
  name = "svetogled-ec2-profile"
  role = aws_iam_role.svetogled.name
}

# --- SSH Key ---

resource "aws_key_pair" "svetogled" {
  key_name   = "svetogled-key"
  public_key = file(var.ssh_public_key_path)
}

# --- EC2 Instance ---

resource "aws_instance" "svetogled" {
  ami                    = data.aws_ami.amazon_linux.id
  instance_type          = var.instance_type
  key_name               = aws_key_pair.svetogled.key_name
  vpc_security_group_ids = [aws_security_group.svetogled.id]
  iam_instance_profile   = aws_iam_instance_profile.svetogled.name

  root_block_device {
    volume_size = 30
    volume_type = "gp3"
  }

  user_data = templatefile("${path.module}/user_data.sh", {
    domain            = var.domain
    deploy_public_key = var.deploy_public_key
  })

  tags = {
    Name = "svetogled-search"
  }
}

# --- Elastic IP ---

resource "aws_eip" "svetogled" {
  instance = aws_instance.svetogled.id

  tags = {
    Name = "svetogled-search"
  }
}

# --- DNS Records ---

resource "aws_route53_record" "root" {
  zone_id = data.aws_route53_zone.main.zone_id
  name    = var.domain
  type    = "A"
  ttl     = 300
  records = [aws_eip.svetogled.public_ip]
}

# --- Monitoring ---

resource "aws_sns_topic" "alerts" {
  name = "svetogled-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_cloudwatch_metric_alarm" "instance_down" {
  alarm_name          = "svetogled-instance-down"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "StatusCheckFailed"
  namespace           = "AWS/EC2"
  period              = 300
  statistic           = "Maximum"
  threshold           = 0
  alarm_description   = "Svetogled EC2 instance is down"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]

  dimensions = {
    InstanceId = aws_instance.svetogled.id
  }
}

resource "aws_cloudwatch_metric_alarm" "high_memory" {
  alarm_name          = "svetogled-high-memory"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "mem_used_percent"
  namespace           = "Svetogled"
  period              = 300
  statistic           = "Average"
  threshold           = 85
  alarm_description   = "Memory utilization above 85% on svetogled instance"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]

  dimensions = {
    InstanceId = aws_instance.svetogled.id
  }
}

resource "aws_route53_health_check" "svetogled" {
  fqdn              = var.domain
  port              = 443
  type              = "HTTPS"
  resource_path     = "/"
  failure_threshold = 3
  request_interval  = 30

  tags = {
    Name = "svetogled-health-check"
  }
}

resource "aws_cloudwatch_metric_alarm" "health_check" {
  alarm_name          = "svetogled-site-down"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  metric_name         = "HealthCheckStatus"
  namespace           = "AWS/Route53"
  period              = 60
  statistic           = "Minimum"
  threshold           = 1
  alarm_description   = "svetogled-arhiv.com is not responding"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]

  dimensions = {
    HealthCheckId = aws_route53_health_check.svetogled.id
  }
}

resource "aws_route53_record" "google_verification" {
  zone_id = data.aws_route53_zone.main.zone_id
  name    = var.domain
  type    = "TXT"
  ttl     = 300
  records = ["google-site-verification=KW5BnT-pkZz33EPM8Hz9oNZ7xhMcr2KcAYeAL3xofr0"]
}

resource "aws_route53_record" "www" {
  zone_id = data.aws_route53_zone.main.zone_id
  name    = "www.${var.domain}"
  type    = "CNAME"
  ttl     = 300
  records = [var.domain]
}
