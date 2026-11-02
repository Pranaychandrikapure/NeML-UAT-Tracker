"""Create a Clerk sign-in ticket for the test admin (prints only the ticket)."""
import urllib.parse
from conftest import _bapi, EMAIL

u = _bapi(f"/users?email_address={urllib.parse.quote(EMAIL)}", method="GET")[0]
print(_bapi("/sign_in_tokens", {"user_id": u["id"], "expires_in_seconds": 7200})["token"])
