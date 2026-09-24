using BancaConversacional.Application.Abstractions;
using BancaConversacional.Application.Models;

namespace BancaConversacional.Application.Services;

public sealed class ServiceCatalogProvider : IServiceCatalogProvider
{
    private static readonly IReadOnlyCollection<ServiceCatalogItem> Catalog =
    [
        new ServiceCatalogItem
        {
            Code = "P1-BALANCE",
            Group = "1-CoreBanking",
            Description = "Consultar saldo del cliente.",
            BackendOperation = "GetBalanceAsync",
            Intent = "Balance",
            FrontRequiredData = "clientId"
        },
        new ServiceCatalogItem
        {
            Code = "P1-MOVEMENTS",
            Group = "1-CoreBanking",
            Description = "Consultar movimientos con filtros por tipo y limite.",
            BackendOperation = "GetMovementsAsync",
            Intent = "Movements",
            FrontRequiredData = "clientId, message (tipo/limite opcional)"
        },
        new ServiceCatalogItem
        {
            Code = "P1-TRANSFER",
            Group = "1-CoreBanking",
            Description = "Crear transaccion (deposito/retiro).",
            BackendOperation = "CreateTransactionAsync",
            Intent = "Transfer",
            FrontRequiredData = "clientId, message con tipo y monto"
        },
        new ServiceCatalogItem
        {
            Code = "P1-ACCOUNTS",
            Group = "1-CoreBanking",
            Description = "Consultar cuentas del cliente.",
            BackendOperation = "GetAccountsAsync",
            Intent = "Accounts",
            FrontRequiredData = "clientId"
        },
        new ServiceCatalogItem
        {
            Code = "P3-PRODUCTS",
            Group = "3-Products",
            Description = "Consultar catalogo de productos para onboarding.",
            BackendOperation = "GetProductsCatalogAsync",
            Intent = "Products",
            FrontRequiredData = "ninguno (opcional productType desde front en siguiente iteracion)"
        },
        new ServiceCatalogItem
        {
            Code = "P3-RATES",
            Group = "3-Products",
            Description = "Consultar tasas (certificados/prestamos).",
            BackendOperation = "GetRatesCatalogAsync",
            Intent = "Rates",
            FrontRequiredData = "ninguno (opcional monto/plazo en siguiente iteracion)"
        },
        new ServiceCatalogItem
        {
            Code = "P5-NOTIFICATIONS",
            Group = "5-Tracking",
            Description = "Consultar capacidades de notificacion disponibles.",
            BackendOperation = "GetNotificationsCatalogAsync",
            Intent = "Notifications",
            FrontRequiredData = "ninguno (opcional email/template en siguiente iteracion)"
        },
        new ServiceCatalogItem
        {
            Code = "P5-DASHBOARD",
            Group = "5-Tracking",
            Description = "Consultar resumen para seguimiento operacional.",
            BackendOperation = "GetDashboardSummaryAsync",
            Intent = "Dashboard",
            FrontRequiredData = "ninguno (opcional rango de fechas y userIdentifier en siguiente iteracion)"
        }
    ];

    public IReadOnlyCollection<ServiceCatalogItem> GetAll() => Catalog;
}
