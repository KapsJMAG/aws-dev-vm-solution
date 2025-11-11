# AWS Dev VM Solution - Deployment Guide

## Quick Start: Deploy in 1 Day

### Prerequisites
- AWS Account with appropriate IAM permissions
- Jira Cloud or Server instance
- VPC already created (or create new one)

---

## Phase 1: Core Infrastructure (2-3 hours)

### Step 1: Create VPC and Security Groups

```bash
# Create VPC (skip if you already have one)
aws ec2 create-vpc --cidr-block 10.0.0.0/16 --tag-specifications 'ResourceType=vpc,Tags=[{Key=Name,Value=dev-vpc}]'

# Create security group
aws ec2 create-security-group \
  --group-name dev-sg \
  --description "Security group for dev VMs" \
  --vpc-id vpc-xxxxx

# Allow SSH from your IP (replace YOUR_IP)
aws ec2 authorize-security-group-ingress \
  --group-id sg-xxxxx \
  --protocol tcp \
  --port 22 \
  --cidr YOUR_IP/32

# Allow NFS (EFS access)
aws ec2 authorize-security-group-ingress \
  --group-id sg-xxxxx \
  --protocol tcp \
  --port 2049 \
  --source-security-group-id sg-xxxxx
```

### Step 2: Create EFS (Persistent Home Storage)

```bash
# Create EFS
EFS_ID=$(aws efs create-file-system \
  --performance-mode generalPurpose \
  --throughput-mode bursting \
  --encrypted \
  --tags Key=Name,Value=dev-home-dirs Key=Environment,Value=dev \
  --query 'FileSystemId' --output text)

echo "EFS ID: $EFS_ID"

# Create mount targets (one per AZ in your VPC)
aws efs create-mount-target \
  --file-system-id $EFS_ID \
  --subnet-id subnet-xxxxx \
  --security-groups sg-xxxxx
```

### Step 3: Create RDS Databases

```bash
# Create Postgres RDS
aws rds create-db-instance \
  --db-instance-identifier dev-postgres \
  --db-instance-class db.t4g.small \
  --engine postgres \
  --master-username admin \
  --master-user-password MySecurePassword123! \
  --allocated-storage 100 \
  --storage-type gp3 \
  --vpc-security-group-ids sg-xxxxx \
  --db-subnet-group-name default \
  --backup-retention-period 7 \
  --multi-az false \
  --tags Key=Environment,Value=dev

# Create MySQL RDS
aws rds create-db-instance \
  --db-instance-identifier dev-mysql \
  --db-instance-class db.t4g.small \
  --engine mysql \
  --master-username admin \
  --master-user-password MySecurePassword123! \
  --allocated-storage 100 \
  --storage-type gp3 \
  --vpc-security-group-ids sg-xxxxx \
  --backup-retention-period 7 \
  --multi-az false \
  --tags Key=Environment,Value=dev

# Wait for instances to be available (~10 minutes)
aws rds describe-db-instances --db-instance-identifier dev-postgres --query 'DBInstances[0].DBInstanceStatus'
```

### Step 4: Create IAM Role for EC2

```bash
# Create IAM role
aws iam create-role \
  --role-name ec2-dev-role \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "ec2.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }'

# Attach policies
aws iam attach-role-policy \
  --role-name ec2-dev-role \
  --policy-arn arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy

aws iam attach-role-policy \
  --role-name ec2-dev-role \
  --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore

# Attach inline policy for EFS and RDS access
aws iam put-role-policy \
  --role-name ec2-dev-role \
  --policy-name dev-resources-policy \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": ["elasticfilesystem:DescribeFileSystems", "elasticfilesystem:DescribeMountTargets"],
        "Resource": "*"
      },
      {
        "Effect": "Allow",
        "Action": ["secretsmanager:GetSecretValue"],
        "Resource": "arn:aws:secretsmanager:*:*:secret:dev/*"
      }
    ]
  }'

# Create instance profile
aws iam create-instance-profile --instance-profile-name ec2-dev-profile
aws iam add-role-to-instance-profile \
  --instance-profile-name ec2-dev-profile \
  --role-name ec2-dev-role
```

### Step 5: Create Lambda Functions

#### Deploy Start/Stop Lambda

```bash
cd /tmp
cat > lambda_function.py << 'LAMBDA_EOF'
# Copy content from ~/lambda_start_stop.py
LAMBDA_EOF

zip lambda_start_stop.zip lambda_function.py

# Create Lambda function
aws lambda create-function \
  --function-name dev-vm-start-stop \
  --runtime python3.11 \
  --role arn:aws:iam::ACCOUNT_ID:role/lambda-ec2-execution-role \
  --handler lambda_function.lambda_handler \
  --zip-file fileb://lambda_start_stop.zip \
  --environment Variables="{AWS_REGION=us-east-1}" \
  --timeout 60

# Give Lambda EC2 permissions
aws iam put-role-policy \
  --role-name lambda-ec2-execution-role \
  --policy-name lambda-ec2-policy \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": ["ec2:DescribeInstances", "ec2:StartInstances", "ec2:StopInstances"],
      "Resource": "*"
    }]
  }'
```

#### Set up EventBridge Rules

```bash
# Start rule (8 AM UTC, weekdays)
aws events put-rule \
  --name dev-vm-start-rule \
  --schedule-expression "cron(0 8 ? * MON-FRI *)" \
  --state ENABLED

aws events put-targets \
  --rule dev-vm-start-rule \
  --targets "Id"="1","Arn"="arn:aws:lambda:us-east-1:ACCOUNT_ID:function:dev-vm-start-stop","RoleArn"="arn:aws:iam::ACCOUNT_ID:role/eventbridge-lambda-role","Input"='{"action":"start"}'

# Stop rule (6 PM UTC, weekdays)
aws events put-rule \
  --name dev-vm-stop-rule \
  --schedule-expression "cron(0 18 ? * MON-FRI *)" \
  --state ENABLED

aws events put-targets \
  --rule dev-vm-stop-rule \
  --targets "Id"="1","Arn"="arn:aws:lambda:us-east-1:ACCOUNT_ID:function:dev-vm-start-stop","RoleArn"="arn:aws:iam::ACCOUNT_ID:role/eventbridge-lambda-role","Input"='{"action":"stop"}'

# Give EventBridge permission to invoke Lambda
aws lambda add-permission \
  --function-name dev-vm-start-stop \
  --statement-id AllowEventBridgeInvoke \
  --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn arn:aws:events:us-east-1:ACCOUNT_ID:rule/dev-vm-*-rule
```

### Step 6: Create EC2 AMI (Base Image)

```bash
# Launch temporary instance
INSTANCE_ID=$(aws ec2 run-instances \
  --image-id ami-0c55b159cbfafe1f0 \
  --instance-type t3.xlarge \
  --key-name your-key \
  --security-group-ids sg-xxxxx \
  --iam-instance-profile Name=ec2-dev-profile \
  --query 'Instances[0].InstanceId' --output text)

# Wait for instance to run
aws ec2 wait instance-running --instance-ids $INSTANCE_ID

# SSH in and run setup:
# ssh -i your-key.pem ec2-user@<public-ip>

# On the instance:
sudo yum update -y
sudo yum install -y efs-utils docker git nodejs python3 postgresql mysql jq
sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -aG docker ec2-user

# Create AMI from instance
AMI_ID=$(aws ec2 create-image \
  --instance-id $INSTANCE_ID \
  --name dev-base-ami \
  --description "Base AMI for dev VMs with Docker, git, databases" \
  --query 'ImageId' --output text)

echo "AMI ID: $AMI_ID"

# Terminate temporary instance
aws ec2 terminate-instances --instance-ids $INSTANCE_ID
```

---

## Phase 2: Jira Integration (2-3 hours)

### Step 1: Create Jira Custom Fields

1. Go to **Jira Admin** → **Custom Fields**
2. Create these fields:
   - `Client` (Single Select): Values = your client names
   - `DeveloperName` (Text): Free text field
   - `InstanceType` (Single Select): Values = t3.large, t3.xlarge, m5.xlarge
   - `OperatingSystem` (Single Select): Values = RHEL8, RHEL9, Ubuntu20.04, Ubuntu22.04
   - `AutoStartTime` (Text): e.g., "08:00"
   - `AutoStopTime` (Text): e.g., "18:00"
   - `Timezone` (Single Select): Values = UTC, US/Eastern, US/Central, etc.

3. Create Issue Type: **"Provision Dev VM"**
4. Add custom fields to this issue type

### Step 2: Create Workflow

1. **Jira Admin** → **Workflows**
2. Create workflow: `Dev VM Provisioning`
3. Statuses: `Open` → `In Progress` → `Ready` → `Provisioned` → `In Use`
4. Add transition condition to "Ready": **Only when all custom fields are filled**

### Step 3: Deploy Provisioning Lambda

```bash
# First, store Jira credentials in Secrets Manager
aws secretsmanager create-secret \
  --name jira/dev-provisioning \
  --secret-string '{
    "jira_url": "https://your-company.atlassian.net",
    "jira_user": "automation@your-company.com",
    "jira_api_token": "YOUR_API_TOKEN_HERE",
    "webhook_secret": "YOUR_WEBHOOK_SECRET_HERE"
  }'

# Upload Lambda function
cd /tmp
cp ~/lambda_provision_from_jira.py lambda_function.py

# Add requirements
cat > requirements.txt << 'REQ_EOF'
boto3
requests
pytz
REQ_EOF

pip install -r requirements.txt -t .
zip -r lambda_provision_vm.zip .

# Create Lambda execution role
aws iam create-role \
  --role-name lambda-provision-role \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "lambda.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }'

# Attach policies
aws iam attach-role-policy \
  --role-name lambda-provision-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

aws iam put-role-policy \
  --role-name lambda-provision-role \
  --policy-name provision-policy \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": ["ec2:RunInstances", "ec2:CreateTags", "ec2:DescribeInstances"],
        "Resource": "*"
      },
      {
        "Effect": "Allow",
        "Action": ["secretsmanager:GetSecretValue"],
        "Resource": "arn:aws:secretsmanager:*:*:secret:jira/*"
      },
      {
        "Effect": "Allow",
        "Action": ["iam:PassRole"],
        "Resource": "arn:aws:iam::ACCOUNT_ID:role/ec2-dev-role"
      }
    ]
  }'

# Create Lambda function
aws lambda create-function \
  --function-name dev-vm-provision \
  --runtime python3.11 \
  --role arn:aws:iam::ACCOUNT_ID:role/lambda-provision-role \
  --handler lambda_function.lambda_handler \
  --zip-file fileb://lambda_provision_vm.zip \
  --timeout 120 \
  --environment Variables="{
    SECURITY_GROUP_ID=sg-xxxxx,
    SUBNET_ID=subnet-xxxxx,
    EFS_ID=fs-xxxxx,
    JIRA_URL=https://your-company.atlassian.net,
    JIRA_USER=automation@your-company.com,
    JIRA_API_TOKEN=YOUR_TOKEN,
    JIRA_WEBHOOK_SECRET=YOUR_WEBHOOK_SECRET,
    AWS_REGION=us-east-1
  }"
```

### Step 4: Create API Gateway Webhook

```bash
# Create REST API
API_ID=$(aws apigateway create-rest-api \
  --name dev-vm-provisioning \
  --query 'id' --output text)

# Get root resource
ROOT_ID=$(aws apigateway get-resources \
  --rest-api-id $API_ID \
  --query 'items[0].id' --output text)

# Create /provision resource
RESOURCE_ID=$(aws apigateway create-resource \
  --rest-api-id $API_ID \
  --parent-id $ROOT_ID \
  --path-part provision \
  --query 'id' --output text)

# Create POST method
aws apigateway put-method \
  --rest-api-id $API_ID \
  --resource-id $RESOURCE_ID \
  --http-method POST \
  --authorization-type NONE

# Create Lambda integration
aws apigateway put-integration \
  --rest-api-id $API_ID \
  --resource-id $RESOURCE_ID \
  --http-method POST \
  --type AWS_LAMBDA \
  --integration-http-method POST \
  --uri arn:aws:apigateway:us-east-1:lambda:path/2015-03-31/functions/arn:aws:lambda:us-east-1:ACCOUNT_ID:function:dev-vm-provision/invocations

# Deploy API
aws apigateway create-deployment \
  --rest-api-id $API_ID \
  --stage-name prod

# Get webhook URL
echo "Webhook URL: https://$API_ID.execute-api.us-east-1.amazonaws.com/prod/provision"

# Allow API Gateway to invoke Lambda
aws lambda add-permission \
  --function-name dev-vm-provision \
  --statement-id AllowAPIGatewayInvoke \
  --action lambda:InvokeFunction \
  --principal apigateway.amazonaws.com \
  --source-arn arn:aws:execute-api:us-east-1:ACCOUNT_ID:$API_ID/*/*/provision
```

### Step 5: Configure Jira Webhook

1. **Jira Admin** → **System webhooks** → **Create webhook**
2. **URL**: `https://{API_ID}.execute-api.us-east-1.amazonaws.com/prod/provision`
3. **Events**: `issue_transitioned`
4. **Conditions**: `status = Ready AND issue type = Provision Dev VM`
5. **Click Test** to verify connection

---

## Testing

### Manual Test: Start a VM

```bash
aws lambda invoke \
  --function-name dev-vm-start-stop \
  --payload '{"action":"start"}' \
  /tmp/response.json

cat /tmp/response.json
```

### Manual Test: Stop a VM

```bash
aws lambda invoke \
  --function-name dev-vm-start-stop \
  --payload '{"action":"stop"}' \
  /tmp/response.json

cat /tmp/response.json
```

### Test Jira Provisioning

1. Create new Jira ticket:
   - Type: "Provision Dev VM"
   - Client: "ClientA"
   - Developer Name: "john-smith"
   - Instance Type: "t3.xlarge"
   - OS: "RHEL8"
   - Start Time: "08:00"
   - Stop Time: "18:00"
2. Move to "Ready" status
3. Check Lambda logs: `aws logs tail /aws/lambda/dev-vm-provision --follow`
4. Verify EC2 instance launched in AWS console
5. Check Jira comment with connection details

---

## Cost Optimization Tips

1. **Use Spot Instances**: Replace `t3.xlarge` with Spot for dev (70% savings)
2. **Set Aggressive Auto-Stop**: Stop VMs at 17:00 instead of 18:00
3. **Use AWS Compute Optimizer**: Find right-sized instances
4. **Reserved Capacity**: If running 24/7 databases, buy RDS Reserved Instances

---

## Troubleshooting

### Lambda not invoking from Jira

- Check API Gateway CloudWatch logs
- Verify webhook URL is correct
- Test with: `curl -X POST https://xxx.execute-api.../prod/provision -d '{}' -H 'Content-Type: application/json'`

### EFS mount failing

- Ensure security group allows NFS (port 2049)
- Check mount target is in same AZ as instance
- Review EC2 instance logs: `/var/log/cloud-init-output.log`

### RDS connection failing

- Verify security group inbound rule for RDS port (5432/3306)
- Check RDS is in public subnet or same VPC as EC2
- Test with: `psql -h <rds-endpoint> -U admin`

---

## Maintenance

### Weekly
- Review CloudWatch logs for errors
- Check RDS backup status

### Monthly
- Review costs in Cost Explorer
- Update AMI with security patches
- Check for unused EBS snapshots

### Quarterly
- Review instance sizes
- Update Lambda functions
- Audit IAM permissions

---

## Next: Destroy Everything (for cleanup)

```bash
# WARNING: This deletes everything!

# Delete Lambda functions
aws lambda delete-function --function-name dev-vm-start-stop
aws lambda delete-function --function-name dev-vm-provision

# Delete EventBridge rules
aws events delete-rule --name dev-vm-start-rule
aws events delete-rule --name dev-vm-stop-rule

# Delete RDS
aws rds delete-db-instance --db-instance-identifier dev-postgres --skip-final-snapshot
aws rds delete-db-instance --db-instance-identifier dev-mysql --skip-final-snapshot

# Delete EFS
aws efs delete-file-system --file-system-id fs-xxxxx

# Delete EC2 resources
aws ec2 delete-security-group --group-id sg-xxxxx
aws ec2 delete-vpc --vpc-id vpc-xxxxx
```

---

