namespace PhotoAssistant.Application.Authentication;

/// <summary>
/// Outcome of an authentication attempt.
///
/// A rejected password is an expected outcome, not an exceptional one, so it is
/// returned rather than thrown. Exceptions stay reserved for genuine faults,
/// which keeps the global handler meaningful.
/// </summary>
public sealed record AuthenticationResult
{
    private AuthenticationResult()
    {
    }

    public bool Succeeded { get; private init; }

    public AuthenticationResponse? Response { get; private init; }

    /// <summary>
    /// Failure reasons, keyed by field name so the API can return them as
    /// per-field validation errors. The empty key carries errors that belong to
    /// the request as a whole.
    /// </summary>
    public IReadOnlyDictionary<string, string[]> Errors { get; private init; } =
        new Dictionary<string, string[]>();

    public static AuthenticationResult Success(AuthenticationResponse response) =>
        new() { Succeeded = true, Response = response };

    public static AuthenticationResult Failure(string key, params string[] messages) =>
        new()
        {
            Succeeded = false,
            Errors = new Dictionary<string, string[]> { [key] = messages },
        };

    public static AuthenticationResult Failure(IReadOnlyDictionary<string, string[]> errors) =>
        new() { Succeeded = false, Errors = errors };
}
