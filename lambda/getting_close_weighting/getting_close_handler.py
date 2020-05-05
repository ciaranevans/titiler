"""Example function to be used as reference if we implement the Weighted Target Groups approach to ALB"""
import logging
import os

import boto3

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)

elb_client = boto3.client("elbv2")


def handler(event, context):
    """ Function to be invoked by a SNS Topic, which a CloudWatch Alarm has sent a message """
    # Using https://aws.amazon.com/blogs/developer/send-real-time-amazon-cloudwatch-alarm-notifications-to-amazon-chime/
    # as inspiration

    message = event["Records"][0]["Sns"]["Subject"]
    LOGGER.info(f"Received CloudWatch Alarm message: {message}")

    listener_arn = os.environ["LISTENER_ARN"]
    lambda_target_group_arn = os.environ["LAMBDA_TARGET_GROUP_ARN"]
    ecs_target_group_arn = os.environ["ECS_TARGET_GROUP_ARN"]

    direct_traffic_to_ecs(listener_arn, lambda_target_group_arn, ecs_target_group_arn)


def direct_traffic_to_ecs(listener_arn, lambda_target_group_arn, ecs_target_group_arn):
    """ Sets weighting on Lambda Target group to 0 and ECS to 100 """
    # Room for the weightings to be configured based on testing of this approach
    # Might not be suitable to completely turn off traffic to Lambda
    elb_client.modify_listener(
        ListenerArn=listener_arn,
        Port=80,
        Protocol="HTTP",
        DefaultActions=[
            {
                "Type": "forward",
                "Order": 1,
                "ForwardConfig": {
                    "TargetGroups": [
                        {"TargetGroupArn": lambda_target_group_arn, "Weight": 0},
                        {"TargetGroupArn": ecs_target_group_arn, "Weight": 100},
                    ]
                },
            }
        ],
    )
