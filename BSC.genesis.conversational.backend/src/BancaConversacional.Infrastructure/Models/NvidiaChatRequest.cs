using System.Text.Json.Serialization;

namespace BancaConversacional.Infrastructure.Models;

internal sealed class NvidiaChatRequest
{
    [JsonPropertyName("model")]
    public required string Model { get; init; }

    [JsonPropertyName("messages")]
    public required List<NvidiaMessage> Messages { get; init; }

    [JsonPropertyName("temperature")]
    public double Temperature { get; init; } = 0;

    [JsonPropertyName("max_completion_tokens")]
    public int MaxCompletionTokens { get; init; } = 64;

    [JsonPropertyName("stream")]
    public bool Stream { get; init; } = false;
}

internal sealed class NvidiaMessage
{
    [JsonPropertyName("role")]
    public required string Role { get; init; }

    [JsonPropertyName("content")]
    public required string Content { get; init; }
}
