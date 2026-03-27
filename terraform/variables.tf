variable "aws_region" {
  default = "eu-central-1"
}

variable "domain" {
  default = "svetogled-arhiv.com"
}

variable "instance_type" {
  default = "t4g.micro"
}

variable "ssh_public_key_path" {
  default = "~/.ssh/id_ed25519.pub"
}

variable "alert_email" {
  default = "tseni.tsenkov@gmail.com"
}
