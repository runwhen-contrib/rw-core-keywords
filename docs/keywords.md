# RunWhen CodeCollection Libraries Documentation

## Overview

This documentation covers the Python libraries that provide Robot Framework keywords for the RunWhen CodeCollection. These keywords are designed to help you create effective runbooks and SLIs for troubleshooting and monitoring.

**Total Libraries:** 6  
**Total Keywords:** 126

## Getting Started

To use these keywords in your Robot Framework files:

1. Import the library in your Robot Framework file
2. Use the keywords in your test cases or tasks
3. Refer to the examples below for syntax

### Example Robot Framework Usage

```robotframework
*** Settings ***
Library    RW.Core
Library    RW.K8s

*** Tasks ***
Check Pod Status
    ${pods}=    RW.K8s.Get Pods    namespace=default
    RW.Core.Add Pre To Report    Found ${pods} pods
```

## Table of Contents

- [Core Operations](#core-operations)
- [Kubernetes](#kubernetes)
- [File Operations](#file-operations)
- [HTTP/API](#httpapi)
- [Monitoring & Metrics](#monitoring--metrics)
- [Utilities](#utilities)
- [Other](#other)

## Core Operations

### Core Library

#### Core.about_fetchsecrets_plugin

---

#### Core.health_check_fetchsecrets_plugin

---

#### Core.get_authenticated_session

---

#### Core.rw_get

**Arguments:**

- `path`
- `params`

---

#### Core.rw_post

**Arguments:**

- `path`
- `data`

---

#### Core.import_secret

Import a secret from the configured secret provider.

Args:
    varname: The variable name for the secret
    description: Optional description for documentation
    example: Optional example value for documentation  
    pattern: Optional pattern for validation
    optional: If True, returns None instead of failing when secret is not found
    **kwargs: Additional keyword arguments
    

    
Raises:
    ImportError: If secret not found and optional=False

**Arguments:**

- `varname`
- `description`
- `example`
- `pattern`
- `optional`

**Returns:**

- platform.Secret: Secret object, or None if optional=True and secret not found

---

#### Core.import_optional_secret

Import an optional secret that may not be set.

This is a convenience method that calls import_secret with optional=True.
If the secret is not found or is marked with an optional value (NONE, OPTIONAL, etc.),
it will return None instead of raising an error.

Args:
    varname: The variable name for the secret
    description: Optional description for documentation
    example: Optional example value for documentation  
    pattern: Optional pattern for validation
    **kwargs: Additional keyword arguments

**Arguments:**

- `varname`
- `description`
- `example`
- `pattern`

**Returns:**

- platform.Secret: Secret object, or None if secret is optional/not found

---

#### Core.import_user_variable

Imports a variable set by the user, raises error if not available.

**Arguments:**

- `varname`
- `type`
- `description`
- `example`
- `pattern`
- `enum`
- `format`
- `default`

**Examples:**

```
Import User Variable   FOO
Debug Log              ${FOO}
```

---

#### Core.import_platform_variable

Imports a variable set by the platform, making it available in the robot runtime
as a suite variable.

Raises ValueError if this isn't a valid platform variable name, or ImportError if not available.

:param str: Name to be used both to lookup the config val and for the
    variable name in robot
:

**Arguments:**

- `varname`

**Returns:**

- The value found

---

#### Core.task_failure

Report a validation failure. Skip to the next task/test.

:param msg: Log message

**Arguments:**

- `msg`

---

#### Core.task_error

Report an error in execution. Skip to the next task/test.

:param msg: Log message

**Arguments:**

- `msg`

---

#### Core.fatal_error

Report a fatal error. Stop the whole robot execution.

:param msg: Log message

**Arguments:**

- `msg`

---

#### Core.error_log

Error log

:param msg: Log message

---

#### Core.warning_log

Warning log

:param msg: Log message

---

#### Core.info_log

Info log

:param msg: Log message

---

#### Core.inspect_object_attributes

**Arguments:**

- `d`
- `console`

---

#### Core.trace_log

Trace log

:param msg: Log message

---

#### Core.console_log

---

#### Core.console_log_if_true

If the condition is evaluated to true, the message is written to the
console.

:param condition: Condition to evaluate as a Python expression
:param msg: Log message

---

#### Core.add_issue

Generic keyword used to raise a human-facing issue.  Unlike reports that are intended
to help recreate

**Arguments:**

- `severity`
- `title`
- `expected`
- `actual`
- `reproduce_hint`
- `next_steps`
- `details`

---

#### Core.add_to_report

Generic keyword used to add to reports.  The common case is adding a string
with "p" formatting, but this is intended to be extensible to include pre-formatted
blocks, code blocks, links and potentially chart data.

**Arguments:**

- `obj`
- `fmt`

---

#### Core.add_code_to_report

Add a block of text to the report that should follow
similar formatting rules as the html tag "code"

**Arguments:**

- `obj`

---

#### Core.add_pre_to_report

Add a block fo text to the report that should follow
similar formatting rules as the html tag "pre"

**Arguments:**

- `obj`

---

#### Core.add_url_to_report

Add a url fo text to the report that should follow
similar formatting rules as the html tag "pre"

**Arguments:**

- `url`
- `text`

---

#### Core.add_json_to_report

Add a json string or json serializable object to the report implying to
most formatters that it should be pretty printed. Internally this is stored
as an object rather than string form.

**Arguments:**

- `obj`

---

#### Core.add_table_to_report

Adds a table of data to the report.  The 'about' string should be
rendered to the left, right or below the table.  The body is expected to
be a 2d array of strings.  head is a 1d array of strings.  The gist
is to map closely to an html table element.

**Arguments:**

- `about`
- `body`
- `head`

---

#### Core.get_report_data

Return the data for this report as an object (not formatted)

---

#### Core.get_report_data_as_string

Return the data for this report (with all formatting hints)
as a string

---

#### Core.export_report_as_string

While most report formatting is done outside of this
library, a very simple formatter is included here for
convenience and reference

---

#### task_failure

Report a validation failure. Skip to the next task/test.

:param msg: Log message

**Arguments:**

- `msg`

---

#### task_error

Report an error in execution. Skip to the next task/test.

:param msg: Log message

**Arguments:**

- `msg`

---

#### fatal_error

Report a fatal error. Stop the whole robot execution.

:param msg: Log message

**Arguments:**

- `msg`

---

#### add_issue

Generic keyword used to raise a human-facing issue.  Unlike reports that are intended
to help recreate

**Arguments:**

- `severity`
- `title`
- `expected`
- `actual`
- `reproduce_hint`
- `next_steps`
- `details`

---

#### add_to_report

Generic keyword used to add to reports.  The common case is adding a string
with "p" formatting, but this is intended to be extensible to include pre-formatted
blocks, code blocks, links and potentially chart data.

**Arguments:**

- `obj`
- `fmt`

---

#### add_code_to_report

Add a block of text to the report that should follow
similar formatting rules as the html tag "code"

**Arguments:**

- `obj`

---

#### add_pre_to_report

Add a block fo text to the report that should follow
similar formatting rules as the html tag "pre"

**Arguments:**

- `obj`

---

#### add_url_to_report

Add a url fo text to the report that should follow
similar formatting rules as the html tag "pre"

**Arguments:**

- `url`
- `text`

---

#### add_json_to_report

Add a json string or json serializable object to the report implying to
most formatters that it should be pretty printed. Internally this is stored
as an object rather than string form.

**Arguments:**

- `obj`

---

#### add_table_to_report

Adds a table of data to the report.  The 'about' string should be
rendered to the left, right or below the table.  The body is expected to
be a 2d array of strings.  head is a 1d array of strings.  The gist
is to map closely to an html table element.

**Arguments:**

- `about`
- `body`
- `head`

---

#### get_report_data

Return the data for this report as an object (not formatted)

---

#### get_report_data_as_string

Return the data for this report (with all formatting hints)
as a string

---

#### export_report_as_string

While most report formatting is done outside of this
library, a very simple formatter is included here for
convenience and reference

---

## Kubernetes

### platform Library

#### Service.health_check

A stub implementation for now, should raise an Exception
if the service is not currently healthy.

---

#### ShellServiceRequest.to_json

Serialize this request out to json appropriate for shell service post body.  (The default
todict implementation of dataclasses doesn't serialize the request_secrets, so this
replaces it for the common use case.)

---

#### ShellServiceResponse.from_json

De-serialize this request from a json obj found in shell service http response and the status_code

**Arguments:**

- `obj`
- `status_code`

---

#### health_check

A stub implementation for now, should raise an Exception
if the service is not currently healthy.

---

#### to_json

Serialize this request out to json appropriate for shell service post body.  (The default
todict implementation of dataclasses doesn't serialize the request_secrets, so this
replaces it for the common use case.)

---

#### from_json

De-serialize this request from a json obj found in shell service http response and the status_code

**Arguments:**

- `obj`
- `status_code`

---

### Core Library

#### Core.import_service

Creates an instance of rwplatform.Service for use by other keywords.

Note that the description, example, default args are parsed in RunWhen static
analysis for type hinting in the GUI, and are not (currently) used here.

**Arguments:**

- `varname`
- `description`
- `example`
- `default`

---

#### Core.shell

Robot Keyword to expose rwplatform.execute_shell_command.

For robot syntax convenience, a single secret and secret_as_file may be given instead of or in addition
to the request_secrets arg (an array of ShellServiceRequestSecrets).  This will wrap secret and secret_as_file in
to a one-item list of ShellServiceRequestSecrets, adding the request_secrets list if one was given.

**Arguments:**

- `cmd`
- `service`
- `request_secrets`
- `secret`
- `secret_as_file`
- `env`
- `files`

---

#### import_service

Creates an instance of rwplatform.Service for use by other keywords.

Note that the description, example, default args are parsed in RunWhen static
analysis for type hinting in the GUI, and are not (currently) used here.

**Arguments:**

- `varname`
- `description`
- `example`
- `default`

---

#### shell

Robot Keyword to expose rwplatform.execute_shell_command.

For robot syntax convenience, a single secret and secret_as_file may be given instead of or in addition
to the request_secrets arg (an array of ShellServiceRequestSecrets).  This will wrap secret and secret_as_file in
to a one-item list of ShellServiceRequestSecrets, adding the request_secrets list if one was given.

**Arguments:**

- `cmd`
- `service`
- `request_secrets`
- `secret`
- `secret_as_file`
- `env`
- `files`

---

#### normalize_lookback_window

Robot Keyword to normalize time period into different formats of units.

The format time specifies, the type of unit the time period needs to be formatted to depending on
the requirement of the variable that is going to use it.

**Arguments:**

- `seconds`
- `format_type`

---

### azure_utils Library

#### az_login

Perform az login using service principal credentials and set the subscription if provided.
If no subscription ID is provided, attempt to retrieve it using the Azure SDK.

**Arguments:**

- `client_id`
- `tenant_id`
- `client_secret`
- `subscription_id`

---

#### get_azure_credential

Obtain Azure credentials either through managed identity or service principal.

**Arguments:**

- `tenant_id`
- `client_id`
- `client_secret`

---

#### enumerate_subscriptions

Enumerate all subscriptions that the service principal has access to.

**Arguments:**

- `credential`

---

## File Operations

### platform Library

#### upload_session_file

Uploads a file generated for this session (a runsession ID for a taskset, '--' for an SLI),
delegates to the fetchfiles plugin supplied either by platform default or by the user.  Returns
a tuple of the fetchfiles response object and a url where the file can be fetched to allow for
user-supplied get functions.

**Arguments:**

- `filename`
- `contents`

---

#### get_session_file

Returns the contents of a session file, or None if the file did not exist

**Arguments:**

- `filename`

---

#### url_for_session_file

Returns the URL where this session file (if it exists) could be downloaded by other systems
given appropriate credentials

**Arguments:**

- `filename`

---

### Core Library

#### Core.upload_session_file

Expose platform.fetchfiles as robot keywords

**Arguments:**

- `filename`
- `contents`

---

#### Core.get_session_file

Returns the contents of a session file, or None if the file did not exist

**Arguments:**

- `filename`

---

#### Core.run_keyword_and_push_metric

Run a keyword and push the returned metric up to the MetricStore.
This should only be called once per sli.robot file.

**Arguments:**

- `name`

**Examples:**

```
Run Keyword and Push Metric   Ping Hosts and Return Highest Avg RTT
...                           hosts=${PING_HOSTS}
```

---

#### Core.debug_log

Debug log

:param str: Log message
:param console: Write log message to console (default is true)

---

#### upload_session_file

Expose platform.fetchfiles as robot keywords

**Arguments:**

- `filename`
- `contents`

---

#### get_session_file

Returns the contents of a session file, or None if the file did not exist

**Arguments:**

- `filename`

---

#### run_keyword_and_push_metric

Run a keyword and push the returned metric up to the MetricStore.
This should only be called once per sli.robot file.

**Arguments:**

- `name`

**Examples:**

```
Run Keyword and Push Metric   Ping Hosts and Return Highest Avg RTT
...                           hosts=${PING_HOSTS}
```

---

#### debug_log

Debug log

:param str: Log message
:param console: Write log message to console (default is true)

---

### fetchfiles Library

#### upload_session_file

**Arguments:**

- `filename`
- `contents`
- `session_id`

---

#### download_session_file

Default implementation to get a session file

**Arguments:**

- `filename`
- `session_id`

---

#### url_for_session_file

Where can this file be found (if it exists) by other systems with appropriate creds?

**Arguments:**

- `filename`
- `session_id`

---

### fetchsecrets Library

#### read_secret

Reads a secret. Note that in order to read, this call must be made from a container that is
running in a workspace (namespace) in a location. (See design notes above.)

This requires the RW_VAULT_URL, RW_WORKSPACE and RW_LOCATION env vars to be set.

key (str): Secret to read

**Arguments:**

- `key`

---

## HTTP/API

### proxy Library

#### get_request_verify

Returns the value of the REQUESTS_CA_BUNDLE environment variable, or None if it is not set

---

#### get_request_verify_workaround

If the REQUESTS_CA_BUNDLE environment variable is not set, returns None. otherwise return False.
This is a workaround for the fact that the requests library does not handle the REQUESTS_CA_BUNDLE
environment variable when using a venv by default. There's a potential workaround for this either
using pip-system-certs or truststore but this is a workaround for now until there's time to investigate further.

---

### platform Library

#### get_authenticated_session

Returns a request.session object authenticated to the RW public API

**Arguments:**

- `force_refresh`

---

#### import_memo_variable

If this is a runbook, the runsession / runrequest may have been initiated with
a memo value.  Get the value for key within the memo, or None if there was no
value found or if there was no memo provided (e.g. with an SLI)

**Arguments:**

- `key`

---

#### request_token

---

### Core Library

#### Core.import_memo_variable

Imports a value from the "memo" dict created when the request to run
was first submitted.  (Note - this is specific to runbooks.  If an SLI,
this simply returns None.). If the memo was not found or this key was not
found, simply return None.
Like Import Platform Variable, this will both set a suite level variable
to key with the value found and will return the value.

**Arguments:**

- `key`

---

#### Core.add_datagrid_to_report

Adds an object that will map closely to a MUI datagrid.  For args,
see https://mui.com/x/react-data-grid/

**Arguments:**

- `about`
- `rows`
- `columns`
- `page_size`
- `rows_per_page_options`

---

#### import_memo_variable

Imports a value from the "memo" dict created when the request to run
was first submitted.  (Note - this is specific to runbooks.  If an SLI,
this simply returns None.). If the memo was not found or this key was not
found, simply return None.
Like Import Platform Variable, this will both set a suite level variable
to key with the value found and will return the value.

**Arguments:**

- `key`

---

#### add_datagrid_to_report

Adds an object that will map closely to a MUI datagrid.  For args,
see https://mui.com/x/react-data-grid/

**Arguments:**

- `about`
- `rows`
- `columns`
- `page_size`
- `rows_per_page_options`

---

## Monitoring & Metrics

### Core Library

#### Core.init_otel

Initialize the OTEL pipeline just once:
 1) Create MeterProvider with a periodic export loop
 2) Register it as the global provider
 3) Keep references so we can record in push_metric

**Arguments:**

- `endpoint`

---

#### Core.push_metric

Push a metric to an OpenTelemetry Collector if self.otel_enabled == True.
If OTEL is not initialized, we attempt to re-init. Includes minimal retry logic.

**Arguments:**

- `value`
- `sub_name`
- `metric_type`
- `dry_run`

---

#### init_otel

Initialize the OTEL pipeline just once:
 1) Create MeterProvider with a periodic export loop
 2) Register it as the global provider
 3) Keep references so we can record in push_metric

**Arguments:**

- `endpoint`

---

#### push_metric

Push a metric to an OpenTelemetry Collector if self.otel_enabled == True.
If OTEL is not initialized, we attempt to re-init. Includes minimal retry logic.

**Arguments:**

- `value`
- `sub_name`
- `metric_type`
- `dry_run`

---

## Utilities

### azure_utils Library

#### convert_and_save_kubeconfig

**Arguments:**

- `kubeconfig_content`
- `client_id`
- `client_secret`

---

#### convert_kubeconfig_using_kubelogin

**Arguments:**

- `login_type`
- `client_id`
- `client_secret`

---

## Other

### platform Library

#### Secret.value

---

#### Secret.key

---

#### error_log

Note: Error logs are automatically written to console.

---

#### warning_log

Note: Warning logs are automatically written to console.

---

#### info_log

---

#### debug_log

---

#### trace_log

---

#### console_log

---

#### console_log_if_true

**Arguments:**

- `condition`

---

#### form_access_token

---

#### import_platform_variable

Imports a variable set by the platform, raises error if not available.

:param str: Name to be used both to lookup the config val and for the
    variable name in robot
:

**Arguments:**

- `varname`

**Returns:**

- The value found

---

#### execute_shell_command

**Arguments:**

- `cmd`
- `service`
- `request_secrets`
- `env`
- `files`

---

#### value

---

#### key

---

#### is_retryable

Determines whether the exception e should trigger a retry.

**Arguments:**

- `e`

---

### Core Library

#### about_fetchsecrets_plugin

---

#### health_check_fetchsecrets_plugin

---

#### get_authenticated_session

---

#### rw_get

**Arguments:**

- `path`
- `params`

---

#### rw_post

**Arguments:**

- `path`
- `data`

---

#### import_secret

Import a secret from the configured secret provider.

Args:
    varname: The variable name for the secret
    description: Optional description for documentation
    example: Optional example value for documentation  
    pattern: Optional pattern for validation
    optional: If True, returns None instead of failing when secret is not found
    **kwargs: Additional keyword arguments
    

    
Raises:
    ImportError: If secret not found and optional=False

**Arguments:**

- `varname`
- `description`
- `example`
- `pattern`
- `optional`

**Returns:**

- platform.Secret: Secret object, or None if optional=True and secret not found

---

#### import_optional_secret

Import an optional secret that may not be set.

This is a convenience method that calls import_secret with optional=True.
If the secret is not found or is marked with an optional value (NONE, OPTIONAL, etc.),
it will return None instead of raising an error.

Args:
    varname: The variable name for the secret
    description: Optional description for documentation
    example: Optional example value for documentation  
    pattern: Optional pattern for validation
    **kwargs: Additional keyword arguments

**Arguments:**

- `varname`
- `description`
- `example`
- `pattern`

**Returns:**

- platform.Secret: Secret object, or None if secret is optional/not found

---

#### import_user_variable

Imports a variable set by the user, raises error if not available.

**Arguments:**

- `varname`
- `type`
- `description`
- `example`
- `pattern`
- `enum`
- `format`
- `default`

**Examples:**

```
Import User Variable   FOO
Debug Log              ${FOO}
```

---

#### import_platform_variable

Imports a variable set by the platform, making it available in the robot runtime
as a suite variable.

Raises ValueError if this isn't a valid platform variable name, or ImportError if not available.

:param str: Name to be used both to lookup the config val and for the
    variable name in robot
:

**Arguments:**

- `varname`

**Returns:**

- The value found

---

#### error_log

Error log

:param msg: Log message

---

#### warning_log

Warning log

:param msg: Log message

---

#### info_log

Info log

:param msg: Log message

---

#### inspect_object_attributes

**Arguments:**

- `d`
- `console`

---

#### trace_log

Trace log

:param msg: Log message

---

#### console_log

---

#### console_log_if_true

If the condition is evaluated to true, the message is written to the
console.

:param condition: Condition to evaluate as a Python expression
:param msg: Log message

---

### azure_utils Library

#### get_subscription_id

**Arguments:**

- `credential`

---

#### generate_kubeconfig_for_aks

**Arguments:**

- `resource_group`
- `cluster_name`
- `tenant_id`
- `client_id`
- `client_secret`

---

#### generate_kubeconfig_with_az_cli

**Arguments:**

- `resource_group`
- `cluster_name`

---

### fetchfiles Library

#### health_check

Checks that any required vars for this storage engine to work are, indeed, set.
Raise AssertionError if this check fails.

---

#### about

Returns a dict of info identifying this particular uploadurls plugin

---

#### UploadURLCache.get_upload_url

**Arguments:**

- `session_id`
- `filename`

---

#### get_upload_url

**Arguments:**

- `session_id`
- `filename`

---

### fetchsecrets Library

#### health_check

Checks that any required vars for this secrets engine to work are, indeed, set.
Raise AssertionError if this check fails.

---

#### about

Returns a dict of info identifying this particular fetchsecrets plugin

---

#### authenticate_vault_client

Dynamically choose the authentication method based on available environment variables.

**Arguments:**

- `vault_addr`
- `auth_mount_point`
- `role_id`
- `secret_id`

---

## Quick Reference

### All Keywords by Library

**proxy:**
- `get_request_verify`
- `get_request_verify_workaround`

**platform:**
- `Secret.value`
- `Secret.key`
- `Service.health_check`
- `ShellServiceRequest.to_json`
- `ShellServiceResponse.from_json`
- `error_log`
- `warning_log`
- `info_log`
- `debug_log`
- `trace_log`
- `console_log`
- `console_log_if_true`
- `form_access_token`
- `get_authenticated_session`
- `import_platform_variable`
- `upload_session_file`
- `get_session_file`
- `url_for_session_file`
- `import_memo_variable`
- `execute_shell_command`
- `value`
- `key`
- `health_check`
- `to_json`
- `from_json`
- `is_retryable`
- `request_token`

**Core:**
- `Core.init_otel`
- `Core.about_fetchsecrets_plugin`
- `Core.health_check_fetchsecrets_plugin`
- `Core.get_authenticated_session`
- `Core.rw_get`
- `Core.rw_post`
- `Core.import_secret`
- `Core.import_optional_secret`
- `Core.import_service`
- `Core.import_user_variable`
- `Core.import_platform_variable`
- `Core.import_memo_variable`
- `Core.upload_session_file`
- `Core.get_session_file`
- `Core.run_keyword_and_push_metric`
- `Core.push_metric`
- `Core.task_failure`
- `Core.task_error`
- `Core.fatal_error`
- `Core.error_log`
- `Core.warning_log`
- `Core.info_log`
- `Core.inspect_object_attributes`
- `Core.debug_log`
- `Core.trace_log`
- `Core.console_log`
- `Core.console_log_if_true`
- `Core.add_issue`
- `Core.add_to_report`
- `Core.add_code_to_report`
- `Core.add_pre_to_report`
- `Core.add_url_to_report`
- `Core.add_json_to_report`
- `Core.add_table_to_report`
- `Core.add_datagrid_to_report`
- `Core.get_report_data`
- `Core.get_report_data_as_string`
- `Core.export_report_as_string`
- `Core.shell`
- `Core.normalize_lookback_window`
- `init_otel`
- `about_fetchsecrets_plugin`
- `health_check_fetchsecrets_plugin`
- `get_authenticated_session`
- `rw_get`
- `rw_post`
- `import_secret`
- `import_optional_secret`
- `import_service`
- `import_user_variable`
- `import_platform_variable`
- `import_memo_variable`
- `upload_session_file`
- `get_session_file`
- `run_keyword_and_push_metric`
- `push_metric`
- `task_failure`
- `task_error`
- `fatal_error`
- `error_log`
- `warning_log`
- `info_log`
- `inspect_object_attributes`
- `debug_log`
- `trace_log`
- `console_log`
- `console_log_if_true`
- `add_issue`
- `add_to_report`
- `add_code_to_report`
- `add_pre_to_report`
- `add_url_to_report`
- `add_json_to_report`
- `add_table_to_report`
- `add_datagrid_to_report`
- `get_report_data`
- `get_report_data_as_string`
- `export_report_as_string`
- `shell`
- `normalize_lookback_window`

**azure_utils:**
- `az_login`
- `get_subscription_id`
- `get_azure_credential`
- `enumerate_subscriptions`
- `generate_kubeconfig_for_aks`
- `generate_kubeconfig_with_az_cli`
- `convert_and_save_kubeconfig`
- `convert_kubeconfig_using_kubelogin`

**fetchfiles:**
- `health_check`
- `about`
- `UploadURLCache.get_upload_url`
- `upload_session_file`
- `download_session_file`
- `url_for_session_file`
- `get_upload_url`

**fetchsecrets:**
- `health_check`
- `about`
- `authenticate_vault_client`
- `read_secret`

