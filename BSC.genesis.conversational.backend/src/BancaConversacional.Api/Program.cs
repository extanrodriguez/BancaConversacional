using System.Reflection;
using System.Threading.RateLimiting;
using System.Text;
using BancaConversacional.Api.Services;
using BancaConversacional.Api.Configuration;
using BancaConversacional.Application.Abstractions;
using BancaConversacional.Application;
using BancaConversacional.Infrastructure;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.AspNetCore.HttpOverrides;
using Microsoft.Extensions.Options;
using Microsoft.IdentityModel.Tokens;

LoadDotEnv();

var builder = WebApplication.CreateBuilder(args);
var jwtAuthOptions = builder.Configuration.GetSection(JwtAuthOptions.SectionName).Get<JwtAuthOptions>() ?? new JwtAuthOptions();
var disableJwtValidation = ResolveDisableJwtValidation(builder.Configuration, jwtAuthOptions);
var signingKeyValue = ResolveSigningKey(jwtAuthOptions.SigningKey, builder.Environment, disableJwtValidation);

builder.Services.AddApplication(builder.Configuration);
builder.Services.AddInfrastructure(builder.Configuration);
builder.Services.Configure<JwtAuthOptions>(builder.Configuration.GetSection(JwtAuthOptions.SectionName));

builder.Services.AddAuthentication(JwtBearerDefaults.AuthenticationScheme)
    .AddJwtBearer(options =>
    {
        var signingKey = Encoding.UTF8.GetBytes(signingKeyValue);

        options.RequireHttpsMetadata = false;
        options.SaveToken = true;
        options.TokenValidationParameters = new TokenValidationParameters
        {
            ValidateIssuerSigningKey = !disableJwtValidation,
            IssuerSigningKey = new SymmetricSecurityKey(signingKey),
            ValidateIssuer = !disableJwtValidation && jwtAuthOptions.ValidateIssuer && !string.IsNullOrWhiteSpace(jwtAuthOptions.Issuer),
            ValidIssuer = jwtAuthOptions.Issuer,
            ValidateAudience = !disableJwtValidation && jwtAuthOptions.ValidateAudience && !string.IsNullOrWhiteSpace(jwtAuthOptions.Audience),
            ValidAudience = jwtAuthOptions.Audience,
            ValidateLifetime = !disableJwtValidation && jwtAuthOptions.ValidateLifetime,
            ClockSkew = TimeSpan.FromSeconds(jwtAuthOptions.ClockSkewSeconds)
        };

        options.Events = new JwtBearerEvents
        {
            OnMessageReceived = context =>
            {
                var accessToken = context.Request.Query["access_token"].ToString();
                if (!string.IsNullOrWhiteSpace(accessToken) &&
                    (context.HttpContext.WebSockets.IsWebSocketRequest || context.Request.Path.StartsWithSegments("/ws")))
                {
                    context.Token = accessToken;
                }

                return Task.CompletedTask;
            }
        };
    });

builder.Services.AddAuthorization();
builder.Services.Configure<ForwardedHeadersOptions>(options =>
{
    options.ForwardedHeaders = ForwardedHeaders.XForwardedFor | ForwardedHeaders.XForwardedProto;
    options.KnownNetworks.Clear();
    options.KnownProxies.Clear();
});

builder.Services.AddRateLimiter(options =>
{
    options.RejectionStatusCode = StatusCodes.Status429TooManyRequests;
    options.GlobalLimiter = PartitionedRateLimiter.Create<HttpContext, string>(context =>
        RateLimitPartition.GetFixedWindowLimiter(
            partitionKey: context.Connection.RemoteIpAddress?.ToString() ?? "unknown",
            factory: _ => new FixedWindowRateLimiterOptions
            {
                PermitLimit = 60,
                Window = TimeSpan.FromMinutes(1),
                QueueLimit = 0,
                AutoReplenishment = true
            }));
});

builder.Services.AddScoped<ChatWebSocketHandler>();
builder.Services.AddSingleton<WebSocketSessionStore>();

var app = builder.Build();

app.UseForwardedHeaders();
app.UseAuthentication();
app.UseAuthorization();
app.UseRateLimiter();
app.UseWebSockets(new WebSocketOptions
{
    KeepAliveInterval = TimeSpan.FromSeconds(30),
    ReceiveBufferSize = 4 * 1024
});

app.MapGet("/health", () => Results.Ok(new { status = "ok", service = "BancaConversacional.Api" }));

app.MapGet("/api/version", () =>
{
    var assembly = Assembly.GetExecutingAssembly();
    var informationalVersion = assembly
        .GetCustomAttribute<AssemblyInformationalVersionAttribute>()?
        .InformationalVersion;

    return Results.Ok(new
    {
        application = "BancaConversacional.Api",
        version = informationalVersion ?? assembly.GetName().Version?.ToString() ?? "unknown",
        assemblyVersion = assembly.GetName().Version?.ToString() ?? "unknown"
    });
});

app.MapGet("/catalog/services", (IServiceCatalogProvider provider) =>
    Results.Ok(new
    {
        generatedAt = DateTimeOffset.UtcNow,
        categories = new[] { "1-CoreBanking", "3-Products", "5-Tracking" },
        services = provider.GetAll()
    }));

async Task HandleWebSocketEndpoint(HttpContext context)
{
    if (!IsSecureWebSocketRequest(context, app.Environment))
    {
        context.Response.StatusCode = StatusCodes.Status426UpgradeRequired;
        await context.Response.WriteAsync("WSS es obligatorio fuera de desarrollo.");
        return;
    }

    if (!context.WebSockets.IsWebSocketRequest)
    {
        context.Response.StatusCode = StatusCodes.Status400BadRequest;
        await context.Response.WriteAsync("WebSocket request expected.");
        return;
    }

    if (!app.Environment.IsDevelopment() && !disableJwtValidation && context.User?.Identity?.IsAuthenticated != true)
    {
        context.Response.StatusCode = StatusCodes.Status401Unauthorized;
        await context.Response.WriteAsync("JWT requerido para conectar al WebSocket.");
        return;
    }

    var customerId = ResolveConnectionCustomerId(context);

    if (string.IsNullOrWhiteSpace(customerId))
    {
        context.Response.StatusCode = StatusCodes.Status400BadRequest;
        await context.Response.WriteAsync("Debe enviar customerId o clientId para establecer la conexion WebSocket.");
        return;
    }

    using var scope = app.Services.CreateScope();
    var handler = scope.ServiceProvider.GetRequiredService<ChatWebSocketHandler>();

    using var socket = await context.WebSockets.AcceptWebSocketAsync();
    await handler.HandleAsync(socket, context, context.RequestAborted);
}

var wsEndpoint = app.Map("/ws", HandleWebSocketEndpoint);
var rootWsEndpoint = app.Map("/", HandleWebSocketEndpoint);

if (!app.Environment.IsDevelopment())
{
    if (disableJwtValidation)
    {
        app.Logger.LogWarning("[AUTH] JwtAuth:DisableValidation=true. La validacion JWT y el requerimiento de autorizacion WebSocket estan deshabilitados temporalmente.");
    }
    else
    {
        wsEndpoint.RequireAuthorization();
        rootWsEndpoint.RequireAuthorization();
    }
}

app.Run();

static string ResolveSigningKey(string configuredKey, IWebHostEnvironment environment, bool disableValidation)
{
    if (disableValidation)
    {
        // Placeholder key to avoid runtime failures when JWT validation is disabled intentionally.
        return "jwt-validation-disabled-placeholder-key-2026";
    }

    if (!string.IsNullOrWhiteSpace(configuredKey))
    {
        return configuredKey;
    }

    if (environment.IsDevelopment())
    {
        return "dev-local-signing-key-change-me-2026-please";
    }

    throw new InvalidOperationException(
        "JwtAuth:SigningKey es requerido fuera de Development. Define JwtAuth__SigningKey en variables de entorno o appsettings.");
}

static bool ResolveDisableJwtValidation(IConfiguration configuration, JwtAuthOptions options)
{
    if (options.DisableValidation)
    {
        return true;
    }

    var legacy = Environment.GetEnvironmentVariable("DisableValidation") ?? configuration["DisableValidation"];
    return bool.TryParse(legacy, out var parsed) && parsed;
}

static bool IsSecureWebSocketRequest(HttpContext context, IWebHostEnvironment environment)
{
    if (environment.IsDevelopment())
    {
        return true;
    }

    if (context.Request.IsHttps)
    {
        return true;
    }

    var forwardedProto = context.Request.Headers["X-Forwarded-Proto"].ToString();
    return string.Equals(forwardedProto, "https", StringComparison.OrdinalIgnoreCase);
}

static string ResolveConnectionCustomerId(HttpContext context)
{
    var fromQuery = context.Request.Query["customerId"].ToString();
    if (!string.IsNullOrWhiteSpace(fromQuery))
    {
        return fromQuery.Trim();
    }

    fromQuery = context.Request.Query["clientId"].ToString();
    if (!string.IsNullOrWhiteSpace(fromQuery))
    {
        return fromQuery.Trim();
    }

    var fromHeader = context.Request.Headers["x-customer-id"].ToString();
    if (!string.IsNullOrWhiteSpace(fromHeader))
    {
        return fromHeader.Trim();
    }

    fromHeader = context.Request.Headers["x-client-id"].ToString();
    return string.IsNullOrWhiteSpace(fromHeader) ? string.Empty : fromHeader.Trim();
}

static void LoadDotEnv()
{
    var envPath = ResolveDotEnvPath();
    if (envPath is null)
    {
        return;
    }

    foreach (var rawLine in File.ReadAllLines(envPath))
    {
        var line = rawLine.Trim();
        if (string.IsNullOrWhiteSpace(line) || line.StartsWith('#'))
        {
            continue;
        }

        var parts = line.Split('=', 2);
        if (parts.Length != 2)
        {
            continue;
        }

        var key = parts[0].Trim();
        var value = parts[1].Trim();
        if (string.IsNullOrWhiteSpace(key))
        {
            continue;
        }

        Environment.SetEnvironmentVariable(key, value);
    }
}

static string? ResolveDotEnvPath()
{
    var current = new DirectoryInfo(Directory.GetCurrentDirectory());
    while (current is not null)
    {
        var candidate = Path.Combine(current.FullName, ".env");
        if (File.Exists(candidate))
        {
            return candidate;
        }

        current = current.Parent;
    }

    return null;
}
