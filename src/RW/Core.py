"""
Core keyword library

Scope: Global
"""

import re
import os
import socket
import shutil
from urllib.parse import urlparse
import requests
from typing import Union, List, Dict
from prometheus_client import CollectorRegistry
from robot.libraries.BuiltIn import BuiltIn
from RW import platform, fetchsecrets

import json, typing
import textwrap
import datetime
from collections import OrderedDict

from opentelemetry import metrics
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    PeriodicExportingMetricReader,
)
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter


registry = CollectorRegistry()
prometheus_gchs = {}

SHARED_LOCATION_SERVICES_NAMESPACE = "location"


class Core:
    """Core keyword library defines keywords used to access key platform features from robot code."""

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    # Issue severity for add_issue
    SEV_1 = 1 # Use in cases where the service is most likely unavailable and will not recover without human intervention
    SEV_2 = 2 # Use in cases where a service is downgraded, slow or may recover
    SEV_3 = 3 # Use in cases where a human needs to take a look eventually (possibly cosmetic issue)
    SEV_4 = 4 # Use in cases where this is unknown and unlikely high severity


    def __init__(self) -> None:
        self.builtin = BuiltIn()  # TODO - use get library instance
        self._report = OrderedDict()  # Our internal struct for Task Set reports

        self.otel_enabled = False
        self.otel_endpoint = None
        self.otel_provider = None
        self.otel_meter = None
        # Attempt to read environment variable (or use default),
        # and then validate that the hostname is resolvable before init.
        otel_endpoint = os.environ.get("RW_OTEL_COLLECTOR_ENDPOINT", "").strip()
        if not otel_endpoint:
            # Fallback to a default endpoint if none was provided
            otel_endpoint = "http://otel-collector:4318/v1/metrics"

        if self._is_collectord_host_resolvable(otel_endpoint):
            self.init_otel(otel_endpoint)
        else:
            # Log that we’re skipping OTEL init
            self.debug_log(
                f"OTEL endpoint {otel_endpoint} not resolvable. "
                "Skipping OTEL initialization."
            )

    def _is_collectord_host_resolvable(self, endpoint: str) -> bool:
        """
        Quick check to see if the hostname in `endpoint` is resolvable.
        Returns True if we can resolve the host, otherwise False.
        """
        parsed = urlparse(endpoint)
        if not parsed.hostname:
            # The URL is malformed or missing hostname
            self.debug_log(f"Cannot parse a hostname from OTEL endpoint: {endpoint}")
            return False

        try:
            socket.gethostbyname(parsed.hostname)
            return True
        except Exception as ex:
            self.debug_log(
                f"Failed to resolve hostname '{parsed.hostname}' from OTEL endpoint '{endpoint}': {ex}"
            )
            return False

    def init_otel(self, endpoint: str):
        """
        Initialize the OTEL pipeline just once:
         1) Create MeterProvider with a periodic export loop
         2) Register it as the global provider
         3) Keep references so we can record in push_metric
        """
        resource = Resource.create({"service.name": "rw_sli_service"})

        exporter = OTLPMetricExporter(endpoint=endpoint)
        # Example: Export every 10 seconds
        reader = PeriodicExportingMetricReader(exporter, export_interval_millis=10_000)

        provider = MeterProvider(resource=resource, metric_readers=[reader])
        metrics.set_meter_provider(provider)

        self.otel_provider = provider
        self.otel_meter = metrics.get_meter("rw_sli_meter")
        self.otel_endpoint = endpoint
        self.otel_enabled = True
        self.debug_log(f"Successfully initialized OTEL with endpoint: {endpoint}")


    def about_fetchsecrets_plugin(self):
        return fetchsecrets.about()

    def health_check_fetchsecrets_plugin(self):
        return fetchsecrets.health_check()

    def get_authenticated_session(self):
        return platform.get_authenticated_session()

    def rw_get(self, path, params):
        session = self.get_authenticated_session()
        return session.get(path, params=params, verify=fetchsecrets.REQUEST_VERIFY)

    def rw_post(self, path, data):
        session = self.get_authenticated_session()
        return session.post(path, data=data, verify=fetchsecrets.REQUEST_VERIFY)

    def import_secret(self, varname: str, description: str = None, example: str = None, pattern: str = None, optional: bool = False, **kwargs):
        """Import a secret from the configured secret provider.
        
        Args:
            varname: The variable name for the secret
            description: Optional description for documentation
            example: Optional example value for documentation  
            pattern: Optional pattern for validation
            optional: If True, returns None instead of failing when secret is not found
            **kwargs: Additional keyword arguments
            
        Returns:
            platform.Secret: Secret object, or None if optional=True and secret not found
            
        Raises:
            ImportError: If secret not found and optional=False
        """
        try:
            env_var_url = "RW_SECRETS_KEYS"
            skeys_json_str = os.getenv(env_var_url)
            if not skeys_json_str:
                if optional:
                    self.info_log(f"Optional secret '{varname}': No secrets configuration found ({env_var_url} not set). Setting to None.")
                    self.builtin.set_suite_variable("${" + varname + "}", None)
                    return None
                raise ImportError(
                    f"Import Secret {varname}: No secrets provided in configuration ({env_var_url} has no value set)"
                )
            
            secrets_config = json.loads(skeys_json_str)
            key = secrets_config.get(varname)
            
            if key is None:
                if optional:
                    self.info_log(f"Optional secret '{varname}': Not found in secrets configuration. Setting to None.")
                    self.builtin.set_suite_variable("${" + varname + "}", None)
                    return None
                raise ImportError(f"Import Secret {varname}: Secret key not found in configuration")
            
            val = fetchsecrets.read_secret(key)
            ret = platform.Secret(varname, val)
            self.builtin.set_suite_variable("${" + varname + "}", ret)
            return ret
            
        except (fetchsecrets.SecretNotFoundError, ValueError, json.JSONDecodeError) as e:
            if optional:
                self.info_log(f"Optional secret '{varname}': Failed to retrieve secret ({str(e)}). Setting to None.")
                self.builtin.set_suite_variable("${" + varname + "}", None)
                return None
            
            # This exception block is for backwards compatibility only as we transition the
            # go operator that provides RW_SECRETS_KEYS.  TODO - remove this when all the dev envs
            # have been updated
            if isinstance(e, fetchsecrets.SecretNotFoundError):
                # Temporarily, retry with the key as the varname
                try:
                    key = varname
                    val = fetchsecrets.read_secret(key)
                    ret = platform.Secret(key, val)
                    self.builtin.set_suite_variable("${" + key + "}", ret)
                    return ret
                except Exception:
                    pass  # Fall through to re-raise original error
            
            raise ImportError(f"Import Secret {varname}: {str(e)}")
    
    def get_credential_cache_info(self):
        """Get information about credential caching configuration.
        
        Returns:
            dict: Cache configuration and shared filesystem directory info
        """
        try:
            return fetchsecrets.get_cache_stats()
        except Exception as e:
            self.error_log(f"Error getting cache info: {e}")
            return {}
    
    def clear_secret_cache(self):
        """Clear in-memory secret cache.
        
        Note: Credential caching is handled via shared filesystem directories.
        """
        try:
            fetchsecrets.clear_all_caches()
            self.info_log("Cleared in-memory secret cache")
        except Exception as e:
            self.error_log(f"Error clearing secret cache: {e}")
    
    def log_credential_cache_status(self):
        """Log comprehensive credential cache status for troubleshooting.
        
        This logs detailed information about:
        - Current credential context and hash
        - Cache directory locations and statistics
        - Environment variables affecting credential context
        - Authentication state for different providers
        """
        try:
            cache_info = fetchsecrets.log_credential_cache_status()
            self.info_log("Credential cache status logged - check logs for details")
            return cache_info
        except Exception as e:
            self.error_log(f"Error logging credential cache status: {e}")
            return {}

    def import_optional_secret(self, varname: str, description: str = None, example: str = None, pattern: str = None, **kwargs):
        """Import an optional secret that may not be set.
        
        This is a convenience method that calls import_secret with optional=True.
        If the secret is not found or is marked with an optional value (NONE, OPTIONAL, etc.),
        it will return None instead of raising an error.
        
        Args:
            varname: The variable name for the secret
            description: Optional description for documentation
            example: Optional example value for documentation  
            pattern: Optional pattern for validation
            **kwargs: Additional keyword arguments
            
        Returns:
            platform.Secret: Secret object, or None if secret is optional/not found
        """
        return self.import_secret(varname, description=description, example=example, 
                                pattern=pattern, optional=True, **kwargs)

    def import_service(
        self, varname: str, description: str = None, example: str = None, default: str = None, **kwargs
    ):
        """Creates an instance of rwplatform.Service for use by other keywords.

        Note that the description, example, default args are parsed in RunWhen static
        analysis for type hinting in the GUI, and are not (currently) used here.
        """
        env_var_url = "RW_SVC_URLS"
        urls_json_str = os.getenv(env_var_url)
        if not urls_json_str:
            raise ImportError(
                f"Import Service {varname}: No services provided in configuration ({env_var_url} has no value set)"
            )
        url = json.loads(urls_json_str).get(varname)
        if not url:
            raise ImportError(f"Import Service {varname}: No service provided, found only ({urls_json_str})")
        ret = platform.Service(url)
        self.builtin.set_suite_variable("${" + varname + "}", ret)
        return ret

    # Pattern used to replace %{} instances with \%{}.
    # %{} is the template syntax for looking up an environment variable in robot framework.
    # %{} is commonly used by curl and other cli tools for dynamic output templating which causes
    # robotframework to evaluate %{some_var}, and if some_var is not an actual env (which it won't be) then it fails.
    # robotframework will ignore %{some_var} if it's escaped with an '\'.
    # Docs ref: https://docs.robotframework.org/docs/variables
    rf_env_escape_pattern = re.compile(r'%(?=\{)')

    def import_user_variable(
        self,
        varname: str,
        type: str = "string",
        description: str = None,
        example: str = None,
        pattern: str = None,
        enum: str = None,
        format: str = None,
        default: str = None,
        **kwargs,
    ) -> str:
        """
        Imports a variable set by the user, raises error if not available.

        Example:
          Import User Variable   FOO
          Debug Log              ${FOO}

        Throws an error if the config variable doesn't exist and no default is
        provided (Implementation subject to change)

        Impl note - the optional args correspond to JSONSchema / OpenAPIv3 properties that are used in RW's static
        analysis of robot code to do type hinting and validation in the ui and pre-commit hooks, i.e. they
        are not (currently) consumed in this code.  For type, we currently support "string", "boolean", "number",
        "integer".  Description and Example should be short phrase or single sentence strings.  Enum, for Robot
        ease-of-use, should be a string of comma-separated values (typically strings themselves) without escaped
        quotes or brackets, e.g. the python call would look like enum="option-1,option-2,option-3" and the Robot
        call looks like enum=option-1,option-2,option-3.
        """
        # IMPL note - this should *not* be exposed as a python interface, thus unavailable in
        # RW.platform
        if varname.startswith("RW_"):
            # Special case: Allow RW_LOOKBACK_WINDOW to be overridden as a user variable
            # ONLY for runbooks (not SLIs). Runbooks have RW_RUNREQUEST_ID set.
            if varname == "RW_LOOKBACK_WINDOW":
                # Check if we're in a runbook context by looking for RW_RUNREQUEST_ID
                runrequest_id = os.getenv("RW_RUNREQUEST_ID")
                if runrequest_id:
                    # We're in a runbook - allow the override with clear logging
                    self.info_log(
                        f"RUNBOOK OVERRIDE: {varname!r} is being imported as a user variable "
                        f"in runbook context (RW_RUNREQUEST_ID={runrequest_id}). "
                        f"This allows runbooks to accept user-customized lookback windows. "
                        f"SLI files should use 'Import Platform Variable' instead."
                    )
                else:
                    # We're in an SLI context - don't allow the override
                    self.fatal_error(
                        f"Variable {varname!r} is a RunWhen platform variable and cannot be "
                        f"imported as a user variable in SLI context. SLI files must use "
                        f"'Import Platform Variable {varname}' instead. Only runbooks may "
                        f"override this as a user variable for customization."
                    )
            else:
                self.fatal_error(
                    f"Variable {varname!r} is a RunWhen platform variable. Use Import Platform Variable keyword."
                )
        val = os.getenv(varname)

        # Handle edge case where configprovided not passed to pod env, but default is available
        if val is None and default is not None:
            val = default

        # An empty string is a valid variable
        if val is None:
            raise ImportError(f"Import User Variable: {varname} has no value configured.")

        # Escape RobotFramework Environment Variable Lookup Characters
        val = self.rf_env_escape_pattern.sub('\\%', val)
        self.builtin.set_suite_variable("${" + varname + "}", val)
        return val

    def import_platform_variable(self, varname: str, *args, **kwargs) -> str:
        """
        Imports a variable set by the platform, making it available in the robot runtime
        as a suite variable.

        Raises ValueError if this isn't a valid platform variable name, or ImportError if not available.

        :param str: Name to be used both to lookup the config val and for the
            variable name in robot
        :return: The value found
        """
        val = platform.import_platform_variable(varname)
        self.builtin.set_suite_variable("${" + varname + "}", val)
        return val

    def import_memo_variable(self, key: str, *args, **kwargs):
        """
        Imports a value from the "memo" dict created when the request to run
        was first submitted.  (Note - this is specific to runbooks.  If an SLI,
        this simply returns None.). If the memo was not found or this key was not
        found, simply return None.
        Like Import Platform Variable, this will both set a suite level variable
        to key with the value found and will return the value.
        """
        val = platform.import_memo_variable(key)
        self.builtin.set_suite_variable("${" + key + "}", val)
        return val

    def upload_session_file(self, filename: str, contents: str):
        """Expose platform.fetchfiles as robot keywords"""
        return platform.upload_session_file(filename, contents)

    def get_session_file(self, filename: str):
        """Returns the contents of a session file, or None if the file did not exist"""
        return platform.get_session_file(filename)

    def run_keyword_and_push_metric(self, name: str, *args) -> None:
        """
        Run a keyword and push the returned metric up to the MetricStore.
        This should only be called once per sli.robot file.

        Example:
          Run Keyword and Push Metric   Ping Hosts and Return Highest Avg RTT
          ...                           hosts=${PING_HOSTS}
        """
        self.debug_log(f"Running keyword: {name}, arguments: {args}")
        result = self.builtin.run_keyword(name, *args)
        self.debug_log(f"Push metric result: {result}")
        return self.push_metric(result)

    GAUGE = "gauge"
    COUNTER = "counter"
    HISTOGRAM = "histogram"
    UNTYPED = "untyped"

    def _coerce_to_numeric(self, val):
        """
        Attempts to convert string values to either int or float, if possible.
        Otherwise, returns the value as-is.
        """
        # If it's already numeric, just return
        if isinstance(val, (int, float)):
            return val

        # If it's a string, strip whitespace and try int or float
        if isinstance(val, str):
            s = val.strip()
            try:
                return int(s)
            except ValueError:
                pass
            try:
                return float(s)
            except ValueError:
                pass

        # If we couldn't parse, or not a string, just return original
        return val

    def push_metric(
        self,
        value=None,
        sub_name=None,
        metric_type=UNTYPED,
        dry_run=False,
        **kwargs,
    ):
        """
        Push a metric to an OpenTelemetry Collector if self.otel_enabled == True.
        If OTEL is not initialized, we attempt to re-init. Includes minimal retry logic.
        """
        # Attempt to coerce the incoming value to int/float if possible
        value = self._coerce_to_numeric(value)

        labels = kwargs if kwargs else {}

        # Check if RW_LOCATION is defined, otherwise skip (consistent with original code).
        try:
            self.import_platform_variable("RW_LOCATION")
        except ImportError:
            msg = f"Metric value={value!r}, labels={labels}\nRW_LOCATION is not defined. Not pushing metric."
            self.debug_log(msg)
            return value

        # The base metric name
        mname = self.import_platform_variable("RW_SLI_METRIC_NAME")
        if sub_name:
            mname = f"{mname}__{sub_name}"

        # The workspace is used as a required label
        workspace = self.import_platform_variable("RW_WORKSPACE")
        labels["workspace"] = workspace

        if dry_run:
            msg = (
                f"Push metric [DRY RUN]: name={mname!r}, value={value!r}, "
                f"labels={labels}, type={metric_type}"
            )
            self.debug_log(msg)
            return value

        # Minimal retry logic in case the OTEL collector was temporarily unavailable
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            # If we don't have OTEL or it was disabled by a previous error, try re-init
            if not self.otel_enabled or not self.otel_meter:
                self.debug_log(
                    f"OTEL not enabled or meter missing. Attempting re-init (Attempt {attempt}/{max_retries})."
                )
                try:
                    self.init_otel(self.otel_endpoint)
                except Exception as reinit_ex:
                    self.warning_log(
                        f"Re-init OTEL failed (attempt {attempt}/{max_retries}): {reinit_ex}"
                    )

            if self.otel_enabled and self.otel_meter:
                try:
                    # Create (or retrieve) the instrument each time
                    if metric_type == self.COUNTER:
                        metric = self.otel_meter.create_counter(mname)
                        metric.add(value, attributes=labels)
                    else:
                        metric = self.otel_meter.create_gauge(mname)
                        metric.set(value, attributes=labels)

                    self.info_log(
                        f"Push Metric to OTEL (endpoint={self.otel_endpoint}): name={mname}, "
                        f"value={value}, labels={labels}, type={metric_type}"
                    )
                    break  # success, no need to retry further
                except Exception as ex:
                    self.warning_log(
                        f"Error pushing metric to OTEL (attempt {attempt}/{max_retries}): {ex}"
                    )
                    # Mark ourselves disabled so we can re-init next loop iteration
                    self.otel_enabled = False

            else:
                # If we're here, re-init failed immediately
                self.warning_log(f"OTEL not available (attempt {attempt}/{max_retries}).")

            if attempt == max_retries:
                # We've tried re-init and push up to max_retries times
                self.error_log(
                    f"Failed to push metric to OTEL after {max_retries} attempts. "
                    f"Metric: {mname}, Value: {value}, Labels: {labels}"
                )

        return value

    def task_failure(self, msg: str) -> None:
        """
        Report a validation failure. Skip to the next task/test.

        :param msg: Log message
        """
        raise platform.TaskFailure(msg)

    def task_error(self, msg: str) -> None:
        """
        Report an error in execution. Skip to the next task/test.

        :param msg: Log message
        """
        raise platform.TaskError(msg)

    def fatal_error(self, msg: str) -> None:
        """
        Report a fatal error. Stop the whole robot execution.

        :param msg: Log message
        """
        raise platform.FatalError(msg)

    def error_log(self, *args, **kwargs) -> None:
        """
        Error log

        :param msg: Log message
        """
        platform.error_log(*args, **kwargs)

    def warning_log(self, *args, **kwargs) -> None:
        """
        Warning log

        :param msg: Log message
        """
        platform.warning_log(*args, **kwargs)

    def info_log(self, *args, **kwargs) -> None:
        """
        Info log

        :param msg: Log message
        """
        platform.info_log(*args, **kwargs)

    def inspect_object_attributes(self, d, console: Union[str, bool] = False) -> None:
        platform.debug_log(dir(d), console=console)

    def debug_log(self, *args, **kwargs) -> None:
        """
        Debug log

        :param str: Log message
        :param console: Write log message to console (default is true)
        """
        platform.debug_log(*args, **kwargs)

    def trace_log(self, *args, **kwargs) -> None:
        """
        Trace log

        :param msg: Log message
        """
        platform.trace_log(*args, **kwargs)

    def console_log(self, *args, **kwargs) -> None:
        platform.console_log(*args, **kwargs)

    def console_log_if_true(self, *args, **kwargs) -> None:
        """
        If the condition is evaluated to true, the message is written to the
        console.

        :param condition: Condition to evaluate as a Python expression
        :param msg: Log message
        """
        platform.console_log_if_true(*args, **kwargs)

    def add_issue(self,
        severity: int,
        title: str,
        expected: str,
        actual: str,
        reproduce_hint: str,
        observed_at: str = None,
        next_steps: str = None,
        details: str = None,
        summary: str = None,
        **kwargs
        ) -> None:
        """
        Generic keyword used to raise a human-facing issue.  Unlike reports that are intended
        to help recreate
        
        Args:
            severity: Issue severity level (use Core.SEV_1, SEV_2, SEV_3, or SEV_4)
            title: Brief title describing the issue
            expected: What was expected to happen
            actual: What actually happened
            reproduce_hint: Instructions on how to reproduce the issue
            next_steps: Optional recommended next steps to resolve the issue
            details: Optional additional details about the issue
            observed_at: Timestamp of when the issue was observed
            summary: str, issue-summary sent by codebundle, if available skip issue-summarization via LLM
            **kwargs: Additional custom fields to include in the issue record
        
        The **kwargs allow you to add custom fields to the issue record, which will be
        included in both the issues.jsonl file and the report object. Examples:
        - component="database", environment="production"
        - priority="high", assignee="team-lead"
        - tags=["urgent", "outage"], custom_field="custom_value"
        """
        if not severity in [Core.SEV_1, Core.SEV_2, Core.SEV_3]:
            severity = Core.SEV_4

        task_name = BuiltIn().get_variable_value("${TEST NAME}")
        task_doc = BuiltIn().get_variable_value("${TEST DOCUMENTATION}")
        task_status = BuiltIn().get_variable_value("${TEST STATUS}")
        task_msg = BuiltIn().get_variable_value("${TEST MESSAGE}")

        if observed_at is None:
            observed_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Each issue should show up as a line in the file
        # summary into a single "metadata" dict
        #   to easily drop before creating the DB Issue row
        issues_line = {
            "severity": severity,
            "title": title,
            "expected": expected,
            "actual": actual,
            "reproduceHint": reproduce_hint,
            "nextSteps": next_steps,
            "details": details,
            "taskName": task_name,
            "taskDoc": task_doc,
            "taskStatus": task_status,
            "taskMessage": task_msg,
            "observedAt": observed_at,
            "metadata": {
                "summary": summary
            }
        }
        
        # Add any additional kwargs to the issues_line
        issues_line.update(kwargs)

        # stream this report line out to the report.jsonl file
        output_dir = BuiltIn().get_variable_value("${OUTPUTDIR}")
        with open(os.path.join(output_dir, "issues.jsonl"), "a") as f:
            f.write(json.dumps(issues_line))
            f.write("\n")
            f.close()

        # in parallel, flag each issue in the report so we can see where in
        # report processing it showed up
        report_obj = {
            "severity": severity,
            "title": title,
            "expected": expected,
            "actual": actual,
            "reproduceHint": reproduce_hint,
            "nextSteps": next_steps,
            "details": details,
            "observedAt": observed_at,
        }
        
        # Add any additional kwargs to the report_obj
        report_obj.update(kwargs)
        
        self.add_to_report(obj = report_obj, fmt="issue")
        return

    def add_to_report(
        self,
        obj: object,
        fmt: str = "p",
        **kwargs,
    ) -> None:
        """
        Generic keyword used to add to reports.  The common case is adding a string
        with "p" formatting, but this is intended to be extensible to include pre-formatted
        blocks, code blocks, links and potentially chart data.
        """
        # Serialize and deserialize object to json as both a deep copy and to
        # suss out any errors
        obj_str = json.dumps(obj)
        obj = json.loads(obj_str)
        kwargs_str = json.dumps(kwargs)
        kwargs = json.loads(kwargs_str)
        task_name = BuiltIn().get_variable_value("${TEST NAME}")
        task_doc = BuiltIn().get_variable_value("${TEST DOCUMENTATION}")
        task_status = BuiltIn().get_variable_value("${TEST STATUS}")
        task_msg = BuiltIn().get_variable_value("${TEST MESSAGE}")

        # Note that while in the extreme case of a task that has many Add To Report keywords this is going to be very inefficient,
        # in the common case where a task has one, perhaps two of these lines, restating the taskDoc and updating the status and
        # err message seems reasonable.
        report_line = {
            "obj": obj,
            "fmt": fmt,
            "kwargs": kwargs,
            "taskName": task_name,
            "taskDoc": task_doc,
            "taskStatus": task_status,
            "taskMessage": task_msg,
        }

        # stream this report line out to the report.jsonl file
        output_dir = BuiltIn().get_variable_value("${OUTPUTDIR}")
        with open(os.path.join(output_dir, "report.jsonl"), "a") as f:
            f.write(json.dumps(report_line))
            f.write("\n")
            f.close()

    def add_code_to_report(self, obj: str) -> None:
        """Add a block of text to the report that should follow
        similar formatting rules as the html tag "code"
        """
        return self.add_to_report(obj=str(obj), fmt="code")

    def add_pre_to_report(self, obj: str) -> None:
        """Add a block fo text to the report that should follow
        similar formatting rules as the html tag "pre"
        """
        return self.add_to_report(obj=str(obj), fmt="pre")

    def add_url_to_report(self, url: str, text: str = None) -> None:
        """Add a url fo text to the report that should follow
        similar formatting rules as the html tag "pre"
        """
        return self.add_to_report(obj=str(url), fmt="a", text=text)

    def add_json_to_report(self, obj) -> None:
        """Add a json string or json serializable object to the report implying to
        most formatters that it should be pretty printed. Internally this is stored
        as an object rather than string form.
        """
        if isinstance(obj, str):  # If we got a string, make sure it is valid json
            obj = json.loads(obj)
        else:
            json.dumps(obj)
        return self.add_to_report(obj=obj, fmt="json")

    def add_table_to_report(self, about: str, body, head: typing.List[str]) -> None:
        """Adds a table of data to the report.  The 'about' string should be
        rendered to the left, right or below the table.  The body is expected to
        be a 2d array of strings.  head is a 1d array of strings.  The gist
        is to map closely to an html table element.
        """
        body_o = body
        head_o = head
        return self.add_to_report(obj=about, fmt="table", body=body_o, head=head_o)

    def add_datagrid_to_report(
        self,
        about: str,
        rows,
        columns: typing.List[str],
        page_size: int,
        rows_per_page_options,
    ) -> None:
        """Adds an object that will map closely to a MUI datagrid.  For args,
        see https://mui.com/x/react-data-grid/
        """
        return self.add_to_report(
            obj=str(about),
            fmt="table",
            rows=rows,
            columns=columns,
            page_size=page_size,
            rows_per_page_options=rows_per_page_options,
        )

    def get_report_data(self) -> object:
        """Return the data for this report as an object (not formatted)"""
        return self._report

    def get_report_data_as_string(self) -> str:
        """Return the data for this report (with all formatting hints)
        as a string
        """
        return json.dumps(self._report, indent=2)

    def _code_to_string(self, obj) -> str:
        """Converts a "code" obj to a string"""
        return str(obj)

    def _pre_to_string(self, obj) -> str:
        """Converts a "pre" obj to a string"""
        return str(obj)

    def _p_to_string(self, obj) -> str:
        """Converts a "p" obj to a string"""
        lines = textwrap.wrap(" ".join(str(obj).split()))
        return "\n".join(lines)

    def _a_to_string(self, obj, text) -> str:
        """Converts a "a" obj to a string"""
        if text:
            return f"{text} ({obj})"
        else:
            return f"{obj}"

    def _json_to_string(self, obj) -> str:
        """Converts a "json" string or json-serializable object to a (prettified) string"""
        if isinstance(obj, str):
            obj = json.loads(obj)
        return json.dumps(obj, indent=2)

    def _table_to_string(self, about, body, head) -> str:
        """Converts a "table" obj to a string"""
        max_lens = []  # Calculate max length of the text in each column
        for col in range(0, len(head)):
            max_lens.append(len(str(head[col])))
        for row in body:
            for col in range(0, len(row)):
                max_lens[col] = max(max_lens[col], len(str(row[col])))
        ret = []
        ret_row = []
        for i in range(0, len(head)):
            txt = head[i]
            max_len = max_lens[i]
            ret_row.append(f"{txt:>{max_len}}")
        ret.append("|".join(ret_row))
        for row in body:
            ret_row = []
            for i in range(0, len(row)):
                txt = row[i]
                max_len = max_lens[i]
                ret_row.append(f"{txt:>{max_len}}")
            ret.append("|".join(ret_row))
        ret.append(about)
        return "\n".join(ret)

    def _datagrid_to_string(self, about, rows, columns) -> str:
        return self._json_to_string(rows)

    def export_report_as_string(self) -> str:
        """While most report formatting is done outside of this
        library, a very simple formatter is included here for
        convenience and reference
        """
        ret = []
        for task_name, report_lines in self._report.items():
            ret.append(f"\n\n{task_name}")
            ret.append(str("-" * len(task_name)))
            for report_line in report_lines:
                fmt = report_line["fmt"]
                obj = report_line["obj"]
                s = ""
                kwargs = report_line["kwargs"]
                if fmt == "p":
                    s = self._p_to_string(obj=obj)
                elif fmt == "pre":
                    s = self._pre_to_string(obj=obj)
                elif fmt == "code":
                    s = self._code_to_string(obj=obj)
                elif fmt == "a":
                    s = self._a_to_string(obj=obj, text=kwargs.get("text"))
                elif fmt == "json":
                    s = self._json_to_string(obj=obj)
                elif fmt == "table":
                    s = self._table_to_string(
                        about=obj,
                        body=kwargs["body"],
                        head=kwargs["head"]
                    )
                elif fmt == "datagrid":
                    s = self._datagrid_to_string(
                        about=obj,
                        rows=kwargs["rows"],
                        columns=kwargs["colums"]
                    )
                else:
                    s = str(obj)
                ret.append(str(s))
        return "\n".join(ret)

    def shell(
        self,
        cmd: str,
        service: platform.Service,
        request_secrets: List[platform.ShellServiceRequestSecret] = None,
        secret: platform.Secret = None,
        secret_as_file: bool = False,
        env: dict = None,
        files: dict = None,
    ):
        """Robot Keyword to expose rwplatform.execute_shell_command.

        For robot syntax convenience, a single secret and secret_as_file may be given instead of or in addition
        to the request_secrets arg (an array of ShellServiceRequestSecrets).  This will wrap secret and secret_as_file in
        to a one-item list of ShellServiceRequestSecrets, adding the request_secrets list if one was given.
        """
        if not isinstance(service, platform.Service):
            raise ValueError(
                f"service {service} is not an instance of rwplatform.Service - check arg type from Robot, see import_service"
            )
        request_secrets_p = request_secrets[:] if request_secrets else []
        if secret:
            ssrs = platform.ShellServiceRequestSecret(secret=secret, as_file=secret_as_file)
            request_secrets_p.append(ssrs)
        return platform.execute_shell_command(
            cmd=cmd, service=service, request_secrets=request_secrets_p, env=env, files=files
        )

    def normalize_lookback_window(self, seconds: int, format_type: int) -> str:
        """
        Normalize the lookback window to a string

        Args:
            seconds: The number of seconds to normalize
            format_type: The format type to use (h or m) or (hours or minutes) or None
            1: will return just the number of minutes without any units
            2: will return the number of minutes/hours with the short hand unit (s, m, h)
            3: will return the number of minutes/hours with the long hand unit (seconds, minutes, hours)

        Returns:
            str: The normalized lookback window
        """
        normalized_lookback_window = ""
        if format_type == 1:
            normalized_lookback_window = f"{seconds // 60}"
        elif format_type == 2:
            if seconds >= 3600:
                normalized_lookback_window = f"{seconds // 3600}h"
            if seconds >= 60:
                normalized_lookback_window = f"{seconds // 60}m"
            else:
                normalized_lookback_window = f"{seconds}s"
        elif format_type == 3:
            for name, unit in (("hour", 3600), ("minute", 60), ("second", 1)):
                value = seconds // unit
                if value:
                    normalized_lookback_window = f"{value} {name}" if value == 1 else f"{value} {name}s"
                    break
        else:
            if seconds >= 3600:
                normalized_lookback_window = f"{seconds // 3600}h"
            if seconds >= 60:
                normalized_lookback_window = f"{seconds // 60}m"
            else:
                normalized_lookback_window = f"{seconds}s"
        self.info_log(f"Normalized lookback window: {normalized_lookback_window}")
        return normalized_lookback_window