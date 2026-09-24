namespace BancaConversacional.Application.Models;

public sealed class MovementsFilter
{
    public string? Type { get; init; }
    public int? Limit { get; init; }
}
