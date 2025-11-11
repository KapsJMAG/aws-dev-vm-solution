# AWS Dev VM Solution: Auto-Scaling with Persistent Storage & Jira Integration

## Phase 1: Core Infrastructure

### Architecture Overview
```
┌─────────────────────────────────────────────────────────┐
│                        VPC                              │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │  Dev VM 1    │  │  Dev VM 2    │  │  Dev VM N    │  │
│  │  (Client A)  │  │  (Client B)  │  │  (Client X)  │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
│         │                 │                 │           │
│         └─────────────────┼─────────────────┘           │
│                           │                             │
│         ┌─────────────────┴──────────────────┐          │
│         │                                    │          │
│    ┌────▼─────┐  ┌──────────────┐  ┌───────▼─────┐    │
│    │  EFS     │  │ Shared RDS   │  │  Lambda     │    │
│    │  (Home)  │  │ (Postgres/   │  │  (Scheduler)│    │
│    │          │  │   MySQL)     │  │             │    │
│    └──────────┘  └──────────────┘  └─────────────┘    │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 1. Storage Solution: EFS for Home Partitions

**Why EFS?**
- NFS-like persistent storage (replaces on-prem NAS)
- Auto-scales with demand
- Each dev's `/home/username` persists across VM shutdowns
- Multiple EC2s can mount same EFS

**Setup:**
```bash
# Create EFS
aws efs create-file-system \
  --performance-mode generalPurpose \
  --throughput-mode bursting \
  --tags Key=Environment,Value=dev Key=Purpose,Value=home-dirs

# Mount in EC2:
# /etc/fstab entry:
# fs-xxxxx:/ /home nfs4 defaults,_netdev 0 0
```

**Cost:** ~$0.30/GB-month (bursting) - minimal for dev use

---

### 2. Database: Shared RDS (Postgres + MySQL)

**Setup:**
```yaml
RDS-Postgres:
  Instance: db.t4g.small (2 vCPU, 2GB RAM)
  Storage: 100GB gp3
  Multi-AZ: false (dev environment)
  Backups: 7 days
  Cost: ~$60/month

RDS-MySQL:
  Instance: db.t4g.small
  Storage: 100GB gp3
  Cost: ~$60/month
```

**Connection String (stored in Secrets Manager):**
```
postgres://shared-db.xxxxx.rds.amazonaws.com:5432/dev_db
mysql://shared-db.xxxxx.rds.amazonaws.com:3306/dev_db
```

**Access Control:**
- Create dev-specific database users
- Grant per-client schema access via RDS policies
- Environment variables in EC2 user data

---

### 3. EC2 Auto-Start/Stop via Lambda + EventBridge

**Architecture:**
```
┌─────────────────────────────────────────┐
│  Developer Action / Scheduled Event     │
└────────────┬────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────┐
│  EventBridge Rule (Cron / Pattern)      │
│  Triggers Lambda on schedule            │
└────────────┬────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────┐
│  Lambda Function (Start/Stop Logic)     │
│  - Read tags (ClientName, Developer)    │
│  - Filter EC2 instances                 │
│  - Start/Stop based on schedule         │
└────────────┬────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────┐
│  EC2 Start/Stop Command                 │
│  Instance state change                  │
└─────────────────────────────────────────┘
```

**Tagging Strategy:**
```yaml
Instance Tags:
  Name: dev-{ClientName}-{DeveloperName}
  ClientName: ClientA
  DeveloperName: john-smith
  Environment: dev
  AutoStart: "08:00"      # UTC time
  AutoStop: "18:00"       # UTC time
  Timezone: US/Eastern    # For local time conversion
  CostCenter: Dev-Team
```

**Lambda Function (Python):**
```python
import boto3
import os
from datetime import datetime
import pytz

ec2 = boto3.client('ec2')

def lambda_handler(event, context):
    action = event.get('action', 'start')  # 'start' or 'stop'
    
    # Get all dev instances
    response = ec2.describe_instances(
        Filters=[
            {'Name': 'tag:Environment', 'Values': ['dev']},
            {'Name': 'instance-state-name', 'Values': ['running', 'stopped']}
        ]
    )
    
    for reservation in response['Reservations']:
        for instance in reservation['Instances']:
            instance_id = instance['InstanceId']
            tags = {tag['Key']: tag['Value'] for tag in instance['Tags']}
            
            # Check if instance should be actioned based on time
            timezone = pytz.timezone(tags.get('Timezone', 'UTC'))
            current_time = datetime.now(timezone).strftime("%H:%M")
            
            if action == 'start' and current_time >= tags.get('AutoStart', '08:00'):
                if instance['State']['Name'] == 'stopped':
                    print(f"Starting {instance_id}")
                    ec2.start_instances(InstanceIds=[instance_id])
                    
            elif action == 'stop' and current_time >= tags.get('AutoStop', '18:00'):
                if instance['State']['Name'] == 'running':
                    print(f"Stopping {instance_id}")
                    ec2.stop_instances(InstanceIds=[instance_id])
    
    return {'statusCode': 200, 'message': 'Done'}
```

**EventBridge Rules:**
```yaml
StartDevVMs:
  Schedule: cron(0 8 ? * MON-FRI *)  # 8 AM UTC, weekdays
  Payload: {"action": "start"}

StopDevVMs:
  Schedule: cron(0 18 ? * MON-FRI *)  # 6 PM UTC, weekdays
  Payload: {"action": "stop"}
```

**Cost Savings:**
- 8 hours running = 67% reduction vs. 24/7
- t3.xlarge: $145/month → ~$48/month per instance

---

### 4. EC2 User Data (at Launch)

```bash
#!/bin/bash
set -e

# Install EFS utilities
sudo yum install -y efs-utils

# Mount EFS for home directories
sudo mkdir -p /home
sudo mount -t efs -o tls fs-xxxxx:/ /home

# Update fstab for persistent mount
echo "fs-xxxxx:/ /home nfs4 defaults,_netdev 0 0" | sudo tee -a /etc/fstab

# Install database clients
sudo yum install -y postgresql mysql

# Inject RDS credentials via Secrets Manager
aws secretsmanager get-secret-value --secret-id dev/rds/postgres \
  --query SecretString --output text | jq -r . > /home/rds-creds.json

# Install Docker, dev tools, etc.
sudo yum install -y docker git nodejs
sudo usermod -aG docker ec2-user

echo "Dev VM initialized for client: ${CLIENT_NAME}"
```

---

## Phase 2: Jira Integration for Automated Provisioning

### High-Level Flow:
```
┌────────────────────────────────────────────────────┐
│  Developer Creates Jira Ticket:                    │
│  - Issue Type: "Provision Dev VM"                  │
│  - Custom Fields:                                  │
│    * Client: (dropdown)                            │
│    * Developer: (text)                             │
│    * Instance Type: t3.xlarge / m5.xlarge / etc.   │
│    * OS: RHEL8 / Ubuntu / Amazon Linux             │
│    * Startup Time: 08:00                           │
│    * Shutdown Time: 18:00                          │
└─────────────────┬──────────────────────────────────┘
                  │
                  ▼
┌────────────────────────────────────────────────────┐
│  Jira Webhook → Lambda                             │
│  (on issue transition to "Ready")                  │
└─────────────────┬──────────────────────────────────┘
                  │
                  ▼
┌────────────────────────────────────────────────────┐
│  Lambda Function:                                  │
│  1. Validate request (JWT signature)               │
│  2. Parse Jira custom fields                       │
│  3. Launch EC2 from AMI                            │
│  4. Apply tags                                     │
│  5. Mount EFS, configure RDS access                │
│  6. Post comment to Jira with connection details   │
└─────────────────┬──────────────────────────────────┘
                  │
                  ▼
┌────────────────────────────────────────────────────┐
│  Jira Comment:                                     │
│  "VM provisioned!"                                 │
│  - Public IP: 1.2.3.4                              │
│  - SSH: ssh -i key.pem ec2-user@1.2.3.4            │
│  - Postgres: postgres://shared-db:5432/clienta_db  │
│  - Status: Ready for development                   │
└────────────────────────────────────────────────────┘
```

### Implementation Steps:

#### Step 1: Jira Project Setup

**Create Custom Fields:**
```
- Client (dropdown, linked to projects)
- DeveloperName (text)
- InstanceType (dropdown: t3.xlarge, m5.xlarge, etc.)
- OperatingSystem (dropdown: RHEL8, Ubuntu20.04)
- AutoStartTime (text: "08:00")
- AutoStopTime (text: "18:00")
- AMIId (text, read-only - populated by automation)
```

**Create Workflow:**
```
Open → In Progress → Ready → Provisioned → In Use
                       ↓ (webhook trigger here)
                    Lambda executes
```

#### Step 2: Webhook + Lambda Integration

**Jira Webhook Config:**
```
URL: https://lambda-url.execute-api.us-east-1.amazonaws.com/prod/provision
Events: Issue Transitioned
Conditions: Status = Ready
Authentication: Basic + API Token OR Signature verification
```

**Lambda Handler (Python):**
```python
import json
import boto3
import hmac
import hashlib
import os
from datetime import datetime

ec2 = boto3.client('ec2')
jira_client = boto3.client('secretsmanager')

def verify_jira_signature(request_body, signature_header):
    """Verify webhook came from Jira"""
    webhook_secret = os.environ['JIRA_WEBHOOK_SECRET']
    expected_sig = hmac.new(
        webhook_secret.encode(),
        request_body.encode(),
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(signature_header, expected_sig)

def lambda_handler(event, context):
    try:
        # Verify signature
        body = event['body']
        signature = event['headers'].get('X-Atlassian-Webhook-Signature')
        
        if not verify_jira_signature(body, signature):
            return {'statusCode': 401, 'body': 'Unauthorized'}
        
        webhook_data = json.loads(body)
        issue = webhook_data['issue']
        fields = issue['fields']
        
        # Extract custom fields
        client_name = fields['customfield_10001']  # Client
        dev_name = fields['customfield_10002']      # DeveloperName
        instance_type = fields['customfield_10003']  # InstanceType
        os_type = fields['customfield_10004']        # OS
        auto_start = fields['customfield_10005']     # AutoStartTime
        auto_stop = fields['customfield_10006']      # AutoStopTime
        
        # Get AMI ID based on OS
        ami_map = {
            'RHEL8': 'ami-0c55b159cbfafe1f0',
            'Ubuntu20.04': 'ami-0dd273d94ed0540c0',
            'AmazonLinux2': 'ami-0c55b159cbfafe1f0'
        }
        ami_id = ami_map.get(os_type, ami_map['AmazonLinux2'])
        
        # Launch EC2
        response = ec2.run_instances(
            ImageId=ami_id,
            InstanceType=instance_type,
            MinCount=1,
            MaxCount=1,
            SecurityGroupIds=['sg-dev-xxxx'],
            SubnetId='subnet-dev-xxxx',
            UserData=generate_user_data(client_name, dev_name),
            TagSpecifications=[{
                'ResourceType': 'instance',
                'Tags': [
                    {'Key': 'Name', 'Value': f"dev-{client_name}-{dev_name}"},
                    {'Key': 'ClientName', 'Value': client_name},
                    {'Key': 'DeveloperName', 'Value': dev_name},
                    {'Key': 'Environment', 'Value': 'dev'},
                    {'Key': 'AutoStart', 'Value': auto_start},
                    {'Key': 'AutoStop', 'Value': auto_stop},
                    {'Key': 'JiraTicket', 'Value': issue['key']},
                    {'Key': 'CreatedDate', 'Value': datetime.now().isoformat()},
                ]
            }]
        )
        
        instance_id = response['Instances'][0]['InstanceId']
        
        # Wait for instance to get public IP
        waiter = ec2.get_waiter('instance_running')
        waiter.wait(InstanceIds=[instance_id])
        
        instance_info = ec2.describe_instances(InstanceIds=[instance_id])
        public_ip = instance_info['Reservations'][0]['Instances'][0]['PublicIpAddress']
        
        # Post comment to Jira
        jira_comment = f"""
VM Provisioned Successfully!

*Instance Details:*
- Instance ID: {instance_id}
- Public IP: {public_ip}
- Instance Type: {instance_type}
- SSH Command: {{ssh -i dev-key.pem ec2-user@{public_ip}}}

*Database Connection:*
- PostgreSQL: postgres://shared-db.xxxxx.rds.amazonaws.com:5432/{client_name.lower()}_db
- MySQL: mysql://shared-db.xxxxx.rds.amazonaws.com:3306/{client_name.lower()}_db

*Home Directory:*
- Mounted at /home (EFS)
- Persists across VM stop/start

*Auto Schedule:*
- Starts: {auto_start} UTC
- Stops: {auto_stop} UTC

Status: Ready for Development 🚀
"""
        
        post_jira_comment(issue['key'], jira_comment)
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'VM provisioned',
                'instance_id': instance_id,
                'public_ip': public_ip
            })
        }
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return {'statusCode': 500, 'body': json.dumps({'error': str(e)})}

def generate_user_data(client_name, dev_name):
    return f"""#!/bin/bash
# User data script
echo "Provisioning dev VM for {client_name} - {dev_name}"
# (same as Phase 1 user data above)
"""

def post_jira_comment(issue_key, comment_text):
    """Post comment to Jira issue"""
    jira_url = os.environ['JIRA_URL']
    auth = (os.environ['JIRA_USER'], os.environ['JIRA_API_TOKEN'])
    
    url = f"{jira_url}/rest/api/3/issue/{issue_key}/comments"
    payload = {
        "body": {
            "version": 1,
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": comment_text}]
                }
            ]
        }
    }
    
    import requests
    requests.post(url, json=payload, auth=auth)
```

#### Step 3: Teardown Automation

**Optional Workflow:**
- Issue Transition to "Closed" → Lambda stops instance
- After 30 days idle → Lambda terminates instance
- Add "TerminateVM" custom workflow

---

## Cost Estimation (Monthly)

| Component | Count | Cost |
|-----------|-------|------|
| **EC2 t3.xlarge (running 8hrs/day)** | 5 VMs | ~$240 |
| **EFS (100GB)** | 1 | ~$30 |
| **RDS Postgres (small)** | 1 | ~$60 |
| **RDS MySQL (small)** | 1 | ~$60 |
| **Lambda invocations** | ~4,000/month | ~$1 |
| **Data transfer** | ~10GB | ~$5 |
| **Total** | | **~$396/month** |

*vs. VMware: eliminate capital, maintenance, licensing (~$5-10K/year)*

---

## Security Best Practices

1. **Secrets Management:**
   - RDS credentials in AWS Secrets Manager
   - SSH keys in Systems Manager Parameter Store
   - Jira API tokens in Secrets Manager

2. **VPC Isolation:**
   - Dev VMs in private subnets (NAT Gateway for outbound)
   - Security group limited to dev team IPs (or SSM Session Manager)
   - RDS accessible only from dev VMs

3. **IAM Permissions:**
   - Lambda execution role: EC2 (run/start/stop), Secrets Manager (read)
   - Developers: EC2 describe-only (no launch/terminate)
   - CloudTrail logging for audit

4. **Network:**
   - Bastion host OR Systems Manager Session Manager for SSH
   - Consider Client VPN for remote developers

---

## Implementation Checklist

### Phase 1 (Weeks 1-2):
- [ ] Create VPC, subnets, security groups
- [ ] Launch EFS, test NFS mount
- [ ] Create RDS Postgres + MySQL instances
- [ ] Build EC2 AMI with tools installed
- [ ] Create Lambda start/stop functions
- [ ] Set up EventBridge cron rules
- [ ] Test manual VM provisioning

### Phase 2 (Weeks 3-4):
- [ ] Set up Jira custom fields
- [ ] Create Jira project workflow
- [ ] Build Lambda webhook handler
- [ ] Test end-to-end Jira → VM provisioning
- [ ] Document for dev team
- [ ] Add teardown automation

---

## References & Next Steps

- AWS EC2 User Data: https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/user-data.html
- EFS Mount Instructions: https://docs.aws.amazon.com/efs/latest/ug/mounting-fs.html
- Jira Webhooks: https://developer.atlassian.com/cloud/jira/platform/webhooks/
- AWS Lambda: https://docs.aws.amazon.com/lambda/latest/dg/getting-started.html

