# Azure AD + AWS Landing Zone Integration Guide

## Overview
Integrate Azure AD with AWS Landing Zone for centralized identity management and automated resource provisioning based on AD users.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    AZURE AD (Azure Entra)                   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Users & Groups                                      │   │
│  │  • Dev Team                                          │   │
│  │  • ClientA Team                                      │   │
│  │  • ClientB Team                                      │   │
│  │  • Admins                                            │   │
│  └────────────────────┬─────────────────────────────────┘   │
└─────────────────────────┼──────────────────────────────────┘
                          │
                          │ SAML 2.0 / OIDC
                          │
        ┌─────────────────▼──────────────────┐
        │  AWS Landing Zone                  │
        │  ┌────────────────────────────┐    │
        │  │ AWS IAM Identity Center    │    │
        │  │ (Formerly AWS SSO)         │    │
        │  └────────────┬───────────────┘    │
        │               │                     │
        │   ┌───────────┴───────────┐        │
        │   │                       │        │
        │   ▼                       ▼        │
        │ ┌─────────────┐   ┌──────────────┐│
        │ │ IAM Roles   │   │ Permission   ││
        │ │ & Policies  │   │ Sets         ││
        │ └─────────────┘   └──────────────┘│
        │                                    │
        │   ┌────────────────────────────┐  │
        │   │ AWS Organizations          │  │
        │   │ • Master Account           │  │
        │   │ • Workload Accounts        │  │
        │   │ • Log Archive Account      │  │
        │   └────────────────────────────┘  │
        └────────────────────────────────────┘
                          │
                          │ API / Cross-Account Access
                          │
        ┌─────────────────▼──────────────────────┐
        │  Dev VM Solution                       │
        │  ┌──────────────────────────────────┐  │
        │  │ Lambda Provisioning Function     │  │
        │  │ • Read Azure AD user attributes  │  │
        │  │ • Create IAM roles per user      │  │
        │  │ • Launch EC2 with user identity  │  │
        │  │ • Manage access permissions      │  │
        │  └──────────────────────────────────┘  │
        │                                        │
        │  ┌──────────────────────────────────┐  │
        │  │ EC2 Dev VMs                      │  │
        │  │ • Per-user access control        │  │
        │  │ • User-specific environment      │  │
        │  │ • Audit trail in CloudTrail      │  │
        │  └──────────────────────────────────┘  │
        └────────────────────────────────────────┘
```

---

## Phase 1: Azure AD + AWS IAM Identity Center Setup

### Step 1.1: Enable IAM Identity Center in Landing Zone

```bash
# AWS CLI commands

# 1. Enable IAM Identity Center in primary region
aws sso-admin list-instances --query 'Instances[0]'

# If not enabled, create instance
aws sso create-instance --name "azure-ad-sync"
```

### Step 1.2: Configure Azure AD as Identity Provider

**In Azure Portal:**

1. Go to: **Azure Entra ID** → **Enterprise applications** → **New application**
2. Search: **AWS IAM Identity Center**
3. Add the application
4. Configure SAML:
   - **Single sign-on URL**: `https://signin.aws.amazon.com/saml`
   - **Identifier**: `urn:amazon:webservices`
   - **Sign out URL**: `https://signin.aws.amazon.com/saml`

5. Download Federation Metadata XML

**In AWS Console:**

1. Go to: **IAM Identity Center** → **Settings**
2. **Identity source** → **Change identity source**
3. Select: **External identity provider**
4. Upload Azure AD Metadata XML
5. Configure attribute mappings

### Step 1.3: Attribute Mapping (Critical for automation)

**Map Azure AD attributes to AWS attributes:**

```
Azure AD Attribute          →  AWS Attribute
userPrincipalName          →  name
givenName                  →  givenName
surname                    →  surname
mail                       →  email
department                 →  department
jobTitle                   →  jobTitle
extensionAttribute1        →  clientName  (custom field)
extensionAttribute2        →  team        (custom field)
```

**Add custom attributes in Azure AD:**

```powershell
# PowerShell: Set custom attributes for dev users
$user = Get-AzureADUser -Filter "userPrincipalName eq 'john.smith@company.com'"
$user | Set-AzureADUser -ExtensionProperty @{
    extension_ClientName = "ClientA"
    extension_Team = "dev"
    extension_CostCenter = "DEV-001"
}
```

### Step 1.4: Create Azure AD Groups for AWS

**In Azure Entra ID:**

```powershell
# PowerShell: Create groups matching AWS needs
$groups = @(
    "AWS-Dev-Team",
    "AWS-ClientA-Team",
    "AWS-ClientB-Team",
    "AWS-Admins",
    "AWS-Provisioning-Users"
)

foreach ($group in $groups) {
    New-AzureADGroup -DisplayName $group `
        -MailNickname $group `
        -MailEnabled $false `
        -SecurityEnabled $true
}

# Add users to groups
$devTeam = Get-AzureADGroup -Filter "DisplayName eq 'AWS-Dev-Team'"
$user = Get-AzureADUser -Filter "userPrincipalName eq 'john.smith@company.com'"
Add-AzureADGroupMember -ObjectId $devTeam.ObjectId -RefObjectId $user.ObjectId
```

---

## Phase 2: AWS Landing Zone IAM Setup

### Step 2.1: Create Permission Sets in IAM Identity Center

```bash
# AWS CLI: Create permission sets for different roles

# 1. Developer Permission Set
aws sso-admin create-permission-set \
    --instance-arn "arn:aws:sso:::instance/ssoins-xxxxx" \
    --name "Developer-Access" \
    --description "Dev VM access and management" \
    --session-duration "PT8H"

# 2. Admin Permission Set
aws sso-admin create-permission-set \
    --instance-arn "arn:aws:sso:::instance/ssoins-xxxxx" \
    --name "Admin-Access" \
    --description "Full AWS admin access" \
    --session-duration "PT4H"
```

### Step 2.2: Attach IAM Policies to Permission Sets

```bash
# Create inline policy for Developer access
POLICY_JSON=$(cat <<'POLICY'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeInstances",
        "ec2:DescribeInstanceStatus",
        "ec2:GetConsoleOutput",
        "ec2:DescribeVolumes"
      ],
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "ap-southeast-2"
        }
      }
    },
    {
      "Effect": "Allow",
      "Action": [
        "ssm:StartSession",
        "ssm:GetConnectionStatus"
      ],
      "Resource": "arn:aws:ec2:*:*:instance/*",
      "Condition": {
        "StringLike": {
          "ssm:resourceTag/Environment": "dev"
        }
      }
    },
    {
      "Effect": "Allow",
      "Action": [
        "rds:DescribeDBInstances",
        "rds-db:connect"
      ],
      "Resource": "*"
    }
  ]
}
POLICY

# Attach to permission set
aws sso-admin put-inline-policy-to-permission-set \
    --instance-arn "arn:aws:sso:::instance/ssoins-xxxxx" \
    --permission-set-arn "arn:aws:sso:::permissionSet/ssoins-xxxxx/ps-xxxxx" \
    --inline-policy "$POLICY_JSON"
```

### Step 2.3: Assign Users to Permission Sets

```bash
# AWS CLI: Assign Azure AD groups to permission sets

# Get ARNs
INSTANCE_ARN="arn:aws:sso:::instance/ssoins-xxxxx"
PERMISSION_SET_ARN="arn:aws:sso:::permissionSet/ssoins-xxxxx/ps-xxxxx"
TARGET_ACCOUNT_ID="123456789012"
GROUP_ID="xxxxx"  # From Azure AD sync

# Create assignment
aws sso-admin create-account-assignment \
    --instance-arn "$INSTANCE_ARN" \
    --target-id "$TARGET_ACCOUNT_ID" \
    --target-type AWS_ACCOUNT \
    --permission-set-arn "$PERMISSION_SET_ARN" \
    --principal-type GROUP \
    --principal-id "$GROUP_ID"
```

---

## Phase 3: Enhanced Lambda for Azure AD-Based Provisioning

### Step 3.1: Updated Lambda Function

```python
"""
Enhanced lambda_provision_from_jira.py with Azure AD integration
"""

import json
import boto3
import requests
from azure.identity import ClientSecretCredential
from azure.graphrbac import GraphRbacManagementClient

ec2 = boto3.client('ec2')
iam = boto3.client('iam')
ssm = boto3.client('ssm')
graph_client = GraphRbacManagementClient(
    credentials=ClientSecretCredential(...),
    tenant_id=os.environ['AZURE_TENANT_ID']
)

def get_user_from_azure_ad(email):
    """
    Fetch user details from Azure AD
    """
    try:
        filter_query = f"mail eq '{email}'"
        users = graph_client.users.list(
            filter=filter_query
        )
        
        if users.value:
            user = users.value[0]
            return {
                'id': user.object_id,
                'name': user.display_name,
                'email': user.mail,
                'client_name': user.additional_properties.get('extension_ClientName'),
                'team': user.additional_properties.get('extension_Team'),
                'cost_center': user.additional_properties.get('extension_CostCenter')
            }
    except Exception as e:
        print(f"Error fetching from Azure AD: {e}")
        return None

def create_iam_role_for_user(email, client_name):
    """
    Create IAM role for user-specific access
    """
    role_name = f"dev-user-{email.split('@')[0]}"
    
    assume_role_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "AWS": f"arn:aws:iam::ACCOUNT_ID:root"
                },
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {
                        "aws:userid": email
                    }
                }
            }
        ]
    }
    
    try:
        role = iam.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(assume_role_policy),
            Tags=[
                {'Key': 'Email', 'Value': email},
                {'Key': 'ClientName', 'Value': client_name},
                {'Key': 'ManagedBy', 'Value': 'Lambda'},
                {'Key': 'CreatedDate', 'Value': datetime.now().isoformat()}
            ]
        )
        
        # Attach inline policy
        user_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": [
                        "ec2:DescribeInstances",
                        "ec2:GetConsoleOutput"
                    ],
                    "Resource": "*",
                    "Condition": {
                        "StringEquals": {
                            "ec2:ResourceTag/ClientName": client_name,
                            "ec2:ResourceTag/OwnerEmail": email
                        }
                    }
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "ssm:StartSession",
                        "ssm:GetConnectionStatus"
                    ],
                    "Resource": "arn:aws:ec2:*:*:instance/*",
                    "Condition": {
                        "StringLike": {
                            "ssm:resourceTag/OwnerEmail": email
                        }
                    }
                }
            ]
        }
        
        iam.put_role_policy(
            RoleName=role_name,
            PolicyName=f"{role_name}-policy",
            PolicyDocument=json.dumps(user_policy)
        )
        
        return role['Role']['Arn']
        
    except iam.exceptions.EntityAlreadyExistsException:
        print(f"Role {role_name} already exists")
        return f"arn:aws:iam::ACCOUNT_ID:role/{role_name}"

def lambda_handler(event, context):
    """
    Enhanced provisioning with Azure AD integration
    """
    try:
        # Parse Jira webhook
        webhook_data = json.loads(event['body'])
        issue = webhook_data['issue']
        fields = issue['fields']
        
        # Get user email from Jira (custom field)
        user_email = fields['customfield_10008']  # User email field
        
        # Fetch user details from Azure AD
        azure_user = get_user_from_azure_ad(user_email)
        if not azure_user:
            return {'statusCode': 404, 'body': 'User not found in Azure AD'}
        
        # Extract details
        client_name = azure_user['client_name'] or fields['customfield_10001']
        dev_name = azure_user['name']
        team = azure_user['team']
        cost_center = azure_user['cost_center']
        
        # Create IAM role for user
        user_role_arn = create_iam_role_for_user(user_email, client_name)
        
        # Get instance type and OS from Jira
        instance_type = fields['customfield_10003']
        os_type = fields['customfield_10004']
        
        # Get AMI ID
        ami_id = AMI_MAP.get(os_type)
        
        # Launch EC2 instance
        response = ec2.run_instances(
            ImageId=ami_id,
            InstanceType=instance_type,
            MinCount=1,
            MaxCount=1,
            SecurityGroupIds=[os.environ['SECURITY_GROUP_ID']],
            SubnetId=os.environ['SUBNET_ID'],
            UserData=generate_user_data(azure_user['name'], client_name),
            IamInstanceProfile={'Arn': user_role_arn},
            TagSpecifications=[
                {
                    'ResourceType': 'instance',
                    'Tags': [
                        {'Key': 'Name', 'Value': f"dev-{client_name}-{dev_name}"},
                        {'Key': 'ClientName', 'Value': client_name},
                        {'Key': 'DeveloperName', 'Value': dev_name},
                        {'Key': 'OwnerEmail', 'Value': user_email},
                        {'Key': 'AzureADObjectId', 'Value': azure_user['id']},
                        {'Key': 'Team', 'Value': team},
                        {'Key': 'CostCenter', 'Value': cost_center},
                        {'Key': 'Environment', 'Value': 'dev'},
                        {'Key': 'ManagedBy', 'Value': 'Azure-AD-Provisioning'}
                    ]
                }
            ]
        )
        
        instance_id = response['Instances'][0]['InstanceId']
        
        # Wait for instance
        waiter = ec2.get_waiter('instance_running')
        waiter.wait(InstanceIds=[instance_id])
        
        # Get instance details
        instance_info = ec2.describe_instances(InstanceIds=[instance_id])
        instance = instance_info['Reservations'][0]['Instances'][0]
        public_ip = instance.get('PublicIpAddress')
        
        # Post to Jira
        jira_comment = f"""
✅ VM Provisioned with Azure AD Integration!

**User Information:**
- Name: {azure_user['name']}
- Email: {user_email}
- Team: {team}
- Cost Center: {cost_center}

**Instance Details:**
- ID: {instance_id}
- IP: {public_ip}
- Type: {instance_type}
- OS: {os_type}

**Access:**
- IAM Role: {user_role_arn}
- SSH: ssh -i key.pem ec2-user@{public_ip}
- SSM Session: aws ssm start-session --target {instance_id}

**Features:**
- User-specific IAM role for fine-grained access
- CloudTrail auditing with user identity
- Automatic access control based on client
"""
        
        post_jira_comment(issue['key'], jira_comment)
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'VM provisioned with Azure AD',
                'instance_id': instance_id,
                'user_email': user_email,
                'azure_id': azure_user['id']
            })
        }
        
    except Exception as e:
        print(f"Error: {e}")
        return {'statusCode': 500, 'body': json.dumps({'error': str(e)})}
```

### Step 3.2: Lambda Environment Variables

```bash
# Set environment variables for Lambda

aws lambda update-function-configuration \
    --function-name dev-vm-provision \
    --environment Variables='{
        "AZURE_TENANT_ID": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
        "AZURE_CLIENT_ID": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
        "AZURE_CLIENT_SECRET": "your-secret",
        "SECURITY_GROUP_ID": "sg-xxxxx",
        "SUBNET_ID": "subnet-xxxxx",
        "AWS_REGION": "ap-southeast-2"
    }'
```

---

## Phase 4: User Access Management

### Step 4.1: User Provisioning Workflow

```
Azure AD User Created
  ↓
Added to AWS-Dev-Team group
  ↓
IAM Identity Center syncs
  ↓
User gets Developer permission set
  ↓
Can access AWS Console
  ↓
Can request VM via Jira ticket
  ↓
Lambda creates user-specific IAM role
  ↓
EC2 instance launched with user role
  ↓
User can SSH with SSM or direct access
```

### Step 4.2: Access Control Policy Example

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowEC2DescribeForOwnVMs",
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeInstances",
        "ec2:DescribeInstanceStatus"
      ],
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "ec2:ResourceTag/OwnerEmail": "${aws:username}"
        }
      }
    },
    {
      "Sid": "AllowSSMSessionForOwnVMs",
      "Effect": "Allow",
      "Action": [
        "ssm:StartSession",
        "ssm:GetConnectionStatus"
      ],
      "Resource": "arn:aws:ec2:*:*:instance/*",
      "Condition": {
        "StringLike": {
          "ssm:resourceTag/OwnerEmail": "${aws:username}"
        }
      }
    },
    {
      "Sid": "AllowRDSAccessForClient",
      "Effect": "Allow",
      "Action": [
        "rds-db:connect"
      ],
      "Resource": "arn:aws:rds:*:*:db:*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "ap-southeast-2"
        }
      }
    }
  ]
}
```

---

## Phase 5: Monitoring & Auditing

### Step 5.1: CloudTrail Setup

```bash
# Enable CloudTrail for audit logging

aws cloudtrail create-trail \
    --name azure-ad-audit-trail \
    --s3-bucket-name audit-bucket

aws cloudtrail start-logging \
    --trail-name azure-ad-audit-trail

# Query for user actions
aws cloudtrail lookup-events \
    --lookup-attributes AttributeKey=Username,AttributeValue=john.smith@company.com \
    --max-results 50
```

### Step 5.2: CloudWatch Monitoring

```python
# Monitor Azure AD sync events
import boto3

logs = boto3.client('logs')

query = """
fields @timestamp, userIdentity.principalId, eventName, sourceIPAddress, requestParameters
| filter eventSource = 'ec2.amazonaws.com' and eventName like /RunInstances|TerminateInstances/
| stats count() as instance_changes by userIdentity.principalId
"""

response = logs.start_query(
    logGroupName='/aws/cloudtrail/azure-ad-audit',
    startTime=int(time.time()) - 86400,
    endTime=int(time.time()),
    queryString=query
)
```

---

## Security Best Practices

### 1. MFA Integration
```
Azure AD MFA → AWS SSO → EC2 Access
All users required to have MFA enabled
```

### 2. Conditional Access
```
Azure Conditional Access policies:
- Require MFA for risky sign-ins
- Block access from unknown locations
- Require compliant devices
```

### 3. Resource Quotas
```bash
# Limit resources per user via SCP

{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "ec2:RunInstances",
      "Resource": "arn:aws:ec2:*:*:instance/*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "ap-southeast-2"
        },
        "NumericLessThan": {
          "aws:CurrentTime": "2"
        }
      }
    }
  ]
}
```

### 4. Password Policy
```bash
# Azure AD password policy enforcement
- Minimum 14 characters
- Require uppercase, lowercase, numbers, symbols
- 90-day expiration
- Block common passwords
```

---

## Troubleshooting

### Issue: Users not syncing from Azure AD
```bash
# Check IAM Identity Center sync status
aws identitystore list-users --identity-store-id d-xxxxx

# Manually trigger sync
aws sso-admin start-identity-center-metadata-sync \
    --identity-center-instance-arn "arn:aws:sso:::instance/ssoins-xxxxx"
```

### Issue: User cannot access EC2 instance
```bash
# Check IAM role permissions
aws iam get-role-policy \
    --role-name dev-user-john.smith \
    --policy-name dev-user-john.smith-policy

# Check EC2 tags
aws ec2 describe-instances \
    --instance-ids i-xxxxx \
    --query 'Reservations[0].Instances[0].Tags'

# Test SSM access
aws ssm start-session --target i-xxxxx
```

### Issue: Lambda not writing to Jira
```bash
# Check Lambda CloudWatch logs
aws logs tail /aws/lambda/dev-vm-provision --follow

# Verify Jira API credentials
aws secretsmanager get-secret-value --secret-id jira/dev-provisioning
```

---

## Next Steps

1. **Week 1-2**: Set up Azure AD + IAM Identity Center integration
2. **Week 2-3**: Implement enhanced Lambda with Azure AD lookup
3. **Week 3-4**: Test user provisioning workflow
4. **Week 4-5**: Configure access policies and quotas
5. **Week 5+**: Deploy to production with monitoring

---

## References

- [AWS IAM Identity Center Documentation](https://docs.aws.amazon.com/singlesignon/)
- [Azure AD SAML Integration](https://docs.microsoft.com/en-us/azure/active-directory/saas-apps/aws-single-sign-on-tutorial)
- [AWS Security Best Practices](https://aws.amazon.com/architecture/security-identity-compliance/)

