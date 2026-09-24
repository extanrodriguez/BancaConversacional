using System.Text.Json.Serialization;
using BancaConversacional.Application.Models;

namespace BancaConversacional.Api.Contracts;

public sealed class SocketEnvelope
{
    [JsonPropertyName("requestId")]
    public string? RequestId { get; init; }

    [JsonPropertyName("type")]
    public string? Type { get; init; }

    [JsonPropertyName("action")]
    public string? Action { get; init; }

    [JsonPropertyName("sessionId")]
    public string? SessionId { get; init; }

    [JsonPropertyName("lastReceivedSequence")]
    public long? LastReceivedSequence { get; init; }

    [JsonPropertyName("sequence")]
    public long? Sequence { get; init; }

    [JsonPropertyName("temperature")]
    public double? Temperature { get; init; }

    [JsonPropertyName("max_tokens")]
    public int? MaxTokens { get; init; }

    [JsonPropertyName("top_p")]
    public double? TopP { get; init; }

    [JsonPropertyName("messages")]
    public List<ChatMessage>? Messages { get; init; }

    [JsonPropertyName("data")]
    public SocketData? Data { get; init; }

    [JsonPropertyName("clientId")]
    public string? ClientId { get; init; }

    [JsonPropertyName("customerId")]
    public string? CustomerId { get; init; }
}

public sealed class SocketData
{
    [JsonPropertyName("message")]
    public string? Message { get; init; }

    [JsonPropertyName("content")]
    public string? Content { get; init; }

    [JsonPropertyName("clientId")]
    public string? ClientId { get; init; }

    [JsonPropertyName("customerId")]
    public string? CustomerId { get; init; }

    [JsonPropertyName("typing")]
    public bool? Typing { get; init; }
}
