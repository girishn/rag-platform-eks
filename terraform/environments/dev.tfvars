aws_region  = "ap-southeast-2"
name_prefix = "rag-platform"
env         = "dev"
state_bucket = "rag-platform-tf-state-603974305345"

tags = {
  Project     = "rag-platform-eks"
  ManagedBy   = "terraform"
  Environment = "dev"
}
