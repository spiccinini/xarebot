"""
Copyright (C) 2025 Santiago Piccinini

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as
published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

import asyncio
import datetime
import json
import logging
import os
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import Any, Dict, FrozenSet, Optional

import aiohttp
import slixmpp
from omemo.storage import Just, Maybe, Nothing, Storage
from omemo.types import DeviceInformation, JSONType
from slixmpp import JID
from slixmpp.exceptions import IqTimeout
from slixmpp.plugins import register_plugin  # type: ignore[attr-defined]
from slixmpp.stanza import Message
from slixmpp_omemo import XEP_0384, TrustLevel
from credentials import OTHER_JID, OWN_JID, PASSWORD

logger = logging.getLogger(__name__)


async def download_file(url):
    filename = os.path.join("/tmp", url.split("/")[-1])
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                resp.raise_for_status()
                with open(filename, "wb") as f:
                    while True:
                        chunk = await resp.content.read(1024)
                        if not chunk:
                            break
                        f.write(chunk)
        logger.info(f"Downloaded file to {filename}")
    except Exception as e:
        logger.info(f"Failed to download file: {e}, {filename}")


class StorageImpl(Storage):
    """
    Example storage implementation that stores all data in a single JSON file.
    """

    JSON_FILE = "omemo-xarebot.json"

    def __init__(self) -> None:
        super().__init__()

        self.__data: Dict[str, JSONType] = {}
        try:
            with open(self.JSON_FILE, encoding="utf8") as f:
                self.__data = json.load(f)
        except Exception:
            pass

    async def _load(self, key: str) -> Maybe[JSONType]:
        if key in self.__data:
            return Just(self.__data[key])
        return Nothing()

    async def _store(self, key: str, value: JSONType) -> None:
        self.__data[key] = value
        with open(self.JSON_FILE, "w", encoding="utf8") as f:
            json.dump(self.__data, f)

    async def _delete(self, key: str) -> None:
        self.__data.pop(key, None)
        with open(self.JSON_FILE, "w", encoding="utf8") as f:
            json.dump(self.__data, f)


class XEP_0384Impl(XEP_0384):  # pylint: disable=invalid-name
    """
    Example implementation of the OMEMO plugin for Slixmpp.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # pylint: disable=redefined-outer-name
        super().__init__(*args, **kwargs)

        # Just the type definition here
        self.__storage: Storage

    def plugin_init(self) -> None:
        self.__storage = StorageImpl()

        super().plugin_init()

    @property
    def storage(self) -> Storage:
        return self.__storage

    @property
    def _btbv_enabled(self) -> bool:
        return False

    async def _devices_blindly_trusted(
        self, blindly_trusted: FrozenSet[DeviceInformation], identifier: Optional[str]
    ) -> None:
        logger.info(f"[{identifier}] Devices trusted blindly: {blindly_trusted}")

    async def _prompt_manual_trust(
        self, manually_trusted: FrozenSet[DeviceInformation], identifier: Optional[str]
    ) -> None:
        session_mananger = await self.get_session_manager()

        for device in manually_trusted:
            while True:
                answer = input(
                    f"[{identifier}] Trust the following device? (yes/no) {device}: "
                )
                if answer in {"yes", "no"}:
                    await session_mananger.set_trust(
                        device.bare_jid,
                        device.identity_key,
                        TrustLevel.TRUSTED.value
                        if answer == "yes"
                        else TrustLevel.DISTRUSTED.value,
                    )
                    break
                print("Please answer yes or no.")


register_plugin(XEP_0384Impl)


class XareBot(slixmpp.ClientXMPP):
    def __init__(self, own_jid, password, other_jid, message=None, file_path=None):
        slixmpp.ClientXMPP.__init__(self, own_jid, password)
        self.own_jid = own_jid
        self.other_jid = other_jid
        self.msg_to_send = message
        self.file_to_send = file_path

        # The session_start event will be triggered when
        # the bot establishes its connection with the server
        # and the XML streams are ready for use. We want to
        # listen for this event so that we we can initialize
        # our roster.
        self.add_event_handler("session_start", self.start)

    async def start(self, event):
        """
        Process the session_start event.

        Typical actions for the session_start event are requesting the roster and broadcasting an initia presence stanza.
        Arguments:
            event -- An empty dictionary. The session_start event does not provide any additional data.
        """
        self.send_presence()
        await self.get_roster()

        received_messages = await self.receive_offline_messages()
        for timestamp, msg in received_messages:
            print(timestamp, msg)

        if self.msg_to_send:
            unencrypted_msg = self.make_message(
                mto=JID(self.other_jid), mbody=self.msg_to_send, mtype="chat"
            )
            await self.send_encrypted_message(unencrypted_msg, to=JID(self.other_jid))

        if self.file_to_send:
            await self.upload_file(Path(self.file_to_send))

        await self.disconnect()

    async def send_encrypted_message(self, unencrypted_message: Message, to):
        xep_0384: XEP_0384 = self["xep_0384"]

        messages, encrypt_errors = await xep_0384.encrypt_message(
            unencrypted_message, to
        )

        if len(encrypt_errors) > 0:
            logger.info(
                f"There were non-critical errors during encryption: {encrypt_errors}"
            )

        for namespace, message in messages.items():
            message["eme"]["namespace"] = namespace
            message["eme"]["name"] = self["xep_0380"].mechanisms[namespace]
            message.send()

    async def receive_offline_messages(self):
        received_messages = []
        start_date = datetime.datetime.now() - datetime.timedelta(hours=6)
        results = self.plugin["xep_0313"].retrieve(
            with_jid=JID(OTHER_JID), iterator=True, rsm={"max": 10}, start=start_date
        )

        async for rsm in results:
            for msg in rsm["mam"]["results"]:
                forwarded = msg["mam_result"]["forwarded"]
                timestamp = forwarded["delay"]["stamp"]
                message = forwarded["stanza"]
                # There are some messages that are "hints" and dont have a body
                if message["from"].bare == OTHER_JID and message["body"]:
                    if message["oob"]["url"]:  # A File sent OOB
                        await download_file(message["oob"]["url"])
                    else:
                        received_messages.append((timestamp, message["body"]))
        return received_messages

    async def upload_file(self, path):
        try:
            url = await self["xep_0454"].upload_file(path, timeout=10)
        except IqTimeout:
            raise TimeoutError("Could not send message in time")
        logger.info("Upload success!")

        logger.info("Sending file to %s.", self.other_jid)
        html = (
            f'<body xmlns="http://www.w3.org/1999/xhtml">'
            f'<a href="{url}">{url}</a></body>'
        )

        unencrypted_msg = self.make_message(
            mto=JID(self.other_jid), mbody=url, mhtml=html
        )
        unencrypted_msg["oob"]["url"] = url
        await self.send_encrypted_message(unencrypted_msg, to=JID(self.other_jid))


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument(
        "-q",
        "--quiet",
        help="set logging to ERROR",
        action="store_const",
        const=logging.ERROR,
        default=logging.INFO,
        dest="loglevel",
    )
    parser.add_argument(
        "-d",
        "--debug",
        help="set logging to DEBUG",
        action="store_const",
        const=logging.DEBUG,
        default=logging.INFO,
        dest="loglevel",
    )
    parser.add_argument("--jid", default=OWN_JID, help="JID to use")
    parser.add_argument("--password", default=PASSWORD, help="password to use")
    parser.add_argument("--to", default=OTHER_JID, help="JID to send the message to")
    parser.add_argument("--send-msg", help="message to send")
    parser.add_argument("--send-file", help="file path")

    args = parser.parse_args()

    logging.basicConfig(level=args.loglevel, format="%(levelname)-8s %(message)s")

    # Setup the EchoBot and register plugins. Note that while plugins may
    # have interdependencies, the order in which you register them does
    # not matter.
    xmpp = XareBot(args.jid, args.password, args.to, args.send_msg, args.send_file)
    xmpp.register_plugin("xep_0030")  # Service Discovery
    xmpp.register_plugin("xep_0199")  # XMPP Ping
    xmpp.register_plugin(
        "xep_0313"
    )  # Message Archive Management (to receive messages while being offline)
    # for file upload
    xmpp.register_plugin("xep_0066")  # Out of band data
    xmpp.register_plugin("xep_0071")  # XHTML-IM To send html
    xmpp.register_plugin("xep_0128")  # Service discovery extensions
    xmpp.register_plugin("xep_0363")  # HTTP file upload
    xmpp.register_plugin("xep_0454")  # OMEMO Media sharing

    # For unencrypted file download
    xmpp.register_plugin("xep_0234")  # Jingle File Transfer

    # for encrypted messages
    xmpp.register_plugin("xep_0380")  # Explicit Message Encryption
    xmpp.register_plugin("xep_0384", module=sys.modules[__name__])  # OMEMO

    # Connect to the XMPP server and start processing XMPP stanzas.
    xmpp.connect()

    asyncio.get_event_loop().run_until_complete(xmpp.disconnected)
