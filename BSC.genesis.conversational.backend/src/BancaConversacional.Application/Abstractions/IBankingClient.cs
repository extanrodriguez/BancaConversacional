using BancaConversacional.Application.Models;

namespace BancaConversacional.Application.Abstractions;

public interface IBankingClient
{
    Task<object> GetPresentationProductAsync(string customerId, CancellationToken cancellationToken);
    Task<object> GetBalanceAsync(string clientId, CancellationToken cancellationToken);
    Task<object> GetMovementsAsync(string clientId, MovementsFilter filter, CancellationToken cancellationToken);
    Task<object> CreateTransactionAsync(string clientId, TransferCommand command, CancellationToken cancellationToken);
    Task<object> GetAccountsAsync(string clientId, CancellationToken cancellationToken);
    Task<object> GetProductsCatalogAsync(CancellationToken cancellationToken);
    Task<object> GetRatesCatalogAsync(CancellationToken cancellationToken);
    Task<object> GetNotificationsCatalogAsync(CancellationToken cancellationToken);
    Task<object> GetDashboardSummaryAsync(CancellationToken cancellationToken);
}
