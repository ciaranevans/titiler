"""Construct App."""

from typing import Any, Union

import os

from aws_cdk import (
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_elasticloadbalancingv2 as elb,
    aws_elasticloadbalancingv2_targets as elb_targets,
    aws_lambda as _lambda,
    core,
)

import config
from titiler_lambda_builder import TitilerLambdaBuilder


class titilerStack(core.Stack):
    """Titiler ECS Fargate Stack."""

    def __init__(
        self,
        scope: core.Construct,
        id: str,
        cpu: Union[int, float] = 256,
        memory: Union[int, float] = 512,
        mincount: int = 1,
        maxcount: int = 50,
        code_dir: str = "./",
        **kwargs: Any,
    ) -> None:
        """Define stack."""
        super().__init__(scope, id, **kwargs)

        vpc = ec2.Vpc(self, f"{id}-vpc", max_azs=2)

        cluster = ecs.Cluster(self, f"{id}-cluster", vpc=vpc)

        task_definition = ecs.TaskDefinition(
            self,
            f"{id}-task-def",
            cpu=str(cpu),
            memory_mib=str(memory),
            compatibility=ecs.Compatibility.FARGATE,
            network_mode=ecs.NetworkMode.AWS_VPC,
        )

        container_def = task_definition.add_container(
            f"{id}-task-container",
            image=ecs.ContainerImage.from_asset(code_dir, exclude=["cdk.out", ".git"]),
            cpu=cpu,
            environment=dict(
                CPL_TMPDIR="/tmp",
                GDAL_CACHEMAX="75%",
                GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
                GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES",
                GDAL_HTTP_MULTIPLEX="YES",
                GDAL_HTTP_VERSION="2",
                MODULE_NAME="titiler.main",
                PYTHONWARNINGS="ignore",
                VARIABLE_NAME="app",
                VSI_CACHE="TRUE",
                VSI_CACHE_SIZE="1000000",
                WORKERS_PER_CORE="1",
                LOG_LEVEL="error",
            ),
            memory_limit_mib=memory,
        )

        container_def.add_port_mappings(
            ecs.PortMapping(container_port=80, host_port=80)
        )

        fargate_service = ecs.FargateService(
            self,
            f"{id}-service",
            cluster=cluster,
            desired_count=mincount,
            task_definition=task_definition,
            assign_public_ip=True,
        )

        fargate_service.connections.allow_from_any_ipv4(
            port_range=ec2.Port(
                protocol=ec2.Protocol.ALL,
                string_representation="All port 80",
                from_port=80,
            ),
            description="Allows traffic on port 80 from NLB",
        )

        lambda_function = _lambda.Function(
            self,
            f"{id}-lambda",
            runtime=_lambda.Runtime.PYTHON_3_7,
            code=_lambda.Code.asset(TitilerLambdaBuilder().get_package_path()),
            handler="handler.handler",
            memory_size=2048,
            timeout=core.Duration.seconds(10),
            environment=dict(
                CPL_TMPDIR="/tmp",
                GDAL_CACHEMAX="25%",
                GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
                GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES",
                GDAL_HTTP_MULTIPLEX="YES",
                GDAL_HTTP_VERSION="2",
                PYTHONWARNINGS="ignore",
                VSI_CACHE="TRUE",
                VSI_CACHE_SIZE="1000000",
            ),
        )

        lambda_target = elb_targets.LambdaTarget(fn=lambda_function)

        load_balancer = elb.ApplicationLoadBalancer(self, f"{id}-alb", vpc=vpc)

        application_listener = elb.ApplicationListener(
            self, f"{id}-listener", load_balancer=load_balancer, port=80, open=True,
        )

        fargate_target_group = application_listener.add_targets(
            f"{id}-fargate-target",
            target_group_name="fargate-target-group",
            port=80,
            targets=[fargate_service],
        )

        _ = application_listener.add_targets(
            f"{id}-lambda-target",
            target_group_name="lambda-target-group",
            targets=[lambda_target],
        )

        scalable_target = fargate_service.auto_scale_task_count(
            min_capacity=mincount, max_capacity=maxcount
        )

        # https://github.com/awslabs/aws-rails-provisioner/blob/263782a4250ca1820082bfb059b163a0f2130d02/lib/aws-rails-provisioner/scaling.rb#L343-L387
        scalable_target.scale_on_request_count(
            "FargateRequestScaling",
            requests_per_target=50,
            scale_in_cooldown=core.Duration.seconds(240),
            scale_out_cooldown=core.Duration.seconds(30),
            target_group=fargate_target_group,
        )

        # Attempt at adding weighted Target Groups from https://aws.amazon.com/blogs/aws/new-application-load-balancer-simplifies-deployment-with-weighted-target-groups/
        # _ = elb.CfnListenerRule(
        #     self,
        #     f"{id}-fargate-target-group-weighting",
        #     actions=[
        #         elb.CfnListenerRule.ActionProperty(
        #             type="forward",
        #             order=1,
        #             forward_config=elb.CfnListenerRule.ForwardConfigProperty(
        #                 target_groups=[
        #                     elb.CfnListenerRule.TargetGroupTupleProperty(
        #                         target_group_arn=fargate_target_group.target_group_arn,
        #                         weight=50,
        #                     ),
        #                     elb.CfnListenerRule.TargetGroupTupleProperty(
        #                         target_group_arn=lambda_target_group.target_group_arn,
        #                         weight=50,
        #                     ),
        #                 ]
        #             ),
        #         )
        #     ],
        #     conditions=[
        #         elb.CfnListenerRule.RuleConditionProperty(
        #             path_pattern_config=elb.CfnListenerRule.PathPatternConfigProperty(
        #                 values=["/"]
        #             )
        #         )
        #     ],
        #     listener_arn=application_listener.listener_arn,
        #     priority=1,
        # )


app = core.App()

# Tag infrastructure
for key, value in {
    "Project": config.PROJECT_NAME,
    "Stack": config.STAGE,
    "Owner": os.environ.get("OWNER"),
    "Client": os.environ.get("CLIENT"),
}.items():
    if value:
        core.Tag.add(app, key, value)

stackname = f"{config.PROJECT_NAME}-{config.STAGE}"
titilerStack(
    app,
    stackname,
    cpu=config.TASK_CPU,
    memory=config.TASK_MEMORY,
    mincount=config.MIN_ECS_INSTANCES,
    maxcount=config.MAX_ECS_INSTANCES,
)
app.synth()
