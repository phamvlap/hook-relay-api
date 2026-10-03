"""Redis Lua script for atomic Token Bucket rate limiting."""

TOKEN_BUCKET_LUA = """
-- KEYS[1]: Rate limit Redis key (e.g. "rl:inbound:tenant:<uuid>:ingest")
-- ARGV[1]: Capacity (bucket max burst size, number)
-- ARGV[2]: Refill rate per second (tokens per second, number)
-- ARGV[3]: Requested tokens / cost (integer, usually 1)

local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local requested = tonumber(ARGV[3])

-- 1. Get Redis server time to prevent application server clock drift
local time_res = redis.call('TIME')          -- 2-element array returned by Redis: [seconds, microseconds]
local now_sec = tonumber(time_res[1])        -- Current UNIX epoch timestamp in whole seconds
local now_usec = tonumber(time_res[2])       -- Sub-second microsecond component (0 to 999,999)
local now = now_sec + (now_usec / 1000000.0) -- Full floating-point epoch timestamp with microsecond precision

-- 2. Fetch current bucket state
local data = redis.call('HMGET', key, 'tokens', 'last_updated')
local tokens = tonumber(data[1])
local last_updated = tonumber(data[2])

-- 3. Calculate replenished tokens
if tokens == nil then
    tokens = capacity
    last_updated = now
else
    local elapsed = math.max(0, now - last_updated)
    tokens = math.min(capacity, tokens + (elapsed * refill_rate))
    last_updated = now
end

local allowed = 0
local retry_after = 0.0

-- 4. Check if sufficient tokens exist
if tokens >= requested then
    allowed = 1
    tokens = tokens - requested
else
    allowed = 0
    retry_after = (requested - tokens) / refill_rate
end

-- 5. Persist updated tokens and timestamp atomically
redis.call('HSET', key, 'tokens', tostring(tokens), 'last_updated', tostring(last_updated))

-- 6. Set key TTL (time to fully replenish from 0 to capacity plus safety buffer)
local ttl = math.ceil(capacity / refill_rate) + 60
redis.call('EXPIRE', key, ttl)

-- 7. Reset epoch timestamp (when bucket will be full again)
local reset_epoch = math.ceil(now + ((capacity - tokens) / refill_rate))

-- Return array: [allowed (0/1), remaining_tokens (string), retry_after (string), reset_epoch (integer)]
return { allowed, tostring(tokens), tostring(retry_after), reset_epoch }
"""
