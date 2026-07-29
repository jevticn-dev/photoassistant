using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.ModelBinding;
using PhotoAssistant.Application.Authentication;

namespace PhotoAssistant.Api.Controllers;

[ApiController]
[Route("api/auth")]
public sealed class AuthController(IAuthenticationService authentication) : ControllerBase
{
    /// <summary>Creates an account and returns an access token for it.</summary>
    [HttpPost("register")]
    [ProducesResponseType<AuthenticationResponse>(StatusCodes.Status200OK)]
    [ProducesResponseType<ValidationProblemDetails>(StatusCodes.Status400BadRequest)]
    public async Task<IActionResult> Register(
        RegisterRequest request,
        CancellationToken cancellationToken)
    {
        var result = await authentication.RegisterAsync(request, cancellationToken);

        return result.Succeeded
            ? Ok(result.Response)
            : ValidationProblem(ToModelState(result));
    }

    /// <summary>Exchanges credentials for an access token.</summary>
    [HttpPost("login")]
    [ProducesResponseType<AuthenticationResponse>(StatusCodes.Status200OK)]
    [ProducesResponseType<ProblemDetails>(StatusCodes.Status401Unauthorized)]
    public async Task<IActionResult> Login(
        LoginRequest request,
        CancellationToken cancellationToken)
    {
        var result = await authentication.LoginAsync(request, cancellationToken);

        if (result.Succeeded)
        {
            return Ok(result.Response);
        }

        // Rejected credentials are 401, not 400: the request was well formed,
        // it just did not identify anyone.
        return Problem(
            title: "Authentication failed",
            detail: result.Errors.SelectMany(entry => entry.Value).FirstOrDefault(),
            statusCode: StatusCodes.Status401Unauthorized);
    }

    private ModelStateDictionary ToModelState(AuthenticationResult result)
    {
        var modelState = new ModelStateDictionary();

        foreach (var (field, messages) in result.Errors)
        {
            foreach (var message in messages)
            {
                modelState.AddModelError(field, message);
            }
        }

        return modelState;
    }
}
