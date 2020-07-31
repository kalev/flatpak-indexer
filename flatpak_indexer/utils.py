import codecs
from contextlib import contextmanager
import hashlib
import logging
import os
import re
from tempfile import NamedTemporaryFile

from requests import Session
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util import Retry


logger = logging.getLogger(__name__)

_RETRY_MAX_TIMES = 3
_RETRY_STATUSES = (
    408,  # Request Timeout
    500,  # Internal Server Error
    502,  # Bad Gateway
    503,  # Service Unavailable
    504   # Gateway Timeout
)


# If we want to retry POST, etc, need to set method_whitelist here
def get_retrying_requests_session(backoff_factor=3):
    retry = Retry(
        backoff_factor=backoff_factor,
        raise_on_status=True,
        status_forcelist=_RETRY_STATUSES,
        total=_RETRY_MAX_TIMES,
    )
    session = Session()
    session.mount('http://', HTTPAdapter(max_retries=retry))
    session.mount('https://', HTTPAdapter(max_retries=retry))

    return session


_ENV_VAR_TOKEN_RE = re.compile(r"\$\{|(?P<varname>[A-Za-z_][A-Za-z0-9_]*)|.")


class SubstitutionError(Exception):
    pass


def _substitute_env_vars(itr, outer=True):
    result = ""
    while True:
        m = next(itr, None)
        if m is None:
            if not outer:
                raise SubstitutionError("unclosed variable reference")
            return result
        elif m.group(0) == "${":
            m = next(itr, None)
            if m is None:
                raise SubstitutionError("unclosed variable reference")
            elif m.group('varname'):
                varname = m.group(0)
                m = next(itr, None)
                if m is None:
                    raise SubstitutionError("unclosed variable reference")
                elif m.group(0) == ":":
                    fallback = _substitute_env_vars(itr, outer=False)
                    result += os.environ.get(varname, fallback)
                elif m.group(0) == "}":
                    try:
                        result += os.environ[varname]
                    except KeyError:
                        raise SubstitutionError(
                            "environment variable {} is not set".format(varname)) from None
                else:
                    raise SubstitutionError(
                        "at position {} in field: expected : or }}".format(m.start()))
            else:
                raise SubstitutionError(
                    "at position {} in field: expected variable name".format(m.start()))
        elif m.group(0) == "}" and not outer:
            return result
        else:
            result += m.group(0)


@contextmanager
def atomic_writer(output_path):
    output_dir = os.path.dirname(output_path)
    tmpfile = NamedTemporaryFile(delete=False,
                                 dir=output_dir,
                                 prefix=os.path.basename(output_path))
    success = False
    try:
        writer = codecs.getwriter("utf-8")(tmpfile)
        yield writer
        writer.close()
        tmpfile.close()

        # We don't overwrite unchanged files, so that the modtime and
        # httpd-computed ETag stay the same.

        changed = True
        if os.path.exists(output_path):
            h1 = hashlib.sha256()
            with open(output_path, "rb") as f:
                h1.update(f.read())
            h2 = hashlib.sha256()
            with open(tmpfile.name, "rb") as f:
                h2.update(f.read())

            if h1.digest() == h2.digest():
                changed = False

        if changed:
            # Atomically write over result
            os.chmod(tmpfile.name, 0o644)
            os.rename(tmpfile.name, output_path)
            logger.info("Wrote %s", output_path)
        else:
            logger.info("%s is unchanged", output_path)
            os.unlink(tmpfile.name)

        success = True
    finally:
        if not success:
            tmpfile.close()
            os.unlink(tmpfile.name)


def substitute_env_vars(val):
    return _substitute_env_vars(_ENV_VAR_TOKEN_RE.finditer(val))
