namespace BancaConversacional.Application.Models;

public sealed class ServiceCatalogItem
{
    public required string Code { get; init; }
    public required string Group { get; init; }
    public required string Description { get; init; }
    public required string BackendOperation { get; init; }
    public required string Intent { get; init; }
    public required string FrontRequiredData { get; init; }
}
