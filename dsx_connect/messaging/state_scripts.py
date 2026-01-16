from __future__ import annotations

# Acquire a scanner slot via an atomic INCR/check/rollback to enforce max inflight.
# This avoids interleaving when multiple scan request workers contend for slots.

ACQUIRE_SCANNER_SLOT_LUA = """
local key = KEYS[1]
local max_inflight = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])

local inflight = redis.call("INCR", key)
if inflight == 1 then
    redis.call("EXPIRE", key, ttl)
end

if inflight > max_inflight then
    redis.call("DECR", key)
    return {0, inflight - 1}
end

return {1, inflight}
"""


def get_acquire_scanner_script(redis_client):
    script = getattr(redis_client, "_acquire_scanner_script", None)
    if script is None:
        script = redis_client.register_script(ACQUIRE_SCANNER_SLOT_LUA)
        setattr(redis_client, "_acquire_scanner_script", script)
    return script
