using System.IdentityModel.Tokens.Jwt;
using System.Security.Claims;
using System.Text;
using Microsoft.IdentityModel.Tokens;
using PhotoAssistant.Application.Authentication;

namespace PhotoAssistant.Infrastructure.Identity;

/// <summary>
/// Builds the signed access token returned after a successful login.
/// </summary>
internal sealed class JwtTokenGenerator(JwtOptions options, TimeProvider timeProvider)
{
    public AuthenticationResponse CreateToken(ApplicationUser user)
    {
        var issuedAt = timeProvider.GetUtcNow();
        var expiresAt = issuedAt.AddMinutes(options.ExpiryMinutes);

        var claims = new List<Claim>
        {
            // "sub" identifies the account; everything downstream reads the user
            // id from here rather than trusting anything the client sends.
            new(JwtRegisteredClaimNames.Sub, user.Id.ToString()),
            new(JwtRegisteredClaimNames.Email, user.Email ?? string.Empty),

            // "jti" gives each token a unique id, which is what a revocation
            // list would key on if one is ever added.
            new(JwtRegisteredClaimNames.Jti, Guid.NewGuid().ToString()),
        };

        var credentials = new SigningCredentials(
            new SymmetricSecurityKey(Encoding.UTF8.GetBytes(options.Key)),
            SecurityAlgorithms.HmacSha256);

        var token = new JwtSecurityToken(
            issuer: options.Issuer,
            audience: options.Audience,
            claims: claims,
            notBefore: issuedAt.UtcDateTime,
            expires: expiresAt.UtcDateTime,
            signingCredentials: credentials);

        return new AuthenticationResponse
        {
            AccessToken = new JwtSecurityTokenHandler().WriteToken(token),
            ExpiresAt = expiresAt,
            UserId = user.Id,
            Email = user.Email ?? string.Empty,
        };
    }
}
