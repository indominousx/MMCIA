provider "aws" {
  region = var.aws_region
}

resource "aws_security_group" "packright_sg" {
  name        = "packright_sg"
  description = "Allow port 8000 for web and 22 for ssh"

  ingress {
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "packright_server" {
  ami           = var.ami_id
  instance_type = var.instance_type
  key_name      = var.key_name

  vpc_security_group_ids = [aws_security_group.packright_sg.id]

  tags = {
    Name = "PackRight-Inventory-Intelligence"
  }

  root_block_device {
    volume_size = 20
  }
}

output "public_ip" {
  value = aws_instance.packright_server.public_ip
}
