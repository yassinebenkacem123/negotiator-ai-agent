"""
call_me.py -- Call YOUR phone via Twilio + AI negotiation pipeline.

USAGE:
  1. ngrok http 8000                       (in a separate terminal)
  2. Note the https:// URL (e.g. https://abc123.ngrok.io)
  3. uvicorn app.main:app --reload         (in a separate terminal)
  4. python call_me.py +33612345678 https://abc123.ngrok.io

Your phone rings. Answer it. The AI says hello and talks to you.
"""

import sys, os

def _load_dotenv():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.isfile(p):
        for line in open(p):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                if k.strip() and k.strip() not in os.environ:
                    os.environ[k.strip()] = v.strip()

_load_dotenv()
from app.config import settings
from twilio.rest import Client

if len(sys.argv) < 3:
    print(__doc__)
    sys.exit(1)

YOUR_PHONE = sys.argv[1]
NGROK_URL  = sys.argv[2].rstrip("/")

client = Client(settings.twilio_account_sid, settings.twilio_auth_token)

# The TwiML URL -- Twilio fetches this when the call is answered.
# Returns <Stream url="wss://abc123.ngrok.io/media-stream/Me"/> which
# opens the WebSocket where stream_handler.py handles everything.
twiml_url = (
    f"{NGROK_URL}/twiml/Me?wss_url={NGROK_URL.replace('https://', 'wss://')}"
)

print(f"Calling {YOUR_PHONE} via {NGROK_URL} ...")
print(f"TwiML URL: {twiml_url}")

call = client.calls.create(
    to=YOUR_PHONE,
    from_=settings.twilio_from_number,
    url=twiml_url,
    timeout=180,
)

print(f"\nCall placed!")
print(f"  SID:       {call.sid}")
print(f"  Status:    {call.status}")
print(f"\nYour phone is ringing -- answer it and talk to the AI.")
print(f"Watch the uvicorn terminal for live logs.")
