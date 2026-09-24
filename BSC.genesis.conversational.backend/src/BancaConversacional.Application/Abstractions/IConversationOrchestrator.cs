using BancaConversacional.Application.Models;

namespace BancaConversacional.Application.Abstractions;

public interface IConversationOrchestrator
{
    Task<ConversationResult> HandleAsync(IReadOnlyCollection<ChatMessage> messages, string? clientId, string conversationId, CancellationToken cancellationToken);
}
