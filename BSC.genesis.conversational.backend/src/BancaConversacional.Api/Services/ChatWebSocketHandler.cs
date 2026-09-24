using System.Net.WebSockets;
using System.Security.Claims;
using System.Text;
using System.Text.Json;
using System.Collections;
using BancaConversacional.Api.Contracts;
using BancaConversacional.Application.Abstractions;
using BancaConversacional.Application.Configuration;
using BancaConversacional.Application.Models;
using Microsoft.Extensions.Primitives;
using Microsoft.Extensions.Options;

namespace BancaConversacional.Api.Services;

public sealed class ChatWebSocketHandler
{
    private const string InitialContextFirstName = "usuario 1";

    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = true
    };

    private readonly IConversationOrchestrator _orchestrator;
    private readonly IBankingClient _bankingClient;
    private readonly IConversationContextLoader _contextLoader;
    private readonly WebSocketSessionStore _sessionStore;
    private readonly BankingOptions _bankingOptions;
    private readonly ILogger<ChatWebSocketHandler> _logger;

    public ChatWebSocketHandler(
        IConversationOrchestrator orchestrator,
        IBankingClient bankingClient,
        IConversationContextLoader contextLoader,
        WebSocketSessionStore sessionStore,
        IOptions<BankingOptions> bankingOptions,
        ILogger<ChatWebSocketHandler> logger)
    {
        _orchestrator = orchestrator;
        _bankingClient = bankingClient;
        _contextLoader = contextLoader;
        _sessionStore = sessionStore;
        _bankingOptions = bankingOptions.Value;
        _logger = logger;
    }

    public async Task HandleAsync(WebSocket socket, HttpContext httpContext, CancellationToken cancellationToken)
    {
        var connectionCustomerId = ResolveConnectionCustomerId(httpContext);
        var session = _sessionStore.Connect(
            httpContext.Request.Query["sessionId"].ToString(),
            ResolveUserId(httpContext.User),
            connectionCustomerId,
            httpContext.Request.Query["conversationId"].ToString());

        await SendAsync(socket, new
        {
            type = "connected",
            action = "handshake_ack",
            message = "Conexion establecida con el servidor .NET",
            sessionId = session.SessionId,
            conversationId = session.ConversationId,
            timestamp = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
            replaySupported = true,
            lastAcknowledgedSequence = session.LastAcknowledgedSequence
        }, cancellationToken);

        await ExecuteInitialBootstrapAsync(socket, session, connectionCustomerId, cancellationToken);

        if (TryParseSequence(httpContext.Request.Query["lastReceivedSequence"], out var handshakeSequence))
        {
            await ReplayPendingAsync(socket, session.SessionId, handshakeSequence, cancellationToken);
        }

        var buffer = new byte[16 * 1024];
        try
        {
            while (socket.State == WebSocketState.Open && !cancellationToken.IsCancellationRequested)
            {
                var received = await ReceiveFullMessage(socket, buffer, cancellationToken);
                if (received is null)
                {
                    break;
                }

                if (!TryParseEnvelope(received, out var envelope, out var parseError))
                {
                    await SendAsync(socket, new { type = "error", action = "invalid_payload", message = parseError }, cancellationToken);
                    continue;
                }

                var requestId = envelope?.RequestId;

                if (await TryHandleControlEventAsync(socket, envelope, session.SessionId, requestId, cancellationToken))
                {
                    continue;
                }

                var messages = NormalizeMessages(envelope);
                if (messages.Count == 0)
                {
                    await SendAsync(socket, new
                    {
                        type = "error",
                        action = "empty_message",
                        message = "No se encontro contenido del usuario.",
                        sessionId = session.SessionId,
                        requestId
                    }, cancellationToken);
                    continue;
                }

                var customerId = ResolveCustomerId(envelope, connectionCustomerId);

                try
                {
                    await SendAsync(socket, new
                    {
                        type = "status",
                        action = "processing",
                        sessionId = session.SessionId,
                        requestId,
                        timestamp = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()
                    }, cancellationToken);

                    var result = await _orchestrator.HandleAsync(messages, customerId, session.ConversationId, cancellationToken);

                    await SendAsync(socket, new
                    {
                        type = "status",
                        action = "typing",
                        sessionId = session.SessionId,
                        requestId,
                        timestamp = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()
                    }, cancellationToken);

                    await SendTrackedAsync(
                        socket,
                        session.SessionId,
                        sequence => new
                        {
                            type = "message",
                            action = "bot_response",
                            sequence,
                            sessionId = session.SessionId,
                            data = new
                            {
                                content = result.Content,
                                message = result.Content,
                                options = (result.ToolData as LlmResponseMetadata)?.Options,
                                clarifications = (result.ToolData as LlmResponseMetadata)?.Clarifications,
                                status = (result.ToolData as LlmResponseMetadata)?.Status
                            },
                            timestamp = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                            requestId,
                            intent = result.Intent.ToString(),
                            toolData = result.ToolData
                        },
                        cancellationToken);
                }
                catch (Exception ex)
                {
                    _logger.LogError(ex, "Error procesando mensaje websocket.");
                    await SendTrackedAsync(
                        socket,
                        session.SessionId,
                        sequence => new
                        {
                            type = "error",
                            action = "processing_error",
                            sequence,
                            sessionId = session.SessionId,
                            message = "Error interno procesando solicitud.",
                            data = new
                            {
                                errorType = ex.GetType().Name,
                                errorMessage = ex.Message,
                                innerError = ex.InnerException?.Message
                            },
                            requestId,
                            timestamp = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()
                        },
                        cancellationToken);
                }
            }
        }
        finally
        {
            _sessionStore.Disconnect(session.SessionId);
        }
    }

    private async Task ExecuteInitialBootstrapAsync(
        WebSocket socket,
        WebSocketSessionStore.SessionState session,
        string customerId,
        CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(customerId))
        {
            await SendTrackedAsync(
                socket,
                session.SessionId,
                sequence => new
                {
                    type = "status",
                    action = "initial_bank_query_audit",
                    sequence,
                    sessionId = session.SessionId,
                    conversationId = session.ConversationId,
                    data = new
                    {
                        status = "skipped",
                        reason = "customer_id_vacio",
                        customerId = customerId
                    },
                    timestamp = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()
                },
                cancellationToken);
            return;
        }

        await SendTrackedAsync(
            socket,
            session.SessionId,
            sequence => new
            {
                type = "status",
                action = "initial_bank_query_audit",
                sequence,
                sessionId = session.SessionId,
                conversationId = session.ConversationId,
                data = new
                {
                    status = "started",
                    customerId
                },
                timestamp = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()
            },
            cancellationToken);

        try
        {
            var initialBankResponse = await _bankingClient.GetPresentationProductAsync(customerId, cancellationToken);
            var normalizedPresentation = NormalizePresentationProductResponse(initialBankResponse);

            await SendTrackedAsync(
                socket,
                session.SessionId,
                sequence => new
                {
                    type = "status",
                    action = "initial_bank_query_audit",
                    sequence,
                    sessionId = session.SessionId,
                    conversationId = session.ConversationId,
                    data = new
                    {
                        status = "success",
                        customerId
                    },
                    timestamp = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()
                },
                cancellationToken);

            await SendTrackedAsync(
                socket,
                session.SessionId,
                sequence => new
                {
                    type = "status",
                    action = "initial_bank_response",
                    sequence,
                    sessionId = session.SessionId,
                    conversationId = session.ConversationId,
                    data = new
                    {
                        customerId,
                        source = "presentation_product",
                        presentation = normalizedPresentation,
                        response = initialBankResponse
                    },
                    timestamp = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()
                },
                cancellationToken);

            if (!ShouldLoadInitialContext(initialBankResponse, normalizedPresentation, out var skipReason))
            {
                _logger.LogWarning(
                    "Se omite carga de contexto inicial para conversationId={ConversationId}, customerId={CustomerId}. Motivo={Reason}",
                    session.ConversationId,
                    customerId,
                    skipReason);

                await SendTrackedAsync(
                    socket,
                    session.SessionId,
                    sequence => new
                    {
                        type = "status",
                        action = "initial_context_load_audit",
                        sequence,
                        sessionId = session.SessionId,
                        conversationId = session.ConversationId,
                        data = new
                        {
                            status = "skipped",
                            customerId,
                            reason = skipReason
                        },
                        timestamp = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()
                    },
                    cancellationToken);

                return;
            }

            var initialContextData = BuildInitialContextData(initialBankResponse, normalizedPresentation);

            await SendTrackedAsync(
                socket,
                session.SessionId,
                sequence => new
                {
                    type = "status",
                    action = "initial_context_load_audit",
                    sequence,
                    sessionId = session.SessionId,
                    conversationId = session.ConversationId,
                    data = new
                    {
                        status = "started",
                        customerId
                    },
                    timestamp = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()
                },
                cancellationToken);

            try
            {
                var contextLoadResponse = await _contextLoader.LoadInitialContextAsync(
                    customerId,
                    session.ConversationId,
                    initialContextData,
                    cancellationToken);

                await SendTrackedAsync(
                    socket,
                    session.SessionId,
                    sequence => new
                    {
                        type = "status",
                        action = "initial_context_load_audit",
                        sequence,
                        sessionId = session.SessionId,
                        conversationId = session.ConversationId,
                        data = new
                        {
                            status = "success",
                            customerId,
                            response = contextLoadResponse
                        },
                        timestamp = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()
                    },
                    cancellationToken);
            }
            catch (Exception contextEx)
            {
                _logger.LogError(contextEx, "Error cargando contexto inicial para conversationId={ConversationId}", session.ConversationId);

                await SendTrackedAsync(
                    socket,
                    session.SessionId,
                    sequence => new
                    {
                        type = "error",
                        action = "initial_context_load_error",
                        sequence,
                        sessionId = session.SessionId,
                        conversationId = session.ConversationId,
                        message = "No se pudo cargar el contexto inicial al endpoint /turn.",
                        data = new
                        {
                            customerId,
                            errorType = contextEx.GetType().Name,
                            errorMessage = contextEx.Message,
                            innerError = contextEx.InnerException?.Message
                        },
                        timestamp = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()
                    },
                    cancellationToken);

                await SendTrackedAsync(
                    socket,
                    session.SessionId,
                    sequence => new
                    {
                        type = "status",
                        action = "initial_context_load_audit",
                        sequence,
                        sessionId = session.SessionId,
                        conversationId = session.ConversationId,
                        data = new
                        {
                            status = "error",
                            customerId,
                            reason = contextEx.GetType().Name,
                            detail = contextEx.Message,
                            innerError = contextEx.InnerException?.Message
                        },
                        timestamp = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()
                    },
                    cancellationToken);
            }
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error consultando respuesta inicial del servicio interno para customerId={CustomerId}", customerId);
            await SendTrackedAsync(
                socket,
                session.SessionId,
                sequence => new
                {
                    type = "error",
                    action = "initial_bank_query_error",
                    sequence,
                    sessionId = session.SessionId,
                    conversationId = session.ConversationId,
                    message = "No se pudo obtener la respuesta inicial del servicio interno.",
                    data = new
                    {
                        customerId,
                        errorType = ex.GetType().Name,
                        errorMessage = ex.Message,
                        innerError = ex.InnerException?.Message
                    },
                    timestamp = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()
                },
                cancellationToken);

            await SendTrackedAsync(
                socket,
                session.SessionId,
                sequence => new
                {
                    type = "status",
                    action = "initial_bank_query_audit",
                    sequence,
                    sessionId = session.SessionId,
                    conversationId = session.ConversationId,
                    data = new
                    {
                        status = "error",
                        customerId,
                        reason = ex.GetType().Name,
                        detail = ex.Message,
                        innerError = ex.InnerException?.Message
                    },
                    timestamp = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()
                },
                cancellationToken);
        }
    }

    private static object BuildInitialContextData(object initialBankResponse, object normalizedPresentation)
    {
        var initialElement = JsonSerializer.SerializeToElement(initialBankResponse, JsonOptions);
        var contextElement = ResolveContextDataElement(initialElement);
        Dictionary<string, object?> data;

        if (contextElement.ValueKind == JsonValueKind.Object)
        {
            data = JsonSerializer.Deserialize<Dictionary<string, object?>>(contextElement.GetRawText(), JsonOptions)
                   ?? new Dictionary<string, object?>(StringComparer.OrdinalIgnoreCase);
        }
        else
        {
            data = new Dictionary<string, object?>(StringComparer.OrdinalIgnoreCase)
            {
                ["raw"] = contextElement
            };
        }

        RemoveKeyIgnoreCase(data, "isSucceded");
        RemoveKeyIgnoreCase(data, "code");
        RemoveKeyIgnoreCase(data, "message");

        if (TryGetValueIgnoreCase(data, "data", out var innerData) &&
            innerData is JsonElement innerDataElement &&
            innerDataElement.ValueKind == JsonValueKind.Array)
        {
            var hasProducts = TryGetValueIgnoreCase(data, "products", out var existingProducts) &&
                              !IsNullOrEmptyArray(existingProducts);

            if (!hasProducts)
            {
                data["products"] = JsonSerializer.Deserialize<object>(innerDataElement.GetRawText(), JsonOptions);
            }

            RemoveKeyIgnoreCase(data, "data");
        }

        if (!TryGetValueIgnoreCase(data, "primerNombre", out var firstName) ||
            string.IsNullOrWhiteSpace(firstName?.ToString()))
        {
            data["primerNombre"] = InitialContextFirstName;
        }

        if (!TryGetValueIgnoreCase(data, "resultCode", out _))
        {
            data["resultCode"] = 0;
        }

        if (!TryGetValueIgnoreCase(data, "resultMessage", out _))
        {
            data["resultMessage"] = "Consulta realizada exitosamente.";
        }

        if (!TryGetValueIgnoreCase(data, "products", out _))
        {
            var normalizedElement = JsonSerializer.SerializeToElement(normalizedPresentation, JsonOptions);
            if (normalizedElement.ValueKind == JsonValueKind.Object &&
                normalizedElement.TryGetProperty("products", out var productsElement))
            {
                data["products"] = JsonSerializer.Deserialize<object>(productsElement.GetRawText(), JsonOptions);
            }
            else
            {
                data["products"] = Array.Empty<object>();
            }
        }

        return data;
    }

    private static JsonElement ResolveContextDataElement(JsonElement initialElement)
    {
        if (initialElement.ValueKind != JsonValueKind.Object)
        {
            return initialElement;
        }

        if (!initialElement.TryGetProperty("data", out var dataElement) || dataElement.ValueKind != JsonValueKind.Object)
        {
            return initialElement;
        }

        var hasTransportWrapper = initialElement.TryGetProperty("isSucceded", out _) ||
                                  initialElement.TryGetProperty("code", out _) ||
                                  initialElement.TryGetProperty("message", out _);

        return hasTransportWrapper ? dataElement : initialElement;
    }

    private static bool TryGetValueIgnoreCase(Dictionary<string, object?> data, string key, out object? value)
    {
        foreach (var pair in data)
        {
            if (string.Equals(pair.Key, key, StringComparison.OrdinalIgnoreCase))
            {
                value = pair.Value;
                return true;
            }
        }

        value = null;
        return false;
    }

    private static void RemoveKeyIgnoreCase(Dictionary<string, object?> data, string key)
    {
        var keyToRemove = data.Keys.FirstOrDefault(existingKey =>
            string.Equals(existingKey, key, StringComparison.OrdinalIgnoreCase));

        if (keyToRemove is not null)
        {
            data.Remove(keyToRemove);
        }
    }

    private static bool IsNullOrEmptyArray(object? value)
    {
        if (value is null)
        {
            return true;
        }

        if (value is JsonElement element)
        {
            return element.ValueKind == JsonValueKind.Array && element.GetArrayLength() == 0;
        }

        if (value is Array array)
        {
            return array.Length == 0;
        }

        if (value is IEnumerable enumerable)
        {
            var enumerator = enumerable.GetEnumerator();
            using (enumerator as IDisposable)
            {
                return !enumerator.MoveNext();
            }
        }

        return false;
    }

    private static bool ShouldLoadInitialContext(object initialBankResponse, object normalizedPresentation, out string reason)
    {
        reason = "ok";

        if (TryGetObjectElement(initialBankResponse, out var initialRoot))
        {
            if (initialRoot.TryGetProperty("statusCode", out var statusCodeElement) &&
                statusCodeElement.ValueKind == JsonValueKind.Number &&
                statusCodeElement.TryGetInt32(out var statusCode) &&
                statusCode >= 400)
            {
                reason = $"bank_status_{statusCode}";
                return false;
            }

            if (initialRoot.TryGetProperty("error", out var errorElement) &&
                errorElement.ValueKind == JsonValueKind.String &&
                !string.IsNullOrWhiteSpace(errorElement.GetString()))
            {
                reason = "bank_response_error";
                return false;
            }
        }

        if (TryGetObjectElement(normalizedPresentation, out var normalizedRoot))
        {
            var isSucceded = normalizedRoot.TryGetProperty("isSucceded", out var succeededElement) &&
                             succeededElement.ValueKind == JsonValueKind.True;

            if (!isSucceded)
            {
                reason = "presentation_not_succeeded";
                return false;
            }
        }

        return true;
    }

    private static bool TryGetObjectElement(object payload, out JsonElement root)
    {
        root = default;

        try
        {
            var element = JsonSerializer.SerializeToElement(payload, JsonOptions);
            if (element.ValueKind != JsonValueKind.Object)
            {
                return false;
            }

            root = element;
            return true;
        }
        catch
        {
            return false;
        }
    }

    private async Task<bool> TryHandleControlEventAsync(
        WebSocket socket,
        SocketEnvelope? envelope,
        string sessionId,
        string? requestId,
        CancellationToken cancellationToken)
    {
        var action = ResolveAction(envelope);

        switch (action)
        {
            case "ack":
            {
                var sequence = envelope?.LastReceivedSequence ?? envelope?.Sequence ?? 0;
                var acknowledged = _sessionStore.Acknowledge(sessionId, sequence);
                await SendAsync(socket, new
                {
                    type = "ack",
                    action = "acknowledged",
                    sessionId,
                    requestId,
                    lastAcknowledgedSequence = acknowledged,
                    timestamp = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()
                }, cancellationToken);
                return true;
            }
            case "resume":
            {
                var fromSequence = envelope?.LastReceivedSequence ?? 0;
                await ReplayPendingAsync(socket, sessionId, fromSequence, cancellationToken);
                return true;
            }
            case "ping":
            {
                await SendAsync(socket, new
                {
                    type = "pong",
                    action = "heartbeat",
                    sessionId,
                    requestId,
                    timestamp = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()
                }, cancellationToken);
                return true;
            }
            case "typing":
            {
                await SendAsync(socket, new
                {
                    type = "status",
                    action = "typing_received",
                    sessionId,
                    requestId,
                    timestamp = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()
                }, cancellationToken);
                return true;
            }
            default:
                return false;
        }
    }

    private async Task ReplayPendingAsync(WebSocket socket, string sessionId, long lastReceivedSequence, CancellationToken cancellationToken)
    {
        var pending = _sessionStore.GetPending(sessionId, lastReceivedSequence);
        if (pending.Count == 0)
        {
            return;
        }

        var replayEvents = new List<JsonElement>(pending.Count);
        foreach (var pendingEvent in pending)
        {
            using var document = JsonDocument.Parse(pendingEvent.Payload);
            replayEvents.Add(document.RootElement.Clone());
        }

        await SendAsync(socket, new
        {
            type = "replay",
            action = "session_replay",
            sessionId,
            lastReceivedSequence,
            eventCount = replayEvents.Count,
            events = replayEvents,
            timestamp = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()
        }, cancellationToken);
    }

    private async Task SendTrackedAsync(
        WebSocket socket,
        string sessionId,
        Func<long, object> payloadFactory,
        CancellationToken cancellationToken)
    {
        var tracked = _sessionStore.AppendOutbound(sessionId, payloadFactory);
        await SendRawAsync(socket, tracked.Payload, cancellationToken);
    }

    private static async Task<string?> ReceiveFullMessage(WebSocket socket, byte[] buffer, CancellationToken cancellationToken)
    {
        var segment = new ArraySegment<byte>(buffer);
        using var ms = new MemoryStream();

        while (true)
        {
            var result = await socket.ReceiveAsync(segment, cancellationToken);
            if (result.MessageType == WebSocketMessageType.Close)
            {
                await socket.CloseAsync(WebSocketCloseStatus.NormalClosure, "Cierre normal", cancellationToken);
                return null;
            }

            ms.Write(buffer, 0, result.Count);
            if (result.EndOfMessage)
            {
                break;
            }
        }

        return Encoding.UTF8.GetString(ms.ToArray());
    }

    private static bool TryParseEnvelope(string payload, out SocketEnvelope? envelope, out string? error)
    {
        try
        {
            envelope = JsonSerializer.Deserialize<SocketEnvelope>(payload, JsonOptions);
            error = null;
            return envelope is not null;
        }
        catch
        {
            envelope = null;
            error = "El mensaje debe ser JSON valido.";
            return false;
        }
    }

    private static string ResolveAction(SocketEnvelope? envelope)
    {
        return (envelope?.Action ?? envelope?.Type ?? string.Empty).Trim().ToLowerInvariant();
    }

    private static bool TryParseSequence(StringValues values, out long sequence)
    {
        return long.TryParse(values.ToString(), out sequence);
    }

    private static string ResolveUserId(ClaimsPrincipal user)
    {
        return user.FindFirstValue(ClaimTypes.NameIdentifier)
            ?? user.FindFirstValue("sub")
            ?? user.Identity?.Name
            ?? "anonymous";
    }

    private static string ResolveConnectionCustomerId(HttpContext httpContext)
    {
        var fromQuery = httpContext.Request.Query["customerId"].ToString();
        if (!string.IsNullOrWhiteSpace(fromQuery))
        {
            return fromQuery.Trim();
        }

        fromQuery = httpContext.Request.Query["clientId"].ToString();
        if (!string.IsNullOrWhiteSpace(fromQuery))
        {
            return fromQuery.Trim();
        }

        var fromHeader = httpContext.Request.Headers["x-customer-id"].ToString();
        if (!string.IsNullOrWhiteSpace(fromHeader))
        {
            return fromHeader.Trim();
        }

        fromHeader = httpContext.Request.Headers["x-client-id"].ToString();
        return string.IsNullOrWhiteSpace(fromHeader) ? string.Empty : fromHeader.Trim();
    }

    private static string ResolveCustomerId(SocketEnvelope? envelope, string connectionCustomerId)
    {
        return envelope?.CustomerId
            ?? envelope?.Data?.CustomerId
            ?? envelope?.ClientId
            ?? envelope?.Data?.ClientId
            ?? connectionCustomerId;
    }

    private static List<ChatMessage> NormalizeMessages(SocketEnvelope? envelope)
    {
        var result = new List<ChatMessage>();

        if (envelope?.Messages is { Count: > 0 })
        {
            result.AddRange(envelope.Messages.Where(static m => !string.IsNullOrWhiteSpace(m.Content)));
            return result;
        }

        var content = envelope?.Data?.Message ?? envelope?.Data?.Content;
        if (!string.IsNullOrWhiteSpace(content))
        {
            result.Add(new ChatMessage("user", content));
        }

        return result;
    }

    private static object NormalizePresentationProductResponse(object response)
    {
        if (response is not JsonElement root || root.ValueKind != JsonValueKind.Object)
        {
            return new
            {
                isSucceded = false,
                code = "UNEXPECTED_PAYLOAD",
                message = "La respuesta del servicio de productos no tiene la estructura esperada.",
                productCount = 0,
                products = Array.Empty<object>()
            };
        }

        var data = root.TryGetProperty("data", out var dataEl) && dataEl.ValueKind == JsonValueKind.Object
            ? dataEl
            : default;

        var products = data.ValueKind == JsonValueKind.Object &&
                       data.TryGetProperty("products", out var productsEl) &&
                       productsEl.ValueKind == JsonValueKind.Array
            ? productsEl.EnumerateArray().Select(static p => p.Clone()).ToArray()
            : [];

        var resultCode = data.ValueKind == JsonValueKind.Object &&
                         data.TryGetProperty("resultCode", out var resultCodeEl) &&
                         resultCodeEl.ValueKind == JsonValueKind.Number &&
                         resultCodeEl.TryGetInt32(out var parsedResultCode)
            ? parsedResultCode
            : -1;

        return new
        {
            isSucceded = root.TryGetProperty("isSucceded", out var succeededEl) && succeededEl.ValueKind == JsonValueKind.True,
            code = root.TryGetProperty("code", out var codeEl) && codeEl.ValueKind == JsonValueKind.String ? codeEl.GetString() : null,
            message = root.TryGetProperty("message", out var messageEl) && messageEl.ValueKind == JsonValueKind.String ? messageEl.GetString() : null,
            resultCode,
            resultMessage = data.ValueKind == JsonValueKind.Object && data.TryGetProperty("resultMessage", out var resultMessageEl) && resultMessageEl.ValueKind == JsonValueKind.String
                ? resultMessageEl.GetString()
                : null,
            productCount = products.Length,
            products
        };
    }

    private static string BuildPresentationProductSummary(object normalizedPresentation)
    {
        if (normalizedPresentation is not { } payload)
        {
            return "No se pudo interpretar la respuesta de productos.";
        }

        var json = JsonSerializer.Serialize(payload, JsonOptions);
        using var doc = JsonDocument.Parse(json);
        var root = doc.RootElement;

        var resultMessage = root.TryGetProperty("resultMessage", out var resultMessageEl) && resultMessageEl.ValueKind == JsonValueKind.String
            ? resultMessageEl.GetString()
            : null;

        var productCount = root.TryGetProperty("productCount", out var productCountEl) && productCountEl.ValueKind == JsonValueKind.Number && productCountEl.TryGetInt32(out var parsedCount)
            ? parsedCount
            : 0;

        var baseMessage = string.IsNullOrWhiteSpace(resultMessage)
            ? "Productos consultados exitosamente."
            : resultMessage;

        return $"{baseMessage} Total productos: {productCount}.";
    }

    private static Task SendAsync(WebSocket socket, object payload, CancellationToken cancellationToken)
    {
        if (socket.State != WebSocketState.Open)
        {
            return Task.CompletedTask;
        }

        var bytes = Encoding.UTF8.GetBytes(JsonSerializer.Serialize(payload, JsonOptions));
        return socket.SendAsync(new ArraySegment<byte>(bytes), WebSocketMessageType.Text, true, cancellationToken);
    }

    private static Task SendRawAsync(WebSocket socket, string payload, CancellationToken cancellationToken)
    {
        if (socket.State != WebSocketState.Open)
        {
            return Task.CompletedTask;
        }

        var bytes = Encoding.UTF8.GetBytes(payload);
        return socket.SendAsync(new ArraySegment<byte>(bytes), WebSocketMessageType.Text, true, cancellationToken);
    }
}
