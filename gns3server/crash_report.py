# -*- coding: utf-8 -*-
#
# Copyright (C) 2014 GNS3 Technologies Inc.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os
import sys
import struct
import aiohttp
import platform
import locale
import distro

try:
    import raven
    from raven.transport.http import HTTPTransport
    RAVEN_AVAILABLE = True
except ImportError:
    # raven is not installed with deb package in order to simplify packaging
    RAVEN_AVAILABLE = False

from .version import __version__, __version_info__
from .config import Config
from .utils.get_resource import get_resource

import logging
log = logging.getLogger(__name__)


# Dev build
if __version_info__[3] != 0:
    import faulthandler

    # Display a traceback in case of segfault crash. Usefull when frozen
    # Not enabled by default for security reason
    log.info("Enable catching segfault")
    try:
        faulthandler.enable()
    except Exception:
        pass  # Could fail when loaded into tests


class CrashReport:

    """
    Report crash to a third party service
    """

    DSN = "https://dfe18e681fad4de580403c7432ae50d1:d9a1927b28c64836a41e4390c3242372@sentry.io/38482"
    if hasattr(sys, "frozen"):
        cacert = get_resource("cacert.pem")
        if cacert is not None and os.path.isfile(cacert):
            DSN += "?ca_certs={}".format(cacert)
        else:
            log.warning("The SSL certificate bundle file '{}' could not be found".format(cacert))
    _instance = None

    def __init__(self):
        self._client = None

        # We don't want sentry making noise if an error is catched when you don't have internet
        sentry_errors = logging.getLogger('sentry.errors')
        sentry_errors.disabled = True

        sentry_uncaught = logging.getLogger('sentry.errors.uncaught')
        sentry_uncaught.disabled = True

    def capture_exception(self, request=None):
        if not RAVEN_AVAILABLE:
            return
        if os.path.exists(".git"):
            log.warning("A .git directory exist crash report is turn off for developers")
            return
        server_config = Config.instance().get_section_config("Server")
        if server_config.getboolean("report_errors"):
            if self._client is None:
                self._client = raven.Client(CrashReport.DSN, release=__version__, raise_send_errors=True, transport=HTTPTransport)
            if request is not None:
                self._client.http_context({
                    "method": request.method,
                    "url": request.path,
                    "data": request.json,
                })

            context = {
                "os:name": platform.system(),
                "os:release": platform.release(),
                "os:win_32": " ".join(platform.win32_ver()),
                "os:mac": "{} {}".format(platform.mac_ver()[0], platform.mac_ver()[2]),
                "os:linux": " ".join(distro.linux_distribution()),
                "aiohttp:version": aiohttp.__version__,
                "python:version": "{}.{}.{}".format(sys.version_info[0],
                                                    sys.version_info[1],
                                                    sys.version_info[2]),
                "python:bit": struct.calcsize("P") * 8,
                "python:encoding": sys.getdefaultencoding(),
                "python:frozen": "{}".format(hasattr(sys, "frozen"))
            }

            if sys.platform.startswith("linux") and not hasattr(sys, "frozen"):
                # add locale information
                try:
                    language, encoding = locale.getlocale()
                    context["locale:language"] = language
                    context["locale:encoding"] = encoding
                except ValueError:
                    pass

                # add GNS3 VM version if it exists
                home = os.path.expanduser("~")
                gns3vm_version = os.path.join(home, ".config", "GNS3", "gns3vm_version")
                if os.path.isfile(gns3vm_version):
                    try:
                        with open(gns3vm_version) as fd:
                            context["gns3vm:version"] = fd.readline().strip()
                    except OSError:
                        pass

            self._client.tags_context(context)
            try:
                report = self._client.captureException()
            except Exception as e:
                log.error("Can't send crash report to Sentry: {}".format(e))
                return
            log.info("Crash report sent with event ID: {}".format(self._client.get_ident(report)))

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = CrashReport()
        return cls._instance
