using BancaConversacional.Application.Models;
using BancaConversacional.Domain;

namespace BancaConversacional.Application.Abstractions;

public interface IIntentClassifier
{
    Task<IntentType> ClassifyAsync(string userMessage, string? clientId, string conversationId, CancellationToken cancellationToken);
    Task<MovementsFilter> ExtractMovementsFilterAsync(string userMessage, CancellationToken cancellationToken);
    Task<TransferCommand> ExtractTransferCommandAsync(string userMessage, CancellationToken cancellationToken);
}
