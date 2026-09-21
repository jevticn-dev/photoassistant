using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using PhotoAssistant.Application.Exports;
using PhotoAssistant.Domain.Entities;
using PhotoAssistant.Domain.Enums;

namespace PhotoAssistant.Infrastructure.Persistence;

internal sealed class JobRepository(PhotoAssistantDbContext context) : IJobRepository
{
    public async Task<Guid?> QueueExportForUserAsync(
        Guid projectId,
        Guid userId,
        string recipe,
        CancellationToken cancellationToken)
    {
        // Ownership and the object key in one query: the export needs the
        // original, and the original belongs to the photograph the project is
        // about. A project whose photograph has no original cannot be exported,
        // and that is the same "no" as not owning it — the caller does not get
        // to learn which.
        var original = await context.Projects
            .Where(project => project.Id == projectId && project.UserId == userId)
            .Select(project => project.Photo.OriginalKey)
            .SingleOrDefaultAsync(cancellationToken);

        if (string.IsNullOrEmpty(original))
        {
            return null;
        }

        using var parsed = JsonDocument.Parse(recipe);

        var job = new Job
        {
            Id = Guid.CreateVersion7(),
            Type = JobType.Export,
            Status = JobStatus.Pending,
            Payload = JsonSerializer.Serialize(new ExportPayload
            {
                ProjectId = projectId,
                OriginalKey = original,
                Recipe = parsed.RootElement,
            }),
            CreatedAt = DateTimeOffset.UtcNow,
            UpdatedAt = DateTimeOffset.UtcNow,
        };

        context.Jobs.Add(job);
        await context.SaveChangesAsync(cancellationToken);

        return job.Id;
    }

    public async Task<IReadOnlyList<JobState>?> ListExportsForUserAsync(
        Guid projectId,
        Guid userId,
        CancellationToken cancellationToken)
    {
        var owned = await context.Projects.AnyAsync(
            project => project.Id == projectId && project.UserId == userId,
            cancellationToken);

        if (!owned)
        {
            return null;
        }

        // The project is named inside the payload rather than in a column of its
        // own, so the filter is a JSON path. It stays in the database
        // deliberately: matching in memory would mean reading every export of
        // every user to answer a question about one project.
        //
        // Written as SQL because LINQ has no translation for it here: the
        // column is jsonb mapped as a string, and `->>` — Postgres' "extract
        // as text" — is what reaches inside it. Interpolated into FromSql, so
        // the id travels as a parameter rather than as text in the statement.
        //
        // The id breaks the tie on created_at for the same reason the version
        // list does it: the clock is coarser than the gap between two rows.
        var rows = await context.Jobs
            .FromSql(
                $"""
                select * from jobs
                 where type = 'Export' and payload ->> 'projectId' = {projectId.ToString()}
                 order by created_at desc, id desc
                """)
            .AsNoTracking()
            .ToListAsync(cancellationToken);

        return [.. rows.Select(Describe)];
    }

    public async Task<JobState?> FindForUserAsync(
        Guid jobId,
        Guid userId,
        CancellationToken cancellationToken)
    {
        var job = await context.Jobs
            .Where(row => row.Id == jobId && row.Type == JobType.Export)
            .AsNoTracking()
            .SingleOrDefaultAsync(cancellationToken);

        if (job is null)
        {
            return null;
        }

        var payload = Read<ExportPayload>(job.Payload);

        if (payload is null)
        {
            return null;
        }

        // The ownership check the jobs table cannot do on its own: the row names
        // a project, and the project names a user.
        var owned = await context.Projects.AnyAsync(
            project => project.Id == payload.ProjectId && project.UserId == userId,
            cancellationToken);

        if (!owned)
        {
            return null;
        }

        return Describe(job);
    }

    /// <summary>One row as a screen needs it. Ownership is settled before this.</summary>
    private static JobState Describe(Job job) =>
        new()
        {
            Id = job.Id,
            Edit = Read<ExportPayload>(job.Payload)?.Recipe,
            // Lower case on the wire: these are values a client compares
            // against, and "Pending" is a C# spelling that happens to be what
            // the column holds.
            Status = job.Status.ToString().ToLowerInvariant(),
            CreatedAt = job.CreatedAt,
            UpdatedAt = job.UpdatedAt,
            Error = job.Error,
            Result = job.Status == JobStatus.Done ? Read<ExportResult>(job.Result) : null,
        };

    /// <summary>
    /// The column is <c>jsonb</c>, so this cannot fail on malformed JSON — but
    /// it can fail on JSON that is not the shape expected, which is what a
    /// pipeline job of another kind would be. Null rather than a throw: a row
    /// this code does not understand is not this request's problem.
    /// </summary>
    private static T? Read<T>(string? document)
        where T : class
    {
        if (string.IsNullOrEmpty(document))
        {
            return null;
        }

        try
        {
            return JsonSerializer.Deserialize<T>(document);
        }
        catch (JsonException)
        {
            return null;
        }
    }
}
