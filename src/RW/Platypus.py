"""
A file for keywords under development that are closely linked to platform
funtionality (in development)
TODO - Likely just remove all of this
"""
import fetchsecrets
import traceback
import RW.Core
import requests, re, os

c = RW.Core.Core()

# class Secret:
#     def __init__(self, key : str, val : str):
#         self._key = key
#         self._val = val

#     @property
#     def value(self):
#         stack = traceback.format_stack()
#         c.info(f"secret {self._key} accessed from callstack {stack}")
#         return self._val

#     def __str__(self):
#         return '*' * len(self.value)


class Platypus:
    """Core keyword library defines some commonly used keywords."""

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    # def import_secret(self, key: str, **kwargs):
    #     val = fetchsecrets.read_secret(key)
    #     ret = Secret(key, val)
    #     return ret

    # def about_fetchsecrets_plugin(self):
    #     return fetchsecrets.about()

    # def get_authenticated_session(self):
    #     """Returns a request.session object authenticated to the RW public API using the
    #     RW_ACCESS_TOKEN that should be available (either a user or service acct)
    #     """
    #     # TODO - implement timeout / refresh if access token has expired
    #     if self.session:
    #         return self.session
    #     self.session = requests.Session()
    #     self.session.headers.update(
    #         {
    #             "Authorization": f"Bearer {os.getenv('RW_ACCESS_TOKEN')}",
    #             "Content-Type": "application/json",
    #             "Accept": "application/json",
    #         }
    #     )
    #     return self.session

    # def RW_GET(self, path, params):
    #     session = self.get_authenticated_session()
    #     return session.get(path, params=params)

    # def RW_POST(self, path, data):
    #     session = self.get_authenticated_session()
    #     return session.post(path, data=data)

    GAUGE = "gauge"
    COUNTER = "counter"
    HISTOGRAM = "histogram"
    UNTYPED = "untyped"

    # def push_metric_2(self, value=None, sub_name=None, metric_type=UNTYPED, dry_run=False, **kwargs):
    #     """
    #     Used to push a metric up to the MetricStore.  Each SLX has a single default  metric
    #     by default that all SLIs should use where the sub_name should be set to None.
    #     Callers may also use this method multiple times in a single SLI with subsequent
    #     metric sub_name args set to various strings in order to push multiple metrics in
    #     addition to the default.

    #     Examples:
    #         #Base case test
    #         Push Metric 2   10

    #         #Try with a sub-name
    #         Push Metric 2   11      sub_name=some_non_default_metric

    #         #Try various types
    #         Push Metric 2   12      sub_name=as_gauge  metric_type=gauge
    #         Push Metric 2   13      sub_name=as_counter  metric_type=counter

    #         #Try with labels
    #         Push Metric 2   12      sub_name=with_labels  a_label=a    b_label=b     c_label=c

    #     Example:
    #       Push Metric	5
    #       Push Metric	5	http_code=200 #Pushes a metric names
    #       Push Metric   10  sub_name=foo    type=${GAUGE}   http_code=300 #Pushes a non-defualt metric

    #     Note that calls to Push Metric are not exactly atomic. Once a metric/sub-metric is pushed
    #     with a set of labels in the scope of a Suite, it is expected that any
    #     subsequent calls have the same set of labels.  Since it would be very
    #     odd (an error?) to have any metric/sub-metric called in more than one place per Suite,
    #     this doesn't seem like a constraint in practice.

    #     Note this requires several platform variables to have been set:
    #     RW_SLI_METRIC_NAMES
    #     RW_SLI_METRIC_TYPE
    #     RW_SLI_METRIC_DESCRIPTION
    #     RW_PUSHGWY_HOST

    #     Don't push metric if RW_LOCATION is not defined.
    #     """

    #     ###Ready to migrate to Core
    #     ###Note that the debug_log and import_platform_variable lines
    #     ###need to be swapped back to self. when importing

    #     labels = kwargs
    #     if not labels:
    #         labels = {}

    #     if sub_name and not re.match(r"^[A-Za-z0-9_]+$", sub_name):
    #         raise ValueError(
    #             f"sub_name mustbe alphanumeric or underscore (regex '^[A-Za-z0-9_]+$'), but got {sub_name}"
    #         )

    #     try:
    #         c.import_platform_variable("RW_LOCATION")
    #     except ImportError:
    #         s = (
    #             f"Metric value: {value!r}, labels: {labels}\n"
    #             + "RW_LOCATION is not defined. Metric is not pushed to"
    #             + " MetricStore."
    #         )
    #         c.debug_log(s)
    #         return value

    #     mname = c.import_platform_variable("RW_SLI_METRIC_NAME")
    #     if sub_name:
    #         mname = f"{mname}__{sub_name}"
    #     workspace = c.import_platform_variable("RW_WORKSPACE")

    #     # Note there *must* be at least one label,
    #     # and the workspace label is absolutely required
    #     # to get these metrics to the right namespace in MetricStore
    #     labels["workspace"] = workspace

    #     # Get the metric name (or stop here for dry_run)
    #     if dry_run:
    #         s = (
    #             f"Push metric value: {value!r}, labels: {labels},"
    #             + f" name: {mname!r}.\nYou are seeing this because dry_run is"
    #             + " set to 'True'.\nThis is *not* pushing the value and labels"
    #             + " to the MetricStore.\n"
    #         )
    #         c.debug_log(s)
    #         return value

    #     mdescription = c.import_platform_variable("RW_SLI_METRIC_DESCRIPTION")
    #     pgh = c.import_platform_variable("RW_PUSHGWY_HOST")

    #     # cat <<EOF | curl --data-binary @- http://pushgateway.example.org:9091/metrics/job/some_job/instance/some_instance
    #     ## TYPE some_metric counter
    #     # some_metric{label="val1"} 42
    #     ## TYPE another_metric gauge
    #     ## HELP another_metric Just an example.
    #     # another_metric 2398.283
    #     # EOF
    #     label_str = ",".join(f'{key}="{val}"' for (key, val) in labels.items())
    #     data = f"# TYPE {mname} {metric_type}\n# HELP {mname} {mdescription}\n{mname}{{{label_str}}} {value}\n"
    #     headers = {"Content-Type": "application/octet-stream"}
    #     job_name = "pushgateway"
    #     rsp = requests.post(url=f"http://{pgh}/metrics/job/{job_name}/", data=data, headers=headers)
    #     c.info_log(
    #         f"Pushed metric:\n {data}\nResponse from push gateway was {rsp} and body {rsp.text}"
    #     )  # useful for troubleshooting
