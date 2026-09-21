using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;
using PhotoAssistant.Api.Tests.Infrastructure;
using PhotoAssistant.Application.Authentication;
using PhotoAssistant.Application.Photos;
using PhotoAssistant.Application.Storage;
using PhotoAssistant.Domain.Enums;
using PhotoAssistant.Infrastructure.Persistence;

namespace PhotoAssistant.Api.Tests;

/// <summary>
/// <c>POST /api/photos</c> against the real database and the real object store.
///
/// <para>
/// Only the ML service is substituted, and not to save time: it deliberately
/// publishes no port (`.claude/rules/ml_service.md`), so nothing on the host can
/// reach it. What needs proving here is the API's behaviour — that it refuses
/// what it should, stores all three objects, and writes both rows — and whether
/// the derivatives are correct is proven where that code lives.
/// </para>
/// </summary>
[Collection(ApiCollection.Name)]
public sealed class PhotoUploadEndpointTests(ApiFactory factory)
{
    private const string ValidPassword = "Str0ng!Passphrase";

    /// <summary>Stands in for the ML service, and records what it was asked.</summary>
    private sealed class FakeDerivatives : IDerivativeGenerator
    {
        public string? LastFileName { get; private set; }

        public int Calls { get; private set; }

        public DerivativeResult Next { get; set; } = DerivativeResult.Success(
            Image("image/png", 512, 341),
            Image("image/jpeg", 2048, 1365),
            sourceWidth: 3000,
            sourceHeight: 2000);

        public Task<DerivativeResult> DeriveAsync(
            ReadOnlyMemory<byte> image,
            string fileName,
            CancellationToken cancellationToken)
        {
            Calls++;
            LastFileName = fileName;

            return Task.FromResult(Next);
        }

        private static DerivedImage Image(string contentType, int width, int height) => new()
        {
            Content = new byte[] { 1, 2, 3, 4 },
            ContentType = contentType,
            Width = width,
            Height = height,
        };
    }

    private (HttpClient Client, FakeDerivatives Derivatives) Arrange()
    {
        var derivatives = new FakeDerivatives();

        var client = factory
            .WithWebHostBuilder(builder => builder.ConfigureServices(services =>
            {
                services.RemoveAll<IDerivativeGenerator>();
                services.AddSingleton<IDerivativeGenerator>(derivatives);
            }))
            .CreateClient();

        return (client, derivatives);
    }

    private static async Task<string> SignInAsync(HttpClient client)
    {
        var response = await client.PostAsJsonAsync(
            "/api/auth/register",
            new { email = ApiFactory.UniqueEmail(), password = ValidPassword });

        var body = await response.Content.ReadFromJsonAsync<AuthenticationResponse>();

        return body!.AccessToken;
    }

    private static MultipartFormDataContent File(
        byte[] bytes,
        string fileName = "sunset.jpg",
        string contentType = "image/jpeg")
    {
        var content = new ByteArrayContent(bytes);
        content.Headers.ContentType = new MediaTypeHeaderValue(contentType);

        return new MultipartFormDataContent { { content, "file", fileName } };
    }

    [Fact]
    public async Task An_anonymous_upload_is_refused()
    {
        var (client, _) = Arrange();

        var response = await client.PostAsync("/api/photos", File([1, 2, 3]));

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task An_upload_creates_a_photograph_and_a_project_on_it()
    {
        var (client, derivatives) = Arrange();
        client.DefaultRequestHeaders.Authorization =
            new AuthenticationHeaderValue("Bearer", await SignInAsync(client));

        var response = await client.PostAsync("/api/photos", File([1, 2, 3, 4, 5]));

        Assert.Equal(HttpStatusCode.Created, response.StatusCode);

        var body = await response.Content.ReadFromJsonAsync<UploadPhotoResponse>();
        Assert.NotNull(body);
        Assert.Equal(1, derivatives.Calls);

        using var scope = factory.Services.CreateScope();
        var context = scope.ServiceProvider.GetRequiredService<PhotoAssistantDbContext>();

        var photo = await context.Photos.SingleAsync(entity => entity.Id == body.PhotoId);
        var project = await context.Projects.SingleAsync(entity => entity.Id == body.ProjectId);

        Assert.Equal(PhotoSource.User, photo.Source);
        Assert.Equal(photo.Id, project.PhotoId);

        // The three keys are what every later screen resolves images by; a null
        // among them is a blank editor rather than an error.
        Assert.NotNull(photo.OriginalKey);
        Assert.NotNull(photo.Pre512Key);
        Assert.NotNull(photo.Proxy2048Key);
    }

    [Fact]
    public async Task The_project_is_named_after_the_file_without_its_extension()
    {
        var (client, _) = Arrange();
        client.DefaultRequestHeaders.Authorization =
            new AuthenticationHeaderValue("Bearer", await SignInAsync(client));

        var response = await client.PostAsync(
            "/api/photos", File([1, 2, 3], fileName: "Alpine Ridge.jpg"));

        var body = await response.Content.ReadFromJsonAsync<UploadPhotoResponse>();

        Assert.Equal("Alpine Ridge", body!.Name);
    }

    [Fact]
    public async Task All_three_objects_are_readable_afterwards()
    {
        var (client, _) = Arrange();
        client.DefaultRequestHeaders.Authorization =
            new AuthenticationHeaderValue("Bearer", await SignInAsync(client));

        var response = await client.PostAsync("/api/photos", File([9, 8, 7]));
        var body = await response.Content.ReadFromJsonAsync<UploadPhotoResponse>();

        using var scope = factory.Services.CreateScope();
        var context = scope.ServiceProvider.GetRequiredService<PhotoAssistantDbContext>();
        var storage = scope.ServiceProvider.GetRequiredService<IObjectStorage>();
        var photo = await context.Photos.SingleAsync(entity => entity.Id == body!.PhotoId);

        // Reading them back, rather than trusting that the write returned: a key
        // in the database that resolves to nothing is exactly the failure this
        // ordering exists to prevent.
        Assert.NotNull(await storage.GetAsync(
            StorageBucket.Originals, photo.OriginalKey!, CancellationToken.None));
        Assert.NotNull(await storage.GetAsync(
            StorageBucket.Derivatives, photo.Pre512Key!, CancellationToken.None));
        Assert.NotNull(await storage.GetAsync(
            StorageBucket.Derivatives, photo.Proxy2048Key!, CancellationToken.None));
    }

    [Fact]
    public async Task A_file_of_the_wrong_kind_is_refused_before_the_service_is_called()
    {
        var (client, derivatives) = Arrange();
        client.DefaultRequestHeaders.Authorization =
            new AuthenticationHeaderValue("Bearer", await SignInAsync(client));

        var response = await client.PostAsync(
            "/api/photos", File([1, 2, 3], "notes.pdf", "application/pdf"));

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.Equal(0, derivatives.Calls);

        var problem = await response.Content.ReadFromJsonAsync<ValidationProblemDetails>();
        Assert.Contains("file", problem!.Errors.Keys);
    }

    [Fact]
    public async Task An_empty_file_is_refused()
    {
        var (client, _) = Arrange();
        client.DefaultRequestHeaders.Authorization =
            new AuthenticationHeaderValue("Bearer", await SignInAsync(client));

        var response = await client.PostAsync("/api/photos", File([]));

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Fact]
    public async Task A_file_the_service_cannot_read_becomes_a_message_about_the_file()
    {
        // The service's verdict is about the upload, so it reaches the person
        // who made it rather than becoming a 500 they cannot act on.
        var (client, derivatives) = Arrange();
        derivatives.Next = DerivativeResult.Failure("not a readable image");
        client.DefaultRequestHeaders.Authorization =
            new AuthenticationHeaderValue("Bearer", await SignInAsync(client));

        var response = await client.PostAsync("/api/photos", File([1, 2, 3]));

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);

        var problem = await response.Content.ReadFromJsonAsync<ValidationProblemDetails>();
        Assert.Contains("not a readable image", problem!.Errors["file"]);
    }

    [Fact]
    public async Task Nothing_is_written_when_the_service_refuses_the_file()
    {
        var (client, derivatives) = Arrange();
        derivatives.Next = DerivativeResult.Failure("not a readable image");
        client.DefaultRequestHeaders.Authorization =
            new AuthenticationHeaderValue("Bearer", await SignInAsync(client));

        using var scope = factory.Services.CreateScope();
        var context = scope.ServiceProvider.GetRequiredService<PhotoAssistantDbContext>();
        var before = await context.Photos.CountAsync(CancellationToken.None);

        await client.PostAsync("/api/photos", File([1, 2, 3]));

        var after = await context.Photos.CountAsync(CancellationToken.None);
        Assert.Equal(before, after);
    }
}
