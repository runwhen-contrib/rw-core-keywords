"""A set of python interfaces also exposed in RW.Core (and used outside of that)"""
import time
import requests, os, pprint, traceback, json
from typing import Union, Optional, List
from dataclasses import dataclass, field
from robot.api import logger as user_logger
from robot.api import Failure, Error, FatalError, logger
from robot.libraries.BuiltIn import BuiltIn

from . import proxy
from ._mode import is_dev_mode

REQUEST_VERIFY = proxy.get_request_verify()

if not is_dev_mode():
    from requests.exceptions import HTTPError, RequestException
    import backoff
    from . import fetchsecrets
    from . import fetchfiles

import logging

platform_logger = logging.getLogger(__name__)
robot_builtin = BuiltIn()

session = None
access_token_expiration_time = 0


class TemporaryException(Exception):
    pass


class PermanentException(Exception):
    pass


class InputException(PermanentException):
    pass


class Secret:
    """The secret class is used as a wrapper around secret values to track their usage
    and to make sure they don't accidentally escape in to logs as strings.  Keyword
    authors should take instances of Secret as arguments when they suspect that the
    content of the string is sensitive, prompting Robot authors to add import secret
    commands and flag this sensitivity to users.
    """

    def __init__(self, key: str, val: str):
        self._key = key
        self._val = val

    @property
    def value(self):
        stack = traceback.format_stack()
        robot_builtin.log(f"secret {self._key} accessed from callstack {stack}")
        return self._val

    @property
    def key(self):
        return self._key

    def __str__(self):
        return "*" * len(self.value)


@dataclass(frozen=True)
class Service:
    """The secret class is used as a wrapper around service URLs, created by
    the Import Service keyword.  (Over time, the gist is to offer health
    check / status / version params as well as providing the basic URL
    for robot authors.)
    """

    url: str

    def health_check(self):
        """A stub implementation for now, should raise an Exception
        if the service is not currently healthy.
        """
        return True


@dataclass(frozen=True)
class ShellServiceRequestSecret:
    secret: Secret
    as_file: bool = False


@dataclass(frozen=True)
class ShellServiceRequest:
    cmd: str
    request_secrets: List[ShellServiceRequestSecret] = field(default_factory=lambda: [])
    env: dict = field(default_factory=lambda: {})
    files: dict = field(default_factory=lambda: {})
    timeout_seconds: int = 60

    def to_json(self):
        """Serialize this request out to json appropriate for shell service post body.  (The default
        todict implementation of dataclasses doesn't serialize the request_secrets, so this
        replaces it for the common use case.)
        """
        # Without the nested dataclass or camel case, this would be json.dumps(self.todict()),
        # but we have both
        obj = {}
        obj["cmd"] = self.cmd
        if self.request_secrets:
            obj["secrets"] = [
                {"key": s.secret.key, "value": s.secret.value, "file": s.as_file} for s in self.request_secrets
            ]
        if self.files:
            obj["files"] = self.files
        if self.env:
            obj["env"] = self.env
        return json.dumps(obj)


@dataclass(frozen=True)
class ShellServiceResponse:
    cmd: str  # The original cmd string given
    parsed_cmd: str = None  # Useful for debugging long commands
    stdout: str = None  # stdout from running cmd
    stderr: str = None  # stderr from running cmd
    returncode: int = -1  # The returncode from running cmd
    status: int = 500  # The http status code from the service, representing any errors
    # the plumbing pre/post command
    body: str = ""  # The raw body of the response as a string for troubleshooting plumbing errors
    # A list of strings with error messages from the plumbing and cmd results
    errors: List[str] = field(default_factory=lambda: [])

    @staticmethod
    def from_json(obj, status_code=200):
        """De-serialize this request from a json obj found in shell service http response and the status_code"""
        if isinstance(obj, list):
            if len(obj) != 1:
                raise ValueError(
                    f"Trying to parse JSON string in to ShellServiceResponse, but"
                    + f"JSON string had more than one object {str(obj)}"
                )
            else:
                obj = obj[0]
        # Note conversion from camelcase is required (and not worth another dependency IMHO)
        try:
            ret = ShellServiceResponse(
                cmd=obj["cmd"],
                parsed_cmd=obj["parsedCmd"],
                stdout=obj["stdout"],
                stderr=obj["stderr"],
                returncode=obj["returncode"],
                status=status_code,
            )
            return ret
        except KeyError as ke:
            raise TaskError(
                f"Error parsing shell service response {type(ke)}: {ke} from object {obj} and status code {status_code}"
            )


class TaskFailure(Failure):
    """
    This exception can be raised for a task failure due to a failed
    validation.
    """


class TaskError(Error):
    """
    This exception can be raised for a task error caused by a malfunction
    or unexpected result.
    """


# def task_failure(msg: str) -> None:
#     raise TaskFailure(msg)


# def task_error(msg: str) -> None:
#     raise TaskError(msg)


# def fatal_error(msg: str) -> None:
#     raise FatalError(msg)


def error_log(*msg, console: Union[bool, str] = False, if_true: Optional[str] = None) -> None:
    """
    Note: Error logs are automatically written to console.
    """
    if if_true is not None and BuiltIn().evaluate(if_true) is not True:
        return
    _ = console
    for s in msg:
        if not isinstance(s, str):
            s = pprint.pformat(s, indent=1, width=80)
        if console or isinstance(console, str) and console.lower() == "true":
            robot_builtin.log_to_console(f"\n{str(s)}")
        logger.error(str(s))


def warning_log(*msg, console: Union[bool, str] = False, if_true: Optional[str] = None) -> None:
    """
    Note: Warning logs are automatically written to console.
    """
    if if_true is not None and BuiltIn().evaluate(if_true) is not True:
        return
    _ = console
    for s in msg:
        if not isinstance(s, str):
            s = pprint.pformat(s, indent=1, width=80)
        if console or isinstance(console, str) and console.lower() == "true":
            robot_builtin.log_to_console(f"\n{str(s)}")
        logger.warn(str(s))


def info_log(*msg, console: Union[bool, str] = False, if_true: Optional[str] = None) -> None:
    if if_true is not None and BuiltIn().evaluate(if_true) is not True:
        return
    _ = console
    for s in msg:
        if not isinstance(s, str):
            s = pprint.pformat(s, indent=1, width=80)
        if console or isinstance(console, str) and console.lower() == "true":
            robot_builtin.log_to_console(f"\n{str(s)}")
        logger.info(str(s))


def debug_log(*msg, console: Union[bool, str] = False, if_true: Optional[str] = None) -> None:
    if if_true is not None and BuiltIn().evaluate(if_true) is not True:
        return
    _ = console
    for s in msg:
        if not isinstance(s, str):
            s = pprint.pformat(s, indent=1, width=80)
        if console or isinstance(console, str) and console.lower() == "true":
            robot_builtin.log_to_console(f"\n{str(s)}")
        logger.debug(str(s))


def trace_log(*msg, console: Union[bool, str] = False, if_true: Optional[str] = None) -> None:
    if if_true is not None and BuiltIn().evaluate(if_true) is not True:
        return
    _ = console
    for s in msg:
        if not isinstance(s, str):
            s = pprint.pformat(s, indent=1, width=80)
        if console or isinstance(console, str) and console.lower() == "true":
            robot_builtin.log_to_console(f"\n{str(s)}")
        logger.trace(str(s))


def console_log(*msg) -> None:
    info_log(*msg, console=True)


def console_log_if_true(condition: str, *msg) -> None:
    info_log(msg, console=True, if_true=condition)


def form_access_token() -> str:
    if is_dev_mode():
        access_token = os.getenv("RW_ACCESS_TOKEN")
        if not access_token:
            doc_url = "https://docs.runwhen.com/public/platform-rest-api/getting-started-with-the-platform-rest-api"
            raise Exception(
                f"In dev mode, set RW_ACCESS_TOKEN in your environment. See {doc_url}"
            )
        return access_token

    global access_token_expiration_time

    base_url = os.getenv("RW_API_BASE_URL")

    def is_retryable(e):
        """Determines whether the exception e should trigger a retry."""
        if isinstance(e, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)):
            return True
        if isinstance(e, HTTPError):
            return e.response.status_code == 503
        return False

    @backoff.on_exception(backoff.expo,
                          RequestException,
                          giveup=lambda e: not is_retryable(e),
                          max_tries=30)
    def request_token():
        username = fetchsecrets.read_secret("rw-service-account-username")
        password = fetchsecrets.read_secret("rw-service-account-pw")
        token_path = f"/api/v3/token/"

        rsp = requests.post(
            base_url + token_path,
            json={"username": username, "password": password},
            headers={"Accept": "application/json"},
            verify=REQUEST_VERIFY,
        )
        rsp.raise_for_status()
        return rsp.json()["access"]

    try:
        access_token = request_token()
        access_token_expiration_time = time.time() + 86400 - 60
        return access_token
    except HTTPError as e:
        status_code = e.response.status_code
        if 400 <= status_code < 500:
            raise AssertionError(f"Received a 4XX error: {e}")
        platform_logger.error(f"Failed to authenticate due to server error: {e}")
    except (RequestException, fetchsecrets.AuthenticationError, fetchsecrets.SecretNotFoundError) as e:
        platform_logger.error(f"Failed authentication: {str(e)}")
        platform_logger.exception(e)

    return ""


def get_authenticated_session(force_refresh: bool = False) -> requests.Session:
    """Returns a request.session object authenticated to the RW public API
    """
    global session, access_token_expiration_time
    if session and (time.time() < access_token_expiration_time or not force_refresh):
        return session

    session = requests.Session()
    session.verify = REQUEST_VERIFY
    access_token = form_access_token()
    session.headers.update(
        {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
    )
    return session


def import_platform_variable(varname: str) -> str:
    """
    Imports a variable set by the platform, raises error if not available.

    :param str: Name to be used both to lookup the config val and for the
        variable name in robot
    :return: The value found
    """
    if not varname.startswith("RW_"):
        raise ValueError(
            f"Variable {varname!r} is not a RunWhen platform variable, Use Import User Variable keyword instead."
        )
    val = os.getenv(varname)
    if not val:
        raise ImportError(f"Import Platform Variable: {varname} has no value defined.")
    return val


def upload_session_file(filename: str, contents: str):
    """Uploads a file generated for this session (a runsession ID for a taskset, '--' for an SLI),
    delegates to the fetchfiles plugin supplied either by platform default or by the user.  Returns
    a tuple of the fetchfiles response object and a url where the file can be fetched to allow for
    user-supplied get functions.
    """
    if is_dev_mode():
        debug_log(f"[dev] upload_session_file skipped for '{filename}' ({len(contents)} bytes)")
        return None, None

    if not isinstance(contents, str):
        raise ValueError(f"Expected contents to be a string, but got contents type {type(contents)}")
    try:
        session_id = import_platform_variable("RW_SESSION_ID")
    except ImportError:
        session_id = "--"

    return fetchfiles.upload_session_file(filename=filename, contents=contents, session_id=session_id)


def get_session_file(filename: str) -> str:
    """Returns the contents of a session file, or None if the file did not exist"""
    if is_dev_mode():
        debug_log(f"[dev] get_session_file skipped for '{filename}'")
        return None

    try:
        session_id = import_platform_variable("RW_SESSION_ID")
    except ImportError:
        session_id = "--"
    return fetchfiles.download_session_file(filename=filename, session_id=session_id)


def url_for_session_file(filename: str) -> str:
    """Returns the URL where this session file (if it exists) could be downloaded by other systems
    given appropriate credentials
    """
    if is_dev_mode():
        debug_log(f"[dev] url_for_session_file skipped for '{filename}'")
        return None

    try:
        session_id = import_platform_variable("RW_SESSION_ID")
    except ImportError:
        session_id = "--"
    return fetchfiles.url_for_session_file(filename=filename, session_id=session_id)


def import_memo_variable(key: str):
    """If this is a runbook, the runsession / runrequest may have been initiated with
    a memo value.  Get the value for key within the memo, or None if there was no
    value found or if there was no memo provided (e.g. with an SLI)
    """
    if is_dev_mode():
        fkeys_json_str = os.getenv("RW_MEMO_FILE", "{}")
        memos_from_files = json.loads(fkeys_json_str)
        if key in memos_from_files:
            with open(memos_from_files[key]) as fh:
                return fh.read()
        raise ValueError(
            f"Memo key {key} not found. Set RW_MEMO_FILE env var, e.g. "
            f'RW_MEMO_FILE=\'{{"{ key}":"/path/to/file"}}\''
        )

    try:
        slx_api_url = import_platform_variable("RW_SLX_API_URL")
        runrequest_id = import_platform_variable("RW_RUNREQUEST_ID")
    except ImportError:
        return None
    s = get_authenticated_session()
    url = f"{slx_api_url}/runbook/runs/{runrequest_id}"
    try:
        rsp = s.get(url, timeout=10, verify=REQUEST_VERIFY)
        return rsp.json().get("memo", {}).get(key, None)
    except (requests.ConnectTimeout, requests.ConnectionError, json.JSONDecodeError) as e:
        warning_log(f"exception while trying to get memo: {e}", str(e), str(type(e)))
        platform_logger.exception(e)


def execute_shell_command(
    cmd: str,
    service: Service,
    request_secrets: List[ShellServiceRequestSecret] = None,
    env: dict = None,
    files: dict = None,
):
    ss_req = ShellServiceRequest(cmd=cmd, request_secrets=request_secrets, env=env, files=files)
    url = service.url + "/api/v1/cmd"
    headers = {"Content-type": "application/json", "Accept": "application/json"}
    try:
        rsp = requests.post(url, data=ss_req.to_json(), headers=headers, verify=REQUEST_VERIFY)
        response_obj = rsp.json()
        ss_rsp = ShellServiceResponse.from_json(response_obj, rsp.status_code)
        logger.debug(f"execute_shell_command with shell service requrest: {ss_req} and received response {ss_rsp}")
        return ss_rsp
    except requests.JSONDecodeError as e:
        raise TaskFailure(
            f"JSON Decode Error {type(e)}: {e} trying to parse shell service response from response {rsp} with body {rsp.text}"
        ) from e
