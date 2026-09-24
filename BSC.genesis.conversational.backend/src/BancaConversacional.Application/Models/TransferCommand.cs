namespace BancaConversacional.Application.Models;

public sealed class TransferCommand
{
    public string? Type { get; init; }
    public decimal? Amount { get; init; }
    public string? Description { get; init; }
}
