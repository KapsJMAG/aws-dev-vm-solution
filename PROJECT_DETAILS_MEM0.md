# AWS Dev VM Solution - Project Details

## Repository Information
- **Repository Name**: aws-dev-vm-solution
- **GitHub URL**: https://github.com/KapsJMAG/aws-dev-vm-solution
- **GitHub Username**: KapsJMAG
- **Email**: kapila.jayasinghe@magentus.com
- **Visibility**: Public
- **Branch**: main

## Project Overview
Complete AWS solution to replace on-premise VMware cluster + NAS storage with cloud-native AWS services.

### Key Features
- ✅ Auto-scheduled EC2 VMs (67% cost savings with 8-hour/day schedule)
- ✅ Persistent home directory using AWS EFS
- ✅ Shared RDS databases (Postgres + MySQL)
- ✅ Jira integration for one-click VM provisioning
- ✅ Per-client VM isolation
- ✅ Lambda-based automation for start/stop scheduling
- ✅ EventBridge for cron-based scheduling

### Monthly Cost Estimate
- 5x t3.xlarge EC2 (8hrs/day): $240
- EFS (100GB): $30
- RDS Postgres: $60
- RDS MySQL: $60
- Lambda/EventBridge: $1
- Data transfer: $5
- **Total: ~$396/month** (vs $5-10K/year on-prem)

## Files in Repository (9 total)

### Documentation (6 files)
1. **README.md** - Project overview, features, FAQ
2. **QUICK_SUMMARY.txt** - 5-minute visual guide with ASCII diagrams
3. **aws_dev_vm_solution.md** - Complete architecture (19 KB, 500+ lines)
4. **DEPLOYMENT_GUIDE.md** - Step-by-step AWS setup (15 KB, 450+ lines)
5. **INDEX.md** - Documentation roadmap and reading guide by role
6. **SETUP_AFTER_DOWNLOAD.md** - Post-download instructions

### Code (2 files)
1. **lambda_start_stop.py** - EventBridge Lambda for EC2 auto-start/stop
   - Reads EC2 tags (AutoStart, AutoStop, Timezone)
   - Respects timezone for start/stop times
   - Filters by Environment=dev tag
   - Logs to CloudWatch

2. **lambda_provision_from_jira.py** - Jira webhook Lambda for VM provisioning
   - Validates Jira webhook signature
   - Extracts custom fields from ticket
   - Launches EC2 with user data
   - Posts connection details back to Jira
   - Supports multiple OS types

### Configuration (1 file)
1. **.gitignore** - Protects secrets (AWS credentials, private keys, passwords)

## Architecture Components

### Phase 1: Infrastructure
- **VPC & Security Groups**: Network isolation
- **EFS**: Persistent home directories (/home mount)
- **RDS**: Shared Postgres + MySQL databases
- **Lambda Functions**: Automation logic
- **EventBridge**: Cron-based scheduling
- **EC2 Instances**: Per-dev VMs with tags

### Phase 2: Jira Integration
- **Jira Custom Fields**: Client, Developer, InstanceType, OS, Schedule
- **API Gateway**: Webhook receiver
- **Lambda**: Provisioning automation
- **Jira Workflow**: Open → In Progress → Ready → Provisioned → In Use

## Implementation Phases

### Phase 1: Infrastructure (Days 1-2, 2-3 hours)
- VPC, subnets, security groups
- EFS setup and testing
- RDS instances (Postgres + MySQL)
- Lambda functions deployment
- EventBridge rules configuration
- Manual VM provisioning testing

### Phase 2: Jira Integration (Days 3-4, 2-3 hours)
- Jira custom fields creation
- Jira workflow definition
- Provisioning Lambda deployment
- API Gateway webhook setup
- End-to-end testing

### Phase 3: Testing & Rollout (Week 2+, 1 week)
- All workflows testing
- Developer migration
- On-prem decommission

## Instance Tagging Strategy

Every EC2 instance includes tags:
```yaml
Name: dev-{ClientName}-{DeveloperName}
ClientName: ClientA/B/C/etc
DeveloperName: john-smith
Environment: dev
AutoStart: "08:00" (UTC)
AutoStop: "18:00" (UTC)
Timezone: US/Eastern (for local time conversion)
JiraTicket: INFRA-123
CreatedDate: 2024-11-11T...
OS: RHEL8/Ubuntu/etc
```

## Security Measures
- ✅ VPC isolation with private subnets
- ✅ Secrets Manager for credentials
- ✅ Security groups for firewall
- ✅ CloudTrail for audit logging
- ✅ RDS automated backups
- ✅ EFS encryption at rest
- ✅ IAM roles with least privilege
- ✅ No credentials in code/git

## How to Use This Repository

### Clone locally
```bash
git clone https://github.com/KapsJMAG/aws-dev-vm-solution.git
cd aws-dev-vm-solution
```

### Download as ZIP
Visit: https://github.com/KapsJMAG/aws-dev-vm-solution → Green "Code" button

### Make changes and push back
```bash
git add .
git commit -m "Your commit message"
git push origin main
```

### Update from GitHub
```bash
git pull origin main
```

## Quick Reference Commands

### Deploy a component
See: DEPLOYMENT_GUIDE.md for step-by-step AWS CLI commands

### Test Lambda functions
```bash
aws lambda invoke --function-name dev-vm-start-stop --payload '{"action":"start"}' /tmp/response.json
cat /tmp/response.json
```

### Check EC2 instances
```bash
aws ec2 describe-instances --filters "Name=tag:Environment,Values=dev"
```

### View logs
```bash
aws logs tail /aws/lambda/dev-vm-start-stop --follow
aws logs tail /aws/lambda/dev-vm-provision --follow
```

## Environment Details
- **Created**: 2024-11-11
- **Status**: Production-ready
- **Version**: 1.0
- **Python**: 3.11 (Lambda compatible)
- **Git**: Initialized with main branch
- **Configuration**: .gitignore protects secrets

## Future Enhancements
- [ ] Terraform templates for IaC
- [ ] GitHub Actions for CI/CD
- [ ] Monitoring with CloudWatch dashboards
- [ ] Cost optimization with Spot instances
- [ ] Multi-region deployment
- [ ] Backup automation
- [ ] Disaster recovery procedures

## Contact & Support
- **Created by**: AWS Solution Generator
- **For questions**: Check documentation files or README.md
- **Issue tracking**: Use GitHub Issues
- **Updates**: Push changes to main branch

---
**Last Updated**: 2024-11-11
**Repository Status**: ✅ Active and ready for deployment

---

## Future Phase: Azure AD Integration

### Overview
Plans to integrate Azure AD with AWS Landing Zone for:
- **Centralized identity management** through Azure AD (Azure Entra)
- **Automatic user sync** via IAM Identity Center
- **User-specific IAM roles** created per user for fine-grained access
- **Automated EC2 provisioning** based on Azure AD users and groups
- **Complete audit trail** via CloudTrail with user identity

### Key Components
1. **Azure AD ↔ AWS IAM Identity Center** (SAML 2.0 integration)
2. **User attributes mapping** (email, client, team, cost center)
3. **Permission Sets** for different roles (Developer, Admin)
4. **Enhanced Lambda** with Azure AD lookup
5. **Per-user IAM roles** for resource access control
6. **CloudTrail auditing** with user identity

### Workflow
```
Azure AD User Created
  ↓
Added to AWS-Dev-Team group
  ↓
IAM Identity Center syncs
  ↓
User gets Developer permission set
  ↓
Developer creates Jira ticket with email
  ↓
Lambda fetches user from Azure AD
  ↓
Creates user-specific IAM role
  ↓
Launches EC2 with user role
  ↓
User can SSH with automatic credentials
```

### Security Features
- MFA integration (Azure AD → AWS)
- Conditional access policies
- Per-user resource quotas
- Comprehensive CloudTrail auditing
- Least-privilege IAM policies

### Files Created
- `AZURE_AD_AWS_INTEGRATION.md` - Complete 5-phase integration guide (comprehensive implementation details)

---

