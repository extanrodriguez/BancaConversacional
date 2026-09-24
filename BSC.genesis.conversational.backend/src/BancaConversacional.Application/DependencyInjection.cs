using BancaConversacional.Application.Abstractions;
using BancaConversacional.Application.Configuration;
using BancaConversacional.Application.Services;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;

namespace BancaConversacional.Application;

public static class DependencyInjection
{
    public static IServiceCollection AddApplication(this IServiceCollection services, IConfiguration configuration)
    {
        services.Configure<BankingOptions>(configuration.GetSection(BankingOptions.SectionName));
        services.AddScoped<IConversationOrchestrator, ConversationOrchestrator>();
        services.AddSingleton<IServiceCatalogProvider, ServiceCatalogProvider>();
        return services;
    }
}
