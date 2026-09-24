using System.Net.Http.Json;
using BancaConversacional.Application.Abstractions;
using BancaConversacional.Application.Models;
using BancaConversacional.Infrastructure.Configuration;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace BancaConversacional.Infrastructure.Clients;

public sealed class BankingApiClient : IBankingClient
{
    private readonly HttpClient _httpClient;
    private readonly ExternalServicesOptions _options;
    private readonly ILogger<BankingApiClient> _logger;

    public BankingApiClient(
        HttpClient httpClient,
        IOptions<ExternalServicesOptions> options,
        ILogger<BankingApiClient> logger)
    {
        _httpClient = httpClient;
        _options = options.Value;
        _logger = logger;

        var baseUrl = ResolveBaseUrl();

        _httpClient.BaseAddress = new Uri(baseUrl.TrimEnd('/') + "/");
        _logger.LogInformation("[BANKING] BaseAddress configurada para entorno {Environment}: {BaseUrl}", ResolveEnvironmentName(), _httpClient.BaseAddress);
    }

    private string ResolveBaseUrl()
    {
        var environment = ResolveEnvironmentName().Trim().ToUpperInvariant();

        var envBaseUrl = environment switch
        {
            "DEVELOPMENT" or "DEV" => _options.BankingApiBaseDev,
            "QA" => _options.BankingApiBaseQa,
            "PRODUCTION" or "PROD" => _options.BankingApiBaseProduction,
            _ => string.Empty
        };

        var resolved = !string.IsNullOrWhiteSpace(envBaseUrl)
            ? envBaseUrl
            : _options.BankingApiBase;

        if (string.IsNullOrWhiteSpace(resolved))
        {
            throw new InvalidOperationException(
                $"No se configuro URL base para servicios bancarios en el entorno '{ResolveEnvironmentName()}'. " +
                "Define ExternalServices__BankingApiBaseDev, ExternalServices__BankingApiBaseQa o ExternalServices__BankingApiBaseProduction segun corresponda.");
        }

        return resolved;
    }

    private static string ResolveEnvironmentName()
    {
        return Environment.GetEnvironmentVariable("ASPNETCORE_ENVIRONMENT")
            ?? Environment.GetEnvironmentVariable("DOTNET_ENVIRONMENT")
            ?? "Production";
    }

    public async Task<object> GetBalanceAsync(string clientId, CancellationToken cancellationToken)
    {
        _logger.LogInformation("[BANKING] Consultando saldo para clientId={ClientId}", clientId);
        var response = await _httpClient.GetAsync($"balance/{Uri.EscapeDataString(clientId)}", cancellationToken);
        return await ToResultAsync(response, "balance", cancellationToken);
    }

    public async Task<object> GetPresentationProductAsync(string customerId, CancellationToken cancellationToken)
    {
        var escapedCustomerId = Uri.EscapeDataString(customerId);
        var url = _options.PresentationProductUrlTemplate
            .Replace("{customerId}", escapedCustomerId, StringComparison.OrdinalIgnoreCase)
            .Replace("{clientId}", escapedCustomerId, StringComparison.OrdinalIgnoreCase)
            .Replace("{clientIdentifier}", escapedCustomerId, StringComparison.OrdinalIgnoreCase);

        _logger.LogInformation("[BANKING] Consultando presentacion de productos para customerId={CustomerId} en {Url}", customerId, url);

        HttpResponseMessage response;
        if (url.StartsWith("https://", StringComparison.OrdinalIgnoreCase))
        {
            _logger.LogWarning("[BANKING] Aplicando bypass TLS explicito para consulta de presentacion de productos.");

            using var insecureHandler = new HttpClientHandler
            {
                ServerCertificateCustomValidationCallback = HttpClientHandler.DangerousAcceptAnyServerCertificateValidator
            };
            using var insecureClient = new HttpClient(insecureHandler)
            {
                Timeout = _httpClient.Timeout
            };

            response = await insecureClient.GetAsync(url, cancellationToken);
        }
        else
        {
            response = await _httpClient.GetAsync(url, cancellationToken);
        }

        return await ToResultAsync(response, "presentation_product", cancellationToken);
    }

    public async Task<object> GetMovementsAsync(string clientId, MovementsFilter filter, CancellationToken cancellationToken)
    {
        var sanitizedType = string.IsNullOrWhiteSpace(filter.Type) || filter.Type.Equals("NULL", StringComparison.OrdinalIgnoreCase) ? null : filter.Type;
        
        _logger.LogInformation("[BANKING] Consultando movimientos para clientId={ClientId}, type={Type}, limit={Limit}", 
            clientId, sanitizedType ?? "<todos>", filter.Limit);
        
        var qs = new List<string>();
        if (!string.IsNullOrWhiteSpace(sanitizedType))
        {
            qs.Add($"type={Uri.EscapeDataString(sanitizedType.ToUpperInvariant())}");
        }

        if (filter.Limit is > 0)
        {
            qs.Add($"limit={filter.Limit.Value}");
        }

        var query = qs.Count > 0 ? $"?{string.Join("&", qs)}" : string.Empty;
        var response = await _httpClient.GetAsync($"movements/{Uri.EscapeDataString(clientId)}{query}", cancellationToken);
        return await ToResultAsync(response, "movements", cancellationToken);
    }

    public async Task<object> CreateTransactionAsync(string clientId, TransferCommand command, CancellationToken cancellationToken)
    {
        _logger.LogInformation("[BANKING] Creando transaccion para clientId={ClientId}, type={Type}, amount={Amount}",
            clientId, command.Type, command.Amount);
        
        var request = new
        {
            clientId,
            amount = command.Amount,
            type = command.Type?.ToUpperInvariant(),
            description = string.IsNullOrWhiteSpace(command.Description) ? "Operacion solicitada desde asistente" : command.Description
        };

        var response = await _httpClient.PostAsJsonAsync("transaction", request, cancellationToken);
        return await ToResultAsync(response, "transaction", cancellationToken);
    }

    public async Task<object> GetAccountsAsync(string clientId, CancellationToken cancellationToken)
    {
        var escapedClientId = Uri.EscapeDataString(clientId);
        var path = _options.AccountsPathTemplate
            .Replace("{clientId}", escapedClientId, StringComparison.OrdinalIgnoreCase)
            .Replace("{clientIdentifier}", escapedClientId, StringComparison.OrdinalIgnoreCase);

        var includeJointAccount = string.IsNullOrWhiteSpace(_options.AccountsIncludeJointAccount)
            ? "S"
            : _options.AccountsIncludeJointAccount.Trim();

        var separator = path.Contains('?', StringComparison.Ordinal) ? "&" : "?";
        path = $"{path}{separator}includeJointAccount={Uri.EscapeDataString(includeJointAccount)}";

        _logger.LogInformation("[BANKING] Consultando cuentas para clientId={ClientId}", clientId);
        var response = await _httpClient.GetAsync(path, cancellationToken);
        return await ToResultAsync(response, "accounts", cancellationToken);
    }

    public async Task<object> GetProductsCatalogAsync(CancellationToken cancellationToken)
    {
        _logger.LogInformation("[BANKING] Consultando catalogo de productos en {Path}", _options.ProductCatalogPath);
        var response = await _httpClient.GetAsync(_options.ProductCatalogPath, cancellationToken);
        return await ToResultAsync(response, "products_catalog", cancellationToken);
    }

    public async Task<object> GetRatesCatalogAsync(CancellationToken cancellationToken)
    {
        _logger.LogInformation("[BANKING] Consultando catalogo de tasas en {Path}", _options.RatesCatalogPath);
        var response = await _httpClient.GetAsync(_options.RatesCatalogPath, cancellationToken);
        return await ToResultAsync(response, "rates_catalog", cancellationToken);
    }

    public async Task<object> GetNotificationsCatalogAsync(CancellationToken cancellationToken)
    {
        _logger.LogInformation("[BANKING] Consultando capacidades de notificaciones en {Path}", _options.NotificationsCatalogPath);
        var response = await _httpClient.GetAsync(_options.NotificationsCatalogPath, cancellationToken);
        return await ToResultAsync(response, "notifications_catalog", cancellationToken);
    }

    public async Task<object> GetDashboardSummaryAsync(CancellationToken cancellationToken)
    {
        var dashboardBaseUrl = ResolveDashboardBaseUrl();
        var absoluteUrl = CombineUrl(dashboardBaseUrl, _options.DashboardSummaryPath);

        _logger.LogInformation("[BANKING] Consultando dashboard summary en {Url}", absoluteUrl);
        var response = await _httpClient.GetAsync(absoluteUrl, cancellationToken);
        return await ToResultAsync(response, "dashboard_summary", cancellationToken);
    }

    private string ResolveDashboardBaseUrl()
    {
        var environment = ResolveEnvironmentName().Trim().ToUpperInvariant();

        var envBaseUrl = environment switch
        {
            "DEVELOPMENT" or "DEV" => _options.DashboardApiBaseDev,
            "QA" => _options.DashboardApiBaseQa,
            "PRODUCTION" or "PROD" => _options.DashboardApiBaseProduction,
            _ => string.Empty
        };

        var resolved = !string.IsNullOrWhiteSpace(envBaseUrl)
            ? envBaseUrl
            : _options.DashboardApiBase;

        if (!string.IsNullOrWhiteSpace(resolved))
        {
            return resolved;
        }

        return ResolveBaseUrl();
    }

    private static string CombineUrl(string baseUrl, string path)
    {
        return $"{baseUrl.TrimEnd('/')}/{path.TrimStart('/')}";
    }

    private async Task<object> ToResultAsync(HttpResponseMessage response, string operation, CancellationToken cancellationToken)
    {
        var payload = await response.Content.ReadAsStringAsync(cancellationToken);
        _logger.LogInformation("[BANKING] Respuesta {Operation}: status={Status}, body={Body}",
            operation, (int)response.StatusCode, payload.Length > 200 ? payload.Substring(0, 200) + "..." : payload);
        
        if (string.IsNullOrWhiteSpace(payload))
        {
            return new { error = $"Respuesta vacia del servicio ({(int)response.StatusCode})" };
        }

        if (!response.IsSuccessStatusCode)
        {
            return new
            {
                error = $"Servicio respondio estado {(int)response.StatusCode}",
                statusCode = (int)response.StatusCode,
                raw = payload
            };
        }

        try
        {
            return System.Text.Json.JsonSerializer.Deserialize<object>(payload) ?? new { error = "No se pudo parsear respuesta" };
        }
        catch (System.Text.Json.JsonException)
        {
            return new
            {
                raw = payload,
                statusCode = (int)response.StatusCode,
                warning = "La respuesta no es JSON valido"
            };
        }
    }
}
