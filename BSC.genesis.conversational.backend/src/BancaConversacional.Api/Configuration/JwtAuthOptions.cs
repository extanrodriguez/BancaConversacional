namespace BancaConversacional.Api.Configuration;

public sealed class JwtAuthOptions
{
    public const string SectionName = "JwtAuth";

    public string Issuer { get; init; } = string.Empty;
    public string Audience { get; init; } = string.Empty;
    public string SigningKey { get; init; } = string.Empty;
    public bool ValidateIssuer { get; init; } = true;
    public bool ValidateAudience { get; init; } = true;
    public bool ValidateLifetime { get; init; } = true;
    public int ClockSkewSeconds { get; init; } = 60;
    public bool DisableValidation { get; init; } = true;
}
