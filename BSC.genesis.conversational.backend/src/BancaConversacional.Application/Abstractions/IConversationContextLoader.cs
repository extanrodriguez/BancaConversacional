namespace BancaConversacional.Application.Abstractions;

public interface IConversationContextLoader
{
    Task<object?> LoadInitialContextAsync(string customerId, string conversationId, object contextData, CancellationToken cancellationToken);
}