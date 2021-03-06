# -*- coding: utf-8 -*-

"""
sceptre.cli

This module implements Sceptre's CLI, and should not be directly imported.
"""

import contextlib
from json import JSONEncoder
import os
import logging
from logging import Formatter
import sys
from uuid import uuid1
from functools import wraps

import click
import colorama
import yaml
from boto3.exceptions import Boto3Error
from botocore.exceptions import BotoCoreError, ClientError
from jinja2.exceptions import TemplateError

from .environment import Environment
from .exceptions import SceptreException
from .stack_status import StackStatus, StackChangeSetStatus
from .stack_status_colourer import StackStatusColourer
from . import __version__


def environment_options(func):
    """
    environment_options is a decorator which adds the environment argument to
    the click function ``func``.

    :param func: The click function to add the arguments to.
    :type func: function
    :returns: function
    """
    func = click.argument("environment")(func)
    return func


def stack_options(func):
    """
    stack_options is a decorator which adds the stack and environment arguments
    to the click function ``func``.

    :param func: The click function to add the arguments to.
    :type func: function
    :returns: function
    """
    func = click.argument("stack")(func)
    func = click.argument("environment")(func)
    return func


def change_set_options(func):
    """
    change_set_options is a decorator which adds the environment, stack and
    change set name arguments to the click function ``func``.

    :param func: The click function to add the arguments to.
    :type func: function
    :returns: function
    """
    func = click.argument("change_set_name")(func)
    func = click.argument("stack")(func)
    func = click.argument("environment")(func)
    return func


def catch_exceptions(func):
    """
    Catches and simplifies expected errors thrown by sceptre.

    catch_exceptions should be used as a decorator.

    :param func: The function which may throw exceptions which should be
        simplified.
    :type func: func
    :returns: The decorated function.
    :rtype: func
    """
    @wraps(func)
    def decorated(*args, **kwargs):
        """
        Invokes ``func``, catches expected errors, prints the error message and
        exits sceptre with a non-zero exit code.
        """
        try:
            return func(*args, **kwargs)
        except (SceptreException, BotoCoreError, ClientError, Boto3Error,
                TemplateError) as error:
            write(error)
            sys.exit(1)

    return decorated


@click.group()
@click.version_option(version=__version__, prog_name="Sceptre")
@click.option("--debug", is_flag=True, help="Turn on debug logging.")
@click.option("--dir", "directory", help="Specify sceptre directory.")
@click.option(
    "--output", type=click.Choice(["yaml", "json"]), default="yaml",
    help="The formatting style for command output.")
@click.option("--no-colour", is_flag=True, help="Turn off output colouring.")
@click.option(
    "--var", multiple=True, help="A variable to template into config files.")
@click.option(
    "--var-file", type=click.File("rb"),
    help="A YAML file of variables to template into config files.")
@click.pass_context
def cli(
        ctx, debug, directory, no_colour, output, var, var_file
):  # pragma: no cover
    """
    Implements sceptre's CLI.
    """
    setup_logging(debug, no_colour)
    colorama.init()
    ctx.obj = {
        "options": {},
        "output_format": output,
        "sceptre_dir": directory if directory else os.getcwd()
    }
    user_variables = {}
    if var_file:
        user_variables.update(yaml.safe_load(var_file.read()))
    if var:
        # --var options overwrite --var-file options
        for variable in var:
            variable_key, variable_value = variable.split("=")
            user_variables.update({variable_key: variable_value})
    if user_variables:
        ctx.obj["options"]["user_variables"] = user_variables


@cli.command(name="validate-template")
@stack_options
@click.pass_context
@catch_exceptions
def validate_template(ctx, environment, stack):
    """
    Validates the template.

    Validates ENVIRONMENT/STACK's template.
    """
    env = get_env(ctx.obj["sceptre_dir"], environment, ctx.obj["options"])
    result = env.stacks[stack].validate_template()
    write(result, ctx.obj["output_format"])


@cli.command(name="generate-template")
@stack_options
@click.pass_context
@catch_exceptions
def generate_template(ctx, environment, stack):
    """
    Displays the template used.

    Prints ENVIRONMENT/STACK's template.
    """
    env = get_env(ctx.obj["sceptre_dir"], environment, ctx.obj["options"])
    template_output = env.stacks[stack].template.body
    write(template_output)


@cli.command(name="lock-stack")
@stack_options
@click.pass_context
@catch_exceptions
def lock_stack(ctx, environment, stack):
    """
    Prevents stack updates.

    Applies a stack policy to ENVIRONMENT/STACK which prevents updates.
    """
    env = get_env(ctx.obj["sceptre_dir"], environment, ctx.obj["options"])
    env.stacks[stack].lock()


@cli.command(name="unlock-stack")
@stack_options
@click.pass_context
@catch_exceptions
def unlock_stack(ctx, environment, stack):
    """
    Allows stack updates.

    Applies a stack policy to ENVIRONMENT/STACK which allows updates.
    """
    env = get_env(ctx.obj["sceptre_dir"], environment, ctx.obj["options"])
    env.stacks[stack].unlock()


# DESCRIBE RESOURCES should merge into "describe-resources"
@cli.command(name="describe-env-resources")
@environment_options
@click.pass_context
@catch_exceptions
def describe_env_resources(ctx, environment):
    """
    Describes the env's resources.

    Prints ENVIRONMENT's resources.
    """
    env = get_env(ctx.obj["sceptre_dir"], environment, ctx.obj["options"])
    responses = env.describe_resources()

    write(responses, ctx.obj["output_format"])


@cli.command(name="describe-stack-resources")
@stack_options
@click.pass_context
@catch_exceptions
def describe_stack_resources(ctx, environment, stack):
    """
    Describes the stack's resources.

    Prints ENVIRONMENT/STACK's resources.
    """
    env = get_env(ctx.obj["sceptre_dir"], environment, ctx.obj["options"])
    response = env.stacks[stack].describe_resources()

    write(response, ctx.obj["output_format"])


@cli.command(name="create-stack")
@stack_options
@click.pass_context
@catch_exceptions
def create_stack(ctx, environment, stack):
    """
    Creates the stack.

    Creates ENVIRONMENT/STACK.
    """
    env = get_env(ctx.obj["sceptre_dir"], environment, ctx.obj["options"])
    response = env.stacks[stack].create()
    if response != StackStatus.COMPLETE:
        exit(1)


@cli.command(name="delete-stack")
@stack_options
@click.pass_context
@catch_exceptions
def delete_stack(ctx, environment, stack):
    """Deletes the stack.

    Deletes ENVIRONMENT/STACK."""
    env = get_env(ctx.obj["sceptre_dir"], environment, ctx.obj["options"])
    response = env.stacks[stack].delete()
    if response != StackStatus.COMPLETE:
        exit(1)


@cli.command(name="update-stack")
@stack_options
@click.pass_context
@catch_exceptions
def update_stack(ctx, environment, stack):
    """
    Updates the stack.

    Updates ENVIRONMENT/STACK.
    """
    env = get_env(ctx.obj["sceptre_dir"], environment, ctx.obj["options"])
    response = env.stacks[stack].update()
    if response != StackStatus.COMPLETE:
        exit(1)


@cli.command(name="launch-stack")
@stack_options
@click.pass_context
@catch_exceptions
def launch_stack(ctx, environment, stack):
    """
    Creates or updates the stack.

    Creates or updates ENVIRONMENT/STACK.
    """
    env = get_env(ctx.obj["sceptre_dir"], environment, ctx.obj["options"])
    response = env.stacks[stack].launch()
    if response != StackStatus.COMPLETE:
        exit(1)


@cli.command(name="launch-env")
@environment_options
@click.pass_context
@catch_exceptions
def launch_env(ctx, environment):
    """
    Creates or updates all stacks.

    Creates or updates all the stacks in ENVIRONMENT.
    """
    env = get_env(ctx.obj["sceptre_dir"], environment, ctx.obj["options"])
    response = env.launch()
    if not all(status == StackStatus.COMPLETE for status in response.values()):
        exit(1)


@cli.command(name="delete-env")
@environment_options
@click.pass_context
@catch_exceptions
def delete_env(ctx, environment):
    """
    Deletes all stacks.

    Deletes all the stacks in ENVIRONMENT.
    """
    env = get_env(ctx.obj["sceptre_dir"], environment, ctx.obj["options"])
    response = env.delete()
    if not all(status == StackStatus.COMPLETE for status in response.values()):
        exit(1)


@cli.command(name="continue-update-rollback")
@stack_options
@click.pass_context
@catch_exceptions
def continue_update_rollback(ctx, environment, stack):
    """
    Rolls stack back to working state.

    If ENVIRONMENT/STACK is in the state UPDATE_ROLLBACK_FAILED, roll it
    back to the UPDATE_ROLLBACK_COMPLETE state.
    """
    env = get_env(ctx.obj["sceptre_dir"], environment, ctx.obj["options"])
    env.stacks[stack].continue_update_rollback()


@cli.command(name="create-change-set")
@change_set_options
@click.pass_context
@catch_exceptions
def create_change_set(ctx, environment, stack, change_set_name):
    """
    Creates a change set.

    Create a change set for ENVIRONMENT/STACK with the name
    CHANGE_SET_NAME.
    """
    env = get_env(ctx.obj["sceptre_dir"], environment, ctx.obj["options"])
    env.stacks[stack].create_change_set(change_set_name)


@cli.command(name="delete-change-set")
@change_set_options
@click.pass_context
@catch_exceptions
def delete_change_set(ctx, environment, stack, change_set_name):
    """
    Deletes the change set.

    Deletes ENVIRONMENT/STACK's change set with name CHANGE_SET_NAME.
    """
    env = get_env(ctx.obj["sceptre_dir"], environment, ctx.obj["options"])
    env.stacks[stack].delete_change_set(change_set_name)


@cli.command(name="describe-change-set")
@change_set_options
@click.option("--verbose", is_flag=True)
@click.pass_context
@catch_exceptions
def describe_change_set(ctx, environment, stack, change_set_name, verbose):
    """
    Describes the change set.

    Describes ENVIRONMENT/STACK's change set with name CHANGE_SET_NAME.
    """
    env = get_env(ctx.obj["sceptre_dir"], environment, ctx.obj["options"])
    description = env.stacks[stack].describe_change_set(change_set_name)
    if not verbose:
        description = _simplify_change_set_description(description)
    write(description, ctx.obj["output_format"])


def _simplify_change_set_description(response):
    desired_response_items = [
        "ChangeSetName",
        "CreationTime",
        "ExecutionStatus",
        "StackName",
        "Status",
        "StatusReason"
    ]
    desired_resource_changes = [
        "Action",
        "LogicalResourceId",
        "PhysicalResourceId",
        "Replacement",
        "ResourceType",
        "Scope"
    ]
    formatted_response = {
        k: v
        for k, v in response.items()
        if k in desired_response_items
    }
    formatted_response["Changes"] = [
        {
            "ResourceChange": {
                k: v
                for k, v in change["ResourceChange"].items()
                if k in desired_resource_changes
            }
        }
        for change in response["Changes"]
    ]
    return formatted_response


@cli.command(name="execute-change-set")
@change_set_options
@click.pass_context
@catch_exceptions
def execute_change_set(ctx, environment, stack, change_set_name):
    """
    Executes the change set.

    Executes ENVIRONMENT/STACK's change set with name CHANGE_SET_NAME.
    """
    env = get_env(ctx.obj["sceptre_dir"], environment, ctx.obj["options"])
    env.stacks[stack].execute_change_set(change_set_name)


@cli.command(name="list-change-sets")
@stack_options
@click.pass_context
@catch_exceptions
def list_change_sets(ctx, environment, stack):
    """
    Lists change sets.

    Lists ENVIRONMENT/STACK's change sets.
    """
    env = get_env(ctx.obj["sceptre_dir"], environment, ctx.obj["options"])
    response = env.stacks[stack].list_change_sets()
    formatted_response = {
        k: v
        for k, v in response.items()
        if k != "ResponseMetadata"
    }
    write(formatted_response, ctx.obj["output_format"])


@cli.command(name="update-stack-cs")
@stack_options
@click.option("--verbose", is_flag=True)
@click.pass_context
@catch_exceptions
def update_with_change_set(ctx, environment, stack, verbose):
    """
    Updates the stack using a change set.

    Creates a change set for ENVIRONMENT/STACK, prints out a description of the
    changes, and prompts the user to decide whether to execute or delete it.
    """
    env = get_env(ctx.obj["sceptre_dir"], environment, ctx.obj["options"])
    change_set_name = "-".join(["change-set", uuid1().hex])
    with change_set(env.stacks[stack], change_set_name):
        status = env.stacks[stack].wait_for_cs_completion(change_set_name)
        description = env.stacks[stack].describe_change_set(change_set_name)
        if not verbose:
            description = _simplify_change_set_description(description)
        write(description, ctx.obj["output_format"])
        if status != StackChangeSetStatus.READY:
            exit(1)
        if click.confirm("Proceed with stack update?"):
            env.stacks[stack].execute_change_set(change_set_name)


@contextlib.contextmanager
def change_set(stack, name):
    """
    Creates and yields and deletes a change set.

    :param stack: The stack to create the change set for.
    :type stack: sceptre.stack.Stack
    :param name: The name of the change set.
    :type name: str
    """
    stack.create_change_set(name)
    try:
        yield
    finally:
        stack.delete_change_set(name)


@cli.command(name="describe-stack-outputs")
@stack_options
@click.option("--export", type=click.Choice(["envvar"]))
@click.pass_context
@catch_exceptions
def describe_stack_outputs(ctx, environment, stack, export):
    """
    Describes stack outputs.

    Describes ENVIRONMENT/STACK's stack outputs.
    """
    env = get_env(ctx.obj["sceptre_dir"], environment, ctx.obj["options"])
    response = env.stacks[stack].describe_outputs()

    if export == "envvar":
        write("\n".join(
            [
                "export SCEPTRE_{0}={1}".format(
                    output["OutputKey"], output["OutputValue"]
                )
                for output in response
            ]
        ))
    else:
        write(response, ctx.obj["output_format"])


@cli.command(name="describe-env")
@environment_options
@click.pass_context
@catch_exceptions
def describe_env(ctx, environment):
    """
    Describes the stack statuses.

    Describes ENVIRONMENT stack statuses.
    """
    env = get_env(ctx.obj["sceptre_dir"], environment, ctx.obj["options"])
    responses = env.describe()
    write(responses, ctx.obj["output_format"])


@cli.command(name="set-stack-policy")
@stack_options
@click.option("--policy-file")
@click.pass_context
@catch_exceptions
def set_stack_policy(ctx, environment, stack, policy_file):
    """
    Sets stack policy.

    Sets a specific ENVIRONMENT/STACK policy.
    """
    env = get_env(ctx.obj["sceptre_dir"], environment, ctx.obj["options"])
    env.stacks[stack].set_policy(policy_file)


@cli.command(name="get-stack-policy")
@stack_options
@click.pass_context
@catch_exceptions
def get_stack_policy(ctx, environment, stack):
    """
    Displays the stack policy used.

    Prints ENVIRONMENT/STACK policy.
    """
    env = get_env(ctx.obj["sceptre_dir"], environment, ctx.obj["options"])
    response = env.stacks[stack].get_policy()

    write(response.get('StackPolicyBody', {}))


def get_env(sceptre_dir, environment_path, options):
    """
    Initialises and returns a sceptre.environment.Environment().

    :param sceptre_dir: The absolute path to the Sceptre directory.
    :type project dir: str
    :param environment_path: The name of the environment.
    :type environment_path: str
    :param options: A dict of key-value pairs to update self.config with.
    :type debug: dict
    :returns: An Environment.
    :rtype: sceptre.environment.Environment
    """
    return Environment(
        sceptre_dir=sceptre_dir,
        environment_path=environment_path,
        options=options
    )


def setup_logging(debug, no_colour):
    """
    Sets up logging.

    By default, the python logging module is configured to push logs to stdout
    as long as their level is at least INFO. The log format is set to
    "[%(asctime)s] - %(name)s - %(message)s" and the date format is set to
    "%Y-%m-%d %H:%M:%S".

    After this function has run, modules should:

    .. code:: python

        import logging

        logging.getLogger(__name__).info("my log message")

    :param debug: A flag indication whether to turn on debug logging.
    :type debug: bool
    :no_colour: A flag to indicating whether to turn off coloured output.
    :type no_colour: bool
    :returns: A logger.
    :rtype: logging.Logger
    """
    if debug:
        sceptre_logging_level = logging.DEBUG
        logging.getLogger("botocore").setLevel(logging.INFO)
    else:
        sceptre_logging_level = logging.INFO
        # Silence botocore logs
        logging.getLogger("botocore").setLevel(logging.CRITICAL)

    formatter_class = Formatter if no_colour else ColouredFormatter

    formatter = formatter_class(
        fmt="[%(asctime)s] - %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    log_handler = logging.StreamHandler()
    log_handler.setFormatter(formatter)
    logger = logging.getLogger("sceptre")
    logger.addHandler(log_handler)
    logger.setLevel(sceptre_logging_level)
    return logger


def write(var, output_format="str"):
    """
    Writes ``var`` to stdout. If output_format is set to "json" or "yaml",
    write ``var`` as a JSON or YAML string.

    :param var: The object to print
    :type var: obj
    :param output_format: The format to print the output as. Allowed values: \
    "str", "json", "yaml"
    :type output_format: str
    """
    if output_format == "json":
        encoder = CustomJsonEncoder()
        stream = encoder.encode(var)
    if output_format == "yaml":
        stream = yaml.safe_dump(var, default_flow_style=False)
    if output_format == "str":
        stream = var
    click.echo(stream)


class ColouredFormatter(Formatter):
    """
    ColouredFormatter add colours to all stack statuses that appear in log
    messages.
    """

    stack_status_colourer = StackStatusColourer()

    def format(self, record):
        """
        Colours and returns all stack statuses in ``record``.

        :param record: The log item to format.
        :type record: str
        :returns: str
        """
        response = super(ColouredFormatter, self).format(record)
        coloured_response = self.stack_status_colourer.colour(response)
        return coloured_response


class CustomJsonEncoder(JSONEncoder):
    """
    CustomJsonEncoder is a JSONEncoder which encodes all items as JSON by
    calling their __str__() method.
    """

    def default(self, item):
        """
        Returns stringified version of item.

        :param item: An arbitrary object to stringify.
        :type item: obj
        :returns: The stringified object.
        :rtype: str
        """
        return str(item)
