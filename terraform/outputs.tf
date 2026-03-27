output "instance_ip" {
  value = aws_eip.svetogled.public_ip
}

output "ssh_command" {
  value = "ssh -i ~/.ssh/id_ed25519 ec2-user@${aws_eip.svetogled.public_ip}"
}

output "url" {
  value = "https://${var.domain}"
}
