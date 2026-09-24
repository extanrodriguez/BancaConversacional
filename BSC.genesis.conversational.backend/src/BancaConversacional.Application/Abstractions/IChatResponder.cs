using BancaConversacional.Application.Models;

namespace BancaConversacional.Application.Abstractions;

public interface IChatResponder
{
    Task<ChatReplyResult> ReplyAsync(IReadOnlyCollection<ChatMessage> messages, string? toolContext, string? clientId, string conversationId, CancellationToken cancellationToken);
}
