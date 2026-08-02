using System.Net;
using System.Net.Http.Json;
using PhotoAssistant.Api.Tests.Infrastructure;
using PhotoAssistant.Application.Authentication;

namespace PhotoAssistant.Api.Tests;

public sealed class AuthEndpointsTests(ApiFactory factory) : IClassFixture<ApiFactory>
{
    private const string ValidPassword = "Str0ng!Passphrase";

    [Fact]
    public async Task Register_creates_an_account_and_returns_a_token()
    {
        var client = factory.CreateClient();
        var email = ApiFactory.UniqueEmail();

        var response = await client.PostAsJsonAsync(
            "/api/auth/register",
            new { email, password = ValidPassword });

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);

        var body = await response.Content.ReadFromJsonAsync<AuthenticationResponse>();
        Assert.NotNull(body);
        Assert.False(string.IsNullOrWhiteSpace(body.AccessToken));
        Assert.Equal(email, body.Email);
        Assert.NotEqual(Guid.Empty, body.UserId);
        Assert.True(body.ExpiresAt > DateTimeOffset.UtcNow);
    }

    [Fact]
    public async Task Register_rejects_an_email_that_is_already_taken()
    {
        var client = factory.CreateClient();
        var email = ApiFactory.UniqueEmail();
        var payload = new { email, password = ValidPassword };

        await client.PostAsJsonAsync("/api/auth/register", payload);
        var second = await client.PostAsJsonAsync("/api/auth/register", payload);

        Assert.Equal(HttpStatusCode.BadRequest, second.StatusCode);
        Assert.Equal("application/problem+json", second.Content.Headers.ContentType?.MediaType);
    }

    [Fact]
    public async Task Register_rejects_a_password_below_the_minimum_length()
    {
        var client = factory.CreateClient();

        var response = await client.PostAsJsonAsync(
            "/api/auth/register",
            new { email = ApiFactory.UniqueEmail(), password = "short" });

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);

        var problem = await response.Content.ReadFromJsonAsync<ValidationProblem>();
        Assert.NotNull(problem);
        Assert.Contains("Password", problem.Errors.Keys);
    }

    [Fact]
    public async Task Login_returns_a_token_for_correct_credentials()
    {
        var client = factory.CreateClient();
        var email = ApiFactory.UniqueEmail();
        await client.PostAsJsonAsync("/api/auth/register", new { email, password = ValidPassword });

        var response = await client.PostAsJsonAsync(
            "/api/auth/login",
            new { email, password = ValidPassword });

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);

        var body = await response.Content.ReadFromJsonAsync<AuthenticationResponse>();
        Assert.NotNull(body);
        Assert.False(string.IsNullOrWhiteSpace(body.AccessToken));
    }

    [Fact]
    public async Task Login_rejects_a_wrong_password_with_problem_details()
    {
        var client = factory.CreateClient();
        var email = ApiFactory.UniqueEmail();
        await client.PostAsJsonAsync("/api/auth/register", new { email, password = ValidPassword });

        var response = await client.PostAsJsonAsync(
            "/api/auth/login",
            new { email, password = "Wr0ng!Passphrase" });

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        Assert.Equal("application/problem+json", response.Content.Headers.ContentType?.MediaType);
    }

    [Fact]
    public async Task Login_gives_the_same_answer_for_an_unknown_account()
    {
        var client = factory.CreateClient();

        var response = await client.PostAsJsonAsync(
            "/api/auth/login",
            new { email = ApiFactory.UniqueEmail(), password = ValidPassword });

        // Same status as a wrong password: the API must not reveal which
        // addresses have accounts.
        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    private sealed record ValidationProblem(Dictionary<string, string[]> Errors);
}
