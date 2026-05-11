output "aws_gateway_api_controller" {
  description = "AWS Gateway API Controller Helm release attributes"
  value       = module.addons.aws_gateway_api_controller
}

output "kube_prometheus_stack" {
  description = "kube-prometheus-stack Helm release attributes"
  value       = module.addons.kube_prometheus_stack
}

output "metrics_server" {
  description = "metrics-server Helm release attributes"
  value       = module.addons.metrics_server
}

output "adot_addon_version" {
  description = "Deployed ADOT add-on version"
  value       = aws_eks_addon.adot.addon_version
}
