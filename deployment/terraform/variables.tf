variable "aws_region" {
  default = "us-east-1"
}

variable "instance_type" {
  default = "t3.micro"
}

variable "ami_id" {
  description = "Ubuntu 22.04 AMI ID for the region"
  default     = "ami-0a936bb624678fd88" # Latest Ubuntu 22.04 LTS for ap-south-1
}

variable "key_name" {
  description = "AWS Key Pair"
  default     = "PackRight-keypair"
}
