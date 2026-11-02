terraform {
  # Supply bucket and prefix with -backend-config during a reviewed init.
  # The bucket is created by infra/gcp/bootstrap, not by this stack.
  backend "gcs" {}
}
