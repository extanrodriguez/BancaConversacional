namespace BancaConversacional.Infrastructure.Configuration;

public sealed class ExternalServicesOptions
{
    public const string SectionName = "ExternalServices";

    public string AzureApiKey { get; init; } = string.Empty;
    public string AzureEndpoint { get; init; } = "https://bancaconversacionalbsc-resource.services.ai.azure.com/api/projects/bancaconversacionalbsc";
    public string DeploymentName { get; init; } = "o4-mini";

    public string NvidiaApiKey { get; init; } = string.Empty;
    public string NvidiaBaseUrl { get; init; } = "https://integrate.api.nvidia.com/v1";
    public string Model { get; init; } = "meta/llama-3.2-3b-instruct";

    public string PrivateRagEndpoint { get; init; } = string.Empty;
    public string PrivateRagApiKey { get; init; } = string.Empty;
    public bool SendPrivateRagApiKey { get; init; } = false;
    public string PrivateRagApiKeyHeaderName { get; init; } = "x-api-key";
    public int PrivateRagTopK { get; init; } = 3;

    // Temporal: permitir certificados no confiables en integraciones internas.
    public bool AllowInsecureBankingTls { get; init; } = false;

    // URL base por entorno para los servicios de la coleccion.
    public string BankingApiBaseDev { get; init; } = string.Empty;
    public string BankingApiBaseQa { get; init; } = string.Empty;
    public string BankingApiBaseProduction { get; init; } = string.Empty;

    // URL base por entorno para servicios de dashboard.
    public string DashboardApiBaseDev { get; init; } = string.Empty;
    public string DashboardApiBaseQa { get; init; } = string.Empty;
    public string DashboardApiBaseProduction { get; init; } = string.Empty;

    // Fallback opcional si no se define una URL especifica del entorno.
    public string BankingApiBase { get; init; } = string.Empty;
    public string DashboardApiBase { get; init; } = string.Empty;

    public string AccountsPathTemplate { get; init; } = "accountmanagent/v1/accounts/{clientIdentifier}";
    public string AccountsIncludeJointAccount { get; init; } = "S";
    public string ProductCatalogPath { get; init; } = "productsManagement/types";
    public string RatesCatalogPath { get; init; } = "certificateManagement/rates";
    public string NotificationsCatalogPath { get; init; } = "notificationManagement";
    public string DashboardSummaryPath { get; init; } = "dashBoard/summary";

    public string PresentationProductUrlTemplate { get; init; } = "https://apigateway-gen.dev.bsc.com.do/api/presentation/product/{customerId}";
}
