using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;
using PhotoAssistant.Api.Tests.Infrastructure;
using PhotoAssistant.Application.Authentication;
using PhotoAssistant.Application.Photos;
using PhotoAssistant.Application.Projects;
using PhotoAssistant.Domain.Enums;
using PhotoAssistant.Infrastructure.Persistence;

namespace PhotoAssistant.Api.Tests;

/// <summary>
/// Serving the working copy, and logging what was chosen.
///
/// <para>
/// The two halves of the suggestion screen that live on the server: the image
/// the browser renders previews from, and the record of what it did with them.
/// </para>
/// </summary>
[Collection(ApiCollection.Name)]
public sealed class ChoiceAndProxyEndpointTests(ApiFactory factory)
{
    private const string ValidPassword = "Str0ng!Passphrase";

    private sealed class FakeDerivatives : IDerivativeGenerator
    {
        /// <summary>Recognisable bytes, so a test can tell which one was served.</summary>
        public static readonly byte[] Proxy = [0xAA, 0xBB, 0xCC, 0xDD];

        public Task<DerivativeResult> DeriveAsync(
            ReadOnlyMemory<byte> image,
            string fileName,
            CancellationToken cancellationToken) =>
            Task.FromResult(DerivativeResult.Success(
                new DerivedImage
                {
                    Content = new byte[] { 1, 1, 1 },
                    ContentType = "image/png",
                    Width = 512,
                    Height = 341,
                },
                new DerivedImage
                {
                    Content = Proxy,
                    ContentType = "image/jpeg",
                    Width = 2048,
                    Height = 1365,
                },
                sourceWidth: 3000,
                sourceHeight: 2000));
    }

    private HttpClient Arrange() => factory
        .WithWebHostBuilder(builder => builder.ConfigureServices(services =>
        {
            services.RemoveAll<IDerivativeGenerator>();
            services.AddSingleton<IDerivativeGenerator>(new FakeDerivatives());
        }))
        .CreateClient();

    private static async Task<HttpClient> SignedInAsync(HttpClient client)
    {
        var response = await client.PostAsJsonAsync(
            "/api/auth/register",
            new { email = ApiFactory.UniqueEmail(), password = ValidPassword });
        var body = await response.Content.ReadFromJsonAsync<AuthenticationResponse>();

        client.DefaultRequestHeaders.Authorization =
            new AuthenticationHeaderValue("Bearer", body!.AccessToken);

        return client;
    }

    private static async Task<Guid> UploadAsync(HttpClient client)
    {
        var file = new ByteArrayContent([9, 9, 9]);
        file.Headers.ContentType = new MediaTypeHeaderValue("image/jpeg");

        var response = await client.PostAsync(
            "/api/photos", new MultipartFormDataContent { { file, "file", "alpine.jpg" } });

        return (await response.Content.ReadFromJsonAsync<UploadPhotoResponse>())!.PhotoId;
    }

    /// <summary>The project the upload opened, found by the photograph it holds.</summary>
    private async Task<Guid> ProjectOfAsync(Guid photoId)
    {
        using var scope = factory.Services.CreateScope();
        var context = scope.ServiceProvider.GetRequiredService<PhotoAssistantDbContext>();

        return await context.Projects
            .Where(project => project.PhotoId == photoId)
            .Select(project => project.Id)
            .SingleAsync();
    }

    private static object[] ThreeSuggestions() =>
    [
        Offered("a0002-dgw_005", "b", 0.11),
        Offered("a0031-kme_101", "d", 0.14),
        Offered("a0440-kme_812", "a", 0.19),
    ];

    private static object Offered(string reference, string expert, double distance) => new
    {
        recipe = new Dictionary<string, object> { ["schema"] = 1 },
        sourceReference = reference,
        expert,
        sceneDistance = distance,
    };

    // -- the working copy -----------------------------------------------------

    [Fact]
    public async Task The_proxy_comes_back_as_the_jpeg_that_was_stored()
    {
        var client = await SignedInAsync(Arrange());
        var photoId = await UploadAsync(client);

        var response = await client.GetAsync($"/api/photos/{photoId}/proxy");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal("image/jpeg", response.Content.Headers.ContentType?.MediaType);
        Assert.Equal(FakeDerivatives.Proxy, await response.Content.ReadAsByteArrayAsync());
    }

    [Fact]
    public async Task The_proxy_is_cacheable_but_never_in_a_shared_cache()
    {
        // It never changes, so the editor should not refetch it on every visit;
        // it belongs to one person, so no proxy in between may keep a copy.
        var client = await SignedInAsync(Arrange());
        var photoId = await UploadAsync(client);

        var response = await client.GetAsync($"/api/photos/{photoId}/proxy");
        var cache = response.Headers.CacheControl;

        Assert.True(cache?.Private);
        Assert.False(cache?.Public);
        Assert.True(cache?.MaxAge > TimeSpan.FromDays(1));
    }

    [Fact]
    public async Task The_proxy_of_someone_elses_photograph_is_not_found()
    {
        var owner = await SignedInAsync(Arrange());
        var photoId = await UploadAsync(owner);
        var intruder = await SignedInAsync(Arrange());

        var response = await intruder.GetAsync($"/api/photos/{photoId}/proxy");

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
    }

    [Fact]
    public async Task An_anonymous_request_for_the_proxy_is_refused()
    {
        var response = await Arrange().GetAsync($"/api/photos/{Guid.NewGuid()}/proxy");

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    // -- the choice log -------------------------------------------------------

    [Fact]
    public async Task Taking_a_suggestion_writes_all_three_and_which_one()
    {
        // Logging only the accepted edit would say nothing about whether the
        // other two were worse or simply unseen — which is the question this
        // log exists to answer (plan §1.1).
        var client = await SignedInAsync(Arrange());
        var photoId = await UploadAsync(client);

        var response = await client.PostAsJsonAsync(
            $"/api/photos/{photoId}/choices",
            new { shown = ThreeSuggestions(), chosenIndex = 1 });

        Assert.Equal(HttpStatusCode.Created, response.StatusCode);

        using var scope = factory.Services.CreateScope();
        var context = scope.ServiceProvider.GetRequiredService<PhotoAssistantDbContext>();
        var choice = await context.Choices.SingleAsync(row => row.PhotoId == photoId);

        Assert.Equal(ChoiceOutcome.Accepted, choice.Outcome);

        using var document = JsonDocument.Parse(choice.ShownSuggestions);
        Assert.Equal(3, document.RootElement.GetProperty("suggestions").GetArrayLength());
        Assert.Equal(1, document.RootElement.GetProperty("chosen_index").GetInt32());
        Assert.Equal(
            "a0031-kme_101",
            document.RootElement.GetProperty("suggestions")[1]
                .GetProperty("source_reference").GetString());
    }

    [Fact]
    public async Task Taking_none_of_them_is_recorded_as_rejected()
    {
        var client = await SignedInAsync(Arrange());
        var photoId = await UploadAsync(client);

        await client.PostAsJsonAsync(
            $"/api/photos/{photoId}/choices",
            new { shown = ThreeSuggestions(), chosenIndex = (int?)null });

        using var scope = factory.Services.CreateScope();
        var context = scope.ServiceProvider.GetRequiredService<PhotoAssistantDbContext>();
        var choice = await context.Choices.SingleAsync(row => row.PhotoId == photoId);

        Assert.Equal(ChoiceOutcome.Rejected, choice.Outcome);
    }

    [Fact]
    public async Task An_index_outside_what_was_shown_is_refused()
    {
        var client = await SignedInAsync(Arrange());
        var photoId = await UploadAsync(client);

        var response = await client.PostAsJsonAsync(
            $"/api/photos/{photoId}/choices",
            new { shown = ThreeSuggestions(), chosenIndex = 7 });

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Fact]
    public async Task The_project_reports_whether_a_choice_has_been_made()
    {
        // The suggestion screen is one way, and the client cannot remember
        // that across a Back button — so the server has to say it. A saved
        // version would be the wrong signal: it misses someone who chose and
        // then left the editor without saving.
        var client = await SignedInAsync(Arrange());
        var photoId = await UploadAsync(client);
        var projectId = await ProjectOfAsync(photoId);

        var before = await client.GetFromJsonAsync<ProjectSummary>($"/api/projects/{projectId}");
        Assert.False(before!.HasChoice);

        await client.PostAsJsonAsync(
            $"/api/photos/{photoId}/choices",
            new { shown = ThreeSuggestions(), chosenIndex = 0 });

        var after = await client.GetFromJsonAsync<ProjectSummary>($"/api/projects/{projectId}");
        Assert.True(after!.HasChoice);
    }

    [Fact]
    public async Task Skipping_also_counts_as_having_been_past_the_screen()
    {
        // Rejected is still a decision. Offering the three again to someone who
        // deliberately passed on them would be the same nuisance as offering
        // them to someone who took one.
        var client = await SignedInAsync(Arrange());
        var photoId = await UploadAsync(client);
        var projectId = await ProjectOfAsync(photoId);

        await client.PostAsJsonAsync(
            $"/api/photos/{photoId}/choices",
            new { shown = ThreeSuggestions(), chosenIndex = (int?)null });

        var project = await client.GetFromJsonAsync<ProjectSummary>($"/api/projects/{projectId}");

        Assert.True(project!.HasChoice);
    }

    [Fact]
    public async Task A_choice_on_someone_elses_photograph_is_not_found()
    {
        var owner = await SignedInAsync(Arrange());
        var photoId = await UploadAsync(owner);
        var intruder = await SignedInAsync(Arrange());

        var response = await intruder.PostAsJsonAsync(
            $"/api/photos/{photoId}/choices",
            new { shown = ThreeSuggestions(), chosenIndex = 0 });

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
    }
}
