# AWS Dev VM Solution - Complete Package

## 📋 What You Have

This solution replaces your on-prem VMware cluster + NAS with a fully automated AWS-based dev environment.

### Files in Your Home Directory

1. **aws_dev_vm_solution.md** - Comprehensive architecture & design document
2. **lambda_start_stop.py** - Lambda function for auto-start/stop via EventBridge
3. **lambda_provision_from_jira.py** - Lambda function for Jira-triggered provisioning
4. **DEPLOYMENT_GUIDE.md** - Step-by-step deployment instructions

## ✨ Key Features

✅ **Persistent Home Storage** - EFS replaces NAS (survives VM stop/start)
✅ **Shared Databases** - RDS Postgres + MySQL for multi-dev access
✅ **Auto-Scheduling** - VMs start/stop automatically via EventBridge + Lambda
✅ **Jira Integration** - Create Jira ticket → Auto-provision VM
✅ **Cost Optimized** - ~67% cost reduction vs 24/7 running
✅ **Per-Client Isolation** - Each dev works on specific client, persistent environment

---

## 🚀 Quick Start (Choose Your Path)

### Option A: Manual Deployment (Full Control)
→ Follow **DEPLOYMENT_GUIDE.md** step-by-step (~4 hours)

### Option B: Terraform (Infrastructure as Code)
```bash
# (Coming soon - create from the Lambda functions provided)
```

---

## 💰 Monthly Cost Estimate

| Component | Cost |
|-----------|------|
| 5x t3.xlarge EC2 (8hrs/day) | $240 |
| EFS (100GB) | $30 |
| RDS Postgres | $60 |
| RDS MySQL | $60 |
| Lambda/EventBridge | $1 |
| Data transfer | $5 |
| **TOTAL** | **~$396/month** |

**vs On-Prem:** Eliminates $5-10K/year in capital + maintenance + licensing

---

## 🏗️ Architecture

```
Developer Creates Jira Ticket
  ↓
Jira Webhook Triggers Lambda
  ↓
Lambda Launches EC2 Instance
  ↓
EC2 Mounts EFS (home) + Gets RDS Credentials
  ↓
Jira Ticket Updated with Connection Details
  ↓
Developer SSH's In & Works
  ↓
EventBridge Auto-Stops at End of Day
```

---

## 🔑 Key Components

### 1. **EFS (Elastic File System)**
- NFS-based persistent storage
- Replaces on-prem NAS
- Home directories persist across VM stop/start
- Multi-client access with shared storage

### 2. **RDS (Relational Database Service)**
- Shared Postgres + MySQL instances
- Per-client databases/schemas
- Automated backups
- Managed failover

### 3. **Lambda Functions** (2x)
- `dev-vm-start-stop`: Reads tags, starts/stops instances
- `dev-vm-provision`: Handles Jira webhooks, launches EC2

### 4. **EventBridge Rules** (2x)
- Morning rule: Starts all dev VMs at 08:00 UTC (weekdays)
- Evening rule: Stops all dev VMs at 18:00 UTC (weekdays)
- Configurable per-instance with tags

### 5. **EC2 Instances**
- Base AMI with Docker, git, dev tools pre-installed
- Auto-mount EFS at `/home`
- Systems Manager Session Manager for SSH access
- IAM role for accessing RDS, EFS, Secrets Manager

---

## 📊 Tag Strategy

Every EC2 instance gets these tags:

```yaml
Name: dev-ClientA-john-smith
ClientName: ClientA
DeveloperName: john-smith
Environment: dev
AutoStart: "08:00"          # UTC time
AutoStop: "18:00"           # UTC time
Timezone: US/Eastern        # For local time conversion
JiraTicket: INFRA-123
OS: RHEL8
CreatedDate: 2024-01-15T10:30:00
```

→ Lambda reads these to determine start/stop actions

---

## 🔐 Security Model

- **VPC Isolation**: Dev VMs in private subnet + NAT Gateway
- **SSH Access**: Systems Manager Session Manager (no bastion)
- **Database Access**: Security group limited to dev VMs only
- **Secrets**: API tokens in AWS Secrets Manager
- **Audit**: CloudTrail logs all resource creation

---

## 🔄 Workflows

### Workflow 1: Daily Start/Stop
```
08:00 UTC: EventBridge triggers start Lambda
  → All instances with Environment=dev tag start
  
18:00 UTC: EventBridge triggers stop Lambda
  → All instances with Environment=dev tag stop
```

### Workflow 2: Provision via Jira
```
1. Dev creates Jira ticket "Provision Dev VM"
2. Fills in: Client, Name, Instance Type, OS, Schedule
3. Transitions to "Ready"
4. Jira webhook → Lambda
5. Lambda launches EC2 with user data
6. Instance mounts EFS, gets RDS credentials
7. Jira ticket updated with SSH command
8. Dev connects via SSH
```

---

## 📝 Next Steps

### Phase 1: Infrastructure (1 day)
- [ ] Review architecture in `aws_dev_vm_solution.md`
- [ ] Create AWS VPC, subnets, security groups
- [ ] Launch EFS + RDS
- [ ] Deploy Lambda functions
- [ ] Set up EventBridge rules
- [ ] Test start/stop automation

### Phase 2: Jira Integration (1 day)
- [ ] Create Jira custom fields
- [ ] Deploy provisioning Lambda
- [ ] Create API Gateway webhook
- [ ] Configure Jira webhook
- [ ] End-to-end testing

### Phase 3: Rollout (1 week)
- [ ] Migrate first dev to new system
- [ ] Collect feedback
- [ ] Adjust schedules/sizing
- [ ] Migrate remaining devs
- [ ] Decommission on-prem VMs

---

## ❓ FAQ

**Q: Will my home directory persist if I stop the VM?**
A: Yes! EFS is persistent. Even when EC2 stops, `/home` data survives. When instance starts again, EFS re-mounts automatically.

**Q: Can multiple devs access the same databases?**
A: Yes. RDS is shared. Each dev gets separate database user with schema-level access. So Dev A can't see Dev B's data unless you explicitly grant it.

**Q: What if I need my VM running 24/7?**
A: Set `AutoStop: "23:59"` tag to stop late at night. Or set both to "00:00" for 24/7 operation.

**Q: How much faster is auto-stop to manual?**
A: Lambda takes ~30 seconds to stop all VMs. Manual stopping could take hours if you forget.

**Q: Can I use different OSes?**
A: Yes. Lambda supports RHEL8, RHEL9, Ubuntu 20.04, Ubuntu 22.04. Set via Jira field.

**Q: What about backups?**
A: EFS has automatic snapshots (via AWS Backup - not included here). RDS has 7-day retention built-in.

---

## 🛠️ Customization Options

### Use Spot Instances (Save 70%)
```python
# In lambda_provision_from_jira.py, add:
SpotOptions={'MaxPrice': '0.50'}
```

### Different Auto-Schedule Per Person
```yaml
# Tag format (in Jira):
AutoStart: "09:00"
AutoStop: "17:00"
Timezone: "US/Pacific"
```

### Private EC2 (No Public IP)
```bash
# In deployment: Don't assign public IPs
# Use Systems Manager Session Manager for access instead
```

### Database Encryption
```bash
# RDS: Enable encryption at rest + in transit
# EFS: Already encrypted by default
```

---

## 📞 Support

### Troubleshooting Steps
1. Check CloudWatch logs: `aws logs tail /aws/lambda/dev-vm-provision --follow`
2. Check EC2 instance logs: `cat /var/log/cloud-init-output.log`
3. Verify security groups allow required ports
4. Check IAM permissions on roles

### Common Issues
- **EFS mount failing**: Security group doesn't allow NFS (port 2049)
- **RDS connection failing**: RDS security group doesn't allow EC2 access
- **Jira webhook not firing**: API Gateway URL not reachable from Jira

---

## 📄 License & Support

This solution uses AWS managed services. See AWS Documentation:
- EC2: https://docs.aws.amazon.com/ec2/
- EFS: https://docs.aws.amazon.com/efs/
- RDS: https://docs.aws.amazon.com/rds/
- Lambda: https://docs.aws.amazon.com/lambda/

---

## 🎯 Success Criteria

✅ Phase 1 Complete:
- [ ] Dev VMs launching manually works
- [ ] EFS mounts and persists across stop/start
- [ ] RDS accessible from EC2
- [ ] Lambda start/stop functions work
- [ ] EventBridge rules firing on schedule

✅ Phase 2 Complete:
- [ ] Jira ticket creation triggers EC2 launch
- [ ] Jira comment with connection details auto-posted
- [ ] Dev can SSH in and work
- [ ] Home directory persists

✅ Rollout Complete:
- [ ] All devs migrated
- [ ] VMs stopping on schedule = cost savings
- [ ] Zero on-prem infrastructure for dev

---

## 🚀 Let's Go!

1. Read: `aws_dev_vm_solution.md` (20 min)
2. Deploy: Follow `DEPLOYMENT_GUIDE.md` (4 hours)
3. Test: Create Jira ticket, verify workflow
4. Scale: Repeat for all developers

Good luck! 🎉

