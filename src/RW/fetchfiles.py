"""
Part of the storage engine (similar to fetchsecrets and the secret engine),
this file is the default implementation that users may replace with their own.
"""
import time
from . import platform

import requests

import logging


class URLTemporarilyUnavailable(Exception):
    pass


class URLPermanentlyUnavailable(Exception):
    pass


def health_check():
    """Checks that any required vars for this storage engine to work are, indeed, set.
    Raise AssertionError if this check fails.
    """
    pass


def about():
    """Returns a dict of info identifying this particular uploadurls plugin"""
    ret = {
        "author": "kyle",
        "version": "0.1",
        "description": "The default uploadurls implementation",
        "home_url": "https://runwhen.com/about/uploadurls",
    }
    return ret


class UploadURLCache:
    def __init__(self):
        self.cache = {}

    def get_upload_url(self, session_id, filename):
        cache_key = f"{session_id}_{filename}"
        upload_url, expiration_time = self.cache.get(cache_key, (None, 0))
        if time.time() >= expiration_time:
            # If the URL has expired or not cached, request a new one from the API endpoint
            slx_api_url = platform.import_platform_variable("RW_SLX_API_URL")
            get_url = f"{slx_api_url}/file-upload-url/{session_id}/{filename}"
            s = platform.get_authenticated_session()
            rsp = s.get(get_url, verify=platform.REQUEST_VERIFY)
            platform.debug_log(f"getting url to upload file {filename}, received rsp {rsp.status_code}: {rsp.text}")
            upload_url = rsp.json().get("url", None)

            if upload_url:
                # Cache the new upload URL and its expiration timestamp for future use during this session
                expiration_time = time.time() + 60 * 55  # 60 minutesis the default expiration time, subtract 5 minutes to be safe
                self.cache[cache_key] = (upload_url, expiration_time)

        return upload_url

upload_url_cache = UploadURLCache()

def upload_session_file(filename: str, contents: str, session_id: str):
    if not isinstance(contents, str):
        raise ValueError(f"Expected contents to be a string, but got contents type {type(contents)}")

    upload_url = upload_url_cache.get_upload_url(session_id, filename)

    try:
        # If we have the upload URL, proceed with the PUT request
        if upload_url:
            rsp = requests.put(upload_url, data=contents.encode("utf-8"), headers={"content-type": "text/plain"}, timeout=25, verify=platform.REQUEST_VERIFY)
            platform.debug_log(
                f"posting file {filename} to {upload_url} of length {len(contents)} returned {rsp.status_code}: {rsp.text}"
            )
            return rsp
        else:
            raise ValueError("Failed to get the upload URL.")

    except requests.exceptions.RequestException as re:
        platform.info_log(
            f"failed to post file {filename} to slx api url at {upload_url}. Error: {re}"
        )
        raise


def download_session_file(filename: str, session_id: str):
    """Default implementation to get a session file"""
    slx_api_url = platform.import_platform_variable("RW_SLX_API_URL")
    s = platform.get_authenticated_session()
    url = f"{slx_api_url}/files/{session_id}/{filename}"
    rsp = s.get(url, verify=platform.REQUEST_VERIFY)
    contents = rsp.json().get("contents", None)
    platform.debug_log(
        f"get session file {filename} to {url}, length {len(contents) if contents else 0} and status {rsp.status_code}"
    )
    return contents


def url_for_session_file(filename: str, session_id: str):
    """Where can this file be found (if it exists) by other systems with appropriate creds?"""
    slx_api_url = platform.import_platform_variable("RW_SLX_API_URL")
    return f"{slx_api_url}/files/{session_id}/{filename}"
