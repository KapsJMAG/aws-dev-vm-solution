"""
Lambda function for auto-starting and stopping dev EC2 instances
Deploy as: lambda_start_stop
"""

import boto3
import os
from datetime import datetime
import pytz
import json

ec2 = boto3.client('ec2', region_name=os.environ.get('AWS_REGION', 'us-east-1'))

def lambda_handler(event, context):
    """
    Lambda handler for EC2 start/stop automation
    
    Event structure:
    {
        "action": "start" or "stop",
        "filter_tag": "ClientName",  # optional
        "filter_value": "ClientA"    # optional
    }
    """
    
    action = event.get('action', 'start')
    filter_tag = event.get('filter_tag')
    filter_value = event.get('filter_value')
    
    print(f"Action: {action}, Filter: {filter_tag}={filter_value}")
    
    # Build filters
    filters = [
        {'Name': 'tag:Environment', 'Values': ['dev']},
        {'Name': 'instance-state-name', 'Values': ['running', 'stopped']}
    ]
    
    if filter_tag and filter_value:
        filters.append({'Name': f'tag:{filter_tag}', 'Values': [filter_value]})
    
    # Get instances
    response = ec2.describe_instances(Filters=filters)
    
    instances_actioned = []
    
    for reservation in response['Reservations']:
        for instance in reservation['Instances']:
            instance_id = instance['InstanceId']
            tags = {tag['Key']: tag['Value'] for tag in instance.get('Tags', [])}
            current_state = instance['State']['Name']
            
            # Get timezone for this instance
            timezone_str = tags.get('Timezone', 'UTC')
            try:
                tz = pytz.timezone(timezone_str)
            except:
                tz = pytz.UTC
            
            current_time = datetime.now(tz).strftime("%H:%M")
            
            should_action = False
            reason = ""
            
            if action == 'start':
                auto_start = tags.get('AutoStart', '08:00')
                if current_time >= auto_start and current_state == 'stopped':
                    should_action = True
                    reason = f"Time {current_time} >= {auto_start} and instance stopped"
            
            elif action == 'stop':
                auto_stop = tags.get('AutoStop', '18:00')
                if current_time >= auto_stop and current_state == 'running':
                    should_action = True
                    reason = f"Time {current_time} >= {auto_stop} and instance running"
            
            if should_action:
                try:
                    if action == 'start':
                        ec2.start_instances(InstanceIds=[instance_id])
                    else:
                        ec2.stop_instances(InstanceIds=[instance_id])
                    
                    instances_actioned.append({
                        'instance_id': instance_id,
                        'action': action,
                        'reason': reason,
                        'name': tags.get('Name', 'N/A')
                    })
                    print(f"✓ {action.upper()} {instance_id} ({tags.get('Name')}): {reason}")
                
                except Exception as e:
                    print(f"✗ Failed to {action} {instance_id}: {str(e)}")
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'action': action,
            'instances_actioned': instances_actioned,
            'count': len(instances_actioned)
        })
    }
