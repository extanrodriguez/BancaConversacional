using BancaConversacional.Application.Abstractions;
using BancaConversacional.Infrastructure.Clients;
using BancaConversacional.Infrastructure.Configuration;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;

namespace BancaConversacional.Infrastructure;

public static class DependencyInjection
{
    public static IServiceCollection AddInfrastructure(this IServiceCollection services, IConfiguration configuration)
    {
        services.Configure<ExternalServicesOptions>(configuration.GetSection(ExternalServicesOptions.SectionName));

        services.AddHttpClient<NvidiaChatClient>(client =>
        {
            client.Timeout = TimeSpan.FromSeconds(40);
        });

        services.AddHttpClient<IBankingClient, BankingApiClient>(client =>
        {
            client.Timeout = TimeSpan.FromSeconds(20);
        })
        .ConfigurePrimaryHttpMessageHandler(sp =>
        {
            _ = sp.GetRequiredService<IOptions<ExternalServicesOptions>>().Value;
            sp.GetRequiredService<ILoggerFactory>()
                .CreateLogger("BankingTls")
                .LogWarning("Bypass TLS de BankingApiClient habilitado de forma fija para entorno interno/dev.");

            return new HttpClientHandler
            {
                ServerCertificateCustomValidationCallback = (_, _, _, _) => true
            };
        });

        services.AddScoped<IIntentClassifier>(sp => sp.GetRequiredService<NvidiaChatClient>());
        services.AddScoped<IChatResponder>(sp => sp.GetRequiredService<NvidiaChatClient>());
        services.AddScoped<IConversationContextLoader>(sp => sp.GetRequiredService<NvidiaChatClient>());

        return services;
    }
}
