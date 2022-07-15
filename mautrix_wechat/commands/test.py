import textwrap

from mautrix.bridge.commands import HelpSection, command_handler
from mautrix.errors import MForbidden
from mautrix.types import EventID

# from mautrix_wechat import puppet as pu, user as u
from mautrix_wechat.commands.types import CommandEvent

SECTION_AUTH = HelpSection("Authentication", 10, "")


@command_handler(
    needs_auth=False,
    management_only=True,
    help_section=SECTION_AUTH,
    help_text="Log in to Wechat",
)
async def login(evt: CommandEvent) -> EventID:
    instructions = f"""
        1. Open [this link]() in your browser.
        2. Log into your Google account normally.
        3. When you reach the loading screen after logging in that says *"One moment please..."*,
           press `F12` to open developer tools.
        4. Select the "Application" (Chrome) or "Storage" (Firefox) tab.
        5. In the sidebar, expand "Cookies" and select `https://accounts.google.com`.
        6. In the cookie list, find the `oauth_code` row and double-click on the value,
           then copy the value and send it here.
    """
    evt.sender.command_status = {
        "action": "Login",
        "room_id": evt.room_id,
    }
    return await evt.reply(textwrap.dedent(instructions.lstrip("\n").rstrip()))

@command_handler(
    needs_auth=False,
    management_only=True,
    help_section=SECTION_AUTH,
    help_text="Mark this room as your bridge notice room",
)
async def set_notice_room(evt: CommandEvent) -> None:
    evt.sender.notice_room = evt.room_id
    await evt.sender.save()
    await evt.reply("This room has been marked as your bridge notice room")
