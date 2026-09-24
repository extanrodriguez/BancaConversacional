using System.Collections.Concurrent;
using System.Text.Json;

namespace BancaConversacional.Api.Services;

public sealed class WebSocketSessionStore
{
    private const int MaxEventsPerSession = 100;
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web);
    private readonly ConcurrentDictionary<string, SessionState> _sessions = new();

    public SessionState Connect(string? requestedSessionId, string userId, string? clientId, string? requestedConversationId)
    {
        var sessionId = string.IsNullOrWhiteSpace(requestedSessionId)
            ? Guid.NewGuid().ToString("N")
            : requestedSessionId.Trim();

        var session = _sessions.AddOrUpdate(
            sessionId,
            _ => SessionState.Create(sessionId, userId, clientId, requestedConversationId),
            (_, current) => current.WithConnection(userId, clientId, requestedConversationId));

        return session;
    }

    public void Disconnect(string sessionId)
    {
        if (!_sessions.TryGetValue(sessionId, out var session))
        {
            return;
        }

        lock (session.SyncRoot)
        {
            session.IsConnected = false;
            session.LastDisconnectedAt = DateTimeOffset.UtcNow;
        }
    }

    public long Acknowledge(string sessionId, long sequence)
    {
        if (!_sessions.TryGetValue(sessionId, out var session))
        {
            return sequence;
        }

        lock (session.SyncRoot)
        {
            session.LastAcknowledgedSequence = Math.Max(session.LastAcknowledgedSequence, sequence);
            session.OutboundEvents.RemoveAll(static e => false);
            session.OutboundEvents.RemoveAll(e => e.Sequence <= session.LastAcknowledgedSequence);
            return session.LastAcknowledgedSequence;
        }
    }

    public StoredSocketEvent AppendOutbound(string sessionId, Func<long, object> payloadFactory)
    {
        if (!_sessions.TryGetValue(sessionId, out var session))
        {
            throw new InvalidOperationException($"No existe la sesion websocket '{sessionId}'.");
        }

        lock (session.SyncRoot)
        {
            var sequence = ++session.LastSequence;
            var payload = payloadFactory(sequence);
            var json = JsonSerializer.Serialize(payload, JsonOptions);
            var stored = new StoredSocketEvent(sequence, json, DateTimeOffset.UtcNow);
            session.OutboundEvents.Add(stored);

            if (session.OutboundEvents.Count > MaxEventsPerSession)
            {
                session.OutboundEvents.RemoveRange(0, session.OutboundEvents.Count - MaxEventsPerSession);
            }

            return stored;
        }
    }

    public IReadOnlyList<StoredSocketEvent> GetPending(string sessionId, long lastReceivedSequence)
    {
        if (!_sessions.TryGetValue(sessionId, out var session))
        {
            return [];
        }

        lock (session.SyncRoot)
        {
            return session.OutboundEvents
                .Where(e => e.Sequence > lastReceivedSequence)
                .Select(e => e with { })
                .ToArray();
        }
    }

    public sealed class SessionState
    {
        public required string SessionId { get; init; }
        public required string UserId { get; init; }
        public required string ConversationId { get; set; }
        public string? ClientId { get; set; }
        public bool IsConnected { get; set; }
        public long LastSequence { get; set; }
        public long LastAcknowledgedSequence { get; set; }
        public DateTimeOffset ConnectedAt { get; set; }
        public DateTimeOffset? LastDisconnectedAt { get; set; }
        public List<StoredSocketEvent> OutboundEvents { get; } = [];
        public object SyncRoot { get; } = new();

        public static SessionState Create(string sessionId, string userId, string? clientId, string? requestedConversationId)
        {
            return new SessionState
            {
                SessionId = sessionId,
                UserId = userId,
                ConversationId = NormalizeConversationId(requestedConversationId) ?? GenerateConversationId(),
                ClientId = clientId,
                IsConnected = true,
                ConnectedAt = DateTimeOffset.UtcNow
            };
        }

        public SessionState WithConnection(string userId, string? clientId, string? requestedConversationId)
        {
            lock (SyncRoot)
            {
                ClientId = string.IsNullOrWhiteSpace(clientId) ? ClientId : clientId;
                var normalizedConversationId = NormalizeConversationId(requestedConversationId);
                if (!string.IsNullOrWhiteSpace(normalizedConversationId))
                {
                    ConversationId = normalizedConversationId;
                }

                IsConnected = true;
                ConnectedAt = DateTimeOffset.UtcNow;
                LastDisconnectedAt = null;
                return this;
            }
        }

        private static string? NormalizeConversationId(string? rawConversationId)
        {
            return string.IsNullOrWhiteSpace(rawConversationId) ? null : rawConversationId.Trim();
        }

        private static string GenerateConversationId()
        {
            var timestamp = DateTimeOffset.UtcNow.ToString("yyyyMMddHHmmssfff");
            var random = Guid.NewGuid().ToString("N")[..8];
            return $"cid-{timestamp}-{random}";
        }
    }

    public sealed record StoredSocketEvent(long Sequence, string Payload, DateTimeOffset CreatedAt);
}
