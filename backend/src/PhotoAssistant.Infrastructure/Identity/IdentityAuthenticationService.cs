using Microsoft.AspNetCore.Identity;
using Microsoft.Extensions.Logging;
using PhotoAssistant.Application.Authentication;

namespace PhotoAssistant.Infrastructure.Identity;

/// <summary>
/// Implements the authentication contract on top of ASP.NET Core Identity.
/// </summary>
internal sealed class IdentityAuthenticationService(
    UserManager<ApplicationUser> userManager,
    JwtTokenGenerator tokenGenerator,
    ILogger<IdentityAuthenticationService> logger) : IAuthenticationService
{
    public async Task<AuthenticationResult> RegisterAsync(
        RegisterRequest request,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();

        var user = new ApplicationUser
        {
            // Identity treats UserName as the login handle. We authenticate by
            // email, so the two are kept identical rather than asking for a
            // separate username the user would have to remember.
            UserName = request.Email,
            Email = request.Email,
        };

        var creation = await userManager.CreateAsync(user, request.Password);

        if (!creation.Succeeded)
        {
            return AuthenticationResult.Failure(GroupByField(creation.Errors));
        }

        return AuthenticationResult.Success(tokenGenerator.CreateToken(user));
    }

    public async Task<AuthenticationResult> LoginAsync(
        LoginRequest request,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();

        var user = await userManager.FindByEmailAsync(request.Email);

        // An unknown email and a wrong password produce the same response on
        // purpose. Distinguishing them would let anyone test which addresses
        // have accounts here.
        if (user is null || !await userManager.CheckPasswordAsync(user, request.Password))
        {
            // A single failed login is unremarkable; a burst of them is an
            // attack. The response deliberately says nothing about which of the
            // two cases occurred, so the log is the only place that can tell an
            // operator whether one address is being targeted. Recorded at
            // warning level so it surfaces without reading every line.
            logger.LogWarning(
                "Failed login attempt for {Email} (account exists: {AccountExists})",
                request.Email,
                user is not null);

            return AuthenticationResult.Failure(string.Empty, "Invalid email or password.");
        }

        if (await userManager.IsLockedOutAsync(user))
        {
            logger.LogWarning("Login attempt on locked-out account {Email}", request.Email);

            return AuthenticationResult.Failure(
                string.Empty,
                "The account is temporarily locked after too many failed attempts.");
        }

        return AuthenticationResult.Success(tokenGenerator.CreateToken(user));
    }

    /// <summary>
    /// Turns Identity's flat error list into per-field errors, so a weak
    /// password is reported against the password field instead of the form.
    /// </summary>
    private static Dictionary<string, string[]> GroupByField(IEnumerable<IdentityError> errors) =>
        errors
            .GroupBy(FieldFor)
            .ToDictionary(
                group => group.Key,
                group => group.Select(error => error.Description).ToArray());

    /// <summary>
    /// Maps an Identity error code onto the request field it belongs to.
    /// Codes are strings such as "PasswordTooShort" or "DuplicateUserName";
    /// anything unrecognised is reported against the request as a whole.
    /// </summary>
    private static string FieldFor(IdentityError error) => error.Code switch
    {
        var code when code.Contains("Password", StringComparison.Ordinal) =>
            nameof(RegisterRequest.Password),

        // We authenticate by email and keep UserName identical to it, so both
        // code families point at the same field.
        var code when code.Contains("Email", StringComparison.Ordinal) =>
            nameof(RegisterRequest.Email),
        var code when code.Contains("UserName", StringComparison.Ordinal) =>
            nameof(RegisterRequest.Email),

        _ => string.Empty,
    };
}
