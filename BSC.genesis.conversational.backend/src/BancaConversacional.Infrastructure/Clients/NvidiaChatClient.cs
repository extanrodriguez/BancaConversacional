using System.Globalization;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;
using BancaConversacional.Application.Abstractions;
using BancaConversacional.Application.Models;
using BancaConversacional.Domain;
using BancaConversacional.Infrastructure.Configuration;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace BancaConversacional.Infrastructure.Clients;

public sealed class NvidiaChatClient : IIntentClassifier, IChatResponder, IConversationContextLoader
{
    private const string DefaultCustomerId = "CUST001";

    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = true
    };

    private readonly HttpClient _httpClient;
    private readonly ExternalServicesOptions _options;
    private readonly ILogger<NvidiaChatClient> _logger;
    private readonly string _turnEndpoint;

    public NvidiaChatClient(HttpClient httpClient, IOptions<ExternalServicesOptions> options, ILogger<NvidiaChatClient> logger)
    {
        _httpClient = httpClient;
        _options = options.Value;
        _logger = logger;

        _turnEndpoint = ResolveTurnEndpoint(_options);
        _logger.LogInformation("[RAG] Endpoint /turn configurado: {Endpoint}", _turnEndpoint);

        _httpClient.DefaultRequestHeaders.Authorization = null;
        _httpClient.DefaultRequestHeaders.Remove("api-key");
        _httpClient.DefaultRequestHeaders.Remove("x-api-key");

        if (_options.SendPrivateRagApiKey && !string.IsNullOrWhiteSpace(_options.PrivateRagApiKey))
        {
            var headerName = string.IsNullOrWhiteSpace(_options.PrivateRagApiKeyHeaderName)
                ? "x-api-key"
                : _options.PrivateRagApiKeyHeaderName.Trim();

            _httpClient.DefaultRequestHeaders.Remove(headerName);
            _httpClient.DefaultRequestHeaders.Add(headerName, _options.PrivateRagApiKey.Trim());
        }
    }

    public async Task<IntentType> ClassifyAsync(string userMessage, string? clientId, string conversationId, CancellationToken cancellationToken)
    {
        var customerId = ResolveCustomerIdValue(clientId);
        var ragResponse = await QueryRagAsync(customerId, userMessage, conversationId, cancellationToken);
        if (ragResponse?.HasError == true)
        {
            _logger.LogWarning("[RAG] Clasificacion degradada por error de /turn: {Error}", ragResponse.ErrorDetail);
            return IntentType.Normal;
        }

        if (string.IsNullOrWhiteSpace(ragResponse?.Intent))
        {
            _logger.LogInformation("[RAG] Respuesta sin intent. Se usara IntentType.Normal. conversationId={ConversationId}", conversationId);
            return IntentType.Normal;
        }

        var intent = ResolveIntent(ragResponse?.Intent, userMessage, ragResponse?.IntentCategory);

        return intent;
    }

    public Task<MovementsFilter> ExtractMovementsFilterAsync(string userMessage, CancellationToken cancellationToken)
    {
        var normalized = userMessage.ToUpperInvariant();

        string? type = null;
        if (normalized.Contains("DEPOSITO") || normalized.Contains("ABONO"))
        {
            type = "deposito";
        }
        else if (normalized.Contains("RETIRO") || normalized.Contains("DEBITO") || normalized.Contains("CARGO"))
        {
            type = "retiro";
        }

        int? limit = null;
        var match = Regex.Match(normalized, @"\b(\d{1,2})\b");
        if (match.Success && int.TryParse(match.Groups[1].Value, out var parsed))
        {
            limit = Math.Clamp(parsed, 1, 100);
        }

        return Task.FromResult(new MovementsFilter
        {
            Type = type,
            Limit = limit
        });
    }

    public Task<TransferCommand> ExtractTransferCommandAsync(string userMessage, CancellationToken cancellationToken)
    {
        var normalized = userMessage.ToUpperInvariant();

        string? type = null;
        if (normalized.Contains("RETIRO"))
        {
            type = "retiro";
        }
        else if (normalized.Contains("DEPOSITO") || normalized.Contains("ABONO"))
        {
            type = "deposito";
        }
        else if (normalized.Contains("TRANSFER") || normalized.Contains("PAGO"))
        {
            type = "transferencia";
        }

        decimal? amount = TryExtractAmount(userMessage);

        return Task.FromResult(new TransferCommand
        {
            Type = type,
            Amount = amount,
            Description = userMessage.Trim()
        });
    }

    public async Task<ChatReplyResult> ReplyAsync(IReadOnlyCollection<ChatMessage> messages, string? toolContext, string? clientId, string conversationId, CancellationToken cancellationToken)
    {
        var userMessage = messages.LastOrDefault(static m => m.Role.Equals("user", StringComparison.OrdinalIgnoreCase))?.Content?.Trim();
        if (string.IsNullOrWhiteSpace(userMessage))
        {
            return new ChatReplyResult
            {
                Content = "No pude leer tu mensaje. Intenta de nuevo, por favor."
            };
        }

        var customerId = ResolveCustomerIdValue(clientId);
        var ragResponse = await QueryRagAsync(customerId, userMessage, conversationId, cancellationToken);
        if (ragResponse is null)
        {
            _logger.LogWarning("[RAG] /turn devolvio error o respuesta vacia. Se retorna fallback conversacional para no romper el socket.");
            return new ChatReplyResult
            {
                Content = "No pude completar la consulta al motor conversacional en este momento. Por favor intenta nuevamente en unos segundos."
            };
        }

        if (ragResponse.HasError)
        {
            return new ChatReplyResult
            {
                Content = "No pude completar la consulta al motor conversacional en este momento."
            };
        }

        return new ChatReplyResult
        {
            Content = string.IsNullOrWhiteSpace(ragResponse.Reply)
                ? "No se pudo generar una respuesta en este momento."
                : ragResponse.Reply.Trim(),
            Status = ragResponse.AppChannelStatus,
            Options = ragResponse.Options,
            Clarifications = ragResponse.Clarifications
        };
    }

    public async Task<object?> LoadInitialContextAsync(string customerId, string conversationId, object contextData, CancellationToken cancellationToken)
    {
        var effectiveCustomerId = ResolveCustomerIdValue(customerId);
        var request = new RagContextLoadRequest
        {
            CustomerId = effectiveCustomerId,
            ConversationId = conversationId,
            Question = null,
            ForceCoreQuery = false,
            ContextInfo = true,
            Context = new RagContextWrapper
            {
                Data = contextData
            }
        };

        var json = JsonSerializer.Serialize(request, JsonOptions);

        _logger.LogInformation(
            "[RAG][TEMP] Payload carga de contexto /turn. customerId={CustomerId}, conversationId={ConversationId}, body={Body}",
            effectiveCustomerId,
            conversationId,
            Truncate(json, 12000));

        using var payload = new ByteArrayContent(Encoding.UTF8.GetBytes(json));
        payload.Headers.ContentType = new MediaTypeHeaderValue("application/json");

        using var response = await _httpClient.PostAsync(_turnEndpoint, payload, cancellationToken);
        var body = await response.Content.ReadAsStringAsync(cancellationToken);

        if (!response.IsSuccessStatusCode)
        {
            throw new HttpRequestException(
                $"Carga de contexto al endpoint /turn fallo con estado {(int)response.StatusCode}. Body={Truncate(body, 1200)}");
        }

        object? parsedResponse = null;
        if (!string.IsNullOrWhiteSpace(body))
        {
            try
            {
                parsedResponse = JsonSerializer.Deserialize<object>(body, JsonOptions);
            }
            catch (JsonException)
            {
                parsedResponse = body;
            }
        }

        _logger.LogInformation(
            "[RAG] Carga de contexto inicial enviada. customerId={CustomerId}, conversationId={ConversationId}, statusCode={StatusCode}",
            effectiveCustomerId,
            conversationId,
            (int)response.StatusCode);

        return parsedResponse;
    }

    private async Task<RagFrontResponse?> QueryRagAsync(string customerId, string userMessage, string conversationId, CancellationToken cancellationToken)
    {
        var request = new RagFrontRequest
        {
            CustomerId = ResolveCustomerIdValue(customerId),
            Question = userMessage,
            ConversationId = conversationId,
            ForceCoreQuery = false
        };

        try
        {
            var json = JsonSerializer.Serialize(request, JsonOptions);
            using var payload = new ByteArrayContent(Encoding.UTF8.GetBytes(json));
            payload.Headers.ContentType = new MediaTypeHeaderValue("application/json");

            using var response = await _httpClient.PostAsync(_turnEndpoint, payload, cancellationToken);
            var body = await response.Content.ReadAsStringAsync(cancellationToken);

            if (!response.IsSuccessStatusCode)
            {
                _logger.LogWarning("[RAG] Error {StatusCode} al consumir endpoint /turn. Body={Body}", (int)response.StatusCode, body);
                return new RagFrontResponse
                {
                    HasError = true,
                    StatusCode = (int)response.StatusCode,
                    ErrorDetail = "Respuesta no exitosa de /turn",
                    RawResponse = Truncate(body, 1200)
                };
            }

            return ParseTurnResponse(body);
        }
        catch (HttpRequestException ex)
        {
            _logger.LogWarning(ex, "[RAG] Fallo de transporte al consumir endpoint /turn.");
            return RagFrontResponse.FromException(ex, "Error de transporte en /turn");
        }
        catch (IOException ex)
        {
            _logger.LogWarning(ex, "[RAG] Error de IO al consumir endpoint /turn.");
            return RagFrontResponse.FromException(ex, "Error de IO en /turn");
        }
        catch (TaskCanceledException ex) when (!cancellationToken.IsCancellationRequested)
        {
            _logger.LogWarning(ex, "[RAG] Timeout al consumir endpoint /turn.");
            return RagFrontResponse.FromException(ex, "Timeout en /turn");
        }
        catch (JsonException ex)
        {
            _logger.LogWarning(ex, "[RAG] No se pudo parsear la respuesta del endpoint /turn.");
            return RagFrontResponse.FromException(ex, "Respuesta JSON invalida de /turn");
        }
    }

    private static string Truncate(string value, int maxLength)
    {
        if (string.IsNullOrEmpty(value) || value.Length <= maxLength)
        {
            return value;
        }

        return value[..maxLength] + "...";
    }

    private static RagFrontResponse ParseTurnResponse(string body)
    {
        using var doc = JsonDocument.Parse(body);
        var root = doc.RootElement;

        var appChannel = root.TryGetProperty("app_channel", out var appChannelElement)
            ? appChannelElement
            : default;

        var reply = TryGetString(appChannel, "client_response")
            ?? TryGetString(root, "reply")
            ?? TryGetString(root, "answer")
            ?? TryGetString(root, "response")
            ?? TryGetString(root, "message");

        var intent = TryGetString(appChannel, "intent_id")
            ?? TryGetString(root, "intent")
            ?? TryGetString(root, "intent_name");

        var intentCategory = TryGetString(appChannel, "status")
            ?? TryGetString(root, "intent_category")
            ?? TryGetString(root, "category");

        var conversationId = TryGetString(appChannel, "conversation_id")
            ?? TryGetString(root, "conversation_id");

        return new RagFrontResponse
        {
            Reply = reply,
            Intent = intent,
            IntentCategory = intentCategory,
            ConversationId = conversationId,
            RawResponse = body,
            AppChannelStatus = TryGetString(appChannel, "status"),
            TurnNumber = TryGetInt(appChannel, "turn_number"),
            AccountRef = TryGetString(appChannel, "account_ref"),
            Options = TryGetObject(appChannel, "options"),
            Clarifications = TryGetObject(appChannel, "clarifications")
        };
    }

    private static string? TryGetString(JsonElement root, string propertyName)
    {
        if (root.ValueKind is JsonValueKind.Undefined or JsonValueKind.Null)
        {
            return null;
        }

        if (!root.TryGetProperty(propertyName, out var value))
        {
            return null;
        }

        return value.ValueKind == JsonValueKind.String ? value.GetString() : value.ToString();
    }

    private static int? TryGetInt(JsonElement root, string propertyName)
    {
        if (root.ValueKind is JsonValueKind.Undefined or JsonValueKind.Null)
        {
            return null;
        }

        if (!root.TryGetProperty(propertyName, out var value))
        {
            return null;
        }

        return value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out var parsed)
            ? parsed
            : null;
    }

    private static object? TryGetObject(JsonElement root, string propertyName)
    {
        if (root.ValueKind is JsonValueKind.Undefined or JsonValueKind.Null)
        {
            return null;
        }

        if (!root.TryGetProperty(propertyName, out var value))
        {
            return null;
        }

        if (value.ValueKind is JsonValueKind.Null or JsonValueKind.Undefined)
        {
            return null;
        }

        return JsonSerializer.Deserialize<object>(value.GetRawText(), JsonOptions);
    }

    private IntentType ResolveIntent(string? endpointIntent, string userMessage, string? endpointIntentCategory)
    {
        var normalizedIntent = NormalizeToken(endpointIntent);
        var normalizedCategory = NormalizeToken(endpointIntentCategory);

        if (string.IsNullOrWhiteSpace(normalizedIntent))
        {
            return IntentType.Normal;
        }

        var mapped = normalizedIntent switch
        {
            "BALANCE" or "CONSULTAR_SALDO" => IntentType.Balance,
            "MOVEMENTS" or "CONSULTAR_MOVIMIENTOS" or "TRANSACTION_SEARCH" => IntentType.Movements,
            "TRANSFER" or "TRANSFERIR_FONDOS" or "PAGAR_TARJETA" or "BLOQUEAR_TARJETA" => IntentType.Transfer,
            "ACCOUNTS" => IntentType.Accounts,
            "PRODUCTS" or "INFORMACION_PRESTAMO" => IntentType.Products,
            "RATES" => IntentType.Rates,
            "NOTIFICATIONS" => IntentType.Notifications,
            "DASHBOARD" => IntentType.Dashboard,
            "CATALOG" or "SERVICE_CATALOG" => IntentType.ServiceCatalog,
            _ => IntentType.Normal
        };

        if (mapped != IntentType.Normal)
        {
            return mapped;
        }

        _logger.LogInformation(
            "[RAG] Intent no homologado recibido: {Intent}. Se tratara como mensaje normal.",
            endpointIntent ?? "<null>");

        // Fallback defensivo: intents conversacionales como "greeting" no deben romper el flujo WS.
        if (normalizedIntent is "GREETING" or "SALUDO" or "SMALLTALK" or "NORMAL")
        {
            return IntentType.Normal;
        }

        if (normalizedCategory is "INFORMATIVA" or "CONVERSACIONAL" or "GENERAL")
        {
            return IntentType.Normal;
        }

        return IntentType.Normal;
    }

    private static string NormalizeToken(string? value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return string.Empty;
        }

        var upper = value.Trim().ToUpperInvariant();
        var chars = upper.Where(static c => c is >= 'A' and <= 'Z' or '_').ToArray();
        return new string(chars);
    }

    private static decimal? TryExtractAmount(string userMessage)
    {
        var match = Regex.Match(userMessage, @"(?:RD\$|USD\$|US\$|\$)?\s*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})|\d+(?:[.,]\d{1,2})?)", RegexOptions.IgnoreCase);
        if (!match.Success)
        {
            return null;
        }

        var raw = match.Groups[1].Value.Trim();
        var normalized = raw.Replace(" ", string.Empty, StringComparison.Ordinal)
            .Replace(".", string.Empty, StringComparison.Ordinal)
            .Replace(',', '.');

        if (decimal.TryParse(normalized, NumberStyles.Number, CultureInfo.InvariantCulture, out var amount))
        {
            return amount;
        }

        return null;
    }

    private static string ResolveCustomerIdValue(string? customerId)
    {
        return string.IsNullOrWhiteSpace(customerId)
            ? DefaultCustomerId
            : customerId.Trim();
    }

    private static string ResolveTurnEndpoint(ExternalServicesOptions options)
    {
        var envEndpoint = Environment.GetEnvironmentVariable("LLM_TURN_ENDPOINT");
        if (string.IsNullOrWhiteSpace(envEndpoint))
        {
            throw new InvalidOperationException(
                "LLM_TURN_ENDPOINT es requerido y no puede ser vacio. " +
                "Para evitar fallback accidental al endpoint legacy, ya no se utiliza ExternalServices:PrivateRagEndpoint para /turn.");
        }

        var trimmed = envEndpoint.Trim();
        if (!Uri.TryCreate(trimmed, UriKind.Absolute, out var uri))
        {
            throw new InvalidOperationException("LLM_TURN_ENDPOINT no es una URL absoluta valida.");
        }

        if (!uri.AbsolutePath.TrimEnd('/').EndsWith("/turn", StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException(
                $"LLM_TURN_ENDPOINT debe apuntar a '/turn'. Valor recibido: '{trimmed}'.");
        }

        return trimmed;
    }

    private sealed class RagFrontRequest
    {
        [JsonPropertyName("customer_id")]
        public string CustomerId { get; init; } = string.Empty;

        [JsonPropertyName("question")]
        public string Question { get; init; } = string.Empty;

        [JsonPropertyName("conversation_id")]
        public string ConversationId { get; init; } = string.Empty;

        [JsonPropertyName("force_core_query")]
        public bool ForceCoreQuery { get; init; }
    }

    private sealed class RagContextLoadRequest
    {
        [JsonPropertyName("customer_id")]
        public string CustomerId { get; init; } = string.Empty;

        [JsonPropertyName("conversation_id")]
        public string ConversationId { get; init; } = string.Empty;

        [JsonPropertyName("question")]
        public string? Question { get; init; }

        [JsonPropertyName("force_core_query")]
        public bool ForceCoreQuery { get; init; }

        [JsonPropertyName("context_info")]
        public bool ContextInfo { get; init; }

        [JsonPropertyName("context")]
        public RagContextWrapper? Context { get; init; }
    }

    private sealed class RagContextWrapper
    {
        [JsonPropertyName("data")]
        public object? Data { get; init; }
    }

    private sealed class RagFrontResponse
    {
        [JsonPropertyName("reply")]
        public string? Reply { get; init; }

        [JsonPropertyName("conversation_id")]
        public string? ConversationId { get; init; }

        [JsonPropertyName("intent")]
        public string? Intent { get; init; }

        [JsonPropertyName("intent_category")]
        public string? IntentCategory { get; init; }

        public string? AppChannelStatus { get; init; }

        public int? TurnNumber { get; init; }

        public string? AccountRef { get; init; }

        public object? Options { get; init; }

        public object? Clarifications { get; init; }

        public string RawResponse { get; init; } = string.Empty;

        public bool HasError { get; init; }

        public int? StatusCode { get; init; }

        public string? ErrorDetail { get; init; }

        public static RagFrontResponse FromException(Exception ex, string detail)
        {
            return new RagFrontResponse
            {
                HasError = true,
                ErrorDetail = detail,
                RawResponse = ex.InnerException?.Message ?? ex.Message
            };
        }
    }
}
