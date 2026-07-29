namespace PhotoAssistant.Infrastructure.Identity;

/// <summary>
/// Token settings, read from configuration. No value has a default: a missing
/// signing key must stop the application at start-up rather than quietly fall
/// back to something guessable.
/// </summary>
public sealed class JwtOptions
{
    public required string Key { get; init; }

    public required string Issuer { get; init; }

    public required string Audience { get; init; }

    public required int ExpiryMinutes { get; init; }
}
