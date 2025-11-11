"""
Lambda function for provisioning EC2 instances from Jira tickets
Deploy as: lambda_provision_vm
Trigger: Jira webhook on issue transition to 'Ready'
"""

import json
import boto3
import hmac
import hashlib
import os
import base64
from datetime import datetime
import requests

ec2 = boto3.client('ec2')
secretsmanager = boto3.client('secretsmanager')

# Configuration
REGION = os.environ.get('AWS_REGION', 'us-east-1')
SECURITY_GROUP_ID = os.environ.get('SECURITY_GROUP_ID', 'sg-xxxxx')
SUBNET_ID = os.environ.get('SUBNET_ID', 'subnet-xxxxx')
EFS_ID = os.environ.get('EFS_ID', 'fs-xxxxx')
JIRA_WEBHOOK_SECRET = os.environ.get('JIRA_WEBHOOK_SECRET', '')
JIRA_URL = os.environ.get('JIRA_URL', 'https://jira.example.com')
JIRA_USER = os.environ.get('JIRA_USER', '')
JIRA_API_TOKEN = os.environ.get('JIRA_API_TOKEN', '')

# AMI mapping
AMI_MAP = {
    'RHEL8': 'ami-0c55b159cbfafe1f0',
    'RHEL9': 'ami-09040d770ffe41de9',
    'Ubuntu20.04': 'ami-0dd273d94ed0540c0',
    'Ubuntu22.04': 'ami-0c9bfc21ac5bf10eb',
    'AmazonLinux2': 'ami-0c55b159cbfafe1f0'
}

def verify_jira_signature(request_body, signature_header):
    """Verify webhook signature from Jira"""
    if not JIRA_WEBHOOK_SECRET:
        print("WARNING: JIRA_WEBHOOK_SECRET not set, skipping signature verification")
        return True
    
    # Jira sends: X-Atlassian-Webhook-Signature: sha256=...
    expected_sig = hmac.new(
        JIRA_WEBHOOK_SECRET.encode(),
        request_body.encode(),
        hashlib.sha256
    ).hexdigest()
    
    actual_sig = signature_header.replace('sha256=', '') if signature_header else ''
    
    return hmac.compare_digest(actual_sig, expected_sig)

def generate_user_data(client_name, dev_name, efs_id):
    """Generate EC2 user data script"""
    return f"""#!/bin/bash
set -e

echo "=== Initializing Dev VM for {client_name} ({dev_name}) ==="

# Update system
sudo yum update -y

# Install EFS utilities
sudo yum install -y efs-utils nfs-utils

# Create home directory mount point
sudo mkdir -p /home
sudo mount -t efs -o tls {efs_id}:/ /home || true

# Add to fstab
if ! grep -q "{efs_id}" /etc/fstab; then
    echo "{efs_id}:/ /home nfs4 defaults,_netdev 0 0" | sudo tee -a /etc/fstab
fi

# Install database clients
sudo yum install -y postgresql mysql

# Install common dev tools
sudo yum install -y docker git nodejs python3 java-11-amazon-corretto-devel

# Start Docker daemon
sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -aG docker ec2-user

# Install AWS CLI v2
curl "https://awscli.amazonaws.com/awscliv2.zip" -o "awscliv2.zip"
unzip -q awscliv2.zip
sudo ./aws/install
rm -rf aws awscliv2.zip

echo "=== Dev VM initialization complete ==="
echo "Client: {client_name}"
echo "Developer: {dev_name}"
echo "EFS mounted at: /home"
"""

def lambda_handler(event, context):
    """
    Main Lambda handler for Jira webhook
    """
    try:
        # Verify request
        body_str = event.get('body', '{}')
        if isinstance(body_str, str):
            body = body_str
        else:
            body = json.dumps(body_str)
        
        signature = event.get('headers', {}).get('X-Atlassian-Webhook-Signature', '')
        
        if not verify_jira_signature(body, signature):
            print("ERROR: Signature verification failed")
            return {
                'statusCode': 401,
                'body': json.dumps({'error': 'Unauthorized'})
            }
        
        # Parse webhook payload
        webhook_data = json.loads(body)
        issue = webhook_data.get('issue', {})
        fields = issue.get('fields', {})
        issue_key = issue.get('key', 'UNKNOWN')
        
        print(f"Processing Jira issue: {issue_key}")
        
        # Extract custom fields (adjust field IDs as needed)
        client_name = fields.get('customfield_10001', 'unknown')
        dev_name = fields.get('customfield_10002', 'unknown')
        instance_type = fields.get('customfield_10003', 't3.xlarge')
        os_type = fields.get('customfield_10004', 'AmazonLinux2')
        auto_start = fields.get('customfield_10005', '08:00')
        auto_stop = fields.get('customfield_10006', '18:00')
        timezone = fields.get('customfield_10007', 'UTC')
        
        # Normalize values
        if isinstance(client_name, dict):
            client_name = client_name.get('value', client_name.get('name', 'unknown'))
        if isinstance(os_type, dict):
            os_type = os_type.get('value', os_type.get('name', 'AmazonLinux2'))
        
        print(f"Client: {client_name}, Dev: {dev_name}, Type: {instance_type}, OS: {os_type}")
        
        # Get AMI ID
        ami_id = AMI_MAP.get(os_type, AMI_MAP['AmazonLinux2'])
        
        # Prepare EC2 launch parameters
        instance_name = f"dev-{client_name.lower()}-{dev_name.lower()}"
        user_data_script = generate_user_data(client_name, dev_name, EFS_ID)
        user_data_b64 = base64.b64encode(user_data_script.encode()).decode()
        
        # Launch EC2 instance
        print(f"Launching EC2 instance: {instance_name}")
        
        response = ec2.run_instances(
            ImageId=ami_id,
            InstanceType=instance_type,
            MinCount=1,
            MaxCount=1,
            SecurityGroupIds=[SECURITY_GROUP_ID],
            SubnetId=SUBNET_ID,
            UserData=user_data_script,
            IamInstanceProfile={'Name': 'ec2-dev-profile'},  # Must have EC2 instance profile
            TagSpecifications=[
                {
                    'ResourceType': 'instance',
                    'Tags': [
                        {'Key': 'Name', 'Value': instance_name},
                        {'Key': 'ClientName', 'Value': client_name},
                        {'Key': 'DeveloperName', 'Value': dev_name},
                        {'Key': 'Environment', 'Value': 'dev'},
                        {'Key': 'AutoStart', 'Value': auto_start},
                        {'Key': 'AutoStop', 'Value': auto_stop},
                        {'Key': 'Timezone', 'Value': timezone},
                        {'Key': 'JiraTicket', 'Value': issue_key},
                        {'Key': 'CreatedDate', 'Value': datetime.utcnow().isoformat()},
                        {'Key': 'OS', 'Value': os_type},
                    ]
                }
            ]
        )
        
        instance_id = response['Instances'][0]['InstanceId']
        print(f"Instance launched: {instance_id}")
        
        # Wait for instance to be running and get public IP
        waiter = ec2.get_waiter('instance_running')
        waiter.wait(InstanceIds=[instance_id])
        
        instance_info = ec2.describe_instances(InstanceIds=[instance_id])
        instance = instance_info['Reservations'][0]['Instances'][0]
        public_ip = instance.get('PublicIpAddress', 'N/A')
        private_ip = instance.get('PrivateIpAddress', 'N/A')
        
        print(f"Instance running - Public IP: {public_ip}, Private IP: {private_ip}")
        
        # Post comment to Jira
        jira_comment = f"""✅ **Dev VM Provisioned Successfully!**

🖥️ *Instance Details:*
• Instance ID: `{instance_id}`
• Instance Name: `{instance_name}`
• Instance Type: `{instance_type}`
• Operating System: `{os_type}`
• Public IP: `{public_ip}`
• Private IP: `{private_ip}`
• Region: `{REGION}`

🔐 *Connection:*
{{code}}
ssh -i /path/to/key.pem ec2-user@{public_ip}
{{code}}

📊 *Databases:*
• PostgreSQL: `shared-db.xxxxx.rds.amazonaws.com:5432`
• MySQL: `shared-db.xxxxx.rds.amazonaws.com:3306`
• See Secrets Manager for credentials

💾 *Home Directory:*
• Mounted at: `/home` (EFS)
• Persists across stop/start cycles
• Shared storage location: `/home/{dev_name}`

⏰ *Auto Schedule:*
• Start: {auto_start} {timezone}
• Stop: {auto_stop} {timezone}

📋 *Next Steps:*
1. SSH into the instance
2. Configure application-specific databases and schemas
3. Clone your project repositories
4. Set up development environment variables
5. Add SSH key to your profile for authentication

✨ Ready for development!
"""
        
        post_jira_comment(issue_key, jira_comment)
        print("Posted comment to Jira")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'VM provisioned successfully',
                'instance_id': instance_id,
                'instance_name': instance_name,
                'public_ip': public_ip,
                'jira_issue': issue_key
            })
        }
        
    except Exception as e:
        print(f"ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e),
                'type': type(e).__name__
            })
        }

def post_jira_comment(issue_key, comment_text):
    """Post comment to Jira issue using REST API v3"""
    
    url = f"{JIRA_URL}/rest/api/3/issue/{issue_key}/comments"
    
    # Jira API v3 requires ADF format for body
    payload = {
        "body": {
            "version": 1,
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": comment_text
                        }
                    ]
                }
            ]
        }
    }
    
    auth = (JIRA_USER, JIRA_API_TOKEN)
    headers = {'Content-Type': 'application/json'}
    
    try:
        response = requests.post(url, json=payload, auth=auth, headers=headers)
        response.raise_for_status()
        print(f"Comment posted successfully to {issue_key}")
    except Exception as e:
        print(f"Failed to post comment: {str(e)}")
        # Don't fail the Lambda, just log the error
