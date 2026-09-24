namespace GenesisBackend.Modules.Users.Domain;

public sealed class User
{
    public Guid Id { get; init; } = Guid.NewGuid();
    public string Username { get; init; } = string.Empty;
    public string Email { get; init; } = string.Empty;
    public DateTime JoinedAt { get; init; } = DateTime.UtcNow;
}
