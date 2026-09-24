using BancaConversacional.Domain;

namespace BancaConversacional.Application.Models;

public sealed class ConversationResult
{
    public required IntentType Intent { get; init; }
    public required string Content { get; init; }
    public object? ToolData { get; init; }
}
