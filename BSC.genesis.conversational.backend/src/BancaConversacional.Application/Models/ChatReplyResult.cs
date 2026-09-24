namespace BancaConversacional.Application.Models;

public sealed class ChatReplyResult
{
    public required string Content { get; init; }
    public string? Status { get; init; }
    public object? Options { get; init; }
    public object? Clarifications { get; init; }
}

public sealed class LlmResponseMetadata
{
    public string? Status { get; init; }
    public object? Options { get; init; }
    public object? Clarifications { get; init; }
}