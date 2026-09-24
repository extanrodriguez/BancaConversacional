using System.Text.Json;
using System.Text;
using BancaConversacional.Application.Abstractions;
using BancaConversacional.Application.Configuration;
using BancaConversacional.Application.Models;
using BancaConversacional.Domain;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace BancaConversacional.Application.Services;

public sealed class ConversationOrchestrator : IConversationOrchestrator
{
    private readonly IIntentClassifier _intentClassifier;
    private readonly IBankingClient _bankingClient;
    private readonly IChatResponder _chatResponder;
    private readonly IServiceCatalogProvider _serviceCatalogProvider;
    private readonly BankingOptions _bankingOptions;
    private readonly ILogger<ConversationOrchestrator> _logger;

    public ConversationOrchestrator(
        IIntentClassifier intentClassifier,
        IBankingClient bankingClient,
        IChatResponder chatResponder,
        IServiceCatalogProvider serviceCatalogProvider,
        IOptions<BankingOptions> bankingOptions,
        ILogger<ConversationOrchestrator> logger)
    {
        _intentClassifier = intentClassifier;
        _bankingClient = bankingClient;
        _chatResponder = chatResponder;
        _serviceCatalogProvider = serviceCatalogProvider;
        _bankingOptions = bankingOptions.Value;
        _logger = logger;
    }

    public async Task<ConversationResult> HandleAsync(IReadOnlyCollection<ChatMessage> messages, string? clientId, string conversationId, CancellationToken cancellationToken)
    {
        var userMessage = messages.LastOrDefault(static m => m.Role.Equals("user", StringComparison.OrdinalIgnoreCase))?.Content?.Trim() ?? string.Empty;
        if (string.IsNullOrWhiteSpace(userMessage))
        {
            return new ConversationResult
            {
                Intent = IntentType.Normal,
                Content = "No pude leer tu mensaje. Intenta de nuevo, por favor."
            };
        }

        var activeClientId = !string.IsNullOrWhiteSpace(clientId) ? clientId : _bankingOptions.ClientId;
        _logger.LogInformation("[ORCHESTRATOR] ClientId activo: {ClientId}", activeClientId);

        IntentType intent;
        try
        {
            intent = await _intentClassifier.ClassifyAsync(userMessage, activeClientId, conversationId, cancellationToken);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "[ORCHESTRATOR] No se pudo clasificar con LLM. Se degradara a flujo normal.");
            intent = IntentType.Normal;
        }

        _logger.LogInformation("[ORCHESTRATOR] Intent detectado: {Intent} para mensaje: {Message}", intent, userMessage);
        
        object? toolData = null;

        switch (intent)
        {
            case IntentType.Balance:
                toolData = await _bankingClient.GetBalanceAsync(activeClientId, cancellationToken);
                _logger.LogInformation("[ORCHESTRATOR] Balance obtenido: {Data}", JsonSerializer.Serialize(toolData));
                break;
            case IntentType.Movements:
            {
                var filter = await _intentClassifier.ExtractMovementsFilterAsync(userMessage, cancellationToken);
                _logger.LogInformation("[ORCHESTRATOR] Filtro extraido: type={Type}, limit={Limit}", filter.Type, filter.Limit);
                toolData = await _bankingClient.GetMovementsAsync(activeClientId, filter, cancellationToken);
                _logger.LogInformation("[ORCHESTRATOR] Movimientos obtenidos: {Data}", JsonSerializer.Serialize(toolData));
                break;
            }
            case IntentType.Transfer:
            {
                var command = await _intentClassifier.ExtractTransferCommandAsync(userMessage, cancellationToken);
                if (command.Amount is null || command.Amount <= 0 || string.IsNullOrWhiteSpace(command.Type))
                {
                    return new ConversationResult
                    {
                        Intent = IntentType.Transfer,
                        Content = "Para procesar la transferencia necesito tipo de operacion (deposito o retiro) y monto."
                    };
                }

                toolData = await _bankingClient.CreateTransactionAsync(activeClientId, command, cancellationToken);
                break;
            }
            case IntentType.Accounts:
                toolData = await _bankingClient.GetAccountsAsync(activeClientId, cancellationToken);
                break;
            case IntentType.Products:
                // "Mis productos" debe consultar productos del cliente (cuentas), no el catalogo general.
                toolData = await _bankingClient.GetAccountsAsync(activeClientId, cancellationToken);
                break;
            case IntentType.Rates:
                toolData = await _bankingClient.GetRatesCatalogAsync(cancellationToken);
                break;
            case IntentType.Notifications:
                toolData = await _bankingClient.GetNotificationsCatalogAsync(cancellationToken);
                break;
            case IntentType.Dashboard:
                toolData = await _bankingClient.GetDashboardSummaryAsync(cancellationToken);
                break;
            case IntentType.ServiceCatalog:
                toolData = _serviceCatalogProvider.GetAll();
                break;
            case IntentType.Normal:
            default:
                break;
        }

        string content;
        if (intent is IntentType.Balance or IntentType.Movements or IntentType.Transfer or
            IntentType.Accounts or IntentType.Products or IntentType.Rates or IntentType.Notifications or
            IntentType.Dashboard or IntentType.ServiceCatalog)
        {
            content = BuildToolSummary(intent, toolData);
        }
        else
        {
            var toolContextNormal = toolData is null ? null : $"Contexto de herramienta bancaria:\n{JsonSerializer.Serialize(toolData)}";
            try
            {
                var llmReply = await _chatResponder.ReplyAsync(messages, toolContextNormal, activeClientId, conversationId, cancellationToken);
                content = llmReply.Content;

                if (llmReply.Options is not null || llmReply.Clarifications is not null || !string.IsNullOrWhiteSpace(llmReply.Status))
                {
                    toolData = new LlmResponseMetadata
                    {
                        Status = llmReply.Status,
                        Options = llmReply.Options,
                        Clarifications = llmReply.Clarifications
                    };
                }
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "[ORCHESTRATOR] No se pudo obtener respuesta del LLM. Se devolvera fallback conversacional.");
                content = "No pude completar la consulta con el motor conversacional en este momento. Intenta nuevamente en unos segundos.";
            }
        }

        if (string.IsNullOrWhiteSpace(content))
        {
            throw new InvalidOperationException($"El flujo principal no devolvio contenido para el intent {intent}.");
        }

        return new ConversationResult
        {
            Intent = intent,
            Content = content,
            ToolData = toolData
        };
    }

    private static string BuildToolSummary(IntentType intent, object? toolData)
    {
        if (intent == IntentType.ServiceCatalog)
        {
            if (toolData is IReadOnlyCollection<ServiceCatalogItem> services)
            {
                return $"Catalogo disponible con {services.Count} servicios para Core Banking, Productos y Seguimiento.";
            }

            return "Catalogo de servicios disponible.";
        }

        if (toolData is not JsonElement element)
        {
            return string.Empty;
        }

        if (intent == IntentType.Balance)
        {
            var balance = element.TryGetProperty("balance", out var balanceEl) ? balanceEl.GetDecimal() : 0m;
            var currency = element.TryGetProperty("currency", out var currencyEl) ? currencyEl.GetString() : "DOP";
            var account = element.TryGetProperty("accountNumber", out var accEl) ? accEl.GetString() : "tu cuenta";
            return $"Tu saldo actual en {account} es {balance:N0} {currency}.";
        }

        if (intent == IntentType.Movements)
        {
            if (!element.TryGetProperty("movements", out var movementsEl) || movementsEl.ValueKind != JsonValueKind.Array)
            {
                return "No encontre movimientos para mostrar en este momento.";
            }

            var sb = new StringBuilder();
            var total = element.TryGetProperty("total", out var totalEl) && totalEl.ValueKind == JsonValueKind.Number
                ? totalEl.GetInt32()
                : movementsEl.GetArrayLength();

            sb.Append($"Encontre {total} movimientos. Ultimos registros:\n");

            var count = 0;
            foreach (var mov in movementsEl.EnumerateArray())
            {
                if (count >= 5)
                {
                    break;
                }

                var createdAt = mov.TryGetProperty("createdAt", out var createdAtEl) ? createdAtEl.GetString() : "sin fecha";
                var type = mov.TryGetProperty("type", out var typeEl) ? typeEl.GetString() : "N/A";
                var amount = mov.TryGetProperty("amount", out var amountEl) && amountEl.ValueKind == JsonValueKind.Number ? amountEl.GetDecimal() : 0m;
                var currency = mov.TryGetProperty("currency", out var currencyEl) ? currencyEl.GetString() : "DOP";
                var description = mov.TryGetProperty("description", out var descriptionEl) ? descriptionEl.GetString() : "sin descripcion";

                sb.Append($"- {createdAt}: {type} {amount:N0} {currency} ({description})\n");
                count++;
            }

            return sb.ToString().Trim();
        }

        if (intent == IntentType.Transfer)
        {
            var status = element.TryGetProperty("status", out var statusEl) ? statusEl.GetString() : "PROCESADA";
            var amount = element.TryGetProperty("amount", out var amountEl) && amountEl.ValueKind == JsonValueKind.Number ? amountEl.GetDecimal() : 0m;
            var currency = element.TryGetProperty("currency", out var currencyEl) ? currencyEl.GetString() : "DOP";
            return $"La transaccion fue registrada con estado {status}. Monto: {amount:N0} {currency}.";
        }

        if (intent == IntentType.Accounts)
        {
            return "Realice la consulta de cuentas del cliente. Te comparto el detalle en los datos adjuntos.";
        }

        if (intent == IntentType.Products)
        {
            if (element.ValueKind == JsonValueKind.Array)
            {
                var total = element.GetArrayLength();
                if (total == 0)
                {
                    return "No encontre productos asociados a tu cliente en este momento.";
                }

                var sb = new StringBuilder();
                sb.Append($"Encontre {total} productos asociados a tu cliente. Primeros registros:\n");

                var count = 0;
                foreach (var item in element.EnumerateArray())
                {
                    if (count >= 5)
                    {
                        break;
                    }

                    var number = item.TryGetProperty("number", out var numberEl) ? numberEl.GetString() : "N/A";
                    var name = item.TryGetProperty("name", out var nameEl) ? nameEl.GetString() : "Producto";
                    var currency = item.TryGetProperty("currency", out var currencyEl) ? currencyEl.GetString() : "DOP";
                    var available = item.TryGetProperty("availableBalance", out var availableEl) && availableEl.ValueKind == JsonValueKind.Number
                        ? availableEl.GetDecimal()
                        : 0m;

                    sb.Append($"- {name} ({number}): {available:N2} {currency}\n");
                    count++;
                }

                return sb.ToString().Trim();
            }

            return "Consulte los productos asociados al cliente.";
        }

        if (intent == IntentType.Rates)
        {
            return "Consulte el catalogo de tasas disponible.";
        }

        if (intent == IntentType.Notifications)
        {
            return "Consulte los servicios de notificacion disponibles.";
        }

        if (intent == IntentType.Dashboard)
        {
            return "Consulte el resumen de seguimiento operacional.";
        }

        return string.Empty;
    }
}
