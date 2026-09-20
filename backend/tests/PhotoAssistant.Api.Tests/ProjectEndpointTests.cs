using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;
using PhotoAssistant.Api.Tests.Infrastructure;
using PhotoAssistant.Application.Authentication;
using PhotoAssistant.Application.Photos;
using PhotoAssistant.Application.Projects;
using PhotoAssistant.Application.Storage;
using PhotoAssistant.Domain.Entities;
using PhotoAssistant.Domain.Enums;
using PhotoAssistant.Infrastructure.Persistence;

namespace PhotoAssistant.Api.Tests;

/// <summary>
/// The projects a person has: listing them, renaming one, and deleting one.
///
/// <para>
/// Ownership is the thread running through all of it. Every route folds the
/// user id into its query, so someone else's project is absent rather than
/// forbidden — and each of these tests checks that from the other side, with a
/// second account.
/// </para>
/// </summary>
[Collection(ApiCollection.Name)]
public sealed class ProjectEndpointTests(ApiFactory factory)
{
    private const string ValidPassword = "Str0ng!Passphrase";

    private sealed class FakeDerivatives : IDerivativeGenerator
    {
        public Task<DerivativeResult> DeriveAsync(
            ReadOnlyMemory<byte> image,
            string fileName,
            CancellationToken cancellationToken) =>
            Task.FromResult(DerivativeResult.Success(
                new DerivedImage
                {
                    Content = new byte[] { 2, 2, 2 },
                    ContentType = "image/png",
                    Width = 512,
                    Height = 341,
                },
                new DerivedImage
                {
                    Content = new byte[] { 3, 3, 3 },
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

    private static async Task<Guid> UploadAsync(HttpClient client, string name = "alpine.jpg")
    {
        var file = new ByteArrayContent([9, 9, 9]);
        file.Headers.ContentType = new MediaTypeHeaderValue("image/jpeg");

        var response = await client.PostAsync(
            "/api/photos", new MultipartFormDataContent { { file, "file", name } });

        return (await response.Content.ReadFromJsonAsync<UploadPhotoResponse>())!.PhotoId;
    }

    private async Task<Guid> ProjectOfAsync(Guid photoId)
    {
        using var scope = factory.Services.CreateScope();
        var context = scope.ServiceProvider.GetRequiredService<PhotoAssistantDbContext>();

        return await context.Projects
            .Where(project => project.PhotoId == photoId)
            .Select(project => project.Id)
            .SingleAsync();
    }

    private async Task SaveVersionAsync(Guid projectId, DateTimeOffset at)
    {
        using var scope = factory.Services.CreateScope();
        var context = scope.ServiceProvider.GetRequiredService<PhotoAssistantDbContext>();

        context.EditVersions.Add(new EditVersion
        {
            Id = Guid.CreateVersion7(),
            ProjectId = projectId,
            Edit = """{"schema":1}""",
            CreatedAt = at,
        });

        await context.SaveChangesAsync();
    }

    private static async Task<IReadOnlyList<ProjectListItem>> ListAsync(HttpClient client) =>
        (await client.GetFromJsonAsync<List<ProjectListItem>>("/api/projects"))!;

    // -- the list -------------------------------------------------------------

    [Fact]
    public async Task Only_your_own_projects_are_listed()
    {
        var owner = await SignedInAsync(Arrange());
        var mine = await ProjectOfAsync(await UploadAsync(owner));

        var stranger = await SignedInAsync(Arrange());
        await UploadAsync(stranger);

        var listed = await ListAsync(owner);

        Assert.Contains(listed, project => project.Id == mine);
        Assert.All(listed, project => Assert.Equal(mine, project.Id));
    }

    [Fact]
    public async Task A_project_with_nothing_saved_still_says_when_it_last_changed()
    {
        // An upload creates the project, so leaving before saving anything is a
        // normal state (decision G) rather than a row with a hole in it.
        var client = await SignedInAsync(Arrange());
        var projectId = await ProjectOfAsync(await UploadAsync(client));

        var project = Assert.Single(await ListAsync(client));

        Assert.Equal(projectId, project.Id);
        Assert.Equal(0, project.VersionCount);
        Assert.NotEqual(default, project.LastEditedAt);
    }

    [Fact]
    public async Task The_newest_work_is_at_the_top()
    {
        var client = await SignedInAsync(Arrange());
        var older = await ProjectOfAsync(await UploadAsync(client, "older.jpg"));
        var newer = await ProjectOfAsync(await UploadAsync(client, "newer.jpg"));

        // Saved out of order on purpose: what orders the list is when the work
        // happened, not when the project was made.
        await SaveVersionAsync(newer, DateTimeOffset.UtcNow.AddHours(-3));
        await SaveVersionAsync(older, DateTimeOffset.UtcNow);

        var listed = await ListAsync(client);

        Assert.Equal(older, listed[0].Id);
        Assert.Equal(newer, listed[1].Id);
        Assert.Equal(1, listed[0].VersionCount);
    }

    [Fact]
    public async Task The_thumbnail_is_the_small_copy_rather_than_the_working_one()
    {
        var client = await SignedInAsync(Arrange());
        var photoId = await UploadAsync(client);

        var response = await client.GetAsync($"/api/photos/{photoId}/thumbnail");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal("image/png", response.Content.Headers.ContentType?.MediaType);
        Assert.Equal(new byte[] { 2, 2, 2 }, await response.Content.ReadAsByteArrayAsync());
    }

    // -- renaming -------------------------------------------------------------

    [Fact]
    public async Task Renaming_keeps_what_was_trimmed_off_out_of_the_name()
    {
        var client = await SignedInAsync(Arrange());
        var projectId = await ProjectOfAsync(await UploadAsync(client));

        var response = await client.PatchAsJsonAsync(
            $"/api/projects/{projectId}", new { name = "  Alpine Ridge  " });

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);

        var project = Assert.Single(await ListAsync(client));
        Assert.Equal("Alpine Ridge", project.Name);
    }

    [Fact]
    public async Task A_name_of_nothing_but_spaces_is_refused()
    {
        // Trimmed rather than rejected is right for a stray space; what is left
        // still has to be something, or the list shows a row with no label.
        var client = await SignedInAsync(Arrange());
        var projectId = await ProjectOfAsync(await UploadAsync(client));

        var response = await client.PatchAsJsonAsync(
            $"/api/projects/{projectId}", new { name = "   " });

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Fact]
    public async Task A_name_longer_than_the_column_is_refused_rather_than_cut()
    {
        var client = await SignedInAsync(Arrange());
        var projectId = await ProjectOfAsync(await UploadAsync(client));

        var response = await client.PatchAsJsonAsync(
            $"/api/projects/{projectId}",
            new { name = new string('x', ProjectName.MaxLength + 1) });

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Fact]
    public async Task Renaming_someone_elses_project_is_not_found()
    {
        var owner = await SignedInAsync(Arrange());
        var projectId = await ProjectOfAsync(await UploadAsync(owner));
        var intruder = await SignedInAsync(Arrange());

        var response = await intruder.PatchAsJsonAsync(
            $"/api/projects/{projectId}", new { name = "Mine now" });

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
    }

    // -- deleting -------------------------------------------------------------

    [Fact]
    public async Task Deleting_takes_the_versions_the_choices_and_the_photograph_with_it()
    {
        // An upload makes exactly one project, so the two are one thing to the
        // person who made them. Keeping the photograph would leave the file
        // they asked to be rid of sitting on the server.
        var client = await SignedInAsync(Arrange());
        var photoId = await UploadAsync(client);
        var projectId = await ProjectOfAsync(photoId);

        await SaveVersionAsync(projectId, DateTimeOffset.UtcNow);
        await client.PostAsJsonAsync(
            $"/api/photos/{photoId}/choices",
            new
            {
                shown = new[]
                {
                    new { recipe = new Dictionary<string, object> { ["schema"] = 1 } },
                },
                chosenIndex = 0,
            });

        var response = await client.DeleteAsync($"/api/projects/{projectId}");

        Assert.Equal(HttpStatusCode.NoContent, response.StatusCode);

        using var scope = factory.Services.CreateScope();
        var context = scope.ServiceProvider.GetRequiredService<PhotoAssistantDbContext>();

        Assert.False(await context.Projects.AnyAsync(row => row.Id == projectId));
        Assert.False(await context.EditVersions.AnyAsync(row => row.ProjectId == projectId));
        Assert.False(await context.Choices.AnyAsync(row => row.PhotoId == photoId));
        Assert.False(await context.Photos.AnyAsync(row => row.Id == photoId));
    }

    [Fact]
    public async Task Deleting_clears_the_stored_objects_as_well_as_the_rows()
    {
        // Rows without objects is a smaller mess than objects without rows, so
        // the database goes first — but the objects still have to go, or the
        // photograph is deleted everywhere except where it actually is.
        var client = await SignedInAsync(Arrange());
        var photoId = await UploadAsync(client);
        var projectId = await ProjectOfAsync(photoId);

        string[] keys;
        using (var before = factory.Services.CreateScope())
        {
            var context = before.ServiceProvider.GetRequiredService<PhotoAssistantDbContext>();
            var photo = await context.Photos.SingleAsync(row => row.Id == photoId);

            keys = [photo.Pre512Key!, photo.Proxy2048Key!];
        }

        await client.DeleteAsync($"/api/projects/{projectId}");

        using var scope = factory.Services.CreateScope();
        var storage = scope.ServiceProvider.GetRequiredService<IObjectStorage>();

        foreach (var key in keys)
        {
            Assert.Null(await storage.GetAsync(StorageBucket.Derivatives, key, default));
        }
    }

    [Fact]
    public async Task Deleting_a_project_never_touches_a_corpus_photograph()
    {
        // The guard that matters most here. The same table holds the 5.000
        // FiveK photographs the whole recommender is built on, and they are
        // referenced by 25.000 fitted examples.
        var client = await SignedInAsync(Arrange());
        var photoId = await UploadAsync(client);
        var projectId = await ProjectOfAsync(photoId);

        using (var arrange = factory.Services.CreateScope())
        {
            var context = arrange.ServiceProvider.GetRequiredService<PhotoAssistantDbContext>();
            var photo = await context.Photos.SingleAsync(row => row.Id == photoId);

            photo.Source = PhotoSource.Fivek;
            await context.SaveChangesAsync();
        }

        var response = await client.DeleteAsync($"/api/projects/{projectId}");

        Assert.Equal(HttpStatusCode.NoContent, response.StatusCode);

        using var scope = factory.Services.CreateScope();
        var after = scope.ServiceProvider.GetRequiredService<PhotoAssistantDbContext>();

        Assert.False(await after.Projects.AnyAsync(row => row.Id == projectId));
        Assert.True(await after.Photos.AnyAsync(row => row.Id == photoId));
    }

    [Fact]
    public async Task Deleting_someone_elses_project_is_not_found()
    {
        var owner = await SignedInAsync(Arrange());
        var projectId = await ProjectOfAsync(await UploadAsync(owner));
        var intruder = await SignedInAsync(Arrange());

        var response = await intruder.DeleteAsync($"/api/projects/{projectId}");

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);

        using var scope = factory.Services.CreateScope();
        var context = scope.ServiceProvider.GetRequiredService<PhotoAssistantDbContext>();

        Assert.True(await context.Projects.AnyAsync(row => row.Id == projectId));
    }

    // -- saving a version -----------------------------------------------------

    private static object Recipe(double exposure) => new
    {
        schema = 1,
        white_balance = new { temperature = 0, tint = 0 },
        tone = new
        {
            exposure,
            contrast = 0,
            highlights = 0,
            shadows = 0,
            whites = 0,
            blacks = 0,
        },
        color = new { saturation = 0, vibrance = 0 },
        tone_curve = new { points = new[] { new[] { 0.0, 0.0 }, new[] { 1.0, 1.0 } } },
    };

    [Fact]
    public async Task Each_save_is_a_whole_recipe_and_earns_the_next_label()
    {
        // ADR-6: a snapshot rather than a delta. A recipe is about a kilobyte,
        // so deltas save nothing while making "restore this" a replay.
        var client = await SignedInAsync(Arrange());
        var projectId = await ProjectOfAsync(await UploadAsync(client));

        var first = await client.PostAsJsonAsync(
            $"/api/projects/{projectId}/versions", Recipe(0.25));
        var second = await client.PostAsJsonAsync(
            $"/api/projects/{projectId}/versions", Recipe(0.5));

        Assert.Equal(HttpStatusCode.Created, first.StatusCode);
        Assert.Equal("V01", (await first.Content.ReadFromJsonAsync<SavedVersion>())!.Label);
        Assert.Equal("V02", (await second.Content.ReadFromJsonAsync<SavedVersion>())!.Label);
    }

    [Fact]
    public async Task What_is_stored_is_the_canonical_form_rather_than_what_arrived()
    {
        // Every key, in schema order, whatever the client sent. What a version
        // means must not depend on which client wrote it.
        var client = await SignedInAsync(Arrange());
        var projectId = await ProjectOfAsync(await UploadAsync(client));

        await client.PostAsJsonAsync($"/api/projects/{projectId}/versions", Recipe(0.25));

        using var scope = factory.Services.CreateScope();
        var context = scope.ServiceProvider.GetRequiredService<PhotoAssistantDbContext>();
        var stored = await context.EditVersions
            .Where(row => row.ProjectId == projectId)
            .Select(row => row.Edit)
            .SingleAsync();

        using var document = System.Text.Json.JsonDocument.Parse(stored);

        Assert.Equal(1, document.RootElement.GetProperty("schema").GetInt32());
        Assert.Equal(
            0.25,
            document.RootElement.GetProperty("tone").GetProperty("exposure").GetDouble());
        Assert.True(document.RootElement.TryGetProperty("tone_curve", out _));
    }

    [Fact]
    public async Task A_document_that_is_not_a_recipe_is_refused_before_it_is_written()
    {
        // The column is jsonb, so the database would take this quite happily
        // (§B107). What refuses it is the C# model of the schema — the same
        // rules the renderer and the pipeline apply.
        var client = await SignedInAsync(Arrange());
        var projectId = await ProjectOfAsync(await UploadAsync(client));

        var response = await client.PostAsJsonAsync(
            $"/api/projects/{projectId}/versions", new { nonsense = true });

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);

        using var scope = factory.Services.CreateScope();
        var context = scope.ServiceProvider.GetRequiredService<PhotoAssistantDbContext>();

        Assert.False(await context.EditVersions.AnyAsync(row => row.ProjectId == projectId));
    }

    [Fact]
    public async Task A_parameter_outside_its_range_is_refused_too()
    {
        var client = await SignedInAsync(Arrange());
        var projectId = await ProjectOfAsync(await UploadAsync(client));

        var response = await client.PostAsJsonAsync(
            $"/api/projects/{projectId}/versions", Recipe(exposure: 42));

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Fact]
    public async Task Saving_into_someone_elses_project_is_not_found()
    {
        var owner = await SignedInAsync(Arrange());
        var projectId = await ProjectOfAsync(await UploadAsync(owner));
        var intruder = await SignedInAsync(Arrange());

        var response = await intruder.PostAsJsonAsync(
            $"/api/projects/{projectId}/versions", Recipe(0.1));

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
    }

    [Fact]
    public async Task The_editor_reopens_on_what_was_saved_last()
    {
        // The read half of this was built in task 4; saving is what finally
        // gives it something of the person's own to prefer.
        var client = await SignedInAsync(Arrange());
        var photoId = await UploadAsync(client);
        var projectId = await ProjectOfAsync(photoId);

        await client.PostAsJsonAsync($"/api/projects/{projectId}/versions", Recipe(0.25));
        await client.PostAsJsonAsync($"/api/projects/{projectId}/versions", Recipe(0.75));

        var project = await client.GetFromJsonAsync<ProjectSummary>($"/api/projects/{projectId}");

        Assert.Equal(2, project!.VersionCount);
        Assert.Equal(
            0.75,
            project.StartingEdit!.Value.GetProperty("tone").GetProperty("exposure").GetDouble());
    }

    [Fact]
    public async Task An_anonymous_request_reaches_none_of_it()
    {
        var client = Arrange();

        Assert.Equal(HttpStatusCode.Unauthorized, (await client.GetAsync("/api/projects")).StatusCode);
        Assert.Equal(
            HttpStatusCode.Unauthorized,
            (await client.DeleteAsync($"/api/projects/{Guid.NewGuid()}")).StatusCode);
    }
}
