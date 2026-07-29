using System.ComponentModel.DataAnnotations;

namespace PhotoAssistant.Application.Authentication;

/// <summary>Credentials for creating an account.</summary>
public sealed record RegisterRequest
{
    [Required]
    [EmailAddress]
    [MaxLength(256)]
    public required string Email { get; init; }

    /// <summary>
    /// Length is checked here so the caller gets a field-level validation error
    /// rather than a generic failure. The remaining rules (digit, upper case,
    /// and so on) are enforced by Identity itself.
    /// </summary>
    [Required]
    [MinLength(8)]
    [MaxLength(128)]
    public required string Password { get; init; }
}

/// <summary>Credentials for obtaining an access token.</summary>
public sealed record LoginRequest
{
    [Required]
    [EmailAddress]
    [MaxLength(256)]
    public required string Email { get; init; }

    [Required]
    [MaxLength(128)]
    public required string Password { get; init; }
}

/// <summary>A successfully issued access token.</summary>
public sealed record AuthenticationResponse
{
    public required string AccessToken { get; init; }

    public required DateTimeOffset ExpiresAt { get; init; }

    public required Guid UserId { get; init; }

    public required string Email { get; init; }
}
