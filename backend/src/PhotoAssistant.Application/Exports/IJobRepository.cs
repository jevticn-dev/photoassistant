namespace PhotoAssistant.Application.Exports;

/// <summary>
/// The queue, from the side that puts things in it and asks how they are going.
///
/// <para>
/// A table rather than a broker (ADR-7). The rows are written here and taken by
/// the ML service, which polls; nothing in this direction ever executes the
/// work.
/// </para>
/// </summary>
public interface IJobRepository
{
    /// <summary>
    /// Queues an export for a project of this user's and returns the job's id.
    /// Null when there is no such project, or when its photograph has no
    /// original left to render.
    /// </summary>
    Task<Guid?> QueueExportForUserAsync(
        Guid projectId,
        Guid userId,
        string recipe,
        CancellationToken cancellationToken);

    /// <summary>
    /// Every export asked for on a project of this user's, newest first. Null
    /// when there is no such project.
    ///
    /// <para>
    /// The editor reads the first entry when it opens, so a finished export
    /// survives a reload: without it the file exists on the server with no way
    /// to it through the application, which is exactly what a person meets
    /// after closing the tab on a render they were waiting for.
    /// </para>
    /// </summary>
    Task<IReadOnlyList<JobState>?> ListExportsForUserAsync(
        Guid projectId,
        Guid userId,
        CancellationToken cancellationToken);

    /// <summary>
    /// A job, if it belongs to a project of this user's.
    ///
    /// <para>
    /// <b>Ownership comes through the payload.</b> The <c>jobs</c> table has no
    /// user column — it is shared with the pipeline's own work and predates any
    /// of this — so the project named in the payload is what is checked, and a
    /// job of somebody else's is absent rather than forbidden, like everything
    /// else addressed by an id here.
    /// </para>
    /// </summary>
    Task<JobState?> FindForUserAsync(Guid jobId, Guid userId, CancellationToken cancellationToken);
}
