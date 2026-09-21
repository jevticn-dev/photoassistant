namespace PhotoAssistant.Application.Projects;

/// <summary>
/// One project as a list row.
///
/// <para>
/// Deliberately not <see cref="ProjectSummary"/>. That one carries the recipe
/// the editor opens on, which is a document per project; a list of twenty would
/// then send twenty recipes so that none of them could be shown.
/// </para>
/// </summary>
public sealed record ProjectListItem
{
    public required Guid Id { get; init; }

    public required string Name { get; init; }

    /// <summary>The photograph the thumbnail is addressed by.</summary>
    public required Guid PhotoId { get; init; }

    public required int VersionCount { get; init; }

    /// <summary>
    /// When the project last changed: the newest saved version, or the moment
    /// it was created when nothing has been saved.
    ///
    /// <para>
    /// Decided on the server rather than left to the client to work out from
    /// two fields, because "last edited" is one idea and splitting it would
    /// have every screen re-deciding what an unsaved project shows.
    /// </para>
    /// </summary>
    public required DateTimeOffset LastEditedAt { get; init; }
}

/// <summary>
/// The signed-in person's projects, newest activity first.
///
/// <para>
/// A project with no version is a normal state, not an error (decision G): the
/// upload creates the project, so leaving before saving anything leaves exactly
/// this. The list has to present it rather than hide it.
/// </para>
/// </summary>
public sealed class ListProjectsHandler(IProjectRepository projects)
{
    public Task<IReadOnlyList<ProjectListItem>> ListAsync(
        Guid userId,
        CancellationToken cancellationToken) =>
        projects.ListForUserAsync(userId, cancellationToken);
}
