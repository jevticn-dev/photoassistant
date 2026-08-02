namespace PhotoAssistant.Application.Authentication;

/// <summary>
/// Account creation and token issuing.
///
/// Declared here and implemented in Infrastructure: this layer states what the
/// application needs, without knowing that ASP.NET Core Identity hashes the
/// passwords or that the token happens to be a JWT.
/// </summary>
public interface IAuthenticationService
{
    Task<AuthenticationResult> RegisterAsync(RegisterRequest request, CancellationToken cancellationToken);

    Task<AuthenticationResult> LoginAsync(LoginRequest request, CancellationToken cancellationToken);
}
