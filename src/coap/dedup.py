"""CoAP Confirmable-message deduplication — design notes.

aiocoap implements RFC 7252 dedup natively in its MessageManager.
When a CON request arrives, the server records the tuple
(remote_endpoint, message_id) in a cache keyed by that tuple for
EXCHANGE_LIFETIME seconds (~247s by default). If a duplicate arrives
within that window, aiocoap replays the cached ACK / piggybacked
response instead of re-invoking the resource handler.

What this means for Phase 2:

    * HvacResource.render_put() runs EXACTLY ONCE per logical request,
      even if the CON is retransmitted because the gateway's ACK was
      lost on the UDP path.
    * apply_command() therefore cannot double-apply an actuator change
      during a UDP retransmit storm — this is a correctness property we
      get for free from aiocoap, without app-level state.
    * We verify this invariant in tests/test_coap_dedup.py by issuing
      two CON messages with the same message_id within EXCHANGE_LIFETIME
      and asserting apply_command is called once.

Implementation note: nothing in this module actually executes. It
exists as a deliberate anchor for the dedup invariant so that a future
reviewer can find the argument in one place. If the aiocoap behavior
ever changes, the linked test will fail and force a re-evaluation.
"""

EXCHANGE_LIFETIME_SECONDS = 247
