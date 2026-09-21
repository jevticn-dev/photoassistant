using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;
using PhotoAssistant.Api.Controllers;
using PhotoAssistant.Api.Tests.Infrastructure;
using PhotoAssistant.Application.Authentication;
using PhotoAssistant.Application.Exports;
using PhotoAssistant.Application.Photos;
using PhotoAssistant.Application.Storage;
using PhotoAssistant.Domain.Enums;
using PhotoAssistant.Infrastructure.Persistence;

namespace PhotoAssistant.Api.Tests;

/// <summary>
/// Exporting the photograph at full size.
///
/// <para>
/// This side queues and reports; the rendering is the ML service's and is
/// tested there. What is checked here is that the row the worker will read says
/// the right thing, that only its owner can see it, and that the file comes
/// back through the API rather than from storage directly (ADR-15).
/// </para>
/// </summary>
[Collection(ApiCollection.Name)]
public sealed class ExportEndpointTests(ApiFactory factory)
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

    private static object Recipe(double exposure = 0.25) => new
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

    private static async Task<Guid> RequestExportAsync(HttpClient client, Guid projectId)
    {
        var response = await client.PostAsJsonAsync(
            $"/api/projects/{projectId}/export", Recipe());

        Assert.Equal(HttpStatusCode.Accepted, response.StatusCode);

        var body = await response.Content
            .ReadFromJsonAsync<ProjectsController.ExportQueuedResponse>();

        return body!.JobId;
    }

    /// <summary>Stands in for the worker, which is the ML service and is not running here.</summary>
    private async Task FinishAsync(Guid jobId, byte[] file)
    {
        using var scope = factory.Services.CreateScope();
        var context = scope.ServiceProvider.GetRequiredService<PhotoAssistantDbContext>();
        var storage = scope.ServiceProvider.GetRequiredService<IObjectStorage>();

        var key = $"{jobId}.png";
        await storage.PutAsync(
            StorageBucket.Exports, key, file, "image/png", CancellationToken.None);

        var job = await context.Jobs.SingleAsync(row => row.Id == jobId);
        job.Status = JobStatus.Done;
        job.Result = JsonSerializer.Serialize(new
        {
            key,
            contentType = "image/png",
            width = 3000,
            height = 2000,
            bytes = file.Length,
        });

        await context.SaveChangesAsync();
    }

    // -- queueing -------------------------------------------------------------

    [Fact]
    public async Task Asking_for_an_export_queues_a_job_the_worker_can_act_on()
    {
        // Everything the ML service needs and nothing it does not: the object to
        // read, the recipe to apply, and the project the ownership check hangs
        // off. It is never told who asked.
        var client = await SignedInAsync(Arrange());
        var photoId = await UploadAsync(client);
        var projectId = await ProjectOfAsync(photoId);

        var jobId = await RequestExportAsync(client, projectId);

        using var scope = factory.Services.CreateScope();
        var context = scope.ServiceProvider.GetRequiredService<PhotoAssistantDbContext>();
        var job = await context.Jobs.SingleAsync(row => row.Id == jobId);

        Assert.Equal(JobType.Export, job.Type);
        Assert.Equal(JobStatus.Pending, job.Status);

        var payload = JsonSerializer.Deserialize<ExportPayload>(job.Payload)!;
        var photo = await context.Photos.SingleAsync(row => row.Id == photoId);

        Assert.Equal(projectId, payload.ProjectId);
        Assert.Equal(photo.OriginalKey, payload.OriginalKey);
        Assert.Equal(
            0.25,
            payload.Recipe.GetProperty("tone").GetProperty("exposure").GetDouble());
    }

    [Fact]
    public async Task The_queued_recipe_is_the_canonical_form_rather_than_what_arrived()
    {
        // The same rule a saved version follows: what the worker renders must
        // not depend on which client asked for it.
        var client = await SignedInAsync(Arrange());
        var projectId = await ProjectOfAsync(await UploadAsync(client));

        var jobId = await RequestExportAsync(client, projectId);

        using var scope = factory.Services.CreateScope();
        var context = scope.ServiceProvider.GetRequiredService<PhotoAssistantDbContext>();
        var job = await context.Jobs.SingleAsync(row => row.Id == jobId);
        var payload = JsonSerializer.Deserialize<ExportPayload>(job.Payload)!;

        Assert.Equal(1, payload.Recipe.GetProperty("schema").GetInt32());
        Assert.True(payload.Recipe.TryGetProperty("tone_curve", out _));
        Assert.True(payload.Recipe.TryGetProperty("color", out _));
    }

    [Fact]
    public async Task Exporting_does_not_save_a_version()
    {
        // Asking for a file is not a turning point somebody meant to keep
        // (§B111), so the history is left exactly as it was.
        var client = await SignedInAsync(Arrange());
        var projectId = await ProjectOfAsync(await UploadAsync(client));

        await RequestExportAsync(client, projectId);

        using var scope = factory.Services.CreateScope();
        var context = scope.ServiceProvider.GetRequiredService<PhotoAssistantDbContext>();

        Assert.False(await context.EditVersions.AnyAsync(row => row.ProjectId == projectId));
    }

    [Fact]
    public async Task A_recipe_the_schema_refuses_is_not_queued_at_all()
    {
        // Refused while somebody is still there to be told. A job that cannot
        // succeed would fail in the background, on a screen they have left.
        var client = await SignedInAsync(Arrange());
        var projectId = await ProjectOfAsync(await UploadAsync(client));

        var response = await client.PostAsJsonAsync(
            $"/api/projects/{projectId}/export", new { nonsense = true });

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);

        using var scope = factory.Services.CreateScope();
        var context = scope.ServiceProvider.GetRequiredService<PhotoAssistantDbContext>();

        // Filtered here rather than in the query: the payload is jsonb, and
        // Postgres will not compare it to a string without a cast. Reading the
        // export jobs back and looking is enough at this size.
        var payloads = await context.Jobs
            .Where(row => row.Type == JobType.Export)
            .Select(row => row.Payload)
            .ToListAsync();

        Assert.DoesNotContain(payloads, payload => payload.Contains(projectId.ToString()));
    }

    [Fact]
    public async Task Exporting_someone_elses_project_is_not_found()
    {
        var owner = await SignedInAsync(Arrange());
        var projectId = await ProjectOfAsync(await UploadAsync(owner));
        var intruder = await SignedInAsync(Arrange());

        var response = await intruder.PostAsJsonAsync(
            $"/api/projects/{projectId}/export", Recipe());

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
    }

    // -- following it ---------------------------------------------------------

    [Fact]
    public async Task A_queued_export_reports_itself_as_pending()
    {
        var client = await SignedInAsync(Arrange());
        var projectId = await ProjectOfAsync(await UploadAsync(client));
        var jobId = await RequestExportAsync(client, projectId);

        var job = await client.GetFromJsonAsync<JobState>($"/api/jobs/{jobId}");

        Assert.Equal("pending", job!.Status);
        Assert.Null(job.Result);
        Assert.Null(job.Error);
    }

    [Fact]
    public async Task A_finished_export_reports_its_size_and_hands_over_the_file()
    {
        var client = await SignedInAsync(Arrange());
        var projectId = await ProjectOfAsync(await UploadAsync(client));
        var jobId = await RequestExportAsync(client, projectId);

        byte[] file = [137, 80, 78, 71, 1, 2, 3];
        await FinishAsync(jobId, file);

        var job = await client.GetFromJsonAsync<JobState>($"/api/jobs/{jobId}");

        Assert.Equal("done", job!.Status);
        Assert.Equal(file.Length, job.Result!.Bytes);
        Assert.Equal("image/png", job.Result.ContentType);

        var download = await client.GetAsync($"/api/jobs/{jobId}/download");

        Assert.Equal(HttpStatusCode.OK, download.StatusCode);
        Assert.Equal("image/png", download.Content.Headers.ContentType?.MediaType);
        Assert.Equal(file, await download.Content.ReadAsByteArrayAsync());

        // Named after the job, so two exports of one project do not land on top
        // of each other in somebody's downloads folder.
        Assert.Contains(jobId.ToString(), download.Content.Headers.ContentDisposition?.FileName);
    }

    [Fact]
    public async Task There_is_nothing_to_download_until_there_is()
    {
        // A download is a file or it is nothing. The screen asks for the status
        // separately, and already knows how.
        var client = await SignedInAsync(Arrange());
        var projectId = await ProjectOfAsync(await UploadAsync(client));
        var jobId = await RequestExportAsync(client, projectId);

        var response = await client.GetAsync($"/api/jobs/{jobId}/download");

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
    }

    [Fact]
    public async Task A_failed_export_says_what_went_wrong()
    {
        var client = await SignedInAsync(Arrange());
        var projectId = await ProjectOfAsync(await UploadAsync(client));
        var jobId = await RequestExportAsync(client, projectId);

        using (var scope = factory.Services.CreateScope())
        {
            var context = scope.ServiceProvider.GetRequiredService<PhotoAssistantDbContext>();
            var job = await context.Jobs.SingleAsync(row => row.Id == jobId);
            job.Status = JobStatus.Failed;
            job.Error = "the original this project was made from is no longer stored";
            await context.SaveChangesAsync();
        }

        var state = await client.GetFromJsonAsync<JobState>($"/api/jobs/{jobId}");

        Assert.Equal("failed", state!.Status);
        Assert.Contains("no longer stored", state.Error);
        Assert.Null(state.Result);
    }

    [Fact]
    public async Task Someone_elses_job_is_not_found_and_neither_is_its_file()
    {
        // The jobs table has no owner column, so this is the check that the
        // payload's project is one of this person's — the one place this route
        // could have been left open.
        var owner = await SignedInAsync(Arrange());
        var projectId = await ProjectOfAsync(await UploadAsync(owner));
        var jobId = await RequestExportAsync(owner, projectId);
        await FinishAsync(jobId, [1, 2, 3]);

        var intruder = await SignedInAsync(Arrange());

        Assert.Equal(
            HttpStatusCode.NotFound,
            (await intruder.GetAsync($"/api/jobs/{jobId}")).StatusCode);
        Assert.Equal(
            HttpStatusCode.NotFound,
            (await intruder.GetAsync($"/api/jobs/{jobId}/download")).StatusCode);
    }

    // -- the exports of a project ---------------------------------------------

    [Fact]
    public async Task A_projects_exports_come_back_newest_first()
    {
        // What the editor reads when it opens, so a finished file survives a
        // reload rather than existing on the server with no way to it.
        var client = await SignedInAsync(Arrange());
        var projectId = await ProjectOfAsync(await UploadAsync(client));

        var first = await RequestExportAsync(client, projectId);
        var second = await RequestExportAsync(client, projectId);

        var listed = await client.GetFromJsonAsync<List<JobState>>(
            $"/api/projects/{projectId}/exports");

        Assert.Equal([second, first], listed!.Select(job => job.Id));
        Assert.All(listed!, job => Assert.Equal("pending", job.Status));
    }

    [Fact]
    public async Task Only_this_projects_exports_are_listed()
    {
        // The jobs table has no project column — the id lives inside the
        // payload — so this is the test that the filter actually filters.
        var client = await SignedInAsync(Arrange());
        var mine = await ProjectOfAsync(await UploadAsync(client));
        var other = await ProjectOfAsync(await UploadAsync(client, "second.jpg"));

        var wanted = await RequestExportAsync(client, mine);
        await RequestExportAsync(client, other);

        var listed = await client.GetFromJsonAsync<List<JobState>>(
            $"/api/projects/{mine}/exports");

        Assert.Equal([wanted], listed!.Select(job => job.Id));
    }

    [Fact]
    public async Task A_finished_export_is_listed_with_its_result()
    {
        var client = await SignedInAsync(Arrange());
        var projectId = await ProjectOfAsync(await UploadAsync(client));
        var jobId = await RequestExportAsync(client, projectId);

        await FinishAsync(jobId, [137, 80, 78, 71, 9]);

        var listed = await client.GetFromJsonAsync<List<JobState>>(
            $"/api/projects/{projectId}/exports");

        var job = Assert.Single(listed!);

        Assert.Equal("done", job.Status);
        Assert.Equal(5, job.Result!.Bytes);
    }

    [Fact]
    public async Task An_export_says_which_recipe_it_rendered()
    {
        // What lets the editor tell whether the file is still the photograph on
        // screen. Without it the download button offers the last export
        // whatever has happened since.
        var client = await SignedInAsync(Arrange());
        var projectId = await ProjectOfAsync(await UploadAsync(client));

        await client.PostAsJsonAsync($"/api/projects/{projectId}/export", Recipe(0.6));

        var listed = await client.GetFromJsonAsync<List<JobState>>(
            $"/api/projects/{projectId}/exports");
        var job = Assert.Single(listed!);

        Assert.Equal(
            0.6,
            job.Edit!.Value.GetProperty("tone").GetProperty("exposure").GetDouble());

        // Canonical, like everything else that stores a recipe: every key, in
        // schema order, whatever the client sent.
        Assert.True(job.Edit.Value.TryGetProperty("tone_curve", out _));
    }

    [Fact]
    public async Task A_project_nobody_has_exported_lists_nothing()
    {
        var client = await SignedInAsync(Arrange());
        var projectId = await ProjectOfAsync(await UploadAsync(client));

        var response = await client.GetAsync($"/api/projects/{projectId}/exports");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Empty((await response.Content.ReadFromJsonAsync<List<JobState>>())!);
    }

    [Fact]
    public async Task Someone_elses_exports_are_not_found()
    {
        var owner = await SignedInAsync(Arrange());
        var projectId = await ProjectOfAsync(await UploadAsync(owner));
        await RequestExportAsync(owner, projectId);

        var intruder = await SignedInAsync(Arrange());
        var response = await intruder.GetAsync($"/api/projects/{projectId}/exports");

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
    }

    [Fact]
    public async Task A_job_that_does_not_exist_is_not_found()
    {
        var client = await SignedInAsync(Arrange());

        Assert.Equal(
            HttpStatusCode.NotFound,
            (await client.GetAsync($"/api/jobs/{Guid.NewGuid()}")).StatusCode);
    }

    [Fact]
    public async Task An_anonymous_request_reaches_none_of_it()
    {
        var client = Arrange();

        Assert.Equal(
            HttpStatusCode.Unauthorized,
            (await client.PostAsJsonAsync(
                $"/api/projects/{Guid.NewGuid()}/export", Recipe())).StatusCode);
        Assert.Equal(
            HttpStatusCode.Unauthorized,
            (await client.GetAsync($"/api/jobs/{Guid.NewGuid()}")).StatusCode);
        Assert.Equal(
            HttpStatusCode.Unauthorized,
            (await client.GetAsync($"/api/jobs/{Guid.NewGuid()}/download")).StatusCode);
        Assert.Equal(
            HttpStatusCode.Unauthorized,
            (await client.GetAsync($"/api/projects/{Guid.NewGuid()}/exports")).StatusCode);
    }
}
