using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;
using PhotoAssistant.Api.Tests.Infrastructure;
using PhotoAssistant.Application.Authentication;
using PhotoAssistant.Application.Photos;

namespace PhotoAssistant.Api.Tests;

/// <summary>
/// <c>POST /api/photos/{id}/recommendations</c> — the bridge to the ML service.
///
/// <para>
/// Both halves of the ML service are substituted: it publishes no port, so
/// nothing on the host can reach it, and what needs proving here is the bridge
/// — who may ask, what is sent, and what each kind of failure becomes. Whether
/// the suggestions are any good was settled in phase 3 against 500 photographs.
/// </para>
/// </summary>
[Collection(ApiCollection.Name)]
public sealed class RecommendationEndpointTests(ApiFactory factory)
{
    private const string ValidPassword = "Str0ng!Passphrase";

    private sealed class FakeDerivatives : IDerivativeGenerator
    {
        public Task<DerivativeResult> DeriveAsync(
            ReadOnlyMemory<byte> image,
            string fileName,
            CancellationToken cancellationToken) =>
            Task.FromResult(DerivativeResult.Success(
                Image("image/png", 512, 341),
                Image("image/jpeg", 2048, 1365),
                sourceWidth: 3000,
                sourceHeight: 2000));

        private static DerivedImage Image(string contentType, int width, int height) => new()
        {
            // Distinguishable, so a test can tell which derivative was sent on.
            Content = contentType == "image/png" ? new byte[] { 1, 1, 1 } : new byte[] { 2, 2 },
            ContentType = contentType,
            Width = width,
            Height = height,
        };
    }

    private sealed class FakeRecommendations : IRecommendationService
    {
        public ReadOnlyMemory<byte> LastImage { get; private set; }

        public int Calls { get; private set; }

        public RecommendationResult Next { get; set; } = RecommendationResult.Success(
            [Suggestion("a0002-dgw_005", "b", 0.11), Suggestion("a0031-kme_101", "d", 0.14),
             Suggestion("a0440-kme_812", "a", 0.19)],
            poolSize: 250,
            neighbours: 50);

        public Task<RecommendationResult> SuggestAsync(
            ReadOnlyMemory<byte> image,
            CancellationToken cancellationToken)
        {
            Calls++;
            LastImage = image;

            return Task.FromResult(Next);
        }

        private static Suggestion Suggestion(string reference, string expert, double distance) =>
            new()
            {
                Recipe = new Dictionary<string, object?> { ["schema"] = 1 },
                SourceReference = reference,
                Expert = expert,
                SceneDistance = distance,
            };
    }

    private (HttpClient Client, FakeRecommendations Recommendations) Arrange()
    {
        var recommendations = new FakeRecommendations();

        var client = factory
            .WithWebHostBuilder(builder => builder.ConfigureServices(services =>
            {
                services.RemoveAll<IDerivativeGenerator>();
                services.AddSingleton<IDerivativeGenerator>(new FakeDerivatives());
                services.RemoveAll<IRecommendationService>();
                services.AddSingleton<IRecommendationService>(recommendations);
            }))
            .CreateClient();

        return (client, recommendations);
    }

    private static async Task<string> SignInAsync(HttpClient client)
    {
        var response = await client.PostAsJsonAsync(
            "/api/auth/register",
            new { email = ApiFactory.UniqueEmail(), password = ValidPassword });

        return (await response.Content.ReadFromJsonAsync<AuthenticationResponse>())!.AccessToken;
    }

    private static async Task<Guid> UploadAsync(HttpClient client)
    {
        var file = new ByteArrayContent([9, 9, 9]);
        file.Headers.ContentType = new MediaTypeHeaderValue("image/jpeg");

        var response = await client.PostAsync(
            "/api/photos", new MultipartFormDataContent { { file, "file", "alpine.jpg" } });

        return (await response.Content.ReadFromJsonAsync<UploadPhotoResponse>())!.PhotoId;
    }

    private static void Authorise(HttpClient client, string token) =>
        client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", token);

    [Fact]
    public async Task An_anonymous_request_is_refused()
    {
        var (client, _) = Arrange();

        var response = await client.PostAsync($"/api/photos/{Guid.NewGuid()}/recommendations", null);

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task Three_suggestions_come_back_for_a_photograph_the_user_owns()
    {
        var (client, _) = Arrange();
        Authorise(client, await SignInAsync(client));
        var photoId = await UploadAsync(client);

        var response = await client.PostAsync($"/api/photos/{photoId}/recommendations", null);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);

        var body = await response.Content.ReadFromJsonAsync<SuggestEditsResponse>();
        Assert.Equal(3, body!.Suggestions.Count);
        Assert.Equal(250, body.PoolSize);
        Assert.Equal("a0002-dgw_005", body.Suggestions[0].SourceReference);
    }

    [Fact]
    public async Task The_response_carries_recipes_and_no_rendered_image()
    {
        // Phase 4, decision C. The browser draws the previews from the proxy it
        // loads anyway, so an image here would be 141 KB of duplication — and at
        // a smaller size than the one being edited.
        var (client, _) = Arrange();
        Authorise(client, await SignInAsync(client));
        var photoId = await UploadAsync(client);

        var response = await client.PostAsync($"/api/photos/{photoId}/recommendations", null);
        var json = await response.Content.ReadAsStringAsync();

        Assert.DoesNotContain("preview", json, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("recipe", json, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task The_512px_derivative_is_what_gets_sent_to_the_service()
    {
        // Not the original: it is the size the corpus vectors were computed at,
        // by the same code, so the comparison is like for like — and it is
        // kilobytes rather than megabytes over a hop taken on every upload.
        var (client, recommendations) = Arrange();
        Authorise(client, await SignInAsync(client));
        var photoId = await UploadAsync(client);

        await client.PostAsync($"/api/photos/{photoId}/recommendations", null);

        Assert.Equal(1, recommendations.Calls);
        // The fake derivative generator marks the 512 with 1s and the proxy
        // with 2s; the original was three 9s.
        Assert.Equal(new byte[] { 1, 1, 1 }, recommendations.LastImage.ToArray());
    }

    [Fact]
    public async Task Someone_elses_photograph_is_not_found_rather_than_forbidden()
    {
        // 403 would confirm the identifier names a real photograph.
        var (client, recommendations) = Arrange();
        Authorise(client, await SignInAsync(client));
        var photoId = await UploadAsync(client);

        var intruder = factory.CreateClient();
        Authorise(intruder, await SignInAsync(intruder));

        var response = await intruder.PostAsync($"/api/photos/{photoId}/recommendations", null);

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
        Assert.Equal(0, recommendations.Calls);
    }

    [Fact]
    public async Task An_unknown_photograph_is_not_found()
    {
        var (client, _) = Arrange();
        Authorise(client, await SignInAsync(client));

        var response = await client.PostAsync($"/api/photos/{Guid.NewGuid()}/recommendations", null);

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
    }

    [Fact]
    public async Task A_service_that_is_down_becomes_503_and_not_500()
    {
        // 503 tells a client that retrying is the sensible response. A 500 says
        // the request itself was the problem, which it was not.
        var (client, recommendations) = Arrange();
        recommendations.Next = RecommendationResult.Failure("Suggestions are unavailable.");
        Authorise(client, await SignInAsync(client));
        var photoId = await UploadAsync(client);

        var response = await client.PostAsync($"/api/photos/{photoId}/recommendations", null);

        Assert.Equal(HttpStatusCode.ServiceUnavailable, response.StatusCode);

        var problem = await response.Content.ReadFromJsonAsync<ProblemDetails>();
        Assert.Equal("Suggestions unavailable", problem!.Title);
    }
}
