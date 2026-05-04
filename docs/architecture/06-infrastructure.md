# Infrastructure Diagram

AWS infrastructure topology: VPC layout, EKS node groups, RDS placement, VPC Lattice service
network, and S3. Shows network boundaries and how components communicate across subnet tiers.

```mermaid
graph TB
    subgraph AWS["AWS ap-southeast-2"]
        subgraph VPC["VPC (10.0.0.0/16)"]
            subgraph PublicSubnets["Public Subnets (AZ-a, AZ-b, AZ-c)"]
                NAT[NAT Gateway]
                IGW[Internet Gateway]
            end

            subgraph PrivateSubnets["Private Subnets (AZ-a, AZ-b, AZ-c)"]
                subgraph EKS["EKS 1.35 Cluster"]
                    subgraph CPUNodePool["CPU NodePool (AL2023)\nm5.xlarge / m5.2xlarge — Spot+OD"]
                        RAGPod[RAG API Pods]
                        LiteLLMPod[LiteLLM Pods]
                        ObsPods[Prometheus / Grafana / OTEL]
                    end
                    subgraph GPUNodePool["GPU NodePool (Bottlerocket Accelerated)\ng5.xlarge — Spot with OD fallback"]
                        vLLMPod[vLLM Pods\nA10G GPU]
                    end
                    subgraph SystemPods["System Pods"]
                        Karpenter[Karpenter]
                        KEDA[KEDA]
                        GatewayCtrl[Gateway API Controller]
                    end
                end

                subgraph RDSSubnetGroup["RDS Subnet Group"]
                    RDS[(RDS PostgreSQL\npgvector\nMulti-AZ)]
                end
            end
        end

        subgraph ManagedServices["AWS Managed Services"]
            Bedrock[AWS Bedrock\nClaude 3.5 + Titan]
            S3[(Amazon S3\nDocuments + Weights)]
            ECR[Amazon ECR\nContainer Images]
            CW[CloudWatch\nX-Ray + Metrics]
            SSM[SSM Parameter Store\nSecrets]
        end

        VPCLattice[AWS VPC Lattice\nService Network]
    end

    Internet((Internet)) --> IGW
    IGW --> NAT
    NAT --> PrivateSubnets

    VPCLattice --> GatewayCtrl
    GatewayCtrl --> RAGPod

    RAGPod --> LiteLLMPod
    RAGPod --> RDS
    LiteLLMPod --> vLLMPod
    LiteLLMPod --> Bedrock
    RAGPod --> Bedrock
    vLLMPod --> S3
    RAGPod --> CW
    ECR --> EKS
    RAGPod --> SSM
```
