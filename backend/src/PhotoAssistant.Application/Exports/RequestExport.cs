using PhotoAssistant.Application.Storage;
using PhotoAssistant.Domain.Edits;

namespace PhotoAssistant.Application.Exports;

public sealed record RequestExportResult
{
    private RequestExportResult()
    {
    }

    public bool Succeeded { get; private init; }

    public bool NotFound { get; private init; }

    public string? Error { get; private init; }

    public Guid JobId { get; private init; }

    public static RequestExportResult Queued(Guid jobId) =>
        new() { Succeeded = true, JobId = jobId };

    public static RequestExportResult Missing() => new() { NotFound = true };

    public static RequestExportResult Invalid(string error) => new() { Error = error };
}

/// <summary>
/// Asking for the photograph at full size, with the edit applied.
///
/// <para>
/// <b>Queued rather than rendered here</b> (ADR-7, plan §9). A full-resolution
/// render is seconds of arithmetic over hundreds of megabytes — twelve seconds
/// at 48 megapixels, measured — so doing it inside the request would hold a web
/// thread for that long and time out from behind a proxy. The row goes in, the
/// ML service takes it, and the screen asks how it is going.
/// </para>
///
/// <para>
/// <b>The recipe is validated before it is queued</b>, by the same
/// <see cref="EditRecipe"/> that guards a saved version. A job that cannot
/// succeed is refused while somebody is still there to be told; refusing it
/// later means a failure notice on a screen the person has probably left.
/// </para>
/// </summary>
public sealed class RequestExportHandler(IJobRepository jobs)
{
    public async Task<RequestExportResult> RequestAsync(
        Guid projectId,
        Guid userId,
        string document,
        CancellationToken cancellationToken)
    {
        EditRecipe recipe;

        try
        {
            recipe = EditRecipe.FromJson(document);
        }
        catch (EditSchemaException error)
        {
            return RequestExportResult.Invalid(error.Message);
        }

        // Canonical form, for the same reason a version stores it: what the
        // worker renders must not depend on which client asked.
        var jobId = await jobs.QueueExportForUserAsync(
            projectId, userId, recipe.ToJson(), cancellationToken);

        return jobId is null
            ? RequestExportResult.Missing()
            : RequestExportResult.Queued(jobId.Value);
    }
}

/// <summary>
/// Reading a job's progress, and its file once there is one.
/// </summary>
public sealed class GetJobHandler(IJobRepository jobs, IObjectStorage storage)
{
    public Task<JobState?> GetAsync(Guid jobId, Guid userId, CancellationToken cancellationToken) =>
        jobs.FindForUserAsync(jobId, userId, cancellationToken);

    /// <summary>
    /// The finished export. Null while it is not finished, when the job is not
    /// this user's, and when the object is gone — all of which the caller
    /// answers the same way.
    /// </summary>
    /// <remarks>
    /// Served through the API rather than from a presigned URL, which ADR-15
    /// requires: object storage is not reachable from the internet, and who may
    /// have this file is decided here. It costs holding the file in memory for
    /// the length of one response — about 25 MB for a photograph of 24
    /// megapixels (§B120), which is the size at which that stops being free and
    /// streaming becomes the thing to do next.
    /// </remarks>
    public async Task<StoredObject?> DownloadAsync(
        Guid jobId,
        Guid userId,
        CancellationToken cancellationToken)
    {
        var job = await jobs.FindForUserAsync(jobId, userId, cancellationToken);

        return job?.Result is null
            ? null
            : await storage.GetAsync(StorageBucket.Exports, job.Result.Key, cancellationToken);
    }
}

/// <summary>
/// The exports asked for on one project, newest first.
///
/// <para>
/// Serves two callers with one query: the editor, which takes the newest so a
/// finished file is still reachable after a reload, and a list of a project's
/// exports for whenever one is wanted.
/// </para>
/// </summary>
public sealed class ListExportsHandler(IJobRepository jobs)
{
    public Task<IReadOnlyList<JobState>?> ListAsync(
        Guid projectId,
        Guid userId,
        CancellationToken cancellationToken) =>
        jobs.ListExportsForUserAsync(projectId, userId, cancellationToken);
}
