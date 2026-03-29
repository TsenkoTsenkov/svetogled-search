variable "aws_region" {
  default = "eu-central-1"
}

variable "domain" {
  default = "svetogled-arhiv.com"
}

variable "instance_type" {
  default = "t4g.small"
}

variable "ssh_public_key_path" {
  default = "~/.ssh/id_ed25519.pub"
}

variable "alert_email" {
  default = "tseni.tsenkov@gmail.com"
}

variable "deploy_public_key" {
  description = "Public key for GitHub Actions deploy (passphrase-free)"
  default     = ""
}
