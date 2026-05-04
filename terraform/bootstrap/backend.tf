# Bootstrap module uses local state — it creates the remote state backend.
# All other modules use the S3 backend created here.
terraform {
  backend "local" {}
}
